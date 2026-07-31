#!/usr/bin/env python3
"""Legacy compiler-feedback repair experiment; excluded from current runs."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None  # type: ignore[assignment]

try:
    from openai import OpenAI
except ImportError:
    OpenAI = None  # type: ignore[assignment]


SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
DEFAULT_INPUT = REPO_ROOT / "LADR_all_material" / "LADR_thms_256.jsonl"
DEFAULT_RESULTS_ROOT = REPO_ROOT / "results"
DEFAULT_LEAN_PROJECT = REPO_ROOT / "lean_checker"
DEFAULT_MODEL = "gpt-5.5"
DEFAULT_REASONING_EFFORT = "none"
REASONING_EFFORTS = ("none", "low", "medium", "high", "xhigh")

CONDITIONS = ("statement_only", "statement_plus_proof")
PROMPT_VERSION = "ladr_statement_repair_agent_v3"
SYSTEM_PROMPT = (
    "Return only one complete Lean 4 file. The first non-empty line must be "
    "`import Mathlib`. Do not use Markdown or explanations outside Lean code."
)
LEAN_PREAMBLE = """\
import Mathlib

set_option linter.style.header false

"""

BASE_RULES = """\
Requirements:
- Start the file with `import Mathlib`.
- Then include `set_option linter.style.header false`.
- Put any Lean comments only after the import line.
- Name the theorem `{name}`.
- Include exactly one Lean `theorem` declaration.
- The theorem declaration should end with `:= by sorry`.
- Return only the complete Lean file.
"""

INITIAL_PROMPT = """\
Formalize the LADR theorem below as one Lean 4 theorem statement.

{rules}
{proof_rule}

Dataset: {dataset}
Theorem dataset name: {name}
Natural-language theorem:
{nl_statement}
{proof_block}"""

REPAIR_FEEDBACK = """\
{validation_feedback}Lean 4 output:
{lean_output}
"""


def die(message: str) -> None:
    print(message, file=sys.stderr)
    raise SystemExit(1)


def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


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


def default_output_path(model: str, reasoning_effort: str) -> Path:
    model_dir = model.replace("/", "__")
    return (
        DEFAULT_RESULTS_ROOT
        / "repair_agent_ab"
        / model_dir
        / f"reasoning_{reasoning_effort}"
        / "results.jsonl"
    )


def output_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def clean_model_text(text: str) -> str:
    text = text.strip()
    fence = re.fullmatch(r"```(?:lean)?\s*(.*?)```", text, flags=re.DOTALL)
    if fence:
        return fence.group(1).strip()
    return text


def lean_input(output_text: str) -> str:
    text = output_text.strip()
    lines = [
        line
        for line in text.splitlines()
        if not re.match(r"\s*import\s+\S+\s*$", line)
        and not re.match(r"\s*set_option\s+linter\.style\.header\s+false\s*$", line)
    ]
    body = "\n".join(lines).strip()
    return LEAN_PREAMBLE + body + "\n"


def validate_output(text: str, expected_name: str | None) -> dict[str, Any]:
    declaration_names = re.findall(r"(?m)^\s*(?:theorem|lemma)\s+([^\s:]+)", text)
    starts_with_import = text.lstrip().startswith("import Mathlib")
    has_sorry_stub = ":= by sorry" in text
    actual_name = declaration_names[0] if len(declaration_names) == 1 else None
    notes: list[str] = []
    if not starts_with_import:
        notes.append("file must start with 'import Mathlib'")
    if len(declaration_names) != 1:
        notes.append(f"expected one theorem/lemma declaration, found {len(declaration_names)}")
    if expected_name and actual_name != expected_name:
        notes.append(f"declaration name {actual_name!r} does not match {expected_name!r}")
    if not has_sorry_stub:
        notes.append("missing ':= by sorry'")
    return {
        "has_sorry_stub": has_sorry_stub,
        "starts_with_import_mathlib": starts_with_import,
        "declaration_count": len(declaration_names),
        "expected_name": expected_name,
        "actual_name": actual_name,
        "name_matches": bool(expected_name) and actual_name == expected_name,
        "passed_basic_checks": starts_with_import
        and len(declaration_names) == 1
        and has_sorry_stub
        and bool(expected_name)
        and actual_name == expected_name,
        "notes": notes,
    }


def render_condition_parts(row: dict[str, Any], condition: str) -> tuple[str, str]:
    if condition == "statement_only":
        return "", ""
    if condition != "statement_plus_proof":
        raise ValueError(f"unknown condition: {condition}")

    informal_proof = (row.get("informal_proof") or "").strip()
    if not informal_proof:
        raise ValueError(f"{row.get('name')}: statement_plus_proof requires informal_proof")
    proof_rule = (
        "- Use the informal proof only to disambiguate the theorem statement; "
        "do not formalize the proof."
    )
    proof_block = f"\nInformal proof:\n{informal_proof}\n"
    return proof_rule, proof_block


def render_initial_prompt(row: dict[str, Any], condition: str) -> str:
    proof_rule, proof_block = render_condition_parts(row, condition)
    return INITIAL_PROMPT.format(
        rules=BASE_RULES.format(name=row["name"]),
        proof_rule=proof_rule,
        dataset=row.get("domain") or "LADR",
        name=row["name"],
        nl_statement=row["nl_statement"],
        proof_block=proof_block,
    )


def initial_messages(row: dict[str, Any], condition: str) -> list[dict[str, str]]:
    return [{"role": "user", "content": render_initial_prompt(row, condition)}]


def validation_feedback(validation: dict[str, Any]) -> str:
    notes = validation.get("notes") or []
    if not notes:
        return ""
    rendered = "\n".join(f"- {note}" for note in notes)
    return f"Format validation:\n{rendered}\n\n"


def lean_feedback(lean_result: dict[str, Any]) -> str:
    message_texts = [
        str(message.get("data") or "").strip()
        for message in lean_result.get("messages") or []
        if str(message.get("data") or "").strip()
    ]
    if message_texts:
        return "\n\n".join(message_texts)

    fallback = str(
        lean_result.get("error_text")
        or lean_result.get("stderr")
        or lean_result.get("stdout_raw")
        or ""
    ).strip()
    if fallback:
        return fallback
    return "No Lean errors, but the output failed format validation."


def render_repair_feedback(validation: dict[str, Any], lean_result: dict[str, Any]) -> str:
    return REPAIR_FEEDBACK.format(
        validation_feedback=validation_feedback(validation),
        lean_output=lean_feedback(lean_result)[:6000],
    )


def extract_response_text(response: Any) -> str:
    output_text = getattr(response, "output_text", None)
    if output_text:
        return output_text.strip()

    parts: list[str] = []
    for item in getattr(response, "output", []) or []:
        if getattr(item, "type", None) != "message":
            continue
        for content in getattr(item, "content", []) or []:
            text = getattr(content, "text", None)
            if text:
                parts.append(text)
    return "\n".join(parts).strip()


def call_openai(
    client: Any,
    *,
    model: str,
    messages: list[dict[str, str]],
    max_tokens: int,
    reasoning_effort: str,
    temperature: float | None,
) -> tuple[str, dict[str, Any] | None]:
    kwargs: dict[str, Any] = {
        "model": model,
        "instructions": SYSTEM_PROMPT,
        "input": messages,
        "max_output_tokens": max_tokens,
        "reasoning": {"effort": reasoning_effort},
    }
    if temperature is not None:
        kwargs["temperature"] = temperature

    response = client.responses.create(**kwargs)
    usage = getattr(response, "usage", None)
    usage_dict = None
    if usage is not None:
        usage_dict = {
            "input_tokens": getattr(usage, "input_tokens", None),
            "output_tokens": getattr(usage, "output_tokens", None),
            "total_tokens": getattr(usage, "total_tokens", None),
        }
    text = clean_model_text(extract_response_text(response))
    if not text:
        # Reasoning models spend max_output_tokens on hidden reasoning; if the
        # budget runs out the response comes back incomplete with empty text.
        status = getattr(response, "status", None)
        details = getattr(response, "incomplete_details", None)
        reason = getattr(details, "reason", None) if details is not None else None
        raise RuntimeError(
            f"empty model response (status={status}, reason={reason}); "
            "consider raising --max-tokens"
        )
    return text, usage_dict


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


def run_lean(code: str, *, lean_project: Path, timeout: float) -> dict[str, Any]:
    try:
        proc = subprocess.run(
            ["lake", "env", "lean", "--stdin", "--json"],
            cwd=lean_project,
            input=code,
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        return {
            "lean_typechecked": False,
            "check_status": "timeout",
            "returncode": None,
            "messages": [],
            "stdout_raw": exc.stdout or "",
            "stderr": exc.stderr or "",
            "error_text": f"Lean timed out after {timeout} seconds.",
        }

    messages, raw_lines = parse_lean_json(proc.stdout)
    return {
        "lean_typechecked": proc.returncode == 0,
        "check_status": "ok" if proc.returncode == 0 else "error",
        "returncode": proc.returncode,
        "messages": messages,
        "stdout_raw": "\n".join(raw_lines),
        "stderr": proc.stderr,
        "error_text": first_lean_error(messages, proc.stderr, "\n".join(raw_lines)),
    }


def first_lean_error(messages: list[dict[str, Any]], stderr: str, stdout_raw: str) -> str:
    for message in messages:
        if message.get("severity") == "error":
            return str(message.get("data") or "")
    return stderr or stdout_raw


def job_key(record: dict[str, Any]) -> tuple[str | None, str | None]:
    return record.get("theorem_dataset_name") or record.get("name"), record.get("condition")


def completed_jobs(path: Path) -> set[tuple[str | None, str | None]]:
    if not path.exists():
        return set()
    done: set[tuple[str | None, str | None]] = set()
    for record in load_jsonl(path):
        if record.get("status") in {"ok", "failed"}:
            done.add(job_key(record))
    return done


def iter_jobs(rows: list[dict[str, Any]], conditions: tuple[str, ...]) -> list[tuple[dict[str, Any], str]]:
    return [(row, condition) for row in rows for condition in conditions]


def run_agent_job(
    client: Any,
    row: dict[str, Any],
    condition: str,
    *,
    args: argparse.Namespace,
    lean_project: Path,
) -> dict[str, Any]:
    attempts: list[dict[str, Any]] = []
    messages = initial_messages(row, condition)
    final_code = ""
    final_lean: dict[str, Any] | None = None
    final_validation: dict[str, Any] | None = None

    for attempt_no in range(1, args.max_iters + 1):
        input_message_count = len(messages)
        output_text, usage = call_openai(
            client,
            model=args.model,
            messages=messages,
            max_tokens=args.max_tokens,
            reasoning_effort=args.reasoning_effort,
            temperature=args.temperature,
        )
        validation = validate_output(output_text, row.get("name"))
        lean_result = run_lean(lean_input(output_text), lean_project=lean_project, timeout=args.timeout)
        final_code = output_text
        final_lean = lean_result
        final_validation = validation
        messages.append({"role": "assistant", "content": output_text})

        attempts.append(
            {
                "attempt": attempt_no,
                "input_message_count": input_message_count,
                "output_text": output_text,
                "output_sha256": output_hash(output_text),
                "usage": usage,
                "validation": validation,
                "lean": lean_result,
            }
        )

        if validation["passed_basic_checks"] and lean_result["lean_typechecked"]:
            break

        if attempt_no < args.max_iters:
            messages.append(
                {
                    "role": "user",
                    "content": render_repair_feedback(validation, lean_result),
                }
            )
            if args.sleep > 0:
                time.sleep(args.sleep)

    assert final_lean is not None
    assert final_validation is not None
    passed = final_validation["passed_basic_checks"] and final_lean["lean_typechecked"]
    return {
        "created_at": iso_now(),
        "prompt_version": PROMPT_VERSION,
        "condition": condition,
        "theorem_dataset_name": row.get("name"),
        "dataset": row.get("domain") or "LADR",
        "input_row": row,
        "model": args.model,
        "reasoning_effort": args.reasoning_effort,
        "temperature": args.temperature,
        "max_tokens": args.max_tokens,
        "max_iters": args.max_iters,
        "status": "ok" if passed else "failed",
        "lean_typechecked": final_lean["lean_typechecked"],
        "final_validation": final_validation,
        "attempt_count": len(attempts),
        "final_output_text": final_code,
        "final_output_sha256": output_hash(final_code),
        "message_history": messages,
        "attempts": attempts,
    }


def load_environment() -> None:
    if load_dotenv is not None:
        load_dotenv(REPO_ROOT / ".env", override=True)


def make_client() -> Any:
    if OpenAI is None:
        die("Missing dependency: openai. Install dependencies with `pip install -r requirements.txt`.")
    if not os.environ.get("OPENAI_API_KEY"):
        extra = ""
        if load_dotenv is None:
            extra = " python-dotenv is also missing, so .env files cannot be loaded."
        die("OPENAI_API_KEY is not set. Export it or add it to repo `.env`." + extra)
    return OpenAI()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate Lean statements, run Lean, and repair with compiler feedback."
    )
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--lean-project", type=Path, default=DEFAULT_LEAN_PROJECT)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument(
        "--reasoning-effort",
        choices=REASONING_EFFORTS,
        default=DEFAULT_REASONING_EFFORT,
    )
    parser.add_argument("--max-tokens", type=int, default=16000)
    parser.add_argument("--temperature", type=float, default=None)
    parser.add_argument("--max-iters", type=int, default=3)
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument("--sleep", type=float, default=0.2)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--condition", choices=CONDITIONS, default=None)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    input_path = args.input if args.input.is_absolute() else REPO_ROOT / args.input
    output_arg = args.output or default_output_path(args.model, args.reasoning_effort)
    output_path = output_arg if output_arg.is_absolute() else REPO_ROOT / output_arg
    lean_project = args.lean_project if args.lean_project.is_absolute() else REPO_ROOT / args.lean_project

    if not input_path.exists():
        die(f"Input file not found: {input_path}")
    if not lean_project.exists():
        die(f"Lean checker project not found: {lean_project}")
    if args.force and output_path.exists():
        output_path.unlink()

    rows = load_jsonl(input_path)
    conditions = (args.condition,) if args.condition else CONDITIONS
    jobs = iter_jobs(rows, conditions)
    if args.limit is not None:
        jobs = jobs[: args.limit]

    print(f"Input: {input_path}")
    print(f"Output: {output_path}")
    print(f"Model: {args.model}")
    print(f"Reasoning effort: {args.reasoning_effort}")
    print(f"Lean project: {lean_project}")
    print(f"Jobs: {len(jobs)}")
    print(f"Max repair iterations per job: {args.max_iters}")

    if args.dry_run:
        for index, (row, condition) in enumerate(jobs[: min(2, len(jobs))], start=1):
            print(f"\n--- dry run prompt {index}: {row.get('name')} / {condition} ---")
            print(render_initial_prompt(row, condition))
        return

    load_environment()
    client = make_client()
    done = completed_jobs(output_path)
    print(f"Skipping {len(done)} completed jobs")

    summary: Counter[str] = Counter()
    by_condition: dict[str, Counter[str]] = defaultdict(Counter)
    for index, (row, condition) in enumerate(jobs, start=1):
        key = (row.get("name"), condition)
        label = f"{row.get('name')} / {condition}"
        if key in done:
            print(f"[{index}/{len(jobs)}] skip {label}")
            continue

        print(f"[{index}/{len(jobs)}] agent {label}")
        try:
            record = run_agent_job(client, row, condition, args=args, lean_project=lean_project)
        except Exception as exc:  # noqa: BLE001 - preserve failed job history in JSONL.
            record = {
                "created_at": iso_now(),
                "prompt_version": PROMPT_VERSION,
                "condition": condition,
                "theorem_dataset_name": row.get("name"),
                "dataset": row.get("domain") or "LADR",
                "input_row": row,
                "model": args.model,
                "reasoning_effort": args.reasoning_effort,
                "status": "error",
                "lean_typechecked": False,
                "attempt_count": 0,
                "error": str(exc),
            }
            print(f"  error: {exc}", file=sys.stderr)

        append_jsonl(output_path, record)
        status = record["status"]
        summary[status] += 1
        by_condition[condition][status] += 1
        print(f"  {status} after {record.get('attempt_count')} attempt(s)")
        if args.sleep > 0:
            time.sleep(args.sleep)

    print("Done.")
    print("New jobs:", dict(summary))
    for condition in sorted(by_condition):
        print(f"{condition}: {dict(by_condition[condition])}")


if __name__ == "__main__":
    main()
