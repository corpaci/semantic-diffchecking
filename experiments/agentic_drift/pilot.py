"""Launch one frozen pilot condition. The API key is supplied only at execution time."""
import argparse
import json
import os
import subprocess
from pathlib import Path

from .case import CASE, sha
from .openrouter import validate_config
from .contract import NONE, POLICIES

ROOT = Path(__file__).resolve().parent
IMAGE = "semantic-drift-metagpt:0.8.2"


def launch(case, condition, out, config, execute, contract_policy=NONE):
    if contract_policy not in POLICIES or (condition == "direct" and contract_policy != NONE):
        raise ValueError("Invalid contract policy for this condition")
    if not execute:
        raise ValueError("No model requests were sent. Live execution requires --execute.")
    if not os.environ.get("DRIFT_API_KEY"):
        raise ValueError("Set DRIFT_API_KEY locally as the final step; do not paste it into chat.")
    case, out, config = Path(case).resolve(), Path(out).resolve(), Path(config).resolve()
    frozen = json.loads((case / "frozen_case.json").read_text())
    for path, field in [(case / "public_task.json", "public_task_sha256"),
                        (CASE / "requirements.json", "requirements_sha256"), (CASE / "checks.py", "checks_sha256")]:
        if sha(path) != frozen[field]:
            raise ValueError(f"Frozen input changed: {path.name}. Prepare a new case version before generation.")
    settings = json.loads(config.read_text())
    validate_config(settings)
    if sha(config) != frozen.get("openrouter_config_sha256"):
        raise ValueError("Model configuration differs from the frozen case. Prepare a new case before either condition.")
    if out.exists():
        raise FileExistsError("Run output already exists. Preserve it and use a new run ID.")
    # Check that the image contains exactly the Python code being reviewed here.
    script = "import pathlib,json,hashlib; p=pathlib.Path('/experiment/experiments/agentic_drift'); print(json.dumps({f.name:hashlib.sha256(f.read_bytes()).hexdigest() for f in p.glob('*.py')}))"
    result = subprocess.run(["docker", "run", "--rm", "--platform", "linux/amd64", "--network", "none",
                             "--entrypoint", "python", IMAGE, "-c", script], check=True, capture_output=True, text=True)
    image_hashes = json.loads(result.stdout)
    local_hashes = {p.name: sha(p) for p in ROOT.glob("*.py")}
    if image_hashes != local_hashes:
        raise ValueError("Docker code differs from local code. Rebuild the image before paid execution.")
    out.mkdir(parents=True, exist_ok=False)
    budget = ROOT / "runs" / "openrouter-budget"
    budget.mkdir(parents=True, exist_ok=True)
    command = ["docker", "run", "--rm", "--platform", "linux/amd64", "--cap-drop", "ALL",
        "--security-opt", "no-new-privileges", "--pids-limit", "128", "--memory", "2g", "--cpus", "2",
        "-e", "DRIFT_API_KEY", "--mount", f"type=bind,source={case / 'public_task.json'},target=/inputs/task.json,readonly",
        "--mount", f"type=bind,source={config},target=/inputs/openrouter.json,readonly",
        "--mount", f"type=bind,source={out},target=/outputs",
        "--mount", f"type=bind,source={budget},target=/budget", IMAGE, "run", "--condition", condition,
        "--router-config", "/inputs/openrouter.json", "--ledger", "/budget/spend.json",
        "--input", "/inputs/task.json", "--out", "/outputs/run", "--execute"]
    command += ["--contract-policy", contract_policy]
    # No evaluation data, reference implementation, test checks, or host credentials are mounted.
    completed = subprocess.run(command, check=False)
    if completed.returncode:
        status_path = out / "run" / "status.json"
        if status_path.exists():
            status = json.loads(status_path.read_text())
            raise ValueError(f"Run failed: {status.get('message') or status.get('category', 'unknown_error')}. "
                             f"Saved artifacts: {out / 'run'}. Preserve this folder; do not retry automatically.")
        raise ValueError(f"Container exited with status {completed.returncode}. Inspect the terminal output. "
                         f"Preserved output folder: {out}")
    print("Saved run: " + str(out / "run"))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--case", required=True)
    p.add_argument("--condition", choices=["direct", "metagpt"], required=True)
    p.add_argument("--contract-policy", choices=POLICIES, default=NONE)
    p.add_argument("--out", required=True)
    p.add_argument("--config", default=str(ROOT / "openrouter_config.json"))
    p.add_argument("--execute", action="store_true")
    a = p.parse_args()
    try:
        launch(a.case, a.condition, a.out, a.config, a.execute, a.contract_policy)
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        p.exit(1, str(error) + "\n")


if __name__ == "__main__":
    main()
