#!/usr/bin/env python3
"""Typecheck generated declarations in one persistent Lean batch process."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
DEFAULT_INPUT = (
    REPO_ROOT
    / "results"
    / "statement_only"
    / "gpt-5.5"
    / "reasoning_none"
    / "generations.jsonl"
)
DEFAULT_LEAN_PROJECT = REPO_ROOT / "lean_checker"
LEAN_PREAMBLE = """\
import Mathlib

set_option linter.style.header false
"""


def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def die(message: str) -> None:
    print(message, file=sys.stderr)
    raise SystemExit(1)


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as f:
        for line_no, line in enumerate(f, start=1):
            if not line.strip():
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as exc:
                die(f"{path}:{line_no}: invalid JSON: {exc}")
    return rows


def append_jsonl(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def output_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def check_key(record: dict[str, Any]) -> tuple[str | None, str | None, str | None]:
    return (
        record.get("theorem_dataset_name") or record.get("name"),
        record.get("condition"),
        record.get("output_sha256"),
    )


def completed_checks(path: Path) -> set[tuple[str | None, str | None, str | None]]:
    if not path.exists():
        return set()
    return {check_key(record) for record in load_jsonl(path)}


def source_job(record: dict[str, Any], source_index: int) -> dict[str, Any] | None:
    if record.get("status") != "ok":
        return None
    output_text = (record.get("output_text") or "").strip()
    if not output_text:
        return None
    return {
        "source_index": source_index,
        "theorem_dataset_name": record.get("theorem_dataset_name") or record.get("name"),
        "condition": record.get("condition"),
        "model": record.get("model"),
        "prompt_version": record.get("prompt_version"),
        "output_sha256": output_hash(output_text),
        "output_text": output_text,
    }


def declaration_body(output_text: str) -> str:
    lines = [
        line
        for line in output_text.strip().splitlines()
        if not re.match(r"\s*import\s+\S+\s*$", line)
        and not re.match(
            r"\s*set_option\s+linter\.style\.header\s+false\s*$", line
        )
    ]
    return "\n".join(lines).strip()


def build_batch(jobs: list[dict[str, Any]]) -> tuple[str, list[tuple[int, int]]]:
    lines = LEAN_PREAMBLE.rstrip().splitlines()
    ranges: list[tuple[int, int]] = []

    for index, job in enumerate(jobs, start=1):
        lines.extend(["", f"-- LADR_BATCH_START {index}"])
        start_line = len(lines) + 1
        body_lines = declaration_body(job["output_text"]).splitlines()
        lines.extend(body_lines)
        end_line = len(lines)
        ranges.append((start_line, end_line))
        lines.append(f"-- LADR_BATCH_END {index}")

    return "\n".join(lines) + "\n", ranges


def parse_lean_json(stdout: str) -> tuple[list[dict[str, Any]], list[str]]:
    messages: list[dict[str, Any]] = []
    raw_lines: list[str] = []
    for line in stdout.splitlines():
        if not line.strip():
            continue
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            raw_lines.append(line)
            continue
        if isinstance(parsed, dict):
            messages.append(parsed)
        else:
            raw_lines.append(line)
    return messages, raw_lines


def message_line(message: dict[str, Any]) -> int | None:
    pos = message.get("pos")
    if not isinstance(pos, dict):
        return None
    line = pos.get("line")
    return line if isinstance(line, int) else None


def run_batch(
    jobs: list[dict[str, Any]], *, lean_project: Path, timeout: float
) -> list[dict[str, Any]]:
    code, ranges = build_batch(jobs)
    cmd = ["lake", "env", "lean", "--stdin", "--json"]

    try:
        proc = subprocess.run(
            cmd,
            cwd=lean_project,
            input=code,
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        return [
            {
                "lean_typechecked": False,
                "check_status": "timeout",
                "returncode": None,
                "timeout_seconds": timeout,
                "messages": [],
                "stdout_raw": exc.stdout or "",
                "stderr": exc.stderr or "",
            }
            for _ in jobs
        ]

    messages, raw_lines = parse_lean_json(proc.stdout)
    by_job: list[list[dict[str, Any]]] = [[] for _ in jobs]
    global_messages: list[dict[str, Any]] = []

    for message in messages:
        line = message_line(message)
        owner = None
        if line is not None:
            for index, (start, end) in enumerate(ranges):
                if start <= line <= end:
                    owner = index
                    break
        if owner is None:
            global_messages.append(message)
        else:
            by_job[owner].append(message)

    global_errors = [
        message for message in global_messages if message.get("severity") == "error"
    ]
    unmapped_failure = proc.returncode != 0 and not any(
        message.get("severity") == "error"
        for job_messages in by_job
        for message in job_messages
    )

    results: list[dict[str, Any]] = []
    for job_messages in by_job:
        errors = [
            message for message in job_messages if message.get("severity") == "error"
        ]
        if global_errors or unmapped_failure:
            errors = errors or global_errors or [{"data": proc.stderr or "Lean batch failed"}]
        passed = not errors
        results.append(
            {
                "lean_typechecked": passed,
                "check_status": "ok" if passed else "error",
                "returncode": 0 if passed else 1,
                "messages": job_messages + global_errors,
                "stdout_raw": "\n".join(raw_lines) if not passed else "",
                "stderr": proc.stderr if not passed else "",
                "batch_returncode": proc.returncode,
                "batch_size": len(jobs),
            }
        )
    return results


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Typecheck generated Lean records in one Lean process."
    )
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--lean-project", type=Path, default=DEFAULT_LEAN_PROJECT)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--timeout", type=float, default=1800.0)
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite the checked output file instead of resuming.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    input_path = args.input if args.input.is_absolute() else REPO_ROOT / args.input
    output_arg = args.output or (input_path.parent / "lean_checks.jsonl")
    output_path = output_arg if output_arg.is_absolute() else REPO_ROOT / output_arg
    lean_project = (
        args.lean_project if args.lean_project.is_absolute() else REPO_ROOT / args.lean_project
    )

    if not input_path.exists():
        die(f"Input file not found: {input_path}")
    if not lean_project.exists():
        die(f"Lean checker project not found: {lean_project}")
    if args.force and output_path.exists():
        output_path.unlink()

    source_rows = load_jsonl(input_path)
    jobs = [
        job
        for index, record in enumerate(source_rows, start=1)
        if (job := source_job(record, index)) is not None
    ]
    if args.limit is not None:
        jobs = jobs[: args.limit]

    done = completed_checks(output_path)
    pending_jobs = [job for job in jobs if check_key(job) not in done]
    print(f"Input: {input_path}")
    print(f"Output: {output_path}")
    print(f"Lean project: {lean_project}")
    print(f"Candidate records: {len(jobs)}")
    print(f"Skipping {len(jobs) - len(pending_jobs)} completed checks")
    print(f"Lean processes: {1 if pending_jobs else 0}")

    if not pending_jobs:
        print("Done.")
        print("New checks: {}")
        return

    print(f"Starting one Lean process for {len(pending_jobs)} declarations...")
    batch_results = run_batch(
        pending_jobs,
        lean_project=lean_project,
        timeout=args.timeout,
    )

    summary: Counter[str] = Counter()
    by_condition: dict[str, Counter[str]] = defaultdict(Counter)
    checked_at = iso_now()

    for index, (job, result) in enumerate(
        zip(pending_jobs, batch_results), start=1
    ):
        record = {
            "checked_at": checked_at,
            "source_index": job["source_index"],
            "theorem_dataset_name": job["theorem_dataset_name"],
            "condition": job["condition"],
            "model": job["model"],
            "prompt_version": job["prompt_version"],
            "output_sha256": job["output_sha256"],
            "lean_preamble": LEAN_PREAMBLE.strip(),
            **result,
        }
        append_jsonl(output_path, record)
        status = record["check_status"]
        summary[status] += 1
        by_condition[str(job["condition"])][status] += 1
        print(f"[{index}/{len(pending_jobs)}] {job['theorem_dataset_name']}: {status}")

    print("Done.")
    print("New checks:", dict(summary))
    for condition in sorted(by_condition):
        print(f"{condition}: {dict(by_condition[condition])}")


if __name__ == "__main__":
    main()
