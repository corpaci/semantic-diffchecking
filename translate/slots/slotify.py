"""ETP formal equation -> positional slot encoding (names removed).

    x ◇ (y ◇ z) = (x ◇ y) ◇ z   ->   [[1, [2, 3]], [[1, 2], 3]]

A variable becomes the number of its first appearance, an operation becomes a
two-element list, and the whole equation is `[lhs, rhs]`. No letters, no
operator symbol, no delimiters that mean anything but nesting.

What survives is exactly the tree shape and the co-reference pattern — which
occurrences are the same variable — and nothing else. Equation 8,
`x = x ◇ (x ◇ x)`, becomes `[1, [1, [1, 1]]]`: pure shape and sharing.

Numbering by first appearance in a left-to-right walk is the same order the
oracle's normalizer uses when it renames variables, so on this catalogue (whose
laws are already canonical) the encoding is a bijection with the law.

CLI:  python3 slotify.py 4512 | python3 slotify.py --selftest
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _catalogue import (  # noqa: E402
    CANONICAL_OP, Equation, ParseFailure, Representation, Var, parse_equation,
    single_main, slot_name,
)


def render(equation: Equation) -> str:
    """Encode the equation as `[lhs, rhs]` over slot numbers."""
    index: dict[str, int] = {}

    def encode(term):
        if isinstance(term, Var):
            return index.setdefault(term.name, len(index) + 1)
        return [encode(term.left), encode(term.right)]

    return json.dumps([encode(equation.lhs), encode(equation.rhs)])


def read_back(text: str) -> Equation:
    """Decode slot numbers back to canonical variable letters and parse."""
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ParseFailure(f"not valid JSON: {exc}") from None
    if not isinstance(data, list) or len(data) != 2:
        raise ParseFailure("the top level must be a two-element list [lhs, rhs]")

    def decode(node, *, top: bool) -> str:
        if isinstance(node, bool) or not isinstance(node, (int, list)):
            raise ParseFailure(f"expected a slot number or a pair, found {node!r}")
        if isinstance(node, int):
            return slot_name(node)
        if len(node) != 2:
            raise ParseFailure(f"an operation must have exactly two arguments, found {node!r}")
        inner = (f"{decode(node[0], top=False)} {CANONICAL_OP} "
                 f"{decode(node[1], top=False)}")
        return inner if top else f"({inner})"

    return parse_equation(f"{decode(data[0], top=True)} = {decode(data[1], top=True)}")


def representation(args=None) -> Representation:
    """The `Representation` this directory exports."""
    return Representation(
        name="slots", key="slots", render=render, read_back=read_back,
        blurb="positional slot encoding",
        style={"form": "nested-lists", "numbering": "first appearance, 1-based",
               "operation": "two-element list"},
    )


_CASES = (
    ("x = x", "[1, 1]"),
    ("x ◇ y = y ◇ x", "[[1, 2], [2, 1]]"),
    ("x ◇ (y ◇ z) = (x ◇ y) ◇ z", "[[1, [2, 3]], [[1, 2], 3]]"),
)

_BAD = (
    ("[1, 2, 3]", "a three-element top level"),
    ("[[1, 2, 3], 1]", "an operation with three arguments"),
    ('[1, "x"]', "a variable given by name instead of slot"),
    ("[1, 99]", "a slot number out of range"),
    ("not json", "not JSON at all"),
)

if __name__ == "__main__":
    single_main(representation, _CASES, _BAD)
