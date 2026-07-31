#!/usr/bin/env python3
"""Shared infrastructure for the two one-shot statement experiments.

Use statement_only.py or statement_plus_proof.py instead of running this module
directly.
"""

from __future__ import annotations

import argparse
import json
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

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
DEFAULT_MODEL = "gpt-5.5"
DEFAULT_REASONING_EFFORT = "none"
REASONING_EFFORTS = ("none", "low", "medium", "high", "xhigh")

CONDITIONS = ("statement_only", "statement_plus_proof")
PROMPT_VERSION = "ladr_statement_v5"
SYSTEM_PROMPT = (
    "Return only one complete Lean 4 file. The first non-empty line must be "
    "`import Mathlib`. Do not use Markdown or explanations outside Lean code."
)


def die(message: str) -> None:
    print(message, file=sys.stderr)
    raise SystemExit(1)


def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as f:
        for line_no, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{line_no}: invalid JSON: {exc}") from exc
    return rows


def append_jsonl(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def default_output_path(condition: str, model: str, reasoning_effort: str) -> Path:
    model_dir = model.replace("/", "__")
    return (
        DEFAULT_RESULTS_ROOT
        / condition
        / model_dir
        / f"reasoning_{reasoning_effort}"
        / "generations.jsonl"
    )


def completed_jobs(path: Path) -> set[tuple[str, str]]:
    if not path.exists():
        return set()

    done: set[tuple[str, str]] = set()
    with path.open(encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if record.get("status") != "ok":
                continue
            name = record.get("theorem_dataset_name") or record.get("name")
            condition = record.get("condition")
            if name and condition:
                done.add((name, condition))
    return done



def iter_jobs(
    rows: list[dict[str, Any]], condition: str
) -> list[tuple[dict[str, Any], str]]:
    return [(row, condition) for row in rows]


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
    prompt: str,
    max_tokens: int,
    reasoning_effort: str,
    temperature: float | None,
    instructions: str = SYSTEM_PROMPT,
) -> tuple[str, dict[str, Any] | None]:
    kwargs: dict[str, Any] = {
        "model": model,
        "instructions": instructions,
        "input": prompt,
        "max_output_tokens": max_tokens,
        "reasoning": {"effort": reasoning_effort},
    }
    if temperature is not None:
        kwargs["temperature"] = temperature

    response = client.responses.create(**kwargs)
    usage = getattr(response, "usage", None)
    usage_dict = None
    if usage is not None:
        if hasattr(usage, "model_dump"):
            usage_dict = usage.model_dump()
        elif hasattr(usage, "to_dict"):
            usage_dict = usage.to_dict()
        else:
            usage_dict = {
                "input_tokens": getattr(usage, "input_tokens", None),
                "output_tokens": getattr(usage, "output_tokens", None),
                "total_tokens": getattr(usage, "total_tokens", None),
            }
    text = extract_response_text(response)
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


def validate_output(text: str, expected_name: str | None) -> dict[str, Any]:
    declaration_names = re.findall(r"(?m)^\s*(?:theorem|lemma)\s+([^\s:]+)", text)
    starts_with_import = text.lstrip().startswith("import Mathlib")
    has_sorry_stub = bool(re.search(r":=\s*by\s+sorry\b", text))
    actual_name = declaration_names[0] if len(declaration_names) == 1 else None
    name_matches = bool(expected_name) and actual_name == expected_name
    notes: list[str] = []
    if not starts_with_import:
        notes.append("file must start with 'import Mathlib'")
    if not has_sorry_stub:
        notes.append("missing ':= by sorry'")
    if len(declaration_names) != 1:
        notes.append(
            f"expected one theorem/lemma declaration, found {len(declaration_names)}"
        )
    elif not name_matches:
        notes.append(f"declaration name {actual_name!r} does not match {expected_name!r}")

    return {
        "has_sorry_stub": has_sorry_stub,
        "starts_with_import_mathlib": starts_with_import,
        "theorem_or_lemma_declaration_count": len(declaration_names),
        "expected_declaration_name": expected_name,
        "actual_declaration_name": actual_name,
        "declaration_name_matches_input": name_matches,
        "passed_basic_checks": starts_with_import
        and has_sorry_stub
        and len(declaration_names) == 1
        and name_matches,
        "notes": notes,
        "lean_typechecked": False,
    }


def base_record(
    *,
    row: dict[str, Any],
    condition: str,
    prompt: str,
    args: argparse.Namespace,
) -> dict[str, Any]:
    return {
        "created_at": iso_now(),
        "prompt_version": PROMPT_VERSION,
        "condition": condition,
        "theorem_dataset_name": row.get("name"),
        "dataset": row.get("domain") or "LADR",
        "input_row": row,
        "system_prompt": SYSTEM_PROMPT,
        "prompt": prompt,
        "model": args.model,
        "reasoning_effort": args.reasoning_effort,
        "temperature": args.temperature,
        "max_tokens": args.max_tokens,
        "output_text": None,
        "validation": None,
        "status": "pending",
        "error": None,
    }


def parse_args(condition: str) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=f"Run the LADR {condition} generation experiment."
    )
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument(
        "--reasoning-effort",
        choices=REASONING_EFFORTS,
        default=DEFAULT_REASONING_EFFORT,
    )
    parser.add_argument("--max-tokens", type=int, default=16000)
    parser.add_argument("--temperature", type=float, default=None)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--sleep", type=float, default=0.2)
    parser.add_argument("--max-workers", type=int, default=1)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--dry-run-count", type=int, default=4)
    return parser.parse_args()


def load_environment() -> None:
    if load_dotenv is not None:
        load_dotenv(REPO_ROOT / ".env", override=True)


def make_client() -> Any:
    if OpenAI is None:
        die(
            "Missing dependency: openai. Install dependencies with "
            "`pip install -r requirements.txt`."
        )
    if not os.environ.get("OPENAI_API_KEY"):
        extra = ""
        if load_dotenv is None:
            extra = " python-dotenv is also missing, so .env files cannot be loaded."
        die(
            "OPENAI_API_KEY is not set. Export it in the environment or add it to "
            f"{REPO_ROOT / '.env'}." + extra
        )
    return OpenAI(timeout=600.0, max_retries=0)


def run_experiment(
    condition: str,
    prompt_builder: Callable[[dict[str, Any]], str],
) -> None:
    if condition not in CONDITIONS:
        die(f"unknown statement experiment: {condition}")

    args = parse_args(condition)
    input_path = args.input if args.input.is_absolute() else REPO_ROOT / args.input
    output_arg = args.output or default_output_path(
        condition, args.model, args.reasoning_effort
    )
    output_path = output_arg if output_arg.is_absolute() else REPO_ROOT / output_arg

    if not input_path.exists():
        die(f"Input file not found: {input_path}")
    if args.max_workers < 1:
        die("--max-workers must be at least 1")

    load_environment()
    rows = load_jsonl(input_path)
    if args.limit is not None:
        rows = rows[: args.limit]

    jobs = iter_jobs(rows, condition)
    if args.dry_run:
        print(f"Dry run: showing {min(args.dry_run_count, len(jobs))} rendered prompts")
        print(f"Experiment: {condition}")
        print(f"Input: {input_path}")
        print(f"Output: {output_path}")
        print(f"Model: {args.model}")
        print(f"Reasoning effort: {args.reasoning_effort}")
        print(f"Max workers: {args.max_workers}")
        for index, (row, _) in enumerate(jobs[: args.dry_run_count], start=1):
            prompt = prompt_builder(row)
            print(f"\n--- prompt {index}: {row.get('name')} ---")
            print("SYSTEM:")
            print(SYSTEM_PROMPT)
            print("USER:")
            print(prompt)
        return

    client = make_client()
    done = completed_jobs(output_path)
    pending_rows = [row for row, _ in jobs if (row.get("name"), condition) not in done]

    print(f"Experiment: {condition}")
    print(f"Input: {input_path}")
    print(f"Output: {output_path}")
    print(f"Model: {args.model}")
    print(f"Reasoning effort: {args.reasoning_effort}")
    print(f"Max workers: {args.max_workers}")
    print(f"Skipping {len(done)} completed records")
    print(f"Requests to make: {len(pending_rows)}")

    def generate_one(row: dict[str, Any]) -> dict[str, Any]:
        prompt = ""
        try:
            prompt = prompt_builder(row)
            record = base_record(row=row, condition=condition, prompt=prompt, args=args)
            output_text, usage = call_openai(
                client,
                model=args.model,
                prompt=prompt,
                max_tokens=args.max_tokens,
                reasoning_effort=args.reasoning_effort,
                temperature=args.temperature,
            )
            record["output_text"] = output_text
            record["usage"] = usage
            record["validation"] = validate_output(output_text, row.get("name"))
            record["status"] = "ok"
        except Exception as exc:  # noqa: BLE001 - preserve failures in JSONL.
            record = base_record(row=row, condition=condition, prompt=prompt, args=args)
            record["status"] = "error"
            record["error"] = str(exc)
        if args.sleep > 0:
            time.sleep(args.sleep)
        return record

    with ThreadPoolExecutor(max_workers=args.max_workers) as executor:
        futures = {executor.submit(generate_one, row): row for row in pending_rows}
        for completed, future in enumerate(as_completed(futures), start=1):
            row = futures[future]
            name = row.get("name")
            try:
                record = future.result()
            except Exception as exc:  # Defensive: generate_one normally records errors.
                record = base_record(row=row, condition=condition, prompt="", args=args)
                record["status"] = "error"
                record["error"] = str(exc)

            append_jsonl(output_path, record)
            status = record["status"]
            print(f"[{completed}/{len(pending_rows)}] {name}: {status}")

    print("Done.")


if __name__ == "__main__":
    die("Run scripts/statement_only.py or scripts/statement_plus_proof.py")
