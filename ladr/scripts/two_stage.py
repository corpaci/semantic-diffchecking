#!/usr/bin/env python3
"""Experiment 3: plan from the informal proof, then generate a Lean statement."""

from __future__ import annotations

import argparse
import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from _statement_runner import (
    DEFAULT_INPUT,
    DEFAULT_MODEL,
    DEFAULT_REASONING_EFFORT,
    REASONING_EFFORTS,
    REPO_ROOT,
    append_jsonl,
    call_openai,
    die,
    iso_now,
    load_environment,
    load_jsonl,
    make_client,
    validate_output,
)


CONDITION = "two_stage"
PROMPT_VERSION = "ladr_two_stage_semantic_plan_v1"
DEFAULT_RESULTS_ROOT = REPO_ROOT / "results"

STAGE1_SYSTEM_PROMPT = (
    "You are an expert in linear algebra. Return only the requested "
    "mathematical formalization plan, without Lean code."
)

STAGE1_PROMPT = """\
Using the natural-language theorem and its textbook proof, write a concise
mathematical formalization plan.

Identify:
- the mathematical objects and their types;
- the assumptions;
- the exact conclusion.

Do not write Lean code.

Natural-language theorem:
{nl_statement}

The informal proof below is the textbook's correct mathematical proof. Use it
to clarify the intended theorem statement.

Informal proof:
{informal_proof}
"""

STAGE2_SYSTEM_PROMPT = (
    "Return Lean 4 code only. Start with `import Mathlib`. Do not use Markdown "
    "or explanations outside Lean code."
)

STAGE2_PROMPT = """\
You are an expert in linear algebra and Lean 4. Please formalize the statement
into Lean 4 code.

Return Lean 4 code only. Put `import Mathlib` at the top, fill the proof with
`sorry`, and name the theorem `{name}`.

Natural-language theorem:
{nl_statement}

Formalization plan:
{formalization_plan}
"""


def default_output_path(model: str, reasoning_effort: str) -> Path:
    model_dir = model.replace("/", "__")
    return (
        DEFAULT_RESULTS_ROOT
        / CONDITION
        / model_dir
        / f"reasoning_{reasoning_effort}"
        / "generations.jsonl"
    )


def completed_names(path: Path) -> set[str]:
    if not path.exists():
        return set()

    done: set[str] = set()
    for row in load_jsonl(path):
        if row.get("status") != "ok":
            continue
        name = row.get("theorem_dataset_name") or row.get("name")
        if name:
            done.add(str(name))
    return done


def render_stage1_prompt(row: dict[str, Any]) -> str:
    statement = row.get("nl_statement")
    proof = (row.get("informal_proof") or "").strip()
    if not statement:
        raise ValueError("input row must include nl_statement")
    if not proof:
        raise ValueError(f"{row.get('name')}: informal_proof is required")
    return STAGE1_PROMPT.format(
        nl_statement=statement,
        informal_proof=proof,
    )


def render_stage2_prompt(row: dict[str, Any], formalization_plan: str) -> str:
    name = row.get("name")
    statement = row.get("nl_statement")
    if not name or not statement:
        raise ValueError("input row must include name and nl_statement")
    return STAGE2_PROMPT.format(
        name=name,
        nl_statement=statement,
        formalization_plan=formalization_plan,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the LADR two-stage semantic-plan experiment."
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
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    input_path = args.input if args.input.is_absolute() else REPO_ROOT / args.input
    output_arg = args.output or default_output_path(args.model, args.reasoning_effort)
    output_path = output_arg if output_arg.is_absolute() else REPO_ROOT / output_arg

    if not input_path.exists():
        die(f"Input file not found: {input_path}")
    if args.max_workers < 1:
        die("--max-workers must be at least 1")

    rows = load_jsonl(input_path)
    if args.limit is not None:
        rows = rows[: args.limit]

    print(f"Experiment: {CONDITION}")
    print(f"Input: {input_path}")
    print(f"Output: {output_path}")
    print(f"Model: {args.model}")
    print(f"Reasoning effort: {args.reasoning_effort}")
    print(f"Max workers: {args.max_workers}")
    print(f"Jobs: {len(rows)}")
    print("Calls per job: 1 planning call + 1 Lean generation call")
    print("Local Lean compilation: disabled")

    if args.dry_run:
        if not rows:
            return
        row = rows[0]
        print(f"\n--- Stage 1 prompt: {row.get('name')} ---")
        print(render_stage1_prompt(row))
        print(f"\n--- Stage 2 prompt template: {row.get('name')} ---")
        print(render_stage2_prompt(row, "<stage_1_formalization_plan>"))
        return

    if args.force and output_path.exists():
        output_path.unlink()

    load_environment()
    client = make_client()
    done = completed_names(output_path)
    pending_rows = [row for row in rows if str(row.get("name") or "") not in done]
    print(f"Skipping {len(rows) - len(pending_rows)} completed records")
    print(f"Theorems to process: {len(pending_rows)}")

    def process_one(row: dict[str, Any]) -> dict[str, Any]:
        name = str(row.get("name") or "")
        record: dict[str, Any] = {
            "created_at": iso_now(),
            "prompt_version": PROMPT_VERSION,
            "condition": CONDITION,
            "theorem_dataset_name": row.get("name"),
            "dataset": row.get("domain") or "LADR",
            "input_row": row,
            "model": args.model,
            "reasoning_effort": args.reasoning_effort,
            "temperature": args.temperature,
            "max_tokens": args.max_tokens,
            "stage1": None,
            "stage2": None,
            "system_prompt": STAGE2_SYSTEM_PROMPT,
            "prompt": None,
            "output_text": None,
            "validation": None,
            "status": "pending",
            "error": None,
        }

        try:
            stage1_prompt = render_stage1_prompt(row)
            plan, stage1_usage = call_openai(
                client,
                model=args.model,
                prompt=stage1_prompt,
                max_tokens=args.max_tokens,
                reasoning_effort=args.reasoning_effort,
                temperature=args.temperature,
                instructions=STAGE1_SYSTEM_PROMPT,
            )
            record["stage1"] = {
                "system_prompt": STAGE1_SYSTEM_PROMPT,
                "prompt": stage1_prompt,
                "output_text": plan,
                "usage": stage1_usage,
            }

            stage2_prompt = render_stage2_prompt(row, plan)
            output_text, stage2_usage = call_openai(
                client,
                model=args.model,
                prompt=stage2_prompt,
                max_tokens=args.max_tokens,
                reasoning_effort=args.reasoning_effort,
                temperature=args.temperature,
                instructions=STAGE2_SYSTEM_PROMPT,
            )
            validation = validate_output(output_text, row.get("name"))
            record["stage2"] = {
                "system_prompt": STAGE2_SYSTEM_PROMPT,
                "prompt": stage2_prompt,
                "output_text": output_text,
                "usage": stage2_usage,
                "validation": validation,
            }
            record["prompt"] = stage2_prompt
            record["output_text"] = output_text
            record["usage"] = stage2_usage
            record["validation"] = validation
            record["status"] = "ok"
        except Exception as exc:  # noqa: BLE001 - preserve failures in JSONL.
            record["status"] = "error"
            record["error"] = str(exc)

        if args.sleep > 0:
            time.sleep(args.sleep)
        return record

    with ThreadPoolExecutor(max_workers=args.max_workers) as executor:
        futures = {executor.submit(process_one, row): row for row in pending_rows}
        for completed, future in enumerate(as_completed(futures), start=1):
            row = futures[future]
            name = str(row.get("name") or "")
            try:
                record = future.result()
            except Exception as exc:  # Defensive: process_one normally records errors.
                record = {
                    "created_at": iso_now(),
                    "prompt_version": PROMPT_VERSION,
                    "condition": CONDITION,
                    "theorem_dataset_name": row.get("name"),
                    "dataset": row.get("domain") or "LADR",
                    "input_row": row,
                    "model": args.model,
                    "reasoning_effort": args.reasoning_effort,
                    "temperature": args.temperature,
                    "max_tokens": args.max_tokens,
                    "stage1": None,
                    "stage2": None,
                    "system_prompt": STAGE2_SYSTEM_PROMPT,
                    "prompt": None,
                    "output_text": None,
                    "validation": None,
                    "status": "error",
                    "error": str(exc),
                }

            append_jsonl(output_path, record)
            print(f"[{completed}/{len(pending_rows)}] {name}: {record['status']}")

    print("Done.")


if __name__ == "__main__":
    main()
