"""ETP formal equation -> JSON syntax tree.

    x ◇ (y ◇ z) = (x ◇ y) ◇ z

    {"=": [{"◇": ["x", {"◇": ["y", "z"]}]}, {"◇": [{"◇": ["x", "y"]}, "z"]}]}

The same tree `../py_lambda/` writes as executable code, written as inert data:
a one-key object per node, a string per variable. There is no evaluation story
and nothing to run, which is the point — it separates "reads a nested
structure" from "simulates a program", two abilities the Python rendering
necessarily conflates.

CLI:  python3 jsonify.py 4512 | python3 jsonify.py --selftest
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _catalogue import (  # noqa: E402
    CANONICAL_OP, Equation, ParseFailure, Representation, Var, parse_equation,
    single_main,
)

EQUALS_KEY = "="


def render(equation: Equation) -> str:
    """Encode the equation as one-key objects over variable-name strings."""

    def encode(term):
        if isinstance(term, Var):
            return term.name
        return {CANONICAL_OP: [encode(term.left), encode(term.right)]}

    return json.dumps({EQUALS_KEY: [encode(equation.lhs), encode(equation.rhs)]},
                      ensure_ascii=False)


def read_back(text: str) -> Equation:
    """Decode the tree and hand canonical infix to the oracle's parser."""
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ParseFailure(f"not valid JSON: {exc}") from None
    if not (isinstance(data, dict) and list(data) == [EQUALS_KEY]):
        raise ParseFailure(f'the top level must be a single {EQUALS_KEY!r} key')
    sides = data[EQUALS_KEY]
    if not (isinstance(sides, list) and len(sides) == 2):
        raise ParseFailure(f"{EQUALS_KEY!r} must hold exactly two sides")

    def decode(node, *, top: bool) -> str:
        if isinstance(node, str):
            if not node.isalnum():
                raise ParseFailure(f"not a variable: {node!r}")
            return node
        if not (isinstance(node, dict) and list(node) == [CANONICAL_OP]):
            raise ParseFailure(f"expected a variable or a single {CANONICAL_OP!r} key, "
                               f"found {node!r}")
        arguments = node[CANONICAL_OP]
        if not (isinstance(arguments, list) and len(arguments) == 2):
            raise ParseFailure(f"{CANONICAL_OP!r} must hold exactly two arguments")
        inner = (f"{decode(arguments[0], top=False)} {CANONICAL_OP} "
                 f"{decode(arguments[1], top=False)}")
        return inner if top else f"({inner})"

    return parse_equation(f"{decode(sides[0], top=True)} = {decode(sides[1], top=True)}")


def representation(args=None) -> Representation:
    """The `Representation` this directory exports."""
    return Representation(
        name="json_ast", key="json_ast", render=render, read_back=read_back,
        blurb="JSON syntax tree",
        style={"format": "json", "equality_key": EQUALS_KEY,
               "operation_key": CANONICAL_OP, "variables": "strings"},
    )


_CASES = (
    ("x = x", '{"=": ["x", "x"]}'),
    ("x ◇ y = y ◇ x", '{"=": [{"◇": ["x", "y"]}, {"◇": ["y", "x"]}]}'),
    ("x ◇ (y ◇ z) = (x ◇ y) ◇ z",
     '{"=": [{"◇": ["x", {"◇": ["y", "z"]}]}, {"◇": [{"◇": ["x", "y"]}, "z"]}]}'),
)

_BAD = (
    ('{"=": ["x"]}', "one side only"),
    ('{"=": ["x", "y"], "extra": 1}', "an extra top-level key"),
    ('{"◇": ["x", "y"]}', "no equality at the top"),
    ('{"=": [{"◇": ["x"]}, "y"]}', "a unary operation"),
    ('["x", "y"]', "an array at the top level"),
)

if __name__ == "__main__":
    single_main(representation, _CASES, _BAD)
