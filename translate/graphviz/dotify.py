"""ETP formal equation -> Graphviz DOT source.

    digraph law {
      ordering=out;
      n1 [label="="];
      n2 [label="◇"];
      ...
      n1 -> n2;
      n1 -> n7;
      ...
    }

The tree as an explicit node and edge list. Nodes are numbered in pre-order,
which is deliberately *not* a path encoding — an id like `n0110` would spell out
the structure the reader is supposed to recover — so the ids identify without
describing, and the shape lives entirely in the edges.

Left versus right survives only as edge order, which is why the graph declares
`ordering=out`: that is real DOT semantics for "out-edge order is significant",
so the convention is stated inside the artifact rather than assumed. It also
makes argument order a separately observable failure, which matters here — the
magma operation is not commutative, so swapping two arguments yields a
different law rather than a cosmetic difference.

CLI:  python3 dotify.py 4512 | python3 dotify.py --selftest
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _catalogue import (  # noqa: E402
    CANONICAL_OP, Equation, ParseFailure, Representation, Var, parse_equation,
    single_main,
)

GRAPH_NAME = "law"

_NODE = re.compile(r'^\s*(\w+)\s*\[label="([^"]*)"\];\s*$', re.M)
_EDGE = re.compile(r"^\s*(\w+)\s*->\s*(\w+);\s*$", re.M)
_ENVELOPE = re.compile(r"^digraph\s+\w+\s*\{(?P<body>.*)\}$", re.S)
ORDERING = "ordering=out;"


def render(equation: Equation) -> str:
    """Emit DOT: node declarations in pre-order, then edges grouped by source."""
    node_lines: list[str] = []
    edges: list[tuple[int, str, str]] = []
    counter = 0

    def declare(label: str) -> str:
        nonlocal counter
        counter += 1
        node_id = f"n{counter}"
        node_lines.append(f'  {node_id} [label="{label}"];')
        return node_id

    def visit(term) -> str:
        if isinstance(term, Var):
            return declare(term.name)
        node_id = declare(CANONICAL_OP)
        left, right = visit(term.left), visit(term.right)
        edges.append((counter_of(node_id), node_id, left))
        edges.append((counter_of(node_id), node_id, right))
        return node_id

    def counter_of(node_id: str) -> int:
        return int(node_id[1:])

    root = declare("=")
    left, right = visit(equation.lhs), visit(equation.rhs)
    edges.append((counter_of(root), root, left))
    edges.append((counter_of(root), root, right))
    edges.sort(key=lambda edge: edge[0])  # stable: left argument stays first

    body = node_lines + [f"  {src} -> {dst};" for _, src, dst in edges]
    return f"digraph {GRAPH_NAME} {{\n  ordering=out;\n" + "\n".join(body) + "\n}"


def read_back(text: str) -> Equation:
    """Rebuild the tree from the declarations and the ordered edge list.

    The envelope is checked before the contents. It would be easy to read only
    the `n1 [label=...]` and `n1 -> n2` lines and ignore everything around
    them, but then a rendering that had lost its closing brace — or, worse, its
    `ordering=out` declaration, which is what states that the first out-edge is
    the left argument — would still round-trip, and the check would be blind to
    the loss of the very convention the representation depends on.
    """
    outer = _ENVELOPE.match(text.strip())
    if not outer:
        raise ParseFailure("not a single complete `digraph <name> { ... }` block")
    text = outer.group("body")
    if ORDERING not in text.replace(" ", ""):
        raise ParseFailure(f"the graph must declare {ORDERING!r}; without it the "
                           "left/right argument order is not stated")
    labels = dict(_NODE.findall(text))
    if not labels:
        raise ParseFailure("no node declarations")
    edges = _EDGE.findall(text)
    children: dict[str, list[str]] = {}
    for source, target in edges:
        children.setdefault(source, []).append(target)

    targets = {target for _, target in edges}
    roots = [node for node in labels if node not in targets]
    if len(roots) != 1:
        raise ParseFailure(f"expected exactly one root node, found {len(roots)}")
    root = roots[0]
    if labels[root] != "=":
        raise ParseFailure(f"the root must be labelled '=', found {labels[root]!r}")

    seen = {root}

    def build(node_id: str, *, top: bool) -> str:
        if node_id in seen:
            raise ParseFailure(f"{node_id} is reachable twice; this is not a tree")
        seen.add(node_id)
        if node_id not in labels:
            raise ParseFailure(f"edge to undeclared node {node_id}")
        label, kids = labels[node_id], children.get(node_id, [])
        if label == CANONICAL_OP:
            if len(kids) != 2:
                raise ParseFailure(f"{node_id} is an operation with {len(kids)} children")
            inner = f"{build(kids[0], top=False)} {CANONICAL_OP} {build(kids[1], top=False)}"
            return inner if top else f"({inner})"
        if kids:
            raise ParseFailure(f"variable node {node_id} has children")
        if not label.isalnum():
            raise ParseFailure(f"not a variable: {label!r}")
        return label

    sides = children.get(root, [])
    if len(sides) != 2:
        raise ParseFailure(f"the root must have exactly two children, found {len(sides)}")
    equation = parse_equation(f"{build(sides[0], top=True)} = {build(sides[1], top=True)}")
    if len(seen) != len(labels):
        raise ParseFailure(f"{len(labels) - len(seen)} declared nodes are unreachable")
    return equation


def representation(args=None) -> Representation:
    """The `Representation` this directory exports."""
    return Representation(
        name="graphviz", key="graphviz", render=render, read_back=read_back,
        multiline=True, blurb="Graphviz DOT source",
        style={"format": "dot", "graph_name": GRAPH_NAME, "numbering": "pre-order",
               "ordering": "out", "first_edge": "left argument"},
    )


_CASES = (
    ("x = x",
     'digraph law {\n  ordering=out;\n  n1 [label="="];\n  n2 [label="x"];\n'
     '  n3 [label="x"];\n  n1 -> n2;\n  n1 -> n3;\n}'),
    ("x ◇ y = y ◇ x",
     'digraph law {\n  ordering=out;\n  n1 [label="="];\n  n2 [label="◇"];\n'
     '  n3 [label="x"];\n  n4 [label="y"];\n  n5 [label="◇"];\n  n6 [label="y"];\n'
     '  n7 [label="x"];\n  n1 -> n2;\n  n1 -> n5;\n  n2 -> n3;\n  n2 -> n4;\n'
     '  n5 -> n6;\n  n5 -> n7;\n}'),
)

_BAD = (
    ('digraph law {\n  ordering=out;\n  n1 [label="◇"];\n  n2 [label="x"];\n  n1 -> n2;\n}',
     "an operation with one child"),
    ('digraph law {\n  ordering=out;\n  n1 [label="="];\n  n2 [label="x"];\n  n1 -> n2;\n  n1 -> n2;\n}',
     "a node reachable twice"),
    ('digraph law {\n  ordering=out;\n  n1 [label="="];\n  n2 [label="x"];\n  n3 [label="x"];\n'
     '  n4 [label="x"];\n  n1 -> n2;\n  n1 -> n3;\n}', "an unreachable node"),
    ('digraph law {\n  ordering=out;\n  n1 [label="x"];\n  n2 [label="x"];\n'
     '  n1 -> n2;\n}', "a root that is not '='"),
    ('digraph law {\n  ordering=out;\n  n1 [label="="];\n  n2 [label="x"];\n'
     '  n3 [label="x"];\n  n1 -> n2;\n  n1 -> n3;', "no closing brace"),
    ('digraph law {\n  n1 [label="="];\n  n2 [label="x"];\n  n3 [label="x"];\n'
     '  n1 -> n2;\n  n1 -> n3;\n}', "no ordering=out declaration"),
)

if __name__ == "__main__":
    single_main(representation, _CASES, _BAD)
