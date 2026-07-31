#!/usr/bin/env python3
"""Experiment 1: translate each theorem statement into a Lean 4 statement."""

from typing import Any

from _statement_runner import run_experiment


PROMPT = """\
You are an expert in linear algebra and Lean 4. Please formalize the statement
into Lean 4 code.

Return Lean 4 code only. Put `import Mathlib` at the top, fill the proof with
`sorry`, and name the theorem `{name}`.

Natural-language theorem:
{nl_statement}
"""


def render_prompt(row: dict[str, Any]) -> str:
    name = row.get("name")
    statement = row.get("nl_statement")
    if not name or not statement:
        raise ValueError("input row must include name and nl_statement")
    return PROMPT.format(name=name, nl_statement=statement)


if __name__ == "__main__":
    run_experiment("statement_only", render_prompt)
