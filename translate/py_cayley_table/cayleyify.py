"""ETP formal equation -> Python finite-magma checker. Pure syntax, no model involved.

An ETP law is a tiny, fully specified object — one binary operation, variables,
and an equality — so turning it into a Python checker is a structural rewrite
of its parse tree, not a translation. There is nothing here for a language
model to guess at, and having one guess would introduce exactly the failure
this project measures.

The target form is a function that decides the law on one finite magma, given
as a Cayley table (`table[a][b]` = a ◇ b over the carrier `range(len(table))`):

    x ◇ y = y ◇ x  ->  def law(table):
                           n = len(table)
                           return all(table[x][y] == table[y][x] for x in range(n) for y in range(n))

Each `◇` becomes a table lookup — `Op(a, b)` renders as `table[a][b]`, nested
lookups for nested operations — and the formal text's implicit universal
quantification becomes one `for` clause per variable, in first-appearance
order. This is the representation under which a law is *decidable*: the ETP
itself refutes implications by exhibiting finite magmas, and this checker run
on such a table reproduces exactly that judgment. Deliberately absent, because
this output is data for translation experiments: the function is always named
`law`, and there is no docstring or comment — nothing that could carry the ETP
equation number or the formal text into the string.

The parse tree comes from [`../../oracle/normalizer.py`](../../oracle/normalizer.py):
`parse_equation` yields `Equation(lhs, rhs)` over `Op(left, right)` and
`Var(name)` nodes, and this module walks that tree. Reusing the oracle's parser
rather than writing a second one is deliberate — a private parser here could
disagree with the one the semantic oracle uses, and then a Python rendering
would no longer be evidence about the same equation.

## Round-tripping

Everything emitted here parses back to the equation it came from — with
Python's own `ast` module, not a parser of ours: `read_back` compiles the
emitted string, checks the fixed scaffold (`def law(table):`, `n = len(table)`,
`return all(...)`), and walks the comparison and the `for` clauses back to the
oracle's AST plus the variable order. `verify_round_trip` checks AST equality
plus that order, which is what `build_catalogue.py` runs over all 4694 laws
(together with a semantic check that the checker *decides* the law — see
`semantically_agrees`).

CLI:
    python3 cayleyify.py "x ◇ (y ◇ z) = (x ◇ y) ◇ z"
    python3 cayleyify.py 43 4512 --json
    python3 cayleyify.py --selftest
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

# The fixed names in the scaffold. Not style options: one fixed spelling each
# is what lets `read_back` recognize the shape unambiguously, and none of them
# hints at a law's identity. All three are reserved below: a law whose
# variable collides with one would shadow it.
FUNC = "law"      # every checker is `def law(table)` — deliberately number-free
TABLE = "table"   # the Cayley table parameter
SIZE = "n"        # the local carrier size, `n = len(table)`

_RESERVED = frozenset({FUNC, TABLE, SIZE})

# What the oracle can emit as a variable name is already almost a Python
# identifier; this pins the claim so `Unrepresentable` is the only escape.
_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")


class Unrepresentable(ValueError):
    """The equation parses, but cannot be written as this Python checker.

    Raised for a variable name Python would reject or capture: a keyword
    (`for`, `in`) or one of the scaffold's own names (`law`, `table`, `n`).
    Distinct from the oracle's ParseFailure/OutsideFragment because the *law*
    is fine — only this rendering target cannot spell it. Never triggered by
    the catalogue, whose variables are drawn from `x y z w u v`.
    """


class ReadBackFailure(ValueError):
    """An emitted string does not have the exact shape this module emits."""


def py_var(name: str) -> str:
    """Render one variable name, or refuse.

    A catalogue variable (`x` … `v`) passes through unchanged — it is already
    a Python identifier. Free-text input can carry a name Python would reject
    as a loop target (a keyword) or silently shadow (`table`, `n`, `law`);
    those raise `Unrepresentable` rather than emit a checker that does not
    mean the law it came from.
    """
    if not _IDENT.match(name) or keyword.iskeyword(name):
        raise Unrepresentable(f"variable {name!r} is not usable as a Python name")
    if name in _RESERVED:
        raise Unrepresentable(f"variable {name!r} would shadow the checker's {name!r}")
    return name


def table_term(term: Var | Op) -> str:
    """Render one side of an equation as nested table lookups.

    `Op(x, Op(y, z))` becomes `table[x][table[y][z]]`. Subscription needs no
    parenthesization decisions at all — the lookup nesting *is* the tree —
    which is what makes this form easy to read back exactly.
    """
    if isinstance(term, Var):
        return py_var(term.name)
    return f"{TABLE}[{table_term(term.left)}][{table_term(term.right)}]"


def equation_variables(equation: Equation) -> list[str]:
    """The law's distinct variables in first-appearance order, LHS then RHS.

    This is the `for`-clause order: the catalogue text is canonical in
    first-appearance order, so the quantifier nest is read straight off the
    formal text.
    """
    names: list[str] = []
    equation.lhs.variables(names)
    equation.rhs.variables(names)
    return names


def checker_source(equation: Equation) -> str:
    """Render a parsed `Equation` to the complete checker string.

    A fixed three-line scaffold, byte-deterministic — the only degrees of
    freedom are the comparison and the `for` clauses. Every ETP law has at
    least one variable (the fragment has no constants), which the generator
    expression relies on; a variable-free identity is refused rather than
    rendered into some second shape.
    """
    names = [py_var(v) for v in equation_variables(equation)]
    if not names:
        raise Unrepresentable("a law with no variables has no generator expression form")
    loops = " ".join(f"for {v} in range({SIZE})" for v in names)
    body = f"{table_term(equation.lhs)} == {table_term(equation.rhs)}"
    return (
        f"def {FUNC}({TABLE}):\n"
        f"    {SIZE} = len({TABLE})\n"
        f"    return all({body} {loops})\n"
    )


# -- Reading a checker back ----------------------------------------------------


def _to_term(node: ast.expr) -> Var | Op:
    """One side of the comparison, from Python AST back to the oracle's AST.

    Only two shapes are legal — a bare name, or `table[<term>][<term>]` — so
    anything else is a hard `ReadBackFailure`, not a best-effort guess. Note
    the nesting: `table[A][B]` is an outer subscript (index B) over an inner
    subscript of `table` itself (index A), so left operand = inner index and
    right operand = outer index.
    """
    if isinstance(node, ast.Name):
        return Var(node.id)
    if isinstance(node, ast.Subscript):
        inner = node.value
        if (
            isinstance(inner, ast.Subscript)
            and isinstance(inner.value, ast.Name)
            and inner.value.id == TABLE
        ):
            return Op(_to_term(inner.slice), _to_term(node.slice))
    raise ReadBackFailure(f"not a variable or a {TABLE}[...][...] lookup: {ast.dump(node)}")


def read_back(code: str) -> tuple[list[str], Equation]:
    """Parse an emitted checker string back to (loop variables, AST).

    Uses Python's own parser (`ast.parse`) and pins the scaffold exactly: one
    `def law(table)`, whose body is `n = len(table)` then `return all(<genexp>)`,
    where the generator expression is a single `==` comparison under plain
    `for <v> in range(n)` clauses with no filters. Returns the loop variables
    in clause order and the reconstructed equation.
    """
    try:
        module = ast.parse(code)
    except SyntaxError as exc:
        raise ReadBackFailure(f"not valid Python: {exc}") from None
    if len(module.body) != 1 or not isinstance(module.body[0], ast.FunctionDef):
        raise ReadBackFailure("not a single function definition")
    fn = module.body[0]
    a = fn.args
    if (
        fn.name != FUNC
        or [arg.arg for arg in a.args] != [TABLE]
        or a.posonlyargs or a.kwonlyargs or a.defaults or a.kw_defaults
        or a.vararg or a.kwarg
        or fn.decorator_list
    ):
        raise ReadBackFailure(f"signature is not `def {FUNC}({TABLE})`")
    if len(fn.body) != 2:
        raise ReadBackFailure("body is not exactly two statements")

    assign, ret = fn.body
    if not (
        isinstance(assign, ast.Assign)
        and len(assign.targets) == 1
        and isinstance(assign.targets[0], ast.Name)
        and assign.targets[0].id == SIZE
        and isinstance(assign.value, ast.Call)
        and isinstance(assign.value.func, ast.Name)
        and assign.value.func.id == "len"
        and [getattr(arg, "id", None) for arg in assign.value.args] == [TABLE]
        and not assign.value.keywords
    ):
        raise ReadBackFailure(f"first statement is not `{SIZE} = len({TABLE})`")
    if not (
        isinstance(ret, ast.Return)
        and isinstance(ret.value, ast.Call)
        and isinstance(ret.value.func, ast.Name)
        and ret.value.func.id == "all"
        and len(ret.value.args) == 1
        and isinstance(ret.value.args[0], ast.GeneratorExp)
        and not ret.value.keywords
    ):
        raise ReadBackFailure("second statement is not `return all(<generator>)`")

    genexp = ret.value.args[0]
    names: list[str] = []
    for comp in genexp.generators:
        if (
            comp.is_async
            or comp.ifs
            or not isinstance(comp.target, ast.Name)
            or not (
                isinstance(comp.iter, ast.Call)
                and isinstance(comp.iter.func, ast.Name)
                and comp.iter.func.id == "range"
                and [getattr(arg, "id", None) for arg in comp.iter.args] == [SIZE]
                and not comp.iter.keywords
            )
        ):
            raise ReadBackFailure(f"clause is not plain `for <v> in range({SIZE})`")
        names.append(comp.target.id)

    elt = genexp.elt
    if not (
        isinstance(elt, ast.Compare)
        and len(elt.ops) == 1
        and isinstance(elt.ops[0], ast.Eq)
    ):
        raise ReadBackFailure("element is not a single == comparison")
    return names, Equation(_to_term(elt.left), _to_term(elt.comparators[0]))


def verify_round_trip(equation: Equation) -> bool:
    """Whether the checker for `equation` reads back as the same equation.

    Structural equality of the parse trees plus an exact loop-variable match —
    the ASTs are frozen dataclasses, so `==` compares shape and variable names
    exactly. This is the check that makes a rendering trustworthy: it catches
    a swapped lookup index, a mis-nested subterm, or a dropped quantifier,
    each of which still *looks* like a plausible checker.
    Returns False (rather than raising) if the output cannot be read back.
    """
    try:
        names, reparsed = read_back(checker_source(equation))
    except (ReadBackFailure, Unrepresentable):
        return False
    return reparsed == equation and names == equation_variables(equation)


# -- Semantic check ------------------------------------------------------------

# Small Cayley tables with known, mutually distinguishing behavior:
# left/right projection (tell a swapped lookup apart), xor on {0,1} and
# addition mod 3 (structured, non-idempotent), min (idempotent commutative),
# and one arbitrary asymmetric table (hard-coded so runs are deterministic).
# Round-tripping proves the *string* has the right structure; evaluating on
# these proves the string *decides* the law — an independent failure to fake.
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

    This is the reference semantics the emitted checker is compared against:
    it never sees the generated string, so the two can only agree by both
    being right.
    """
    if isinstance(term, Var):
        return env[term.name]
    return table[eval_term(term.left, env, table)][eval_term(term.right, env, table)]


def holds(equation: Equation, table) -> bool:
    """Whether the law holds in the finite magma `table`, by brute force over
    every assignment — the reference judgment for `semantically_agrees`."""
    names = equation_variables(equation)
    n = len(table)
    return all(
        eval_term(equation.lhs, env, table) == eval_term(equation.rhs, env, table)
        for assignment in product(range(n), repeat=len(names))
        for env in (dict(zip(names, assignment)),)
    )


def compile_checker(code: str):
    """The emitted string as a callable, with only `len`/`range`/`all` in scope.

    Exactly the three builtins the scaffold uses and nothing else — a
    generated string that reached for anything more would fail here.
    """
    namespace: dict = {"__builtins__": {"len": len, "range": range, "all": all}}
    exec(compile(code, "<py_cayley_table>", "exec"), namespace)
    return namespace[FUNC]


def semantically_agrees(equation: Equation, code: str) -> bool:
    """Whether the compiled checker and the reference judgment agree on every
    table in `TABLES` — verdict by verdict, not just "both always true", since
    most laws fail on most tables and the *pattern* of verdicts is what
    identifies the law."""
    fn = compile_checker(code)
    return all(bool(fn(table)) is holds(equation, table) for table in TABLES)


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
        code = checker_source(equation)
    except Unrepresentable as exc:
        return {"input": text, "ok": False, "error": "python-unrepresentable", "reason": str(exc)}

    return {
        "input": text,
        "ok": True,
        "formal": equation.render(),
        "node": node,
        "py_cayley_table": code,
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


def _checker(body: str, loops: str) -> str:
    """Assemble an expected-output string for the selftest cases below."""
    return (
        f"def {FUNC}({TABLE}):\n"
        f"    {SIZE} = len({TABLE})\n"
        f"    return all({body} {loops})\n"
    )


# (input, expected checker). Chosen to pin the decisions that matter: nesting
# on each side, repeated variables, loop order, an operator-free law, and the
# maximum-order shape.
_CASES = (
    ("x ◇ y = y ◇ x",
     _checker("table[x][y] == table[y][x]", "for x in range(n) for y in range(n)")),
    ("x = x",
     _checker("x == x", "for x in range(n)")),
    ("x = y",
     _checker("x == y", "for x in range(n) for y in range(n)")),
    ("x = x ◇ (x ◇ x)",
     _checker("x == table[x][table[x][x]]", "for x in range(n)")),
    ("x = (y ◇ x) ◇ (x ◇ z)",
     _checker("x == table[table[y][x]][table[x][z]]",
              "for x in range(n) for y in range(n) for z in range(n)")),
    ("x ◇ (y ◇ z) = (x ◇ y) ◇ z",
     _checker("table[x][table[y][z]] == table[table[x][y]][z]",
              "for x in range(n) for y in range(n) for z in range(n)")),
    ("(x ◇ y) ◇ z = (w ◇ u) ◇ v",
     _checker("table[table[x][y]][z] == table[table[w][u]][v]",
              "for x in range(n) for y in range(n) for z in range(n) "
              "for w in range(n) for u in range(n) for v in range(n)")),
)


def selftest() -> None:
    """Check the rendering cases, the round trip, the semantics, and the
    error cases; exit non-zero on failure."""
    failures = 0
    for text, expected in _CASES:
        equation = parse_equation(text)
        got = checker_source(equation)
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

    # A deliberately wrong checker must fail the semantic check: the law
    # `x = x ◇ y` (left projection) with its lookup swapped decides the
    # different law `x = y ◇ x`, which the projection tables tell apart.
    wrong = _checker("x == table[y][x]", "for x in range(n) for y in range(n)")
    ok = not semantically_agrees(parse_equation("x = x ◇ y"), wrong)
    failures += not ok
    print(f"[{'ok ' if ok else 'FAIL'}] semantic check rejects a swapped-lookup checker")

    for bad, expected_error in (("a * b * c = c", "parse-failure"),
                                ("a * b = b + a", "outside-fragment"),
                                ("table ◇ y = y ◇ table", "python-unrepresentable"),
                                ("n ◇ y = y ◇ n", "python-unrepresentable"),
                                ("for ◇ y = y ◇ for", "python-unrepresentable")):
        result = analyze(bad)
        ok = not result["ok"] and result["error"] == expected_error
        failures += not ok
        print(f"[{'ok ' if ok else 'FAIL'}] {bad!r} -> {result.get('error')}")

    print("selftest:", "all passed" if not failures else f"{failures} failures")
    raise SystemExit(1 if failures else 0)


def main() -> None:
    """CLI entry point: render each argument, or run the selftest."""
    parser = argparse.ArgumentParser(
        description="Convert ETP magma equations to finite-magma checkers (no model involved)."
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
        print("python:")
        for line in record["py_cayley_table"].rstrip().splitlines():
            print(f"  {line}")
        node = record["node"]
        print(f"node:   {'Equation ' + str(node) if node is not None else 'not in the catalogue'}")
        print(f"order:  {record['order']}   variables: {', '.join(record['variables'])}\n")
    if any(not r["ok"] for r in records):
        raise SystemExit(1)


if __name__ == "__main__":
    main()


# Exported for `build_catalogue.py` and any other consumer.
__all__ = [
    "FUNC",
    "ORACLE_DIR",
    "SIZE",
    "TABLE",
    "TABLES",
    "ReadBackFailure",
    "Unrepresentable",
    "analyze",
    "checker_source",
    "compile_checker",
    "equation_variables",
    "eval_term",
    "holds",
    "lookup_node",
    "py_var",
    "read_back",
    "semantically_agrees",
    "table_term",
    "verify_round_trip",
]
