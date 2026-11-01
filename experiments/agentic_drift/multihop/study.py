"""Prepare, generate, and separately evaluate frozen code-refactoring chains."""
import argparse
import ast
import asyncio
import fcntl
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import uuid
from collections import defaultdict
from pathlib import Path

from ..budget import Ledger
from ..openrouter import OpenRouterSession, RouterError, validate_config
from ..trace import Trace, dump
from .tasks import all_tasks
from .etp import Oracle, UnsupportedCode, decode, pointwise_probe
from .recovery import recover, settled_truncation

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
REPO = ROOT.parents[1]
DATA = Path(os.environ.get("DRIFT_ORACLE_DATA", REPO / "oracle" / "data")).resolve()
IMAGE = "semantic-drift-refactor:1"
CONDITIONS = ("none", "every", "sparse")
TARGETED = "alternating_refactor_v1"
OBJECTIVES = {
    "permissions": [
        "Expand the final compound permission expression into explicit conditional branches returning True or False. "
        "Keep the existing validation and decision order. Do not return compound Boolean expressions; "
        "conditions may contain Boolean operators.",
        "Combine the role-specific permission branches into one final Boolean return expression. "
        "Keep the earlier validation and decision order. Do not merely reformat the previous code.",
    ],
    "etp_associativity": [
        "Introduce separate named local values for the left and right equation expressions. "
        "Return the equality between those local names. Preserve every operation argument and grouping.",
        "Inline all local term aliases into one final equality return expression. "
        "Use no local assignments. Preserve every operation argument and grouping.",
    ],
}
GRAMMAR = ("ETP code grammar: one function law(op, x, y, z); optional docstrings; "
           "zero or more single-assignment local term aliases; final return is one == comparison. "
           "Terms are x/y/z, prior local aliases, or op(term, term). No imports, helpers, branches, "
           "loops, constants, annotations, argument rebinding, repeated assignment, or other calls. "
           "op is a pure total arbitrary binary operation, with no assumed algebraic properties. "
           "All variables are universally quantified for law evaluation. Preserve pointwise results too.")


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def source_hashes():
    paths = list(HERE.glob("*.py")) + [ROOT / n for n in ("openrouter.py", "budget.py", "trace.py")]
    paths += [REPO / "oracle" / n for n in ("oracle.py", "normalizer.py", "mapper.py", "build_matrix.py")]
    result = {str(p.relative_to(REPO)): digest(p) for p in paths}
    for name in ("equations.txt", "matrix.bin", "matrix_meta.json"):
        result["oracle-data/" + name] = digest(DATA / name)
    return dict(sorted(result.items()))


def configuration(family, hops):
    p = ROOT / "openrouter_config.json" if family == "qwen" else ROOT / "configs" / f"{family}.json"
    config = json.loads(p.read_text())
    config["max_calls"] = hops
    validate_config(config)
    return config


def prepare(out, stage, calibration_path=None):
    if out.exists():
        raise FileExistsError("Study folder exists. Use its frozen plan; do not overwrite it.")
    calibration_path = Path(calibration_path).resolve() if calibration_path else ROOT / "runs" / "multihop-calibration-v1" / "calibration.json"
    calibration = json.loads(calibration_path.read_text()) if calibration_path.exists() else None
    tasks = all_tasks()
    if stage in {"integration", "targeted", "targeted_long"}:
        selected, hops, repetitions, conditions = ["permissions", "etp_associativity"], 1, 1, ["none", "every"]
        if stage == "targeted":
            hops = 2
        elif stage == "targeted_long":
            hops, repetitions = 20, 3
    else:
        selected, hops, repetitions, conditions = list(tasks), 5, 1, list(CONDITIONS)
        if stage == "extended":
            hops, repetitions = 20, 3
    rows = []
    # Interleave families, tasks and conditions; rotate condition order by cell.
    for rep in range(1, repetitions + 1):
        for ti, task_id in enumerate(selected):
            for fi, family in enumerate(("qwen", "deepseek", "glm")):
                offset = (ti + fi + rep - 1) % len(conditions)
                for condition in conditions[offset:] + conditions[:offset]:
                    rows.append(dict(id=f"{task_id}-{family}-{condition}-r{rep:02}", task=task_id,
                                     family=family, condition=condition, repetition=rep))
    out.mkdir(parents=True)
    for task_id in selected:
        p = out / "tasks" / task_id
        p.mkdir(parents=True)
        (p / "reference.py").write_text(tasks[task_id]["reference"])
        dump(p / "task.json", tasks[task_id])
    plan = dict(schema=1, study_id=str(uuid.uuid4()), stage=stage, hops=hops,
                prompt_policy=TARGETED if stage in {"targeted", "targeted_long"} else "clarity_v1",
                refactor_objectives=OBJECTIVES if stage in {"targeted", "targeted_long"} else {},
                sparse_reminder_hops=list(range(5, hops + 1, 5)),
                checkpoints=list(range(hops + 1)) if stage in {"targeted", "targeted_long"} else [h for h in [0, 1, 5, 10, 20] if h <= hops],
                rows=rows, source_hashes=source_hashes(),
                configs={f: configuration(f, hops) for f in ("qwen", "deepseek", "glm")},
                task_hashes={t: digest(out / "tasks" / t / "task.json") for t in selected},
                reference_hashes={t: digest(out / "tasks" / t / "reference.py") for t in selected},
                ledger=str(ROOT / "runs" / "openrouter-budget" / "spend.json"),
                max_paid_calls=len(rows)*hops,
                evaluation_image=IMAGE, evidence_scope="authored_small_tasks_not_population_generalization")
    if calibration and calibration["source_hashes"] == plan["source_hashes"]:
        plan["calibration"] = dict(path=str(calibration_path), sha256=digest(calibration_path),
                                   image=calibration["image"])
        plan["evaluation_image"] = calibration["image"]
    dump(out / "plan.json", plan)
    (out / "plan.sha256").write_text(digest(out / "plan.json") + "\n")
    print(json.dumps(dict(study=str(out), chains=len(rows), max_paid_calls=plan["max_paid_calls"],
                          status="prepared_no_model_requests")))


def load_plan(out):
    if digest(out / "plan.json") != (out / "plan.sha256").read_text().strip():
        raise ValueError("Frozen plan changed")
    plan = json.loads((out / "plan.json").read_text())
    if source_hashes() != plan["source_hashes"]:
        raise ValueError("Frozen source or oracle data changed. Prepare a new study folder.")
    for task_id in plan["task_hashes"]:
        if (digest(out / "tasks" / task_id / "task.json") != plan["task_hashes"][task_id]
                or digest(out / "tasks" / task_id / "reference.py") != plan["reference_hashes"][task_id]):
            raise ValueError("Frozen task changed")
    if str(ROOT / "runs" / "openrouter-budget" / "spend.json") != plan["ledger"]:
        raise ValueError("Shared budget ledger location changed")
    return plan


def messages(task, previous, condition, hop, sparse_hops, prompt_policy="clarity_v1"):
    text = ("Refactor the supplied Python code for clarity while preserving all behavior. "
            "Keep the exact public interface: " + task["signature"] + ". "
            "Return exactly one Python code block containing the complete module. "
            "Do not add features, dependencies, tests, examples, or explanatory prose. "
            "You may leave code unchanged when no safe refactor improves clarity.")
    if prompt_policy == TARGETED:
        text = text.replace("You may leave code unchanged when no safe refactor improves clarity.",
                            "Perform the requested structural transformation while preserving behavior. "
                            "If the code already has the requested structure, preserve it.")
        text += " Refactoring objective: " + OBJECTIVES[task["id"]][(hop - 1) % 2]
    elif prompt_policy != "clarity_v1":
        raise ValueError("Unknown prompt policy")
    if task["track"] == "etp":
        text += " " + GRAMMAR
    result = [{"role": "system", "content": text}]
    if condition == "every" or condition == "sparse" and hop in sparse_hops:
        contract = "Original behavioral requirements (preserve these when the previous code conflicts):\n"
        contract += "\n".join(f"{k}: {v}" for k, v in task["requirements"].items())
        if task["track"] == "etp":
            # The precise initial identity must be restored, not only a generic instruction.
            contract += "\nOriginal equation code:\n" + task["reference"]
        result.append({"role": "system", "content": contract})
    result.append({"role": "user", "content": "Previous code:\n```python\n" + previous + "\n```"})
    return result


def extract(answer):
    blocks = re.findall(r"```(?:python|py)?[ \t]*\n(.*?)```", answer, flags=re.S | re.I)
    if len(blocks) != 1 or len(re.findall(r"```", answer)) != 2:
        raise ValueError("Expected one unambiguous code block; raw response is preserved")
    source = blocks[0].strip() + "\n"
    if not source.strip() or len(source.encode()) > 65536:
        raise ValueError("Empty or oversized candidate")
    # Preserve syntax failures as executable-artifact outcomes, not extraction failures.
    return source


async def generate(out):
    plan = load_plan(out)
    evidence = plan.get("calibration")
    if not evidence or digest(evidence["path"]) != evidence["sha256"]:
        raise ValueError("Validated calibration must match the frozen source before paid generation")
    key = os.environ.get("DRIFT_API_KEY")
    if not key:
        raise ValueError("Set DRIFT_API_KEY locally. Do not paste it into chat.")
    ledger = Ledger(plan["ledger"], "50")
    for row in plan["rows"]:
        task = json.loads((out / "tasks" / row["task"] / "task.json").read_text())
        chain = out / "chains" / row["id"]
        chain.mkdir(parents=True, exist_ok=True)
        status_file = chain / "status.json"
        if status_file.exists():
            state = json.loads(status_file.read_text())
            for name, expected in state.get("artifact_hashes", {}).items():
                if digest(chain / name) != expected:
                    raise ValueError("Saved chain artifact changed: " + str(chain / name))
            if state["status"] in {"complete", "format_failure", "output_limit"}:
                continue
            if state["status"] != "between_hops":
                raise ValueError(f"Inspect stopped chain {row['id']}. No automatic retry is allowed.")
        else:
            (chain / "hop-000.py").write_text(task["reference"])
            dump(status_file, dict(status="between_hops", completed_hops=0))
        state = json.loads(status_file.read_text())
        for name, expected in state.get("artifact_hashes", {}).items():
            if digest(chain / name) != expected:
                raise ValueError("Saved chain artifact changed: " + str(chain / name))
        start = state["completed_hops"] + 1
        hashes = state.get("artifact_hashes", {"hop-000.py": digest(chain / "hop-000.py")})
        config = plan["configs"][row["family"]]
        trace = Trace(chain / "transport", chain / "workspace", secrets=[key])
        existing_events = trace.root / "events.jsonl"
        if existing_events.exists():
            trace.sequence = sum(1 for _ in existing_events.open())
        async with OpenRouterSession(config, key, trace, ledger, plan["study_id"] + ":" + row["id"]) as session:
            await session.preflight()
            for hop in range(start, plan["hops"] + 1):
                previous = (chain / f"hop-{hop-1:03}.py").read_text()
                prompt = messages(task, previous, row["condition"], hop, plan["sparse_reminder_hops"],
                                  plan.get("prompt_policy", "clarity_v1"))
                dump(chain / f"hop-{hop:03}-input.json", trace.redact(prompt))
                dump(status_file, dict(status="request_pending", completed_hops=hop-1, attempted_hop=hop,
                                       artifact_hashes=hashes))
                try:
                    answer = await session.complete(prompt)
                    (chain / f"hop-{hop:03}-response.txt").write_text(trace.redact(answer))
                    try:
                        source = extract(answer)
                    except ValueError as error:
                        dump(status_file, dict(status="format_failure", completed_hops=hop-1,
                                               attempted_hop=hop, message=str(error), artifact_hashes=hashes))
                        break
                    (chain / f"hop-{hop:03}.py").write_text(trace.redact(source))
                    hashes[f"hop-{hop:03}.py"] = digest(chain / f"hop-{hop:03}.py")
                    dump(status_file, dict(status="complete" if hop == plan["hops"] else "between_hops",
                                           completed_hops=hop, artifact_hashes=hashes))
                    print(json.dumps(dict(chain=row["id"], hop=hop, status="saved")), flush=True)
                except BaseException as error:
                    output_limit = (isinstance(error, RouterError) and error.category == "truncated_output"
                                    and settled_truncation(trace, ledger, config, plan["study_id"] + ":" + row["id"]))
                    dump(status_file, dict(status="output_limit" if output_limit else "request_stopped", completed_hops=hop-1,
                                           attempted_hop=hop, category=type(error).__name__,
                                           message=trace.redact(str(error)), artifact_hashes=hashes))
                    if output_limit:
                        print(json.dumps(dict(chain=row["id"], hop=hop, status="output_limit_no_retry")), flush=True)
                        break
                    raise


def docker_evaluate(path, task_id, image):
    command = ["docker", "run", "--rm", "--platform", "linux/amd64", "--network", "none",
               "--read-only", "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
               "--user", "65534:65534", "--pids-limit", "32", "--memory", "256m", "--cpus", "1",
               "--tmpfs", "/tmp:rw,noexec,nosuid,size=8m", "-e", "PYTHONDONTWRITEBYTECODE=1",
               "--mount", f"type=bind,source={HERE},target=/evaluation,readonly",
               "--mount", f"type=bind,source={path.parent},target=/candidate,readonly",
               "--entrypoint", "python", image, "/evaluation/worker.py", task_id]
    # Output goes to bounded, temporary files rather than unbounded capture buffers.
    with tempfile.TemporaryDirectory() as temporary:
        candidate = Path(temporary) / "solution.py"
        candidate.write_bytes(path.read_bytes())
        os.chmod(temporary, 0o755)
        # Mount only this one candidate, never the generation directory or credentials.
        command[command.index(f"type=bind,source={path.parent},target=/candidate,readonly")] = f"type=bind,source={temporary},target=/candidate,readonly"
        with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
            name = "drift-eval-" + uuid.uuid4().hex
            command[2:2] = ["--name", name]
            try:
                result = subprocess.run(command, stdout=stdout, stderr=stderr, timeout=30)
            except subprocess.TimeoutExpired:
                subprocess.run(["docker", "rm", "-f", name], capture_output=True, timeout=15)
                return dict(status="evaluation_timeout", all_pass=False, requirements={}, checks=[])
            stdout.seek(0)
            output = stdout.read(2 * 1024 * 1024)
            if result.returncode:
                stderr.seek(0)
                detail = stderr.read(1000).decode(errors="replace")
                if result.returncode in {125, 126, 127}:
                    raise RuntimeError("Evaluation infrastructure failed: " + detail)
                return dict(status="execution_resource_failure", exit_code=result.returncode,
                            all_pass=False, requirements={}, checks=[])
    try:
        parsed = json.loads(output)
    except ValueError:
        return dict(status="evaluation_output_error", all_pass=False, requirements={}, checks=[])
    if not isinstance(parsed, dict) or "status" not in parsed or "all_pass" not in parsed:
        return dict(status="evaluation_output_error", all_pass=False, requirements={}, checks=[])
    return parsed


def objective_met(source, task_id, hop):
    """Structural compliance only. This does not score semantic preservation."""
    try:
        tree = ast.parse(source)
    except (SyntaxError, RecursionError):
        return False
    name = "law" if task_id.startswith("etp_") else "permitted"
    functions = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name]
    if len(functions) != 1:
        return False
    fn = functions[0]
    returns = [n.value for n in ast.walk(fn) if isinstance(n, ast.Return)]
    if task_id == "permissions":
        if hop % 2:
            return len(returns) >= 5 and all(isinstance(n, ast.Constant) and type(n.value) is bool for n in returns)
        return bool(fn.body) and isinstance(fn.body[-1], ast.Return) and isinstance(fn.body[-1].value, ast.BoolOp)
    assignments = [n for n in ast.walk(fn) if isinstance(n, (ast.Assign, ast.AnnAssign, ast.AugAssign))]
    comparisons = [n for n in returns if isinstance(n, ast.Compare) and len(n.comparators) == 1]
    if not comparisons:
        return False
    if hop % 2:
        return len(assignments) >= 2 and isinstance(comparisons[-1].left, ast.Name) and isinstance(comparisons[-1].comparators[0], ast.Name)
    return not assignments and len(returns) == 1


def calibrate(out, image=IMAGE):
    """Run authored references and defects in the same isolated evaluator as candidates."""
    out.mkdir(parents=True, exist_ok=False)
    image_id = subprocess.check_output(["docker", "image", "inspect", "--format", "{{.Id}}", image], text=True).strip()
    report = dict(kind="authored_fixture_validation_not_model_results", image=image_id,
                  source_hashes=source_hashes(), ordinary={}, etp={})
    with tempfile.TemporaryDirectory() as temporary:
        path = Path(temporary) / "solution.py"
        for task in all_tasks().values():
            if task["track"] != "ordinary":
                continue
            results = []
            for code in [task["reference"]] + task["mutations"]:
                path.write_text(code)
                results.append(docker_evaluate(path, task["id"], image_id))
            if not results[0]["all_pass"] or any(r["all_pass"] for r in results[1:]):
                raise ValueError("Reference or controlled-defect calibration failed: " + task["id"])
            report["ordinary"][task["id"]] = dict(reference_pass=True,
                checks=len(results[0]["checks"]), requirements=results[0]["requirements"],
                controlled_defects_detected=len(results)-1,
                defect_categories=[sorted({c["category"] for c in r["checks"] if c["category"]}) for r in results[1:]])
    oracle = Oracle(REPO / "oracle", DATA)
    try:
        for task in all_tasks().values():
            if task["track"] == "etp":
                eq = decode(task["reference"])
                verdict = oracle.compare(eq, eq)
                if verdict["label"] != "equal":
                    raise ValueError("ETP reference did not map")
                report["etp"][task["id"]] = dict(equation=eq, node=verdict["intended"]["node"],
                    relation=verdict["label"], pointwise=pointwise_probe(eq, eq))
        report["etp_direction_checks"] = []
        for a, b, expected in [("x * y = x", "x * x = x", "weaker"),
                               ("x * x = x", "x * y = x", "stronger"),
                               ("x * y = x", "x * y = y", "incomparable")]:
            verdict = oracle.compare(a, b)
            if verdict["label"] != expected:
                raise ValueError("ETP directional calibration failed")
            report["etp_direction_checks"].append(verdict)
    finally:
        oracle.close()
    dump(out / "calibration.json", report)
    print(json.dumps(dict(status="calibration_passed", ordinary_tasks=4, controlled_defects=8,
                          etp_tasks=4, output=str(out / "calibration.json"))))


def summarize(out):
    plan = load_plan(out)
    records = json.loads((out / "evaluations.json").read_text())["records"]
    groups, chains = {}, []
    histories = defaultdict(list)
    for record in records:
        histories[record["id"]].append(record)
    for row in plan["rows"]:
        task = json.loads((out / "tasks" / row["task"] / "task.json").read_text())
        for hop in range(plan["hops"] + 1):
            key = (task["track"], row["family"], row["condition"], hop)
            group = groups.setdefault(key, dict(track=key[0], family=key[1], condition=key[2], hop=hop,
                                               planned=0, evaluated=0, all_checks_pass=0, unavailable=0))
            group["planned"] += 1
    for row in plan["rows"]:
        history = sorted(histories[row["id"]], key=lambda r: r["hop"])
        if not history:
            continue
        status_file = out / "chains" / row["id"] / "status.json"
        generation = json.loads(status_file.read_text()) if status_file.exists() else {"status": "not_started"}
        trajectory = {}
        for record in history:
            for requirement, value in record["result"].get("requirements", {}).items():
                trajectory.setdefault(requirement, []).append(dict(hop=record["hop"], outcome=value))
        transitions = {}
        for requirement, observations in trajectory.items():
            first_fail = next((v["hop"] for v in observations if v["outcome"] == "fail"), None)
            restored = next((v["hop"] for v in observations if first_fail is not None and
                             v["hop"] > first_fail and v["outcome"] == "pass"), None)
            transitions[requirement] = dict(first_observed_failure=first_fail,
                                           first_observed_restoration=restored, observations=observations)
        changes = sum(a["artifact_sha256"] != b["artifact_sha256"] for a, b in zip(history, history[1:]))
        chains.append(dict(**row, generation_status=generation["status"],
                           evaluated_hops=len(history)-1, changed_code_hops=changes,
                           first_nonpassing_checkpoint=next((r["hop"] for r in history if r["hop"] > 0
                                                            and not r["result"]["all_pass"]), None),
                           first_invalid_artifact=next((r["hop"] for r in history if r["hop"] > 0 and
                               r["result"]["status"] in {"syntax_failure", "execution_failure", "unsupported_code",
                                                          "execution_resource_failure", "evaluation_timeout",
                                                          "evaluation_output_error"}), None),
                           objective_outcomes=[dict(hop=r["hop"], met=r["result"]["objective_met"])
                                               for r in history if "objective_met" in r["result"]],
                           requirement_trajectories=transitions))
        for record in history:
            key = (record["track"], row["family"], row["condition"], record["hop"])
            group = groups[key]
            group["evaluated"] += 1
            group["all_checks_pass"] += bool(record["result"]["all_pass"])
            if "objective_met" in record["result"]:
                group["objective_evaluated"] = group.get("objective_evaluated", 0) + 1
                group["objective_met"] = group.get("objective_met", 0) + record["result"]["objective_met"]
    for group in groups.values():
        group["unavailable"] = group["planned"] - group["evaluated"]
    report = dict(groups=list(groups.values()), chains=chains,
                  scope="Descriptive results; chain checkpoints and test cases are not independent runs.",
                  incomplete_chains=sum(c["generation_status"] != "complete" for c in chains))
    dump(out / "summary.json", report)
    print(json.dumps(dict(status="summarized", chains=len(chains), output=str(out / "summary.json"))))


def evaluate(out):
    plan = load_plan(out)
    # Fail before evaluating candidates if Docker itself is unavailable.
    subprocess.run(["docker", "info"], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, check=True, timeout=20)
    image_id = subprocess.check_output(["docker", "image", "inspect", "--format", "{{.Id}}", plan["evaluation_image"]], text=True).strip()
    oracle = Oracle(REPO / "oracle", DATA)
    records = []
    try:
        for row in plan["rows"]:
            task = json.loads((out / "tasks" / row["task"] / "task.json").read_text())
            chain = out / "chains" / row["id"]
            # Evaluate starting references too, even before generation exists.
            previous_eq = None
            for hop in range(plan["hops"] + 1):
                path = out / "tasks" / row["task"] / "reference.py" if hop == 0 else chain / f"hop-{hop:03}.py"
                if not path.exists():
                    break
                if hop > 0:
                    state = json.loads((chain / "status.json").read_text())
                    if state.get("artifact_hashes", {}).get(path.name) != digest(path):
                        raise ValueError("Saved artifact lacks a matching generation checksum: " + str(path))
                if task["track"] == "ordinary":
                    result = docker_evaluate(path, row["task"], image_id)
                else:
                    try:
                        eq = decode(path.read_text())
                        original = decode(task["reference"])
                        versus_original = oracle.compare(original, eq)
                        result = dict(status="evaluated", equation=eq, versus_original=versus_original,
                                      versus_previous=oracle.compare(previous_eq, eq) if previous_eq else None,
                                      pointwise=pointwise_probe(original, eq),
                                      all_pass=versus_original["label"] in {"equal", "equivalent"})
                        result["requirements"] = {"R01": "pass" if result["all_pass"] else
                            "unknown" if versus_original["label"] in {"unknown", "outside-fragment"} else "fail",
                            "R02": "fail" if result["pointwise"]["status"] == "counterexample" else "finite_checks_pass",
                            "R03": "pass"}
                        result["all_pass"] &= result["pointwise"]["status"] != "counterexample"
                        previous_eq = eq
                    except (UnsupportedCode, RecursionError) as error:
                        result = dict(status="unsupported_code", reason=str(error), all_pass=False,
                                      requirements={"R01": "blocked", "R02": "blocked", "R03": "fail"})
                        previous_eq = None
                record = dict(**row, hop=hop, track=task["track"], artifact_sha256=digest(path), result=result)
                if hop > 0 and plan.get("prompt_policy") == TARGETED:
                    result["refactor_objective"] = OBJECTIVES[task["id"]][(hop - 1) % 2]
                    result["objective_met"] = objective_met(path.read_text(), task["id"], hop)
                records.append(record)
                if hop == 0 and not result["all_pass"]:
                    raise ValueError("Reference calibration failed: " + row["task"])
    finally:
        oracle.close()
    dump(out / "evaluations.json", dict(evaluation_image=image_id, records=records))
    # Flat JSONL supports plots without parsing nested run folders.
    with (out / "requirements.jsonl").open("w") as stream:
        for record in records:
            for requirement, outcome in record["result"].get("requirements", {}).items():
                stream.write(json.dumps({k: v for k, v in record.items() if k != "result"} |
                                        dict(requirement=requirement, outcome=outcome)) + "\n")
    print(json.dumps(dict(status="evaluated", artifacts=len(records), output=str(out / "evaluations.json"))))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["prepare", "generate", "evaluate", "calibrate", "summarize", "run", "recover"])
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--stage", choices=["integration", "pilot", "extended", "targeted", "targeted_long"], default="integration")
    parser.add_argument("--calibration", type=Path, help="Validated calibration record for this source version")
    parser.add_argument("--evaluation-image", default=IMAGE, help="Offline worker image used by calibrate")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--chain", help="Inspected stopped chain for explicit recovery")
    parser.add_argument("--request-id", help="Inspected reservation ID for explicit recovery")
    args = parser.parse_args()
    out = args.out.resolve()
    try:
        if args.command == "prepare":
            prepare(out, args.stage, args.calibration)
        elif args.command in {"generate", "run", "recover"}:
            if args.command != "recover" and not args.execute:
                raise ValueError("Paid generation requires --execute")
            plan = load_plan(out)
            lock_path = Path(plan["ledger"]).parent / "launcher.lock"
            lock_path.parent.mkdir(parents=True, exist_ok=True)
            with lock_path.open("a") as lock:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                if args.command == "recover":
                    if not args.chain or not args.request_id:
                        raise ValueError("Recovery requires --chain and --request-id; defaults to inspection only")
                    recover(out, plan, args.chain, args.request_id, args.execute)
                else:
                    asyncio.run(generate(out))
            if args.command == "run":
                evaluate(out)
                summarize(out)
        elif args.command == "evaluate":
            evaluate(out)
        elif args.command == "calibrate":
            calibrate(out, args.evaluation_image)
        else:
            summarize(out)
    except (ValueError, OSError, RuntimeError, subprocess.SubprocessError) as error:
        parser.exit(1, str(error) + "\n")


if __name__ == "__main__":
    main()
