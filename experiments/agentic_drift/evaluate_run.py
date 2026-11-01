"""Evaluate saved BankAccount code checkpoints in a separate, offline container."""
import argparse
import ast
import hashlib
import json
import subprocess
import sys
from pathlib import Path

from .case import stage_for
from .trace import dump


def evaluate_run(run, dataset, checks, out):
    if not Path("/.dockerenv").exists():
        raise RuntimeError("Use the network-disabled evaluation container")
    run, out = Path(run), Path(out)
    out.mkdir(parents=True, exist_ok=False)
    seen, checkpoints, previous = set(), [], {}
    for line in (run / "events.jsonl").read_text().splitlines():
        event = json.loads(line)
        if event["kind"] != "snapshot":
            continue
        for path, metadata in event["files"].items():
            key = (path, metadata["sha256"])
            if key in seen or stage_for(path) != "code":
                continue
            seen.add(key)
            blob = run / "blobs" / metadata["sha256"]
            if hashlib.sha256(blob.read_bytes()).hexdigest() != metadata["sha256"]:
                raise ValueError("Code checkpoint checksum mismatch")
            try:
                tree = ast.parse(blob.read_text())
            except (SyntaxError, UnicodeError):
                checkpoints.append({"snapshot_sequence": event["sequence"], "path": path,
                    "sha256": metadata["sha256"], "status": "syntax_error_or_nontext", "requirements": {}})
                continue
            if not any(isinstance(node, ast.ClassDef) and node.name == "BankAccount" for node in tree.body):
                continue
            index = len(checkpoints)
            source = out / "materialized" / f"checkpoint-{index}.py"
            source.parent.mkdir(exist_ok=True)
            source.write_bytes(blob.read_bytes())
            result_path = out / "results" / f"checkpoint-{index}.json"
            result_path.parent.mkdir(exist_ok=True)
            command = [sys.executable, "-m", "experiments.agentic_drift.benchmark", "--dataset", str(dataset),
                       "--task", "ClassEval_8", "--checks", str(checks), "--source", str(source),
                       "--out", str(result_path)]
            try:
                completed = subprocess.run(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=20)
                result = json.loads(result_path.read_text()) if completed.returncode == 0 and result_path.exists() else {
                    "status": "evaluation_process_error", "requirements": {}}
            except subprocess.TimeoutExpired:
                result = {"status": "evaluation_timeout", "requirements": {}}
            regressions = [requirement for requirement, value in result.get("requirements", {}).items()
                           if value["status"] == "fail" and previous.get((path, requirement)) == "pass"]
            for requirement, value in result.get("requirements", {}).items():
                previous[(path, requirement)] = value["status"]
            checkpoints.append({"snapshot_sequence": event["sequence"], "path": path,
                "sha256": metadata["sha256"], "result": result, "regressions_after_previous_pass": regressions,
                "note": "An early code checkpoint can be incomplete. This does not identify a responsible agent."})
    dump(out / "checkpoint-report.json", {"checkpoints": checkpoints,
        "status": "evaluated" if checkpoints else "no_bankaccount_code_checkpoints",
        "attribution": "Compare these observations with reviewed documents and actual role inputs. No causal blame is inferred."})
    print(json.dumps({"code_checkpoints": len(checkpoints), "report": str(out / "checkpoint-report.json")}))


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--run", required=True)
    p.add_argument("--dataset", required=True)
    p.add_argument("--checks", required=True)
    p.add_argument("--out", required=True)
    a = p.parse_args()
    evaluate_run(a.run, a.dataset, a.checks, a.out)
