"""Prepare a frozen requirement case and evidence-based review packets."""
import argparse
import ast
import hashlib
import json
from pathlib import Path

from .trace import dump

CASE = Path(__file__).resolve().parent / "cases" / "bankaccount_v1"
STAGES = ("request", "requirements_document", "design", "task_list", "code")


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def check_map(path):
    result = {}
    for node in ast.walk(ast.parse(Path(path).read_text())):
        if not isinstance(node, ast.FunctionDef) or not node.name.startswith("test_"):
            continue
        for decorator in node.decorator_list:
            if isinstance(decorator, ast.Call) and isinstance(decorator.func, ast.Name) and decorator.func.id == "covers":
                for argument in decorator.args:
                    result.setdefault(ast.literal_eval(argument), []).append(node.name)
    return result


def prepare_case(dataset, out, config=None):
    dataset, out = Path(dataset), Path(out).resolve()
    provenance = json.loads(dataset.with_name("provenance.json").read_text())
    if sha(dataset) != provenance["sha256"]:
        raise ValueError("Dataset checksum mismatch")
    ledger = json.loads((CASE / "requirements.json").read_text())
    if provenance["commit"] != ledger["source_commit"]:
        raise ValueError("This case requires the recorded ClassEval snapshot")
    record = next(r for r in json.loads(dataset.read_text()) if r["task_id"] == ledger["task_id"])
    mapping = check_map(CASE / "checks.py")
    ids = {r["id"] for r in ledger["requirements"]}
    if ids != set(mapping):
        raise ValueError("Every requirement must have a mapped independent check")
    request = ("Implement this Python class in solution.py. Preserve its public API.\n\n"
               + record["skeleton"] + "\n\nPilot scope: " + ledger["scope"]
               + "\nThe following requirements clarify the original skeleton. They form the evaluation contract.\n"
               + "\n".join(f"{r['id']}: {r['text']}" for r in ledger["requirements"]))
    out.mkdir(parents=True, exist_ok=False)
    public = {"case_id": ledger["case_id"], "task_id": ledger["task_id"], "source": ledger["variant"],
              "dataset_commit": provenance["commit"], "requirement": request}
    dump(out / "public_task.json", public)
    dump(out / "frozen_case.json", {"case_id": ledger["case_id"], "public_task_sha256": sha(out / "public_task.json"),
         "requirements_sha256": sha(CASE / "requirements.json"), "checks_sha256": sha(CASE / "checks.py"),
         "openrouter_config_sha256": sha(config or CASE.parent.parent / "openrouter_config.json"),
         "dataset_sha256": sha(dataset), "test_mapping": mapping,
         "status": "prepared_before_model_outputs", "scope": ledger["scope"]})
    rows = [{"requirement_id": r["id"], "stage": stage,
             "label": "preserved" if stage == "request" else "not_generated",
             "evidence_quote": r["text"] if stage == "request" else "",
             "artifact": "public_task.json" if stage == "request" else None,
             "reviewer": "case_preparation" if stage == "request" else None}
            for r in ledger["requirements"] for stage in STAGES]
    dump(out / "stage_tracking.json", {"rows": rows, "note": "No agent artifacts exist yet. No loss attribution is made."})
    text = ["# BankAccount requirement and test map", "", "The public request includes every clarification before generation.", "",
            "| ID | Requirement | Independent checks |", "|---|---|---|"]
    for r in ledger["requirements"]:
        text.append(f"| {r['id']} | {r['text']} | {', '.join(mapping[r['id']])} |")
    (out / "requirement-test-map.md").write_text("\n".join(text) + "\n")
    return out


def stage_for(path):
    normalized = "/" + str(path).replace("\\", "/")
    if "/docs/prd/" in normalized:
        return "requirements_document"
    if "/docs/system_design/" in normalized:
        return "design"
    if "/docs/task/" in normalized:
        return "task_list"
    if path.endswith(".py") and "/tests/" not in normalized:
        return "code"
    return None


def review_packet(run, out):
    run, out = Path(run), Path(out)
    ledger = json.loads((CASE / "requirements.json").read_text())
    manifest = json.loads((run / "manifest.json").read_text())
    if manifest["task"].get("case_id") != ledger["case_id"]:
        raise ValueError("Run does not use this case")
    seen, artifacts, observations = set(), [], []
    for line in (run / "events.jsonl").read_text().splitlines():
        event = json.loads(line)
        if event["kind"] == "role_observed":
            observations.append({"sequence": event["sequence"], "role": event["role"],
                                 "messages": event["messages"]})
        if event["kind"] != "snapshot":
            continue
        for path, info in event["files"].items():
            stage = stage_for(path)
            identity = (path, info["sha256"])
            if stage is None or identity in seen:
                continue
            blob = run / "blobs" / info["sha256"]
            if sha(blob) != info["sha256"]:
                raise ValueError("Artifact checksum mismatch")
            seen.add(identity)
            artifacts.append({"artifact_id": f"{event['sequence']}:{path}", "path": path, "stage": stage,
                "sha256": info["sha256"], "snapshot_sequence": event["sequence"], "blob": str(blob.resolve()),
                "additions": [], "scope_rationale": "",
                "requirements": [{"requirement_id": r["id"], "label": "unassessed", "evidence_quote": "",
                                  "line_start": None, "line_end": None, "reviewer": None, "rationale": ""}
                                 for r in ledger["requirements"]]})
    out.mkdir(parents=True, exist_ok=False)
    dump(out / "review.json", {"run": str(run.resolve()), "artifacts": artifacts,
         "role_observations": observations,
         "allowed_labels": ["preserved", "omitted", "contradicted", "unclear", "not_applicable", "unassessed"],
         "attribution": "Earliest observed change is not proof of causal responsibility. Inspect actual received messages and replay a repaired handoff."})


def main():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="command", required=True)
    a = sub.add_parser("prepare")
    a.add_argument("--dataset", required=True)
    a.add_argument("--out", required=True)
    a.add_argument("--config", help="Freeze a model configuration; defaults to openrouter_config.json")
    a = sub.add_parser("packet")
    a.add_argument("--run", required=True)
    a.add_argument("--out", required=True)
    a = p.parse_args()
    if a.command == "prepare":
        print(prepare_case(a.dataset, a.out, a.config))
    else:
        review_packet(a.run, a.out)


if __name__ == "__main__":
    main()
