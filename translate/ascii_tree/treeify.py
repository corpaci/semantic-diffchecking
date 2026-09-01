"""ETP formal equation -> indented syntax tree.

    x ◇ (y ◇ z) = (x ◇ y) ◇ z

    =
    ├── ◇
    │   ├── x
    │   └── ◇
    │       ├── y
    │       └── z
    └── ◇
        ├── ◇
        │   ├── x
        │   └── y
        └── z

The only rendering in `translate/` whose structure is not carried by any token:
it lives in the indentation. Every other representation is a sentence to be
parsed left to right; this one has to be read down a column, and the first
child of a node is always its left argument.

Depth is four columns per level, drawn with the usual box characters, so a
reader recovers the tree by counting indentation and nothing else.

CLI:  python3 treeify.py 4512 | python3 treeify.py --selftest
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _catalogue import (  # noqa: E402
    CANONICAL_OP, Equation, Op, ParseFailure, Representation, Var, parse_equation,
    single_main,
)

BRANCH, LAST, PIPE, GAP = "├── ", "└── ", "│   ", "    "
WIDTH = 4


def render(equation: Equation) -> str:
    """Draw the equation as a two-child tree rooted at `=`."""
    lines = ["="]

    def emit(term, prefix: str, last: bool) -> None:
        label = term.name if isinstance(term, Var) else CANONICAL_OP
        lines.append(f"{prefix}{LAST if last else BRANCH}{label}")
        if isinstance(term, Op):
            child = prefix + (GAP if last else PIPE)
            emit(term.left, child, False)
            emit(term.right, child, True)

    emit(equation.lhs, "", False)
    emit(equation.rhs, "", True)
    return "\n".join(lines)


def read_back(text: str) -> Equation:
    """Recover (depth, label) per line, then rebuild the tree by descent."""
    lines = text.rstrip("\n").splitlines()
    if not lines or lines[0].strip() != "=":
        raise ParseFailure("the first line must be the root '='")

    nodes: list[tuple[int, str]] = []
    for raw in lines[1:]:
        found = [i for i in (raw.find(BRANCH), raw.find(LAST)) if i >= 0]
        if not found:
            raise ParseFailure(f"no branch marker on line {raw!r}")
        start = min(found)
        if start % WIDTH:
            raise ParseFailure(f"branch marker is not on a {WIDTH}-column boundary: {raw!r}")
        prefix = raw[:start]
        if any(prefix[i:i + WIDTH] not in (PIPE, GAP) for i in range(0, start, WIDTH)):
            raise ParseFailure(f"malformed indentation: {raw!r}")
        nodes.append((start // WIDTH + 1, raw[start + WIDTH:]))

    position = 0

    def build(depth: int, *, top: bool) -> str:
        nonlocal position
        if position >= len(nodes):
            raise ParseFailure("the tree ends before every argument is given")
        found_depth, label = nodes[position]
        if found_depth != depth:
            raise ParseFailure(f"expected a node at depth {depth}, found depth {found_depth}")
        position += 1
        if label == CANONICAL_OP:
            left = build(depth + 1, top=False)
            right = build(depth + 1, top=False)
            inner = f"{left} {CANONICAL_OP} {right}"
            return inner if top else f"({inner})"
        if not label.isalnum():
            raise ParseFailure(f"not a variable: {label!r}")
        return label

    lhs = build(1, top=True)
    rhs = build(1, top=True)
    if position != len(nodes):
        raise ParseFailure(f"{len(nodes) - position} lines left over after the tree")
    return parse_equation(f"{lhs} = {rhs}")


def representation(args=None) -> Representation:
    """The `Representation` this directory exports."""
    return Representation(
        name="ascii_tree", key="ascii_tree", render=render, read_back=read_back,
        multiline=True, blurb="indented syntax tree",
        style={"form": "indented tree", "indent_columns": WIDTH,
               "markers": [BRANCH.strip(), LAST.strip(), PIPE.strip()],
               "first_child": "left argument"},
    )


_CASES = (
    ("x = x", "=\n├── x\n└── x"),
    ("x ◇ y = y ◇ x",
     "=\n├── ◇\n│   ├── x\n│   └── y\n└── ◇\n    ├── y\n    └── x"),
    ("x ◇ (y ◇ z) = (x ◇ y) ◇ z",
     "=\n├── ◇\n│   ├── x\n│   └── ◇\n│       ├── y\n│       └── z\n"
     "└── ◇\n    ├── ◇\n    │   ├── x\n    │   └── y\n    └── z"),
)

_BAD = (
    ("◇\n├── x\n└── x", "a root that is not '='"),
    ("=\n├── x", "only one side"),
    ("=\n├── ◇\n│   ├── x\n└── x", "an operation missing an argument"),
    ("=\n├── x\n└── x\n└── x", "a leftover line"),
    ("=\n  ├── x\n  └── x", "indentation off the column boundary"),
)

if __name__ == "__main__":
    single_main(representation, _CASES, _BAD)
