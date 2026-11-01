"""Offline direct-generation and MetaGPT wrapper checks."""
import asyncio
import json
import tempfile
import unittest
from pathlib import Path

from .__main__ import bootstrap
from .metagpt_adapter import extract_python, extract_python_with_metadata, instrument, run_direct
from .trace import Trace


class ExtractionTests(unittest.TestCase):
    def test_accepts_single_code_block_and_raw_source(self):
        code = "class BankAccount:\n    pass\n"
        self.assertEqual(extract_python(code), code)
        self.assertEqual(extract_python("```python\n" + code + "```"), code)

    def test_rejects_ambiguous_or_invalid_source(self):
        for text in ("```python\nclass BankAccount: pass\n```\n```python\nx=1\n```",
                     "```python\nclass BankAccount: pass\n```\n```text\nother file\n```",
                     "```python\nclass BankAccount: pass", "```javascript\nclass BankAccount: pass\n```",
                     "class WrongClass: pass", "class BankAccount(:"):
            with self.subTest(text=text), self.assertRaises((ValueError, SyntaxError)):
                extract_python(text)

    def test_commentary_is_separate_from_unchanged_code(self):
        source = "class BankAccount:\n    pass\n"
        code, metadata = extract_python_with_metadata("An explanation.\n```python\n" + source + "```\nMore explanation.")
        self.assertEqual(code, source)
        self.assertTrue(metadata["surrounding_commentary"])
        self.assertFalse(metadata["format_instruction_followed"])

    def test_crlf_and_py_fences(self):
        self.assertIn("class BankAccount:", extract_python("```py\r\nclass BankAccount:\r\n    pass\r\n```\r\n"))


class PipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.tmp.name)
        bootstrap(cls.root)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_direct_condition_preserves_exact_user_request(self):
        root = self.root / "direct"
        trace = Trace(root, root / "workspace")

        class FakeTransport:
            config = {"temperature": 0.6, "max_tokens": 16384}
            received = None

            async def complete(self, messages):
                self.received = messages
                return "```python\nclass BankAccount:\n    pass\n```"

        fake = FakeTransport()
        original = "Fixture original request; no actual model generation."
        asyncio.run(run_direct(trace, original, "fixture/model", "https://openrouter.ai/api/v1", "fixture-key", fake))
        self.assertEqual([m["content"] for m in fake.received if m["role"] == "user"], [original])
        self.assertTrue((trace.workspace / "solution.py").exists())
        events = [json.loads(x) for x in (root / "events.jsonl").read_text().splitlines()]
        self.assertEqual(sum(e["kind"] == "llm_request" for e in events), 1)

    def test_provider_failure_blocks_subsequent_calls(self):
        from metagpt.config2 import Config
        from metagpt.provider.openai_api import OpenAILLM
        trace = Trace(self.root / "failure", self.root / "failure-workspace")

        class FailedTransport:
            calls = 0

            async def complete(self, messages):
                self.calls += 1
                raise RuntimeError("fixture failed response")

        async def execute():
            config = Config.from_llm_config({"model": "fixture/model", "api_key": "fixture-key"})
            llm = OpenAILLM(config.llm)
            transport = FailedTransport()
            try:
                with instrument(trace, 3, transport=transport) as state:
                    for _ in range(2):
                        with self.assertRaises(RuntimeError):
                            await llm.acompletion_text(messages=[{"role": "user", "content": "fixture"}])
                    self.assertTrue(state["failed"])
                    self.assertEqual(transport.calls, 1)
            finally:
                await llm.aclient.close()
        asyncio.run(execute())

    def test_original_contract_reaches_every_native_provider_call(self):
        from metagpt.config2 import Config
        from metagpt.provider.openai_api import OpenAILLM
        from .contract import contract_message
        trace = Trace(self.root / "contract", self.root / "contract-workspace")
        original = "Immutable public fixture contract. Keep balance public."

        class FakeTransport:
            received = []

            async def complete(self, messages):
                self.received.append(messages)
                return "fixture response"

        async def execute():
            llm = OpenAILLM(Config.from_llm_config({"model": "fixture/model", "api_key": "fixture-key"}).llm)
            transport = FakeTransport()
            try:
                with instrument(trace, max_calls=6, transport=transport, original_contract=original):
                    for stage in ["requirements", "design", "tasks", "code", "review", "rewrite"]:
                        messages = [{"role": "system", "content": "Preserve native format"},
                                    {"role": "user", "content": stage}]
                        await llm.acompletion_text(messages=messages)
                        self.assertEqual(len(messages), 2)
                self.assertEqual(len(transport.received), 6)
                for messages in transport.received:
                    self.assertEqual(messages[0]["content"], "Preserve native format")
                    self.assertEqual(messages[1], contract_message(original))
                requests = [json.loads(l) for l in (trace.root / "events.jsonl").read_text().splitlines()
                            if json.loads(l)["kind"] == "llm_request"]
                self.assertEqual([r["messages"] for r in requests], transport.received)
            finally:
                await llm.aclient.close()
        asyncio.run(execute())

    def test_planning_only_uses_native_role_context(self):
        from metagpt.actions import Action, UserRequirement
        from metagpt.config2 import Config
        from metagpt.context import Context
        from metagpt.roles.role import Role
        from metagpt.schema import Message
        from metagpt.team import Team
        from .contract import HEADER, PLANNING_ONLY
        trace = Trace(self.root / "planning-only", self.root / "planning-only-workspace")

        class FixtureCall(Action):
            async def run(self, *args, **kwargs):
                return await self._aask("fixture stage prompt")

        class FixtureRole(Role):
            def __init__(self, **kwargs):
                super().__init__(**kwargs)
                self.set_actions([FixtureCall])
                self._watch([UserRequirement])

            async def _act(self):
                return Message(content=await self.rc.todo.run(), role=self.profile, cause_by=FixtureCall)

        class FakeTransport:
            async def complete(self, messages):
                return "fixture response"

        config = Config.from_llm_config({"model": "fixture/model", "api_key": "fixture-key"})
        config.workspace.path = trace.workspace
        team = Team(context=Context(config=config))
        profiles = ["Product Manager", "Architect", "Project Manager", "Engineer"]
        team.hire([FixtureRole(name=p, profile=p) for p in profiles])

        async def execute():
            with instrument(trace, max_calls=4, transport=FakeTransport(), original_contract="Original public contract.",
                            contract_policy=PLANNING_ONLY):
                team.run_project("fixture public task")
                await team.run(n_round=1, auto_archive=False)
        asyncio.run(execute())
        requests = [json.loads(l) for l in (trace.root / "events.jsonl").read_text().splitlines()
                    if json.loads(l)["kind"] == "llm_request"]
        self.assertEqual({r["role"] for r in requests}, set(profiles))
        for r in requests:
            count = sum(m.get("role") == "system" and m.get("content", "").startswith(HEADER) for m in r["messages"])
            self.assertEqual(count, int(r["role"] in {"Architect", "Project Manager"}))


if __name__ == "__main__":
    unittest.main()
