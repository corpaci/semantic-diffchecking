"""ETP formal equation -> Python lambda predicate. Pure syntax, no model involved.

An ETP law is a tiny, fully specified object — one binary operation, variables,
and an equality — so turning it into a Python predicate is a structural rewrite
of its parse tree, not a translation. There is nothing here for a language
model to guess at, and having one guess would introduce exactly the failure
this project measures.

The target form is a bare lambda over an abstract binary operation:

    x ◇ y = y ◇ x            ->  lambda op, x, y: op(x, y) == op(y, x)
    x = x ◇ (y ◇ x)          ->  lambda op, x, y: x == op(x, op(y, x))

`op` is the magma operation as a two-argument callable; the remaining
parameters are the law's variables in first-appearance order, so the implicit
universal quantification of the formal text becomes the parameter list. Every
`◇` becomes a prefix call `op(a, b)` — prefix application has no precedence or
associativity, so the Python expression tree is isomorphic to the law's term
tree by construction. Deliberately absent, because this output is data for
translation experiments: no function name, no docstring, no comment — nothing
that could carry the ETP equation number or the formal text into the string.

The parse tree comes from [`../../oracle/normalizer.py`](../../oracle/normalizer.py):
`parse_equation` yields `Equation(lhs, rhs)` over `Op(left, right)` and
`Var(name)` nodes, and this module walks that tree. Reusing the oracle's parser
rather than writing a second one is deliberate — a private parser here could
disagree with the one the semantic oracle uses, and then a Python rendering
would no longer be evidence about the same equation.

## Round-tripping

Everything emitted here parses back to the equation it came from — with
Python's own `ast` module, not a parser of ours: `read_back` compiles the
emitted string, walks the `Lambda` node back to the oracle's AST, and returns
the parameter list alongside. `verify_round_trip` checks AST equality plus the
parameter order, which is what `build_catalogue.py` runs over all 4694 laws
(together with a semantic check that the lambda *computes* the law — see
`semantically_agrees`).

CLI:
    python3 lambdify.py "x ◇ (y ◇ z) = (x ◇ y) ◇ z"
    python3 lambdify.py 43 4512 --json
    python3 lambdify.py --selftest
"""

from __future__ import annotations

import argparse
import ast
import json
import keyword
import os
import re
import sys
from itertools import product
from pathlib import Path

# The oracle package is imported by path rather than installed: its modules
# import each other by top-level name and locate their own data with absolute
# paths, so putting the directory on sys.path is both necessary and sufficient.
ORACLE_DIR = Path(
    os.environ.get("TRANSLATE_ORACLE_DIR", Path(__file__).resolve().parents[2] / "oracle")
)
if str(ORACLE_DIR) not in sys.path:
    sys.path.insert(0, str(ORACLE_DIR))

from normalizer import (  # noqa: E402  (path bootstrap must run first)
    Equation,
    Op,
    OutsideFragment,
    ParseFailure,
    Var,
    canonical_key,
    parse_equation,
)

# The operation's parameter name. Not a style option: one fixed spelling is
# what lets `read_back` recognize an application unambiguously, and `op` reads
# as "the operation" without hinting at any concrete interpretation. Doubles
# as a reserved name below: a law whose variable is literally named `op`
# would shadow the operation parameter.
OPNAME = "op"

# What the oracle can emit as a variable name is already almost a Python
# identifier; this pins the claim so `Unrepresentable` is the only escape.
_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")


class Unrepresentable(ValueError):
    """The equation parses, but cannot be written as this Python predicate.

    Raised for a variable name Python would reject or capture: a keyword
    (`lambda`, `in`) or the operation parameter name `op` itself. Distinct
    from the oracle's ParseFailure/OutsideFragment because the *law* is fine —
    only this rendering target cannot spell it. Never triggered by the
    catalogue, whose variables are drawn from `x y z w u v`.
    """


class ReadBackFailure(ValueError):
    """An emitted string does not have the exact shape this module emits."""


def py_var(name: str) -> str:
    """Render one variable name, or refuse.

    A catalogue variable (`x` … `v`) passes through unchanged — it is already
    a Python identifier. Free-text input can carry a name Python would reject
    as a parameter (a keyword) or silently shadow (`op`, the operation); those
    raise `Unrepresentable` rather than emit a lambda that does not mean the
    law it came from.
    """
    if not _IDENT.match(name) or keyword.iskeyword(name):
        raise Unrepresentable(f"variable {name!r} is not usable as a Python parameter")
    if name == OPNAME:
        raise Unrepresentable(f"variable {name!r} would shadow the operation parameter")
    return name


def py_term(term: Var | Op) -> str:
    """Render one side of an equation as nested prefix calls.

    `Op(x, Op(y, z))` becomes `op(x, op(y, z))`. Prefix application needs no
    parenthesization decisions at all — the call syntax *is* the tree — which
    is what makes the Python form the easiest of the representations to read
    back exactly.
    """
    if isinstance(term, Var):
        return py_var(term.name)
    return f"{OPNAME}({py_term(term.left)}, {py_term(term.right)})"


def equation_variables(equation: Equation) -> list[str]:
    """The law's distinct variables in first-appearance order, LHS then RHS.

    This is the parameter order after `op`: the catalogue text is canonical in
    first-appearance order, so the lambda's signature is read straight off the
    formal text.
    """
    names: list[str] = []
    equation.lhs.variables(names)
    equation.rhs.variables(names)
    return names


def py_expression(equation: Equation) -> str:
    """The comparison itself: `op(x, y) == op(y, x)`.

    `==` on the intended domains (ints from a finite carrier) is honest
    equality; the lambda's truth value under every assignment is the law's
    truth value in the magma `op` describes.
    """
    return f"{py_term(equation.lhs)} == {py_term(equation.rhs)}"


def py_lambda(equation: Equation) -> str:
    """Render a parsed `Equation` to the complete lambda string.

    One line, byte-deterministic: `lambda op, <vars>: <lhs> == <rhs>`, with
    the variables in first-appearance order. The catalogue's maximum order is
    4 and maximum variable count 6, so no law is long enough to want wrapping.
    """
    names = [py_var(n) for n in equation_variables(equation)]
    params = ", ".join([OPNAME, *names])
    return f"lambda {params}: {py_expression(equation)}"


# -- Reading a lambda back -----------------------------------------------------


def _to_term(node: ast.expr) -> Var | Op:
    """One side of the comparison, from Python AST back to the oracle's AST.

    Only two shapes are legal — a bare name, or a two-argument positional call
    of `op` — so anything else (an attribute, a keyword argument, a different
    callee) is a hard `ReadBackFailure`, not a best-effort guess.
    """
    if isinstance(node, ast.Name):
        return Var(node.id)
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == OPNAME
        and len(node.args) == 2
        and not node.keywords
    ):
        return Op(_to_term(node.args[0]), _to_term(node.args[1]))
    raise ReadBackFailure(f"not a variable or a binary {OPNAME}(...) call: {ast.dump(node)}")


def read_back(code: str) -> tuple[list[str], Equation]:
    """Parse an emitted lambda string back to (variable parameters, AST).

    Uses Python's own parser (`ast.parse`), so the check is against the
    language's reading of the string, not a private one. The shape is pinned
    exactly: a single lambda, positional-only-free parameters with `op` first,
    a body that is one `==` comparison. Returns the parameters after `op` and
    the reconstructed equation.
    """
    try:
        tree = ast.parse(code, mode="eval")
    except SyntaxError as exc:
        raise ReadBackFailure(f"not valid Python: {exc}") from None
    lam = tree.body
    if not isinstance(lam, ast.Lambda):
        raise ReadBackFailure("not a lambda expression")
    a = lam.args
    if a.posonlyargs or a.kwonlyargs or a.defaults or a.kw_defaults or a.vararg or a.kwarg:
        raise ReadBackFailure("lambda signature is not plain positional parameters")
    params = [arg.arg for arg in a.args]
    if not params or params[0] != OPNAME:
        raise ReadBackFailure(f"first parameter is not {OPNAME!r}: {params}")
    body = lam.body
    if not (
        isinstance(body, ast.Compare)
        and len(body.ops) == 1
        and isinstance(body.ops[0], ast.Eq)
    ):
        raise ReadBackFailure("body is not a single == comparison")
    return params[1:], Equation(_to_term(body.left), _to_term(body.comparators[0]))


def verify_round_trip(equation: Equation) -> bool:
    """Whether the lambda for `equation` reads back as the same equation.

    Structural equality of the parse trees plus an exact parameter-list match —
    the ASTs are frozen dataclasses, so `==` compares shape and variable names
    exactly. This is the check that makes a rendering trustworthy: it catches
    a swapped operand, a mis-nested subterm, or a parameter out of order, each
    of which still *looks* like a plausible lambda.
    Returns False (rather than raising) if the output cannot be read back.
    """
    try:
        params, reparsed = read_back(py_lambda(equation))
    except (ReadBackFailure, Unrepresentable):
        return False
    return reparsed == equation and params == equation_variables(equation)


# -- Semantic check ------------------------------------------------------------

# Small Cayley tables with known, mutually distinguishing behavior:
# left/right projection (tell a swapped operand apart), xor on {0,1} and
# addition mod 3 (structured, non-idempotent), min (idempotent commutative),
# and one arbitrary asymmetric table (hard-coded so runs are deterministic).
# Round-tripping proves the *string* has the right structure; evaluating on
# these proves the string *computes* the law — an independent failure to fake.
TABLES: tuple[tuple[tuple[int, ...], ...], ...] = (
    ((0, 0), (1, 1)),                       # left projection
    ((0, 1), (0, 1)),                       # right projection
    ((0, 1), (1, 0)),                       # xor
    ((0, 1, 2), (1, 2, 0), (2, 0, 1)),      # addition mod 3
    ((0, 0, 0), (0, 1, 1), (0, 1, 2)),      # min
    ((0, 2, 1), (2, 2, 0), (1, 0, 2)),      # arbitrary asymmetric
)


def eval_term(term: Var | Op, env: dict[str, int], table) -> int:
    """Interpret one side of a law in a finite magma, straight off the tree.

    This is the reference semantics the emitted lambda is compared against:
    it never sees the generated string, so the two can only agree by both
    being right.
    """
    if isinstance(term, Var):
        return env[term.name]
    return table[eval_term(term.left, env, table)][eval_term(term.right, env, table)]


def compile_lambda(code: str):
    """The emitted string as a callable, evaluated with no builtins in scope.

    The body needs nothing but its parameters and `==`, so an empty
    `__builtins__` costs nothing and pins that claim — a generated string that
    reached for anything else would fail here.
    """
    return eval(compile(code, "<py_lambda>", "eval"), {"__builtins__": {}})


def semantically_agrees(equation: Equation, code: str) -> bool:
    """Whether the compiled lambda and the tree interpreter agree everywhere.

    Every assignment of every table in `TABLES`, compared truth value by
    truth value — not just "both always true", since most laws fail on most
    tables and the *pattern* of failures is what identifies the law.
    """
    fn = compile_lambda(code)
    names = equation_variables(equation)
    for table in TABLES:
        n = len(table)
        def op(a: int, b: int) -> int:
            return table[a][b]
        for assignment in product(range(n), repeat=len(names)):
            env = dict(zip(names, assignment))
            expected = eval_term(equation.lhs, env, table) == eval_term(equation.rhs, env, table)
            if bool(fn(op, *assignment)) is not expected:
                return False
    return True


# -- Catalogue lookup ----------------------------------------------------------

_MAPPER = None  # None = not tried; False = tried and unavailable


def _get_mapper():
    """The oracle's `NodeMapper`, loaded lazily; None when no catalogue exists.

    A missing catalogue degrades to None rather than failing, so the renderer
    stays usable with no ETP data present — only node lookup goes dark.
    """
    global _MAPPER
    if _MAPPER is None:
        try:
            from mapper import NodeMapper

            _MAPPER = NodeMapper()
        except SystemExit:
            _MAPPER = False
    return _MAPPER or None


def lookup_node(equation: Equation) -> int | None:
    """The ETP node of this law, up to variable renaming and `=` orientation."""
    mapper = _get_mapper()
    if mapper is None:
        return None
    return mapper.key_to_node.get(canonical_key(equation))


def analyze(text: str, node: int | None = None) -> dict:
    """Parse + render, returning errors as data rather than exceptions.

    Mirrors `normalizer.analyze`, so a batch caller can branch on `ok` instead
    of catching, and a failure row still carries the input and the reason.
    """
    try:
        equation = parse_equation(text)
    except ParseFailure as exc:
        return {"input": text, "ok": False, "error": "parse-failure", "reason": str(exc)}
    except OutsideFragment as exc:
        return {"input": text, "ok": False, "error": "outside-fragment", "reason": str(exc)}

    if node is None:
        node = lookup_node(equation)
    try:
        code = py_lambda(equation)
    except Unrepresentable as exc:
        return {"input": text, "ok": False, "error": "python-unrepresentable", "reason": str(exc)}

    return {
        "input": text,
        "ok": True,
        "formal": equation.render(),
        "node": node,
        "py_lambda": code,
        "order": equation.size(),
        "variables": equation_variables(equation),
    }


# -- CLI -----------------------------------------------------------------------


def _resolve(spec: str) -> tuple[str, int | None]:
    """Expand an ETP equation number to (catalogue text, node); pass text
    through as (text, None) for `analyze` to look up. A bare integer means
    "Equation N", the same convention as the sibling renderers."""
    if not spec.strip().isdigit():
        return spec, None
    mapper = _get_mapper()
    if mapper is None:
        raise SystemExit(
            "an ETP equation number was given but no catalogue could be located "
            "($ETP_EQUATIONS, $ETP_ROOT/data/equations.txt, or the oracle's default)"
        )
    node = int(spec)
    if not 1 <= node <= len(mapper.laws):
        raise SystemExit(f"ETP equation number out of range 1..{len(mapper.laws)}: {node}")
    return mapper.laws[node - 1], node


# (input, expected lambda). Chosen to pin the decisions that matter: nesting on
# each side, repeated variables, parameter order, an operator-free law, and the
# maximum-order shape.
_CASES = (
    ("x ◇ y = y ◇ x", "lambda op, x, y: op(x, y) == op(y, x)"),
    ("x = x", "lambda op, x: x == x"),
    ("x = y", "lambda op, x, y: x == y"),
    ("x = x ◇ (x ◇ x)", "lambda op, x: x == op(x, op(x, x))"),
    ("x = (y ◇ x) ◇ (x ◇ z)", "lambda op, x, y, z: x == op(op(y, x), op(x, z))"),
    ("x ◇ (y ◇ z) = (x ◇ y) ◇ z",
     "lambda op, x, y, z: op(x, op(y, z)) == op(op(x, y), z)"),
    ("(x ◇ y) ◇ z = (w ◇ u) ◇ v",
     "lambda op, x, y, z, w, u, v: op(op(x, y), z) == op(op(w, u), v)"),
)


def selftest() -> None:
    """Check the rendering cases, the round trip, the semantics, and the
    error cases; exit non-zero on failure."""
    failures = 0
    for text, expected in _CASES:
        equation = parse_equation(text)
        got = py_lambda(equation)
        ok = got == expected
        failures += not ok
        print(f"[{'ok ' if ok else 'FAIL'}] {text!r} -> {got!r}"
              + ("" if ok else f"  expected {expected!r}"))
        for check, label in ((verify_round_trip(equation), "round trip"),
                             (semantically_agrees(equation, got), "semantics")):
            failures += not check
            if not check:
                print(f"[FAIL] {label} {text!r}")
    print(f"[ok ] round trip + semantics: {len(_CASES)} equations")

    # A deliberately wrong lambda must fail the semantic check: same law text,
    # operands swapped — the mistake round-tripping alone would also catch,
    # and the mistake only semantics catches (a plausible different law).
    wrong = "lambda op, x, y: op(y, x) == op(x, y)"
    ok = not semantically_agrees(parse_equation("x = x ◇ y"), "lambda op, x, y: x == op(y, x)")
    failures += not ok
    print(f"[{'ok ' if ok else 'FAIL'}] semantic check rejects a swapped-operand lambda")
    ok = semantically_agrees(parse_equation("x ◇ y = y ◇ x"), wrong)
    failures += not ok  # symmetric law: swapping sides is still the same law
    print(f"[{'ok ' if ok else 'FAIL'}] semantic check accepts a flipped symmetric law")

    for bad, expected_error in (("a * b * c = c", "parse-failure"),
                                ("a * b = b + a", "outside-fragment"),
                                ("op ◇ y = y ◇ op", "python-unrepresentable"),
                                ("lambda ◇ y = y ◇ lambda", "python-unrepresentable")):
        result = analyze(bad)
        ok = not result["ok"] and result["error"] == expected_error
        failures += not ok
        print(f"[{'ok ' if ok else 'FAIL'}] {bad!r} -> {result.get('error')}")

    print("selftest:", "all passed" if not failures else f"{failures} failures")
    raise SystemExit(1 if failures else 0)


def main() -> None:
    """CLI entry point: render each argument, or run the selftest."""
    parser = argparse.ArgumentParser(
        description="Convert ETP magma equations to Python lambda predicates (no model involved)."
    )
    parser.add_argument("equations", nargs="*",
                        help="equation strings and/or ETP equation numbers")
    parser.add_argument("--json", action="store_true",
                        help="emit a JSON array of records instead of text")
    parser.add_argument("--selftest", action="store_true")
    args = parser.parse_args()

    if args.selftest:
        selftest()
    if not args.equations:
        parser.error("give at least one equation or ETP number (or use --selftest)")

    records = [analyze(text, node) for text, node in map(_resolve, args.equations)]

    if args.json:
        print(json.dumps(records, ensure_ascii=False, indent=2))
        return

    for record in records:
        if not record["ok"]:
            print(f"input:  {record['input']}")
            print(f"error:  {record['error']}")
            print(f"reason: {record['reason']}\n")
            continue
        print(f"formal: {record['formal']}")
        print(f"python: {record['py_lambda']}")
        node = record["node"]
        print(f"node:   {'Equation ' + str(node) if node is not None else 'not in the catalogue'}")
        print(f"order:  {record['order']}   variables: {', '.join(record['variables'])}\n")
    if any(not r["ok"] for r in records):
        raise SystemExit(1)


if __name__ == "__main__":
    main()


# Exported for `build_catalogue.py` and any other consumer.
__all__ = [
    "OPNAME",
    "ORACLE_DIR",
    "TABLES",
    "ReadBackFailure",
    "Unrepresentable",
    "analyze",
    "compile_lambda",
    "equation_variables",
    "eval_term",
    "lookup_node",
    "py_expression",
    "py_lambda",
    "py_term",
    "py_var",
    "read_back",
    "semantically_agrees",
    "verify_round_trip",
]
