#!/usr/bin/env python3
"""Normalize generated Lean artifacts so `import Mathlib` is first.

Lean requires all imports to appear before module docstrings, comments, options,
or declarations. This script rewrites generated `.lean` files and JSONL Lean-code
fields into a complete-file format:

    import Mathlib

    set_option linter.style.header false

    <rest of generated code>
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
DEFAULT_ROOT = REPO_ROOT / "results" / "archive" / "pilot_27" / "gpt-5.4" / "reasoning_none"

LEAN_PREAMBLE = """\
import Mathlib

set_option linter.style.header false

"""

CODE_FIELDS = ("output_text", "final_output_text", "skeleton_output_text")
HASH_FIELDS = {
    "output_text": "output_sha256",
    "final_output_text": "final_output_sha256",
    "skeleton_output_text": "skeleton_output_sha256",
}


def output_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def is_import_or_header_option(line: str) -> bool:
    return bool(
        re.match(r"\s*import\s+\S+\s*$", line)
        or re.match(r"\s*set_option\s+linter\.style\.header\s+false\s*$", line)
    )


def normalize_lean_code(text: str) -> str:
    body_lines = [line for line in text.strip().splitlines() if not is_import_or_header_option(line)]
    body = "\n".join(body_lines).strip()
    if not body:
        return LEAN_PREAMBLE.rstrip() + "\n"
    return LEAN_PREAMBLE + "\n" + body + "\n"


def normalize_code_field(record: dict[str, Any], field: str) -> bool:
    value = record.get(field)
    if not isinstance(value, str) or not value.strip():
        return False
    normalized = normalize_lean_code(value)
    changed = normalized != value
    record[field] = normalized
    hash_field = HASH_FIELDS.get(field)
    if hash_field:
        new_hash = output_hash(normalized)
        if record.get(hash_field) != new_hash:
            record[hash_field] = new_hash
            changed = True
    return changed


def normalize_attempts(record: dict[str, Any]) -> int:
    changed = 0
    attempts = record.get("attempts")
    if isinstance(attempts, list):
        for attempt in attempts:
            if isinstance(attempt, dict) and normalize_code_field(attempt, "output_text"):
                changed += 1

    stages = record.get("stages")
    if isinstance(stages, dict):
        for stage_record in stages.values():
            if not isinstance(stage_record, dict):
                continue
            for field in CODE_FIELDS:
                if normalize_code_field(stage_record, field):
                    changed += 1
            stage_attempts = stage_record.get("attempts")
            if isinstance(stage_attempts, list):
                for attempt in stage_attempts:
                    if isinstance(attempt, dict) and normalize_code_field(attempt, "output_text"):
                        changed += 1
    return changed


def normalize_jsonl(path: Path) -> tuple[int, int]:
    rows: list[dict[str, Any]] = []
    changed_rows = 0
    changed_fields = 0

    with path.open(encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            record = json.loads(line)
            before = json.dumps(record, sort_keys=True, ensure_ascii=False)
            for field in CODE_FIELDS:
                if normalize_code_field(record, field):
                    changed_fields += 1
            changed_fields += normalize_attempts(record)
            after = json.dumps(record, sort_keys=True, ensure_ascii=False)
            if before != after:
                changed_rows += 1
            rows.append(record)

    if changed_rows:
        with path.open("w", encoding="utf-8") as f:
            for record in rows:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
    return changed_rows, changed_fields


def normalize_lean_file(path: Path) -> bool:
    original = path.read_text(encoding="utf-8")
    normalized = normalize_lean_code(original)
    if normalized == original:
        return False
    path.write_text(normalized, encoding="utf-8")
    return True


def sync_one_shot_checked_hashes(root: Path) -> int:
    raw_path = root / "one_shot_ab" / "lean_statement_pilot_ab.jsonl"
    checked_path = root / "one_shot_ab" / "lean_statement_pilot_ab_checked.jsonl"
    if not raw_path.exists() or not checked_path.exists():
        return 0

    raw_hashes: dict[tuple[Any, Any], str] = {}
    with raw_path.open(encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            record = json.loads(line)
            key = (record.get("theorem_dataset_name"), record.get("condition"))
            raw_hash = record.get("output_sha256")
            if not raw_hash and isinstance(record.get("output_text"), str):
                raw_hash = output_hash(record["output_text"])
            raw_hashes[key] = str(raw_hash or "")

    checked_rows: list[dict[str, Any]] = []
    changed = 0
    with checked_path.open(encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            record = json.loads(line)
            key = (record.get("theorem_dataset_name"), record.get("condition"))
            new_hash = raw_hashes.get(key)
            if new_hash and record.get("output_sha256") != new_hash:
                record["output_sha256"] = new_hash
                changed += 1
            checked_rows.append(record)

    if changed:
        with checked_path.open("w", encoding="utf-8") as f:
            for record in checked_rows:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
    return changed


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Move `import Mathlib` to the start of generated Lean artifacts."
    )
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    root = args.root if args.root.is_absolute() else REPO_ROOT / args.root
    if not root.exists():
        raise SystemExit(f"root does not exist: {root}")

    jsonl_paths = sorted(root.rglob("*.jsonl"))
    lean_paths = sorted(root.rglob("*.lean"))

    if args.dry_run:
        print(f"Would scan {len(jsonl_paths)} JSONL files and {len(lean_paths)} Lean files under {root}")
        return

    jsonl_rows = 0
    jsonl_fields = 0
    for path in jsonl_paths:
        changed_rows, changed_fields = normalize_jsonl(path)
        jsonl_rows += changed_rows
        jsonl_fields += changed_fields
        if changed_rows:
            print(f"normalized JSONL: {path} ({changed_rows} rows, {changed_fields} fields)")

    lean_changed = 0
    for path in lean_paths:
        if normalize_lean_file(path):
            lean_changed += 1

    checked_hashes_changed = sync_one_shot_checked_hashes(root)

    print(
        "Done. "
        f"JSONL rows changed: {jsonl_rows}; "
        f"code fields changed: {jsonl_fields}; "
        f"Lean files changed: {lean_changed}; "
        f"checked hashes synced: {checked_hashes_changed}"
    )


if __name__ == "__main__":
    main()
