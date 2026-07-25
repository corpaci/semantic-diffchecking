#!/usr/bin/env python3
"""Summarize Lean typecheck results and classify compiler errors."""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import Counter, defaultdict
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
    / "lean_checks.jsonl"
)


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


def first_error_message(record: dict[str, Any]) -> dict[str, Any] | None:
    for message in record.get("messages") or []:
        if message.get("severity") == "error":
            return message
    return None


def first_error_text(record: dict[str, Any]) -> str:
    message = first_error_message(record)
    if message is not None:
        return str(message.get("data") or "")
    return str(record.get("stderr") or record.get("stdout_raw") or "")


def first_error_kind(record: dict[str, Any]) -> str:
    message = first_error_message(record)
    if message is None:
        return ""
    return str(message.get("kind") or "")


def one_line(text: str, *, max_len: int = 180) -> str:
    line = " ".join((text or "").split())
    if len(line) <= max_len:
        return line
    return line[: max_len - 3] + "..."


def classify_error(record: dict[str, Any]) -> str:
    if record.get("lean_typechecked") or record.get("check_status") == "ok":
        return "ok"

    text = first_error_text(record)
    lower = text.lower()
    kind = first_error_kind(record)

    if "unknown constant" in lower:
        return "unknown_constant"
    if "unknown identifier" in lower or "unknownidentifier" in kind.lower():
        return "unknown_identifier"
    if "unexpected token" in lower:
        return "unexpected_token"
    if lower.startswith("expected token") or " expected token" in lower:
        return "expected_token"
    if "application type mismatch" in lower:
        return "application_type_mismatch"
    if "type mismatch" in lower:
        return "type_mismatch"
    if "function expected at" in lower:
        return "function_expected"
    if "failed to synthesize" in lower:
        return "failed_to_synthesize_instance"
    if "typeclass instance problem is stuck" in lower:
        return "typeclass_stuck"
    if "invalid binder annotation" in lower:
        return "invalid_binder_annotation"
    if "tactic `assumption` failed" in lower:
        return "unexpected_tactic_term"
    if "invalid field" in lower:
        return "invalid_field_or_projection"
    if "invalid universe" in lower or "universe" in lower:
        return "universe_error"
    if record.get("check_status") == "timeout":
        return "timeout"
    if not text:
        return "unknown_error_without_message"
    return "other_error"


def extract_symbol(error_text: str) -> str:
    constant = re.search(r"Unknown constant `([^`]+)`", error_text)
    if constant:
        return constant.group(1)
    ident = re.search(r"Unknown identifier `([^`]+)`", error_text)
    if ident:
        return ident.group(1)
    function_expected = re.search(r"Function expected at\s+([^\s]+)", error_text)
    if function_expected:
        return function_expected.group(1)
    unexpected = re.search(r"unexpected token '([^']+)'", error_text)
    if unexpected:
        return unexpected.group(1)
    return ""


def normalized_record(record: dict[str, Any]) -> dict[str, Any]:
    error_text = first_error_text(record)
    return {
        "theorem_dataset_name": record.get("theorem_dataset_name"),
        "condition": record.get("condition"),
        "check_status": record.get("check_status"),
        "lean_typechecked": bool(record.get("lean_typechecked")),
        "error_class": classify_error(record),
        "error_kind": first_error_kind(record),
        "error_symbol": extract_symbol(error_text),
        "error_summary": one_line(error_text),
        "returncode": record.get("returncode"),
        "source_index": record.get("source_index"),
        "output_sha256": record.get("output_sha256"),
    }


def print_counter(title: str, counter: Counter[str]) -> None:
    print(title)
    for key, value in counter.most_common():
        print(f"  {key}: {value}")


def paired_outcomes(rows: list[dict[str, Any]]) -> Counter[str]:
    by_name: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    for record in rows:
        name = str(record.get("theorem_dataset_name"))
        condition = str(record.get("condition"))
        by_name[name][condition] = record

    outcomes: Counter[str] = Counter()
    for conds in by_name.values():
        only_ok = bool(conds.get("statement_only", {}).get("lean_typechecked"))
        proof_ok = bool(conds.get("statement_plus_proof", {}).get("lean_typechecked"))
        if only_ok and proof_ok:
            outcomes["both_ok"] += 1
        elif only_ok:
            outcomes["statement_only_only"] += 1
        elif proof_ok:
            outcomes["statement_plus_proof_only"] += 1
        else:
            outcomes["both_fail"] += 1
    return outcomes


def write_tsv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "theorem_dataset_name",
        "condition",
        "check_status",
        "lean_typechecked",
        "error_class",
        "error_symbol",
        "error_summary",
        "error_kind",
        "returncode",
        "source_index",
        "output_sha256",
    ]
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Classify Lean compiler errors in checked JSONL output."
    )
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--tsv", type=Path, default=None)
    parser.add_argument("--examples-per-class", type=int, default=3)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    input_path = args.input if args.input.is_absolute() else REPO_ROOT / args.input
    if not input_path.exists():
        die(f"Input file not found: {input_path}")

    rows = load_jsonl(input_path)
    normalized = [normalized_record(record) for record in rows]

    print(f"Input: {input_path}")
    print(f"Records: {len(rows)}")
    print_counter("Check status:", Counter(str(row["check_status"]) for row in normalized))
    print_counter("Error classes:", Counter(str(row["error_class"]) for row in normalized))

    by_condition: dict[str, Counter[str]] = defaultdict(Counter)
    by_condition_class: dict[str, Counter[str]] = defaultdict(Counter)
    for row in normalized:
        condition = str(row["condition"])
        by_condition[condition][str(row["check_status"])] += 1
        by_condition_class[condition][str(row["error_class"])] += 1

    print("By condition:")
    for condition in sorted(by_condition):
        print(f"  {condition}: {dict(by_condition[condition])}")

    print("Error class by condition:")
    for condition in sorted(by_condition_class):
        print(f"  {condition}: {dict(by_condition_class[condition])}")

    print_counter("Paired outcomes:", paired_outcomes(rows))

    examples_by_class: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in normalized:
        if row["error_class"] == "ok":
            continue
        bucket = examples_by_class[str(row["error_class"])]
        if len(bucket) < args.examples_per_class:
            bucket.append(row)

    print("Examples:")
    for error_class in sorted(examples_by_class):
        print(f"  {error_class}:")
        for row in examples_by_class[error_class]:
            print(
                "    "
                f"{row['theorem_dataset_name']} / {row['condition']} / "
                f"{row['error_symbol'] or '-'} / {row['error_summary']}"
            )

    if args.tsv is not None:
        tsv_path = args.tsv if args.tsv.is_absolute() else REPO_ROOT / args.tsv
        write_tsv(tsv_path, normalized)
        print(f"Wrote TSV: {tsv_path}")


if __name__ == "__main__":
    main()
