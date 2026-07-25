#!/usr/bin/env python3
"""Experiment 2: add the informal proof when translating the Lean statement."""

from typing import Any

from _statement_runner import run_experiment


PROMPT = """\
You are an expert in linear algebra and Lean 4. Please formalize the statement
into Lean 4 code.

Return Lean 4 code only. Put `import Mathlib` at the top, fill the proof with
`sorry`, and name the theorem `{name}`.

Natural-language theorem:
{nl_statement}

The informal proof below is the textbook's correct mathematical proof. You may
use it to help formalize the theorem statement.

Informal proof:
{informal_proof}
"""


def render_prompt(row: dict[str, Any]) -> str:
    name = row.get("name")
    statement = row.get("nl_statement")
    proof = (row.get("informal_proof") or "").strip()
    if not name or not statement:
        raise ValueError("input row must include name and nl_statement")
    if not proof:
        raise ValueError(f"{name}: informal_proof is required")
    return PROMPT.format(
        dataset=row.get("domain") or "LADR",
        name=name,
        nl_statement=statement,
        informal_proof=proof,
    )


if __name__ == "__main__":
    run_experiment("statement_plus_proof", render_prompt)
