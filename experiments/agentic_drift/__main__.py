"""No-cost preparation by default. Live execution requires --execute."""
import argparse
import asyncio
import hashlib
import json
import os
import platform
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen

from .tasks import TASKS, public_task
from .trace import Trace, dump
from .contract import NONE, EVERY_CALL, POLICIES, contract_message, delivery_audit

ROOT = Path(__file__).resolve().parent


def fresh(path):
    path = Path(path).resolve()
    path.mkdir(parents=True, exist_ok=False)
    return path


def bootstrap(root):
    """Import MetaGPT without reading a user's home config or writing a real key."""
    if "metagpt.config2" in sys.modules:
        raise RuntimeError("Launch each MetaGPT run in a fresh process")
    runtime = root / "runtime"
    (runtime / "config").mkdir(parents=True)
    (runtime / "config" / "config2.yaml").write_text(
        "llm:\n  api_type: openai\n  api_key: offline-placeholder\n  model: offline-placeholder\n")
    os.environ["METAGPT_PROJECT_ROOT"] = str(runtime)
    # The container has an empty home directory. Refuse implicit user config elsewhere.
    if (Path.home() / ".metagpt" / "config2.yaml").exists():
        raise RuntimeError("Use the Docker environment with an empty home config")


def calibrate(out):
    from .evaluate import evaluate
    out = fresh(out)
    report = {"kind": "authored_fixture_calibration_not_agent_results", "tasks": {}}
    for task_id, task in TASKS.items():
        root = out / task_id
        trace = Trace(root, root / "workspace")
        trace.event("original_requirement", **public_task(task_id))
        rows = []
        for label, code in [("reference", task["reference"]), ("mutation", task["mutation"])]:
            (trace.workspace / "solution.py").write_text(code)
            trace.snapshot(label)
            result = evaluate(task_id, trace.workspace / "solution.py")
            trace.event("evaluation", checkpoint=label, result=result)
            rows.append(result)
        if not rows[0]["all_pass"] or rows[1]["checks"][task["lost"]]["status"] != "fail":
            raise RuntimeError(f"Calibration failed: {task_id}")
        report["tasks"][task_id] = {"reference": rows[0], "mutation": rows[1],
            "known_mutated_obligation": task["lost"]}
    dump(out / "calibration.json", report)
    print(json.dumps({"calibration": "passed", "tasks": len(TASKS), "report": str(out / "calibration.json")}))


def fetch_classeval(out, commit=None):
    out = Path(out).resolve()
    if out.exists() and any(out.iterdir()):
        raise FileExistsError(f"Refusing to overwrite dataset: {out}")

    def get(url):
        with urlopen(Request(url, headers={"User-Agent": "semantic-drift-research"}), timeout=60) as response:
            return response.read()

    if commit is None:
        commit = json.loads((ROOT / "cases/bankaccount_v1/requirements.json").read_text())["source_commit"]
    if len(commit) != 40 or any(c not in "0123456789abcdef" for c in commit):
        raise ValueError("Use a full lowercase ClassEval commit SHA")
    url = f"https://raw.githubusercontent.com/FudanSELab/ClassEval/{commit}/data/ClassEval_data.json"
    content = get(url)
    records = json.loads(content)
    if not isinstance(records, list) or not records or not all("task_id" in r and "skeleton" in r for r in records):
        raise ValueError("Unexpected ClassEval schema")
    out.mkdir(parents=True, exist_ok=True)
    (out / "ClassEval_data.json").write_bytes(content)
    dump(out / "provenance.json", {"source": url, "commit": commit,
         "sha256": hashlib.sha256(content).hexdigest(), "tasks": len(records),
         "license": "CC BY-NC 4.0 (dataset); retain upstream attribution",
         "retrieved_utc": datetime.now(timezone.utc).isoformat()})
    print(json.dumps({"tasks": len(records), "commit": commit, "path": str(out)}))


def prepare(args):
    if args.dataset:
        data_path = Path(args.dataset)
        provenance = json.loads(data_path.with_name("provenance.json").read_text())
        if hashlib.sha256(data_path.read_bytes()).hexdigest() != provenance["sha256"]:
            raise ValueError("ClassEval dataset checksum mismatch")
        record = next(r for r in json.loads(data_path.read_text()) if r["task_id"] == args.task)
        task = {"task_id": args.task, "source": "ClassEval", "dataset_commit": provenance["commit"],
                "requirement": "Implement this Python class. Preserve the public API and all stated behavior.\n"
                               "Write the implementation in solution.py.\n\n" + record["skeleton"]}
    else:
        task = public_task(args.task)
    out = fresh(args.out)
    dump(out / "public_task.json", task)
    dump(out / "plan.json", {"status": "prepared_no_model_calls", "task_id": args.task,
         "pipeline": "metagpt_software_company", "metagpt": "0.8.2",
         "roles": ["ProductManager", "Architect", "ProjectManager", "Engineer"],
         "record": ["original_requirement", "published_message", "role_observed", "llm_request",
                    "llm_response", "snapshot", "usage"],
         "prose_evaluation": "unassessed; requirement annotation protocol still needed",
         "withheld_fields": ["test", "solution_code"],
         "next": "Run integration-smoke, then select a model and budget before live execution."})
    print(out / "public_task.json")


def live(args):
    if not args.execute:
        raise ValueError("Live execution requires --execute. Preparation makes no model calls.")
    if not Path("/.dockerenv").exists():
        raise ValueError("Use Docker for live runs and generated-code evaluation")
    from .openrouter import OpenRouterSession, BASE_URL, validate_config
    from .budget import Ledger
    router_config = json.loads(Path(args.router_config).read_text())
    validate_config(router_config)
    key = os.environ.get("DRIFT_API_KEY", "")
    if not key:
        raise ValueError("Set DRIFT_API_KEY through the environment; do not paste it into commands")
    task = json.loads(Path(args.input).read_text())
    policy = args.contract_policy
    if args.condition == "direct" and policy != NONE:
        raise ValueError("The contract intervention is defined only for the MetaGPT condition")
    if task.get("case_id") != "bankaccount-v1":
        raise ValueError("Use the frozen BankAccount case for this paired pilot")
    root = fresh(args.out)
    trace = Trace(root, root / "workspace", secrets=[key])
    run_id = str(uuid.uuid4())
    ledger = Ledger(args.ledger, router_config["total_budget_usd"])
    dump(root / "manifest.json", {"status": "started", "task": task,
         "condition": args.condition, "pipeline": "MetaGPT roles" if args.condition == "metagpt" else "direct generation",
         "metagpt": "0.8.2", "openrouter_config": router_config,
         "source_sha256": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in ROOT.glob("*.py")},
         "contract_policy": policy,
         "contract_message": contract_message(task["requirement"]) if policy != NONE else None,
         "base_url": BASE_URL, "run_id": run_id, "python": platform.python_version(),
         "public_task_sha256": hashlib.sha256(Path(args.input).read_bytes()).hexdigest(),
         "limitations": ["Dedicated non-resetting provider key limit is required alongside local reservations.",
                         "No automatic semantic labels for prose artifacts.",
                         "Direct and pipeline conditions use different call counts; report token usage and cost.",
                         "Provider-exposed reasoning is not causal ground truth."]})
    bootstrap(root)
    from .metagpt_adapter import run_company, run_direct
    trace.event("original_requirement", **task)

    async def execute():
        async with OpenRouterSession(router_config, key, trace, ledger, run_id) as router:
            try:
                await router.preflight()
                if args.condition == "direct":
                    await run_direct(trace, task["requirement"], router_config["model"], BASE_URL, key, router)
                else:
                    await run_company(trace, task["requirement"], router_config["model"], BASE_URL, key,
                        router_config["rounds"], router_config["max_calls"],
                        float(router_config["per_run_budget_usd"]), transport=router,
                        original_contract=task["requirement"] if policy != NONE else None,
                        contract_policy=policy)
                events = [json.loads(line) for line in (root / "events.jsonl").read_text().splitlines()]
                dump(root / "contract_delivery.json", delivery_audit(events, task["requirement"], policy))
            finally:
                dump(root / "openrouter_usage.json", {"attempted_requests": router.requests,
                     "known_cost_usd": str(router.cost), "failed": router.failed,
                     "responses": router.usage_records,
                     "billing_ledger": str(Path(args.ledger).resolve()),
                     "note": "See raw responses for tokens, reasoning details, routing, and finish reasons."})
    try:
        asyncio.run(execute())
    except BaseException as error:
        category = getattr(error, "category", type(error).__name__)
        message = trace.redact(str(error))
        trace.event("run_failed", exception_type=type(error).__name__, category=category)
        trace.snapshot("failed_partial_run")
        dump(root / "status.json", {"status": "failed", "exception_type": type(error).__name__, "category": category,
             "message": message,
             "next": "Preserve this run. Reconcile request logs and billing before retrying."})
        raise RuntimeError(f"Run stopped: {message}. Saved artifacts: {root}") from None
    dump(root / "status.json", {"status": "generation_finished_not_semantically_verified"})
    print(root)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ["calibrate", "integration-smoke", "fetch-classeval"]:
        p = commands.add_parser(name)
        p.add_argument("--out", required=True)
        if name == "fetch-classeval":
            p.add_argument("--commit", help="ClassEval commit; defaults to the BankAccount case snapshot")
    p = commands.add_parser("prepare")
    p.add_argument("--task", default="stable_unique")
    p.add_argument("--dataset", help="Pinned ClassEval_data.json; do not mount in generation container")
    p.add_argument("--out", required=True)
    p = commands.add_parser("run")
    p.add_argument("--input", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--condition", choices=["direct", "metagpt"], required=True)
    p.add_argument("--contract-policy", choices=POLICIES, default=NONE)
    p.add_argument("--router-config", required=True)
    p.add_argument("--ledger", required=True, help="Shared persistent ledger for all experiment runs")
    p.add_argument("--execute", action="store_true")
    p = commands.add_parser("evaluate")
    p.add_argument("--task", choices=TASKS, required=True)
    p.add_argument("--source", required=True)
    p.add_argument("--out", required=True)
    args = parser.parse_args()
    if args.command == "calibrate":
        calibrate(args.out)
    elif args.command == "fetch-classeval":
        fetch_classeval(args.out, args.commit)
    elif args.command == "prepare":
        prepare(args)
    elif args.command == "run":
        try:
            live(args)
        except (RuntimeError, ValueError) as error:
            parser.exit(1, str(error) + "\n")
    elif args.command == "integration-smoke":
        root = fresh(args.out)
        bootstrap(root)
        from .metagpt_adapter import integration_smoke
        trace = Trace(root, root / "workspace")
        integration_smoke(trace)
        events = [json.loads(x) for x in (root / "events.jsonl").read_text().splitlines()]
        assert any(e["kind"] == "role_observed" for e in events)
        assert sum(e["kind"] == "published_message" for e in events) >= 2
        assert sum(e["kind"] == "llm_request" for e in events) == 1
        assert any(e["kind"] == "mock_transport_begin" for e in events)
        dump(root / "status.json", {"status": "passed", "model_calls": 0,
             "mocked_provider_requests": 1,
             "scope": "Native role construction, real routing, mocked provider tracing and call-limit enforcement; no funded generation."})
        print("MetaGPT routing and trace hooks passed; model calls: 0")
    elif args.command == "evaluate":
        if not Path("/.dockerenv").exists():
            parser.error("Evaluate generated code in a network-disabled, credential-free Docker container")
        from .evaluate import evaluate
        # A separate process prevents hangs from blocking the orchestration process.
        # The Docker invocation must also set memory, CPU and PID limits.
        script = "from experiments.agentic_drift.evaluate import evaluate; import json,sys; print(json.dumps(evaluate(sys.argv[1],sys.argv[2])))"
        result = subprocess.run([sys.executable, "-c", script, args.task, args.source],
                                capture_output=True, text=True, timeout=20)
        if result.returncode:
            dump(args.out, {"status": "error", "exit_code": result.returncode})
        else:
            dump(args.out, json.loads(result.stdout.splitlines()[-1]))


if __name__ == "__main__":
    main()
