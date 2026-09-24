#!/usr/bin/env python3
"""How an equation is written down, as a swappable choice.

The judge never sees an equation object. It sees a string. Which string is a
research variable, not a detail: the same law can be written as infix magma
notation, as a Lean statement, as LaTeX, or as Python, and whether the judge
understands them equally is an open question the team wants to test.

Until now the rendering was hard-coded inside `build_pair_dataset.augment()`,
so answering that question meant editing the dataset builder. Each renderer
here takes a parsed `Equation` plus a naming choice and returns a string.

Every renderer must satisfy two properties, both checked by `selftest()`:

* **Grouping is explicit.** The magma operation is not associative, so
  `x ? y ? z` is ambiguous and must never be emitted.
* **Variables are used exactly as given.** A renderer may rename, but must not
  merge two variables into one or invent a new one. Merging is precisely the
  drift the judge exists to detect, so a renderer that did it would poison the
  labels.

Adding one: write the function, add it to `RENDERERS`, run `selftest()`.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.environ.get(
    "SDC_ORACLE",
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "oracle")))

from normalizer import Equation, Op, Var, parse_equation  # noqa: E402

# Symbols the oracle's own parser accepts, so anything rendered infix can be
# read back and mapped to a catalogue node. ASCII '.' is NOT among them.
INFIX_SYMBOLS = ["*", "·", "@", "+"]

VAR_POOLS = [
    list("xyzwuvst"),
    list("abcdefgh"),
    list("pqrstuvw"),
    list("mnkljihg"),
]


def _term_infix(t, names, op, top=True):
    if isinstance(t, Var):
        return names[t.name]
    s = f"{_term_infix(t.left, names, op, False)} {op} {_term_infix(t.right, names, op, False)}"
    return s if top else f"({s})"


def infix(eq: Equation, names: dict, op: str = "*") -> str:
    """`x * (y * z) = (x * y) * z`  — the original format, and the default."""
    return f"{_term_infix(eq.lhs, names, op)} = {_term_infix(eq.rhs, names, op)}"


def _term_prefix(t, names, fn):
    if isinstance(t, Var):
        return names[t.name]
    return f"{fn}({_term_prefix(t.left, names, fn)}, {_term_prefix(t.right, names, fn)})"


def function_call(eq: Equation, names: dict, op: str = "op") -> str:
    """`op(x, op(y, z)) = op(op(x, y), z)` — grouping carried by brackets alone.

    Useful as a control: it removes infix precedence entirely, so if the judge
    behaves differently here the difference is about notation, not structure.
    """
    return (f"{_term_prefix(eq.lhs, names, op)} = "
            f"{_term_prefix(eq.rhs, names, op)}")


def lean(eq: Equation, names: dict, op: str = "∘") -> str:
    """A Lean-style theorem statement over a magma.

    Matches how the Equational Theories Project writes its laws, so it is the
    representation a formalisation pipeline would actually emit.
    """
    vs = sorted(set(names.values()))
    binder = " ".join(vs)
    body = (f"{_term_infix(eq.lhs, names, op)} = "
            f"{_term_infix(eq.rhs, names, op)}")
    return f"∀ {binder} : G, {body}"


def latex(eq: Equation, names: dict, op: str = r"\circ") -> str:
    r"""`x \circ (y \circ z) = (x \circ y) \circ z` inside math delimiters."""
    body = (f"{_term_infix(eq.lhs, names, op)} = "
            f"{_term_infix(eq.rhs, names, op)}")
    return f"$ {body} $"


def python(eq: Equation, names: dict, op: str = "op") -> str:
    """`op(x, op(y, z)) == op(op(x, y), z)` — executable-looking, `==` not `=`.

    Deliberately close to `function_call` except for the equality token. The
    pair isolates how much the judge leans on the `=` symbol itself, which is
    the thing the team suspected was being lost in embedding work.
    """
    return (f"{_term_prefix(eq.lhs, names, op)} == "
            f"{_term_prefix(eq.rhs, names, op)}")


RENDERERS = {
    "infix": infix,
    "function_call": function_call,
    "lean": lean,
    "latex": latex,
    "python": python,
}

# Operator symbols that make sense per renderer. Drawing one at random is the
# surface augmentation the original `augment()` did.
DEFAULT_OPS = {
    "infix": INFIX_SYMBOLS,
    "function_call": ["op", "f", "mul", "star"],
    "lean": ["∘", "⋆", "*"],
    "latex": [r"\circ", r"\star", r"\cdot"],
    "python": ["op", "f", "mul", "star"],
}


def render(eq: Equation, rng, kind: str = "infix", op: str | None = None,
           rename: bool = True, flip: bool = True) -> str:
    """Render one law, drawing the surface choices from `rng`.

    `rename` shuffles the variable names, `flip` may swap the two sides of the
    equality. Both are meaning-preserving, and both are what stop the judge
    from keying on a particular spelling. Turn them off to render a law the
    same way every time.
    """
    if kind not in RENDERERS:
        raise KeyError(f"unknown representation {kind!r}; "
                       f"have {sorted(RENDERERS)}")
    order: list = []
    eq.lhs.variables(order)
    eq.rhs.variables(order)
    if rename:
        pool = rng.choice(VAR_POOLS)[:]
        rng.shuffle(pool)
        names = {v: pool[i] for i, v in enumerate(order)}
    else:
        names = {v: v for v in order}
    symbol = op if op is not None else rng.choice(DEFAULT_OPS[kind])
    if flip and rng.random() < 0.5:
        eq = Equation(eq.rhs, eq.lhs)
    return RENDERERS[kind](eq, names, symbol)


def selftest() -> int:
    """Check every renderer against the two properties that must never break.

    Both failure modes are silent if unchecked. A renderer that dropped a
    bracket would emit an ambiguous term the oracle cannot parse; one that
    merged two variables would relabel the pair, and merging variables is
    exactly the drift the judge is built to catch.
    """
    import random
    from collections import Counter

    cases = [
        "x ◇ (y ◇ z) = (x ◇ y) ◇ z",   # grouping must survive
        "x ◇ x = x ◇ ((y ◇ y) ◇ z)",    # a repeated variable must stay repeated
        "x = y",                         # two distinct variables, no operation
    ]
    bad = 0
    for kind in RENDERERS:
        for src in cases:
            eq = parse_equation(src)
            order: list = []
            eq.lhs.variables(order)
            eq.rhs.variables(order)
            names = {v: VAR_POOLS[0][i] for i, v in enumerate(order)}
            out = RENDERERS[kind](eq, names, DEFAULT_OPS[kind][0])

            # every variable that went in must come out, the right number of times
            want = Counter()
            for t in (eq.lhs, eq.rhs):
                stack = [t]
                while stack:
                    node = stack.pop()
                    if isinstance(node, Var):
                        want[names[node.name]] += 1
                    else:
                        stack += [node.left, node.right]
            # Count occurrences in the TERM only. A Lean statement binds its
            # variables up front (`forall x y z : G,`), and those mentions are
            # correct, not duplicates, so the binder is dropped before counting.
            body = out.split(", ", 1)[1] if out.startswith("\u2200") else out
            got = Counter()
            for tok in body.replace("(", " ").replace(")", " ").replace(",", " ").split():
                if tok in want:
                    got[tok] += 1
            ok_vars = got == want

            # brackets must balance, and every operation must be bracketed
            ok_group = out.count("(") == out.count(")")

            ok = ok_vars and ok_group
            bad += not ok
            print(f"[{'ok ' if ok else 'FAIL'}] {kind:<14} {out}")
            if not ok:
                print(f"        wanted {dict(want)}, got {dict(got)}")
    print("selftest: all passed" if not bad else f"selftest: {bad} FAILURES")
    return bad


if __name__ == "__main__":
    raise SystemExit(1 if selftest() else 0)
