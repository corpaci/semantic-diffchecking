#!/usr/bin/env python3
"""Back-translate generated Lean theorem statements into math audit cards."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
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
DEFAULT_ROOT = REPO_ROOT / "results" / "archive" / "pilot_27" / "gpt-5.4" / "reasoning_none"
DEFAULT_OUTPUT = DEFAULT_ROOT / "backtranslation" / "lean_statement_backtranslation_cards.jsonl"
PROMPT_VERSION = "ladr_backtranslation_card_v1"

SYSTEM_PROMPT = (
    "You translate Lean 4 theorem statements into concise mathematical English. "
    "The goal is to help a mathematician audit semantic faithfulness without "
    "reading Lean. Do not prove the theorem and do not silently repair the Lean code."
)

PROMPT_TEMPLATE = """\
Back-translate the generated Lean 4 theorem statement into a concise math card.

Important instructions:
- Explain what the Lean statement literally says mathematically.
- Use the original theorem only as comparison context; do not silently repair the Lean statement.
- Flag missing assumptions, extra assumptions, changed objects, changed quantifiers, or trivial/vacuous statements when visible.
- If the Lean statement says `True`, or otherwise has almost no mathematical content, mark that as a red flag.
- Return valid JSON only. Do not use Markdown.

JSON schema:
{{
  "lean_plain_english": "one or two sentences saying what the Lean theorem claims",
  "objects": ["main mathematical objects and their types"],
  "assumptions": ["explicit assumptions/hypotheses in the Lean statement"],
  "conclusion": "the conclusion of the Lean statement",
  "quantifiers": "short description of the quantifier structure",
  "comparison_hints": {{
    "missing_from_generated": ["parts of the original theorem that seem absent from the Lean statement"],
    "extra_in_generated": ["extra assumptions or claims added by the Lean statement"],
    "changed_or_ambiguous": ["objects, domains, quantifiers, or conclusions that look changed or unclear"],
    "red_flags": ["triviality, vacuity, type/domain mismatch, or other obvious semantic risks"]
  }},
  "suggested_audit_label": "faithful | weakened | strengthened | incomparable | trivial_or_vacuous | unclear",
  "confidence": "low | medium | high"
}}

Dataset: {dataset}
Theorem dataset name: {name}
Experiment: {experiment_label}

Original natural-language theorem:
{nl_statement}

Original informal proof, for context:
{informal_proof}

Generated Lean 4 theorem statement:
{lean_statement}
"""


def die(message: str) -> None:
    print(message, file=sys.stderr)
    raise SystemExit(1)


def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
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


def lean_code_hash(code: str) -> str:
    return sha256(code.strip())


def experiment_id(source: str, condition: str) -> str:
    if source == "one_shot_ab":
        return f"one_shot_{condition}"
    if source == "repair_agent_ab":
        return f"repair_agent_{condition}"
    return "multistage_skeleton"


def experiment_label(item: dict[str, Any]) -> str:
    labels = {
        "one_shot_statement_only": "One-shot A: statement only",
        "one_shot_statement_plus_proof": "One-shot B: statement + informal proof",
        "repair_agent_statement_only": "Repair-agent A: statement only",
        "repair_agent_statement_plus_proof": "Repair-agent B: statement + informal proof",
        "multistage_skeleton": "C: multistage proof skeleton",
    }
    return labels.get(item["experiment_id"], item["experiment_id"])


def checked_map(root: Path) -> dict[tuple[str, str, str], dict[str, Any]]:
    rows = load_jsonl(root / "one_shot_ab" / "lean_statement_pilot_ab_checked.jsonl")
    out: dict[tuple[str, str, str], dict[str, Any]] = {}
    for row in rows:
        key = (
            str(row.get("theorem_dataset_name") or ""),
            str(row.get("condition") or ""),
            str(row.get("output_sha256") or ""),
        )
        out[key] = row
    return out


def source_items(root: Path) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []

    checks = checked_map(root)
    one_shot = load_jsonl(root / "one_shot_ab" / "lean_statement_pilot_ab.jsonl")
    for row in one_shot:
        code = str(row.get("output_text") or "").strip()
        name = str(row.get("theorem_dataset_name") or "")
        condition = str(row.get("condition") or "")
        code_hash = str(row.get("output_sha256") or lean_code_hash(code))
        check = checks.get((name, condition, code_hash)) or checks.get((name, condition, "")) or {}
        items.append(
            {
                "source": "one_shot_ab",
                "experiment_id": experiment_id("one_shot_ab", condition),
                "condition": condition,
                "theorem_dataset_name": name,
                "dataset": row.get("dataset") or "LADR",
                "input_row": row.get("input_row") or {},
                "lean_statement": code,
                "lean_statement_sha256": code_hash,
                "status": "ok" if check.get("lean_typechecked") else "failed",
                "lean_typechecked": bool(check.get("lean_typechecked")),
                "attempt_count": 1,
            }
        )

    repair = load_jsonl(root / "repair_agent_ab" / "lean_statement_agent_ab.jsonl")
    for row in repair:
        code = str(row.get("final_output_text") or "").strip()
        condition = str(row.get("condition") or "")
        items.append(
            {
                "source": "repair_agent_ab",
                "experiment_id": experiment_id("repair_agent_ab", condition),
                "condition": condition,
                "theorem_dataset_name": str(row.get("theorem_dataset_name") or ""),
                "dataset": row.get("dataset") or "LADR",
                "input_row": row.get("input_row") or {},
                "lean_statement": code,
                "lean_statement_sha256": str(row.get("final_output_sha256") or lean_code_hash(code)),
                "status": row.get("status") or "failed",
                "lean_typechecked": bool(row.get("lean_typechecked")),
                "attempt_count": row.get("attempt_count"),
            }
        )

    multistage = load_jsonl(root / "multistage_skeleton" / "lean_statement_multistage_skeleton.jsonl")
    for row in multistage:
        code = str(row.get("final_output_text") or "").strip()
        items.append(
            {
                "source": "multistage_skeleton",
                "experiment_id": "multistage_skeleton",
                "condition": "multistage_skeleton",
                "theorem_dataset_name": str(row.get("theorem_dataset_name") or ""),
                "dataset": row.get("dataset") or "LADR",
                "input_row": row.get("input_row") or {},
                "lean_statement": code,
                "lean_statement_sha256": str(row.get("final_output_sha256") or lean_code_hash(code)),
                "status": row.get("status") or "failed",
                "lean_typechecked": bool(row.get("lean_typechecked")),
                "attempt_count": row.get("attempt_count"),
                "stage_statuses": row.get("stage_statuses"),
                "skeleton_output_text": row.get("skeleton_output_text"),
            }
        )

    return items


def completed_keys(path: Path) -> set[tuple[str, str, str, str]]:
    keys: set[tuple[str, str, str, str]] = set()
    for row in load_jsonl(path):
        if row.get("status") != "ok":
            continue
        keys.add(
            (
                str(row.get("prompt_version") or ""),
                str(row.get("theorem_dataset_name") or ""),
                str(row.get("experiment_id") or ""),
                str(row.get("lean_statement_sha256") or ""),
            )
        )
    return keys


def job_key(item: dict[str, Any]) -> tuple[str, str, str, str]:
    return (
        PROMPT_VERSION,
        str(item.get("theorem_dataset_name") or ""),
        str(item.get("experiment_id") or ""),
        str(item.get("lean_statement_sha256") or ""),
    )


def render_prompt(item: dict[str, Any]) -> str:
    input_row = item.get("input_row") or {}
    return PROMPT_TEMPLATE.format(
        dataset=item.get("dataset") or input_row.get("domain") or "LADR",
        name=item["theorem_dataset_name"],
        experiment_label=experiment_label(item),
        nl_statement=input_row.get("nl_statement") or "",
        informal_proof=input_row.get("informal_proof") or "",
        lean_statement=item.get("lean_statement") or "",
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


def parse_json_card(text: str) -> tuple[dict[str, Any] | None, str | None]:
    cleaned = text.strip()
    fence = re.fullmatch(r"```(?:json)?\s*(.*?)```", cleaned, flags=re.DOTALL)
    if fence:
        cleaned = fence.group(1).strip()
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        return None, str(exc)
    if not isinstance(parsed, dict):
        return None, "model returned JSON, but not a JSON object"
    return parsed, None


def usage_to_dict(usage: Any) -> dict[str, Any] | None:
    if usage is None:
        return None
    if hasattr(usage, "model_dump"):
        return usage.model_dump()
    return {
        "input_tokens": getattr(usage, "input_tokens", None),
        "output_tokens": getattr(usage, "output_tokens", None),
        "total_tokens": getattr(usage, "total_tokens", None),
    }


def call_openai(client: Any, *, model: str, prompt: str, max_tokens: int, temperature: float | None) -> tuple[str, dict[str, Any] | None]:
    kwargs: dict[str, Any] = {
        "model": model,
        "instructions": SYSTEM_PROMPT,
        "input": prompt,
        "max_output_tokens": max_tokens,
    }
    if temperature is not None:
        kwargs["temperature"] = temperature
    response = client.responses.create(**kwargs)
    return extract_response_text(response), usage_to_dict(getattr(response, "usage", None))


def load_environment() -> None:
    if load_dotenv is not None:
        load_dotenv(REPO_ROOT / ".env", override=True)


def make_client() -> Any:
    if OpenAI is None:
        die("Missing dependency: openai. Install dependencies with `pip install -r requirements.txt`.")
    if not os.environ.get("OPENAI_API_KEY"):
        die("OPENAI_API_KEY is not set. Put it in the environment or repo .env file.")
    return OpenAI()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Back-translate compiled generated Lean statements into audit cards.")
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--model", default="gpt-5.4")
    parser.add_argument("--max-tokens", type=int, default=1400)
    parser.add_argument("--temperature", type=float, default=None)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--theorem", action="append", default=[])
    parser.add_argument("--experiment", action="append", default=[])
    parser.add_argument("--c-success-only", action="store_true")
    parser.add_argument("--include-uncompiled", dest="compiled_only", action="store_false")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--sleep", type=float, default=0.2)
    parser.set_defaults(compiled_only=True)
    return parser.parse_args()


def selected_items(args: argparse.Namespace) -> list[dict[str, Any]]:
    root = args.root if args.root.is_absolute() else REPO_ROOT / args.root
    items = source_items(root)
    theorem_filter = set(args.theorem or [])
    experiment_filter = set(args.experiment or [])
    if args.c_success_only:
        c_success = {
            item["theorem_dataset_name"]
            for item in items
            if item["experiment_id"] == "multistage_skeleton" and item["lean_typechecked"]
        }
        theorem_filter = theorem_filter & c_success if theorem_filter else c_success

    filtered: list[dict[str, Any]] = []
    for item in items:
        if args.compiled_only and not item.get("lean_typechecked"):
            continue
        if theorem_filter and item["theorem_dataset_name"] not in theorem_filter:
            continue
        if experiment_filter and item["experiment_id"] not in experiment_filter:
            continue
        if not item.get("lean_statement"):
            continue
        filtered.append(item)
    return filtered[: args.limit] if args.limit is not None else filtered


def main() -> None:
    args = parse_args()
    root = args.root if args.root.is_absolute() else REPO_ROOT / args.root
    output = args.output if args.output.is_absolute() else REPO_ROOT / args.output
    items = selected_items(args)
    done = set() if args.force else completed_keys(output)

    print(f"Root: {root}")
    print(f"Output: {output}")
    print(f"Jobs selected: {len(items)}")
    print(f"Completed cards in output: {len(done)}")

    if args.dry_run:
        for item in items[:10]:
            print(item["theorem_dataset_name"], item["experiment_id"], item["status"])
        return

    load_environment()
    client = make_client()

    written = 0
    skipped = 0
    for index, item in enumerate(items, start=1):
        key = job_key(item)
        if key in done:
            skipped += 1
            continue

        print(f"[{index}/{len(items)}] {item['theorem_dataset_name']} / {item['experiment_id']}")
        prompt = render_prompt(item)
        try:
            raw_text, usage = call_openai(
                client,
                model=args.model,
                prompt=prompt,
                max_tokens=args.max_tokens,
                temperature=args.temperature,
            )
            card, parse_error = parse_json_card(raw_text)
            status = "ok" if card is not None else "parse_error"
            error = parse_error
        except Exception as exc:  # noqa: BLE001 - keep progress in JSONL.
            raw_text = ""
            usage = None
            card = None
            status = "api_error"
            error = str(exc)

        append_jsonl(
            output,
            {
                "created_at": iso_now(),
                "prompt_version": PROMPT_VERSION,
                "source": item["source"],
                "experiment_id": item["experiment_id"],
                "condition": item["condition"],
                "theorem_dataset_name": item["theorem_dataset_name"],
                "dataset": item["dataset"],
                "input_row": item.get("input_row"),
                "lean_statement": item["lean_statement"],
                "lean_statement_sha256": item["lean_statement_sha256"],
                "lean_typechecked": item["lean_typechecked"],
                "model": args.model,
                "temperature": args.temperature,
                "max_tokens": args.max_tokens,
                "prompt": prompt,
                "status": status,
                "card": card,
                "raw_output_text": raw_text,
                "error": error,
                "usage": usage,
            },
        )
        written += 1
        if args.sleep:
            time.sleep(args.sleep)

    print(f"Done. Written: {written}; skipped: {skipped}")


if __name__ == "__main__":
    main()
