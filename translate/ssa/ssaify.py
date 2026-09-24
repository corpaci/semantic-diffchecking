"""ETP formal equation -> single-assignment (let-bound) straight-line form.

    x ◇ (y ◇ z) = (x ◇ y) ◇ z

    t1 = y ◇ z
    t2 = x ◇ t1
    t3 = x ◇ y
    t4 = t3 ◇ z
    assert t2 = t4

Every operation gets its own line and its own name, so the rendering contains
no nesting at all: the tree survives only as the def-use edges between
temporaries. That is the point. Each of the other representations lets a reader
recover structure by matching delimiters or counting arities; here there is
nothing to match, and the tree has to be rebuilt from data flow.

Temporaries are numbered in post-order, left side before right, so the numbering
is a function of the tree and nothing else. `t` is a legal ETP variable letter
but never collides: the catalogue's laws use at most six distinct variables
(`x y z w u v`), and a temporary is always `t` followed by digits.

CLI:  python3 ssaify.py 4512 | python3 ssaify.py --selftest
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _catalogue import (  # noqa: E402
    CANONICAL_OP, Equation, ParseFailure, Representation, Var, single_main,
    parse_equation,
)

TEMP = "t"


def render(equation: Equation) -> str:
    """Emit the straight-line form: one definition per operation, then `assert`."""
    lines: list[str] = []
    counter = 0

    def go(term) -> str:
        nonlocal counter
        if isinstance(term, Var):
            return term.name
        left, right = go(term.left), go(term.right)
        counter += 1
        name = f"{TEMP}{counter}"
        lines.append(f"{name} = {left} {CANONICAL_OP} {right}")
        return name

    lhs, rhs = go(equation.lhs), go(equation.rhs)
    lines.append(f"assert {lhs} = {rhs}")
    return "\n".join(lines)


def _is_temp(name: str) -> bool:
    """Whether `name` is a temporary (`t` followed by at least one digit)."""
    return name.startswith(TEMP) and name[len(TEMP):].isdigit()


def read_back(text: str) -> Equation:
    """Rebuild the equation by substituting each definition into its uses.

    Definitions are inlined as parenthesized infix, and the result is handed to
    the oracle's parser. A temporary that is used before it is defined is an
    error rather than a silently-invented variable — otherwise a mangled
    rendering could still read back as *some* equation.
    """
    env: dict[str, str] = {}
    target: tuple[str, str] | None = None

    def resolve(atom: str) -> str:
        if atom in env:
            return env[atom]
        if _is_temp(atom):
            raise ParseFailure(f"{atom} is used before it is defined")
        return atom

    for raw in text.strip().splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("assert "):
            if target is not None:
                raise ParseFailure("more than one assert line")
            parts = line[len("assert "):].split(" = ")
            if len(parts) != 2:
                raise ParseFailure(f"malformed assert line: {line!r}")
            target = (resolve(parts[0].strip()), resolve(parts[1].strip()))
            continue
        if target is not None:
            raise ParseFailure("a definition follows the assert line")
        name, sep, expr = line.partition(" = ")
        if not sep:
            raise ParseFailure(f"not a definition: {line!r}")
        if name in env:
            raise ParseFailure(f"{name} is defined twice")
        operands = expr.split(f" {CANONICAL_OP} ")
        if len(operands) != 2:
            raise ParseFailure(f"a definition must combine exactly two operands: {line!r}")
        env[name] = f"({resolve(operands[0].strip())} {CANONICAL_OP} "\
                    f"{resolve(operands[1].strip())})"

    if target is None:
        raise ParseFailure("no assert line")
    return parse_equation(f"{target[0]} = {target[1]}")


def representation(args=None) -> Representation:
    """The `Representation` this directory exports."""
    return Representation(
        name="ssa", key="ssa", render=render, read_back=read_back, multiline=True,
        blurb="single-assignment straight-line form",
        style={"form": "ssa", "temporary_prefix": TEMP, "order": "post-order",
               "operator": CANONICAL_OP},
    )


_CASES = (
    ("x = x", "assert x = x"),
    ("x ◇ y = y ◇ x", "t1 = x ◇ y\nt2 = y ◇ x\nassert t1 = t2"),
    ("x ◇ (y ◇ z) = (x ◇ y) ◇ z",
     "t1 = y ◇ z\nt2 = x ◇ t1\nt3 = x ◇ y\nt4 = t3 ◇ z\nassert t2 = t4"),
)

_BAD = (
    ("t1 = x ◇ y\nassert t1 = t9", "a temporary that is never defined"),
    ("t1 = x ◇ y\nt1 = y ◇ x\nassert t1 = t1", "a temporary defined twice"),
    ("t1 = x ◇ y ◇ z\nassert t1 = t1", "a definition with three operands"),
    ("t1 = x ◇ y", "no assert line"),
)

if __name__ == "__main__":
    single_main(representation, _CASES, _BAD)
