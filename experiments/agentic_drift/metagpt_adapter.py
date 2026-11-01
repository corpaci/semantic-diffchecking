"""Instrumentation for unmodified MetaGPT 0.8.2 software-company roles."""
import asyncio
import ast
import re
from contextlib import nullcontext
from contextlib import contextmanager
from contextvars import ContextVar
from importlib.metadata import version
from pathlib import Path
from unittest.mock import patch

from .trace import dump
from .contract import NONE, EVERY_CALL, apply_contract, inject_for_role


def messages(items):
    return [x.model_dump(mode="json") for x in items]


@contextmanager
def instrument(trace, max_calls, transport=None, original_contract=None, contract_policy=EVERY_CALL):
    from metagpt.environment.base_env import Environment
    from metagpt.roles.role import Role
    from metagpt.provider.openai_api import OpenAILLM

    current_role = ContextVar("drift_role", default="unknown")
    publish_original = Environment.publish_message
    observe_original = Role._observe
    run_original = Role.run
    completion_original = OpenAILLM.acompletion_text
    state = {"calls": 0, "failed": False}

    def publish(env, message, *args, **kwargs):
        seq = trace.event("published_message", message=message.model_dump(mode="json"))
        result = publish_original(env, message, *args, **kwargs)
        trace.snapshot(f"published_message_{seq}")
        return result

    async def observe(role, *args, **kwargs):
        result = await observe_original(role, *args, **kwargs)
        if role.rc.news:
            trace.event("role_observed", role=role.profile, name=role.name,
                        messages=messages(role.rc.news))
        return result

    async def run(role, *args, **kwargs):
        token = current_role.set(role.profile)
        try:
            return await run_original(role, *args, **kwargs)
        finally:
            current_role.reset(token)

    async def completion(llm, messages, *args, **kwargs):
        if state["failed"]:
            raise RuntimeError("A previous request failed. Reconcile billing before retrying.")
        if state["calls"] >= max_calls:
            state["failed"] = True
            raise RuntimeError("Experiment model-call limit reached")
        state["calls"] += 1
        call_id = state["calls"]
        selected = original_contract is not None and inject_for_role(contract_policy, current_role.get())
        messages = apply_contract(messages, original_contract if selected else None)
        trace.event("llm_request", call_id=call_id, role=current_role.get(), messages=messages)
        try:
            if transport is not None:
                answer = await transport.complete(messages)
            else:
            # Disable provider retries. An unanswered request has ambiguous billing state.
                llm.aclient.max_retries = 0
                original = getattr(completion_original, "__wrapped__", completion_original)
                answer = await original(llm, messages, *args, **kwargs)
        except BaseException as error:
            state["failed"] = True
            trace.event("llm_error", call_id=call_id, exception_type=type(error).__name__,
                        retry_policy="stop_and_reconcile_before_resume")
            raise
        trace.event("llm_response", call_id=call_id, role=current_role.get(), content=answer)
        trace.snapshot(f"llm_response_{call_id}")
        return answer

    async def blocked(*args, **kwargs):
        state["failed"] = True
        raise RuntimeError("Uninstrumented provider path blocked; no request was sent")

    with patch.object(Environment, "publish_message", publish), \
         patch.object(Role, "_observe", observe), patch.object(Role, "run", run), \
         patch.object(OpenAILLM, "acompletion_text", completion), \
         (patch.object(OpenAILLM, "acompletion", blocked) if transport else nullcontext()), \
         (patch.object(OpenAILLM, "aask_code", blocked) if transport else nullcontext()), \
         (patch.object(OpenAILLM, "_achat_completion", blocked) if transport else nullcontext()), \
         (patch.object(OpenAILLM, "_achat_completion_stream", blocked) if transport else nullcontext()), \
         (patch.object(OpenAILLM, "_achat_completion_function", blocked) if transport else nullcontext()):
        yield state


async def run_company(trace, requirement, model, base_url, key, rounds, max_calls, budget, transport=None,
                      original_contract=None, contract_policy=NONE):
    if version("metagpt") != "0.8.2":
        raise RuntimeError("Use the pinned MetaGPT 0.8.2 environment")
    from metagpt.config2 import Config
    from metagpt.context import Context
    from metagpt.roles import ProductManager, Architect, ProjectManager, Engineer
    from metagpt.team import Team

    config = Config.from_llm_config({"api_type": "openai", "model": model,
                                   "api_key": key, "base_url": base_url,
                                   "temperature": transport.config["temperature"] if transport else 0.0,
                                   "max_token": transport.config["max_tokens"] if transport else 4096,
                                   "timeout": 120})
    config.workspace.path = trace.workspace
    config.project_name = "candidate"
    config.max_auto_summarize_code = 0
    ctx = Context(config=config)
    team = Team(context=ctx)
    team.hire([ProductManager(), Architect(), ProjectManager(), Engineer(n_borg=1, use_code_review=True)])
    team.invest(budget)
    # These constructors use no model calls. All calls occur under the hooks.
    with instrument(trace, max_calls, transport=transport, original_contract=original_contract,
                    contract_policy=contract_policy) as state:
        team.run_project(requirement)
        await team.run(n_round=rounds, auto_archive=False)
    if state["failed"]:
        raise RuntimeError("A model request failed; this run requires reconciliation")
    trace.snapshot("final")
    costs = team.cost_manager
    dump(trace.root / "usage.json", {"model_calls": state["calls"],
         "accounting_source": "openrouter_usage.json" if transport else "framework_estimate",
         "reported_cost_usd": None if transport else costs.total_cost,
         "prompt_tokens": None if transport else costs.total_prompt_tokens,
         "completion_tokens": None if transport else costs.total_completion_tokens,
         "note": "Use openrouter_usage.json and raw response usage for the OpenRouter transport."})


def extract_python_with_metadata(answer):
    """Extract one unambiguous solution, without rewriting its implementation."""
    if not isinstance(answer, str) or not answer.strip():
        raise ValueError("Direct response is empty or not text")
    matches = list(re.finditer(r"^```(?:python|py)[ \t]*\r?\n(.*?)^```[ \t]*(?:\r?\n|\Z)",
                              answer, flags=re.MULTILINE | re.DOTALL))
    if "```" in answer:
        if len(matches) != 1 or answer.count("```") != 2:
            raise ValueError("Expected exactly one unambiguous Python code block")
        match = matches[0]
        code = match.group(1)
        commentary = bool(answer[:match.start()].strip() or answer[match.end():].strip())
        metadata = {"parser": "single_python_block_v2", "source": "fenced_python",
                    "format_instruction_followed": not commentary,
                    "surrounding_commentary": commentary}
    else:
        code = answer
        metadata = {"parser": "single_python_block_v2", "source": "plain_python",
                    "format_instruction_followed": False, "surrounding_commentary": False}
    tree = ast.parse(code)
    if not any(isinstance(node, ast.ClassDef) and node.name == "BankAccount" for node in tree.body):
        raise ValueError("Direct response does not define the required BankAccount class")
    return code.rstrip() + "\n", metadata


def extract_python(answer):
    return extract_python_with_metadata(answer)[0]


async def run_direct(trace, requirement, model, base_url, key, transport):
    from metagpt.config2 import Config
    from metagpt.context import Context
    config = Config.from_llm_config({"api_type": "openai", "model": model,
        "api_key": key, "base_url": base_url, "temperature": transport.config["temperature"],
        "max_token": transport.config["max_tokens"]})
    ctx = Context(config=config)
    llm = ctx.llm()
    try:
        with instrument(trace, max_calls=1, transport=transport):
            answer = await llm.aask(requirement, stream=False,
                system_msgs=["Implement the supplied Python task directly. Return exactly one fenced python block "
                             "containing the complete solution.py. Preserve the requested public API."])
        code, metadata = extract_python_with_metadata(answer)
        trace.event("direct_code_extraction", **metadata)
        (trace.workspace / "solution.py").write_text(code)
        trace.snapshot("direct_final")
    finally:
        await llm.aclient.close()


def integration_smoke(trace):
    """Use real MetaGPT routing with a deterministic Action. No model calls."""
    from metagpt.actions import Action, UserRequirement
    from metagpt.context import Context
    from metagpt.config2 import Config
    from metagpt.roles.role import Role
    from metagpt.schema import Message
    from metagpt.team import Team
    from metagpt.roles import ProductManager, Architect, ProjectManager, Engineer

    class Echo(Action):
        async def run(self, *args, **kwargs):
            return "Return distinct values in first-occurrence order."

    class Planner(Role):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            self.set_actions([Echo])
            self._watch([UserRequirement])

        async def _act(self):
            content = await self.rc.todo.run()
            return Message(content=content, role=self.profile, cause_by=Echo)

    config = Config.from_llm_config({"api_key": "offline-placeholder", "model": "offline-placeholder"})
    config.workspace.path = trace.workspace
    team = Team(context=Context(config=config))
    team.hire([Planner(name="FixturePlanner", profile="FixturePlanner")])
    native = Team(context=Context(config=config))
    native.hire([ProductManager(), Architect(), ProjectManager(), Engineer(n_borg=1, use_code_review=True)])
    trace.event("native_roles_initialized", roles=[r.profile for r in native.env.roles.values()], model_calls=0)

    async def execute():
        with instrument(trace, max_calls=0):
            team.run_project("Return unique integers in first-occurrence order.")
            await team.run(n_round=1, auto_archive=False)
    asyncio.run(execute())

    # Exercise the real provider wrapper with a mocked transport and keyword arguments.
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from metagpt.provider.openai_api import OpenAILLM

    async def check_provider():
        llm = OpenAILLM(config.llm)
        response = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="fixture response"))])
        trace.event("mock_transport_begin", network_calls=0)
        with patch.object(OpenAILLM, "_achat_completion", new=AsyncMock(return_value=response)):
            with instrument(trace, max_calls=1):
                answer = await llm.acompletion_text(messages=[{"role": "user", "content": "fixture"}], stream=False)
                assert answer == "fixture response"
                try:
                    await llm.acompletion_text(messages=[{"role": "user", "content": "blocked"}], stream=False)
                except RuntimeError:
                    pass
                else:
                    raise AssertionError("Model-call limit did not stop the second request")
        await llm.aclient.close()
    asyncio.run(check_provider())
