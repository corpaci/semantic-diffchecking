"""ETP formal equation -> Polish (prefix) notation, symbols only.

    x ◇ (y ◇ z) = (x ◇ y) ◇ z   ->   = ◇ x ◇ y z ◇ ◇ x y z

The operator comes before its arguments and nothing delimits them; the tree is
recovered by knowing that `◇` takes exactly two. Unambiguous for the same
reason `../text2/` is, with every word of English scaffolding removed.

That makes it the control for `../text2/`, which is this same prefix order
dressed as `the diamond of … and …`. Comparing the two isolates how much of
`text2/`'s legibility came from the words rather than the ordering — the sort of
minimal pair this project is built to measure.

CLI:  python3 polishify.py 4512 | python3 polishify.py --selftest
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _catalogue import (  # noqa: E402
    CANONICAL_OP, Equation, ParseFailure, Representation, Var, parse_equation,
    single_main,
)


def _prefix(term) -> str:
    if isinstance(term, Var):
        return term.name
    return f"{CANONICAL_OP} {_prefix(term.left)} {_prefix(term.right)}"


def render(equation: Equation) -> str:
    """Emit `= <lhs> <rhs>` in prefix order."""
    return f"= {_prefix(equation.lhs)} {_prefix(equation.rhs)}"


def read_back(text: str) -> Equation:
    """Recursive descent over the tokens; rebuilds canonical infix, then parses."""
    tokens = text.split()
    if not tokens or tokens[0] != "=":
        raise ParseFailure("a prefix equation must start with '='")
    position = 1

    def term(*, top: bool) -> str:
        nonlocal position
        if position >= len(tokens):
            raise ParseFailure("ran out of tokens while reading a term")
        token = tokens[position]
        position += 1
        if token == CANONICAL_OP:
            left = term(top=False)
            right = term(top=False)
            inner = f"{left} {CANONICAL_OP} {right}"
            return inner if top else f"({inner})"
        if not token.isalnum():
            raise ParseFailure(f"not a variable: {token!r}")
        return token

    lhs = term(top=True)
    rhs = term(top=True)
    if position != len(tokens):
        raise ParseFailure(f"trailing tokens: {' '.join(tokens[position:])!r}")
    return parse_equation(f"{lhs} = {rhs}")


def representation(args=None) -> Representation:
    """The `Representation` this directory exports."""
    return Representation(
        name="polish", key="polish", render=render, read_back=read_back,
        blurb="Polish (prefix) notation",
        style={"form": "prefix", "operator": CANONICAL_OP, "equality": "="},
    )


_CASES = (
    ("x = x", "= x x"),
    ("x ◇ y = y ◇ x", "= ◇ x y ◇ y x"),
    ("x ◇ (y ◇ z) = (x ◇ y) ◇ z", "= ◇ x ◇ y z ◇ ◇ x y z"),
)

_BAD = (
    ("◇ x y", "no leading '='"),
    ("= x y z", "a trailing token"),
    ("= ◇ x ◇ y", "ran out of arguments"),
    ("= x", "only one side"),
)

if __name__ == "__main__":
    single_main(representation, _CASES, _BAD)
