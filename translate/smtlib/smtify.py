"""ETP formal equation -> SMT-LIB 2 (the dialect Z3 and cvc5 read).

    (declare-sort M 0)
    (declare-fun op (M M) M)
    (assert (forall ((x M) (y M) (z M))
      (= (op x (op y z)) (op (op x y) z))))

The same term as `../tptp/`, wrapped in the ceremony a real SMT script carries:
a sort declaration, a typed function symbol, and an explicit quantifier block
with a sort on every binder. Nothing about the law changes, so the pair
isolates whether surrounding boilerplate dilutes the signal — the law is four
tokens of a four-line file.

CLI:  python3 smtify.py 4512 | python3 smtify.py --selftest
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _catalogue import (  # noqa: E402
    CANONICAL_OP, Equation, ParseFailure, Representation, Var, parse_equation,
    single_main, variables,
)

SORT = "M"
FUNCTION = "op"


def _sexpr(term) -> str:
    if isinstance(term, Var):
        return term.name
    return f"({FUNCTION} {_sexpr(term.left)} {_sexpr(term.right)})"


def render(equation: Equation) -> str:
    """Emit a self-contained SMT-LIB script asserting the law."""
    binders = " ".join(f"({name} {SORT})" for name in variables(equation))
    return (f"(declare-sort {SORT} 0)\n"
            f"(declare-fun {FUNCTION} ({SORT} {SORT}) {SORT})\n"
            f"(assert (forall ({binders})\n"
            f"  (= {_sexpr(equation.lhs)} {_sexpr(equation.rhs)})))")


def _forms(text: str) -> list:
    """Tokenize and parse the script into nested lists."""
    tokens = text.replace("(", " ( ").replace(")", " ) ").split()
    position = 0

    def parse():
        nonlocal position
        if position >= len(tokens):
            raise ParseFailure("unexpected end of input")
        token = tokens[position]
        position += 1
        if token == ")":
            raise ParseFailure("unexpected ')'")
        if token != "(":
            return token
        out = []
        while position < len(tokens) and tokens[position] != ")":
            out.append(parse())
        if position >= len(tokens):
            raise ParseFailure("unbalanced '('")
        position += 1
        return out

    forms = []
    while position < len(tokens):
        forms.append(parse())
    return forms


def read_back(text: str) -> Equation:
    """Find the single `assert`, walk its body, and parse the recovered term.

    The declarations are checked too. They are boilerplate, but a script that
    asserted a law about an undeclared function would not be an SMT script, and
    a reader that ignored them could not tell the difference.
    """
    forms = _forms(text)
    if not any(isinstance(f, list) and f[:1] == ["declare-fun"] and f[1:2] == [FUNCTION]
               for f in forms):
        raise ParseFailure(f"no (declare-fun {FUNCTION} ...) declaration")
    asserts = [f for f in forms if isinstance(f, list) and f[:1] == ["assert"]]
    if len(asserts) != 1 or len(asserts[0]) != 2:
        raise ParseFailure(f"expected exactly one (assert ...), found {len(asserts)}")

    body = asserts[0][1]
    if not (isinstance(body, list) and len(body) == 3 and body[0] == "forall"):
        raise ParseFailure("the assertion must be (forall (binders) body)")
    binders = body[1]
    if not isinstance(binders, list) or not binders:
        raise ParseFailure("the quantifier must bind at least one variable")
    declared = []
    for binder in binders:
        if not (isinstance(binder, list) and len(binder) == 2):
            raise ParseFailure(f"a binder must be (name sort), found {binder!r}")
        declared.append(binder[0])

    equality = body[2]
    if not (isinstance(equality, list) and len(equality) == 3 and equality[0] == "="):
        raise ParseFailure("the quantifier body must be (= lhs rhs)")

    def term(node, *, top: bool) -> str:
        if isinstance(node, str):
            return node
        if len(node) == 3 and node[0] == FUNCTION:
            inner = f"{term(node[1], top=False)} {CANONICAL_OP} {term(node[2], top=False)}"
            return inner if top else f"({inner})"
        raise ParseFailure(f"expected ({FUNCTION} a b) or a variable, found {node!r}")

    parsed = parse_equation(f"{term(equality[1], top=True)} = {term(equality[2], top=True)}")
    if sorted(declared) != sorted(variables(parsed)):
        raise ParseFailure(
            f"bound variables {sorted(declared)} do not match the ones used "
            f"{sorted(variables(parsed))}"
        )
    return parsed


def representation(args=None) -> Representation:
    """The `Representation` this directory exports."""
    return Representation(
        name="smtlib", key="smtlib", render=render, read_back=read_back, multiline=True,
        blurb="SMT-LIB 2 script",
        style={"logic": "uninterpreted functions", "sort": SORT, "function": FUNCTION,
               "quantifier": "forall", "declarations": True},
    )


_CASES = (
    ("x = x",
     "(declare-sort M 0)\n(declare-fun op (M M) M)\n(assert (forall ((x M))\n  (= x x)))"),
    ("x ◇ y = y ◇ x",
     "(declare-sort M 0)\n(declare-fun op (M M) M)\n(assert (forall ((x M) (y M))\n"
     "  (= (op x y) (op y x))))"),
    ("x ◇ (y ◇ z) = (x ◇ y) ◇ z",
     "(declare-sort M 0)\n(declare-fun op (M M) M)\n(assert (forall ((x M) (y M) (z M))\n"
     "  (= (op x (op y z)) (op (op x y) z))))"),
)

_BAD = (
    ("(assert (forall ((x M)) (= x x)))", "no declare-fun"),
    ("(declare-fun op (M M) M)\n(= x x)", "no assert"),
    ("(declare-fun op (M M) M)\n(assert (= x x))", "no quantifier"),
    ("(declare-fun op (M M) M)\n(assert (forall ((x M)) (= (op x y) x)))",
     "a free variable in the body"),
    ("(declare-fun op (M M) M)\n(assert (forall ((x M)) (= (op x) x)))",
     "a unary application of op"),
)

if __name__ == "__main__":
    single_main(representation, _CASES, _BAD)
