"""ETP formal equation -> Lean 4 declaration. Pure syntax, no model involved.

An ETP law is a tiny, fully specified object — one binary operation, variables,
and an equality — so turning it into a Lean 4 declaration is a structural
rewrite of its parse tree, not a translation. There is nothing here for a
language model to guess at, and having one guess would introduce exactly the
failure this project measures.

The statement is the one the ETP itself uses. In the ETP repository,
`equation 43 := x ◇ y = y ◇ x` elaborates (via `Equations/Command.lean`) to a
reducible definition whose surface Lean is

    abbrev Equation43 (G : Type u) [Magma G] : Prop := ∀ x y : G, x ◇ y = y ◇ x

and this module emits that full signature — carrier type, `Magma` instance,
`Prop` codomain — with the law universally quantified over its variables in
first-appearance order. The declaration wrapper is a style choice: `abbrev`
and `def` reproduce the ETP's named form above, while `example` emits the
same statement anonymously —

    example (G : Type u) [Magma G] : Prop := ∀ x y : G, x ◇ y = y ◇ x

— which is what `build_catalogue.py` uses by default, because a name like
`Equation43` would carry the ETP equation number into a string that serves as
test data for representation-translation experiments. `◇` is the ETP
`Magma.op` notation, so the output drops directly into a file that has the
`Magma` class in scope (`build_catalogue.py --lean` writes such a file,
self-contained).

The parse tree comes from [`../../oracle/normalizer.py`](../../oracle/normalizer.py):
`parse_equation` yields `Equation(lhs, rhs)` over `Op(left, right)` and
`Var(name)` nodes, and this module walks that tree. Reusing the oracle's parser
rather than writing a second one is deliberate — a private parser here could
disagree with the one the semantic oracle uses, and then a Lean rendering would
no longer be evidence about the same equation.

## Parenthesization

Every nested operator is parenthesized, on both sides:

    Op(x, Op(y, z))  ->  x ◇ (y ◇ z)
    Op(Op(x, y), z)  ->  (x ◇ y) ◇ z

The ETP declares `◇` as `infix:65` — *non*-associative — so an unparenthesized
chain would not even parse in Lean; more importantly, the magma operation is
not associative, so explicit grouping is the meaning. This matches both the
catalogue's notation and the ETP's own Lean source.

## Round-tripping

Everything emitted here parses back to the equation it came from: `read_back`
strips the declaration head and the `∀ … : G,` binder from the emitted string
itself, and hands the body to the oracle's parser (which reads `◇` natively).
`verify_round_trip` checks AST equality plus the binder list, which is what
`build_catalogue.py` runs over all 4694 laws.

CLI:
    python3 leanify.py "x ◇ (y ◇ z) = (x ◇ y) ◇ z"
    python3 leanify.py 43 4512 --decl def
    python3 leanify.py --universe star --docstring 43
    python3 leanify.py --selftest
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass
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

# The operation symbol. Not a style option: `◇` *is* the ETP's notation for
# `Magma.op` (declared `infix:65 " ◇ "` in Magma.lean), and it is also the
# oracle's canonical operator, which is what lets the round trip below hand the
# emitted body straight back to the oracle's parser.
OP = "◇"

# The carrier type variable. `G` matches the ETP's own generated declarations
# (`∀ (G : Type u) [Magma G], Prop`), and doubles as a reserved name below: a
# law whose variable is literally named `G` would capture the carrier binder.
CARRIER = "G"

DECLS = ("abbrev", "def", "example")

# How the carrier is typed. "u" is the ETP's form (universe-polymorphic; a
# file using it needs a `universe u` line, which `build_catalogue.py --lean`
# emits). "star" is the Mathlib idiom `Type*` — Mathlib-only notation, so it
# will not elaborate in a plain-Lean file. "zero" is monomorphic `Type`.
UNIVERSES = {"u": "Type u", "star": "Type*", "zero": "Type"}

# Names that cannot serve as a `∀`-binder in a Lean declaration: keywords,
# sort formers, and the carrier itself (which the binder would capture). The
# catalogue only ever uses x y z w u v, so this guards free-text input.
_RESERVED = frozenset(
    """fun let in do if then else match with by at have show from calc where suffices
    theorem def abbrev lemma example instance structure class inductive deriving
    open universe variable section namespace end import forall exists
    Prop Type Sort""".split()
) | {CARRIER}

# What the oracle can emit as a variable name is already almost a Lean
# identifier; this pins the claim so `Unrepresentable` is the only escape.
_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")

# The name a valid `--prefix` must be a prefix *of*: prefix + digits must stay
# one identifier, so the prefix itself must be a bare identifier.
_PREFIX = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")


class Unrepresentable(ValueError):
    """The equation parses, but cannot be written as a Lean declaration.

    Raised for a variable name that Lean would reject or capture: a keyword
    (`fun`), a sort former (`Prop`), or the carrier name `G` itself. Distinct
    from the oracle's ParseFailure/OutsideFragment because the *law* is fine —
    only this rendering target cannot spell it. Never triggered by the
    catalogue, whose variables are drawn from `x y z w u v`.
    """


@dataclass(frozen=True)
class LeanStyle:
    """How an equation is rendered. Every field is recorded in the output.

    Fields:
      decl       "abbrev" (default), "def", or "example". The ETP marks its
                 equations reducible — the `equation` command compiles to an
                 abbrev-hinted definition — so that tactics like `decide`
                 look through the name; "def" makes the name opaque;
                 "example" is anonymous — no name at all, so nothing in the
                 emitted string carries the ETP equation number.
      universe   "u" (`Type u`, the ETP's universe-polymorphic form, default),
                 "star" (`Type*`, Mathlib notation — needs Mathlib in scope),
                 or "zero" (plain `Type`).
      prefix     declaration name prefix; the name is `{prefix}{node}`, so the
                 default "Equation" reproduces the ETP's `Equation43` etc.
      docstring  prefix the declaration with a `/-- … -/` doc comment carrying
                 the node number and the canonical formal text.
    """

    decl: str = "abbrev"
    universe: str = "u"
    prefix: str = "Equation"
    docstring: bool = False

    def __post_init__(self):
        if self.decl not in DECLS:
            raise ValueError(f"decl must be one of {DECLS}, got {self.decl!r}")
        if self.universe not in UNIVERSES:
            raise ValueError(
                f"universe must be one of {tuple(UNIVERSES)}, got {self.universe!r}"
            )
        if not _PREFIX.match(self.prefix):
            raise ValueError(f"prefix must be a Lean identifier, got {self.prefix!r}")
        if self.decl == "example" and self.docstring:
            raise ValueError(
                "docstring cannot be combined with decl='example': the doc text "
                "carries the node number, which the anonymous form exists to omit"
            )

    @property
    def carrier_type(self) -> str:
        """The carrier's type as it appears in the signature, e.g. `Type u`."""
        return UNIVERSES[self.universe]


DEFAULT_STYLE = LeanStyle()


def lean_var(name: str) -> str:
    """Render one variable name, or refuse.

    A catalogue variable (`x` … `v`) passes through unchanged — it is already a
    Lean identifier. Free-text input can carry a name Lean would reject as a
    binder (a keyword, `Prop`) or silently capture (`G`, the carrier); those
    raise `Unrepresentable` rather than emit a declaration that does not mean
    the law it came from.
    """
    if not _IDENT.match(name):
        raise Unrepresentable(f"variable {name!r} is not a Lean identifier")
    if name in _RESERVED:
        reason = "the carrier name" if name == CARRIER else "reserved in Lean"
        raise Unrepresentable(f"variable {name!r} is {reason}")
    return name


def lean_term(term: Var | Op, *, top: bool = True) -> str:
    """Render one side of an equation.

    `top` marks the root of a term: the outermost operator needs no
    parentheses, every nested one does. This mirrors `Op.render` in the
    normalizer, so the Lean text and the canonical text agree on structure —
    and it is required, not stylistic: `◇` is `infix:65`, non-associative, so
    a bare chain would not parse.
    """
    if isinstance(term, Var):
        return lean_var(term.name)
    inner = f"{lean_term(term.left, top=False)} {OP} {lean_term(term.right, top=False)}"
    return inner if top else f"({inner})"


def equation_variables(equation: Equation) -> list[str]:
    """The law's distinct variables in first-appearance order, LHS then RHS.

    This is the binder order: the ETP's `equation` command numbers leaves by
    first appearance in the term, and the catalogue text is canonical in the
    same order, so `∀ x y z : G` here is binder-for-binder the ETP's own.
    """
    names: list[str] = []
    equation.lhs.variables(names)
    equation.rhs.variables(names)
    return names


def lean_statement(equation: Equation) -> str:
    """The proposition itself: `∀ x y : G, x ◇ y = y ◇ x`.

    One `∀` with all binders sharing the ascription `: G` — the form Lean's
    pretty-printer uses and the ETP's docs display. A law with no variables
    cannot occur in the catalogue (the fragment has no constants), but is
    rendered without the quantifier rather than rejected.
    """
    body = f"{lean_term(equation.lhs)} = {lean_term(equation.rhs)}"
    names = [lean_var(n) for n in equation_variables(equation)]
    if not names:
        return body
    return f"∀ {' '.join(names)} : {CARRIER}, {body}"


def lean_name(style: LeanStyle = DEFAULT_STYLE, node: int | None = None) -> str | None:
    """The declaration's name: `Equation43`, or `EquationUnknown` for a law
    with no catalogue node (order > 4, or no catalogue available to look it
    up in). `build_catalogue.py` always has a node; the fallback exists so the
    CLI can still render exploratory input into a well-formed declaration.
    None for the anonymous `example` form, which has no name at all."""
    if style.decl == "example":
        return None
    return f"{style.prefix}{node if node is not None else 'Unknown'}"


def lean_signature(style: LeanStyle = DEFAULT_STYLE, node: int | None = None) -> str:
    """The full signature: `Equation43 (G : Type u) [Magma G] : Prop`.

    Exactly the ETP's: an explicit carrier, an instance-implicit `Magma`
    structure on it, and `Prop` as the stated codomain. The anonymous
    `example` form is the same signature with the name simply absent.
    """
    binders = f"({CARRIER} : {style.carrier_type}) [Magma {CARRIER}] : Prop"
    name = lean_name(style, node)
    return binders if name is None else f"{name} {binders}"


def lean_decl(
    equation: Equation, style: LeanStyle = DEFAULT_STYLE, node: int | None = None
) -> str:
    """Render a parsed `Equation` to a complete Lean 4 declaration.

    One line (two with `docstring`): keyword, signature, `:=`, statement. The
    catalogue's maximum order is 4, so no law is long enough to want wrapping,
    and a fixed layout keeps the output byte-deterministic.
    """
    decl = f"{style.decl} {lean_signature(style, node)} := {lean_statement(equation)}"
    if style.docstring:
        origin = (
            f"Equation {node} of the ETP catalogue"
            if node is not None
            else "A magma law outside the ETP catalogue"
        )
        decl = f"/-- {origin}: `{equation.render()}`. -/\n{decl}"
    return decl


# -- Catalogue lookup ---------------------------------------------------------

_MAPPER = None  # None = not tried; False = tried and unavailable


def _get_mapper():
    """The oracle's `NodeMapper`, loaded lazily; None when no catalogue exists.

    A missing catalogue degrades to None rather than failing, so the renderer
    stays usable with no ETP data present — only node lookup and the
    `canonical` flag go dark.
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
    """The ETP node of this law, up to variable renaming and `=` orientation.

    Note what a hit means: the *law* is Equation N — the statement as written
    may still be a renamed or flipped spelling of the catalogue line. `analyze`
    reports that distinction as `canonical`.
    """
    mapper = _get_mapper()
    if mapper is None:
        return None
    return mapper.key_to_node.get(canonical_key(equation))


def to_lean(
    text: str, style: LeanStyle = DEFAULT_STYLE, node: int | None = None
) -> str:
    """Parse an equation string and render it to a Lean 4 declaration.

    `node` names the declaration; when omitted it is looked up in the ETP
    catalogue. Raises the oracle's `ParseFailure` / `OutsideFragment` for input
    that is not a single-operation magma identity, and `Unrepresentable` for a
    law whose variable names Lean cannot bind. Use `analyze` for a
    never-raising version.
    """
    equation = parse_equation(text)
    if node is None:
        node = lookup_node(equation)
    return lean_decl(equation, style, node)


def analyze(text: str, style: LeanStyle = DEFAULT_STYLE, node: int | None = None) -> dict:
    """Parse + render, returning errors as data rather than exceptions.

    Mirrors `normalizer.analyze`, so a batch caller can branch on `ok` instead
    of catching, and a failure row still carries the input and the reason.
    On success the record holds the declaration (`lean`), its parts (`name`,
    `statement`), the resolved `node` (or null), and `canonical` — whether the
    statement as written is byte-identical to the catalogue line, as opposed to
    merely denoting the same law under renaming or orientation.
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
        decl = lean_decl(equation, style, node)
    except Unrepresentable as exc:
        return {"input": text, "ok": False, "error": "lean-unrepresentable", "reason": str(exc)}

    formal = equation.render()
    mapper = _get_mapper() if node is not None else None
    return {
        "input": text,
        "ok": True,
        "formal": formal,
        "node": node,
        "canonical": (
            mapper.law_text(node) == formal
            if mapper is not None and 1 <= node <= len(mapper.laws)
            else None
        ),
        "name": lean_name(style, node),
        "lean": decl,
        "statement": lean_statement(equation),
        "order": equation.size(),
        "variables": equation_variables(equation),
    }


# -- Reading a declaration back -----------------------------------------------

_FORALL = re.compile(rf"∀ (.+?) : {CARRIER}, (.*)\Z")


def read_back(decl: str) -> tuple[list[str], Equation]:
    """Parse an emitted declaration's statement back to (binders, AST).

    Operates on the actual output string — last line (skipping a doc comment),
    the part after `:=`, the `∀ … : G,` prefix split off by regex — so a
    formatting bug in the emitter cannot hide from the check that uses it. The
    body goes to the oracle's parser, which reads `◇` natively; whatever it
    raises propagates.
    """
    line = decl.rstrip().splitlines()[-1]
    _head, sep, statement = line.partition(":=")
    if not sep:
        raise ParseFailure(f"no ':=' in declaration: {line!r}")
    statement = statement.strip()
    match = _FORALL.match(statement)
    binders = match.group(1).split() if match else []
    body = match.group(2) if match else statement
    return binders, parse_equation(body)


def verify_round_trip(text: str, style: LeanStyle = DEFAULT_STYLE) -> bool:
    """Whether the Lean for `text` reads back as the same equation.

    Structural equality of the parse trees plus an exact binder-list match —
    the ASTs are frozen dataclasses, so `==` compares shape and variable names
    exactly. This is the check that makes a rendering trustworthy: it catches
    a dropped parenthesis, a mis-nested subterm, or a binder out of order,
    each of which still *looks* like a plausible declaration.

    Unlike the LaTeX renderer there is no `readable_style` indirection: every
    style option here (keyword, universe, prefix, docstring) leaves the
    statement untouched, so the round trip covers each style as emitted.
    Returns False (rather than raising) if the output cannot be read back.
    """
    equation = parse_equation(text)
    try:
        binders, reparsed = read_back(lean_decl(equation, style))
    except (ParseFailure, OutsideFragment, Unrepresentable):
        return False
    return reparsed == equation and binders == equation_variables(equation)


# -- CLI ----------------------------------------------------------------------


def _resolve(spec: str) -> tuple[str, int | None]:
    """Expand an ETP equation number to (catalogue text, node); pass text
    through as (text, None) for `analyze` to look up.

    A bare integer means "Equation N", the same convention as `oracle.py
    --intended` and `latexify.py`. The catalogue is loaded lazily so the
    renderer stays usable with no ETP data present.
    """
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
    return mapper.law_text(node), node


def style_from_args(args) -> LeanStyle:
    """Build a `LeanStyle` from parsed CLI flags."""
    try:
        return LeanStyle(
            decl=args.decl,
            universe=args.universe,
            prefix=args.prefix,
            docstring=args.docstring,
        )
    except ValueError as exc:
        raise SystemExit(str(exc)) from None


def add_style_args(parser: argparse.ArgumentParser, *, default_decl: str = "abbrev") -> None:
    """Register the style flags shared by this CLI and `build_catalogue.py`.

    `default_decl` lets each CLI pick its own default keyword: this CLI keeps
    the ETP's `abbrev`, while `build_catalogue.py` defaults to the anonymous
    `example` so its dataset carries no equation numbers.
    """
    group = parser.add_argument_group("lean style")
    group.add_argument("--decl", choices=DECLS, default=default_decl,
                       help=f"declaration keyword (default {default_decl}; abbrev is "
                            "the ETP's choice: reducible, so `decide` and friends "
                            "look through the name; example is anonymous — no name, "
                            "so no equation number in the emitted string)")
    group.add_argument("--universe", choices=tuple(UNIVERSES), default="u",
                       help="carrier type: u -> `Type u` (ETP form, default), "
                            "star -> `Type*` (Mathlib notation), zero -> `Type`")
    group.add_argument("--prefix", default="Equation",
                       help="declaration name prefix (default Equation, "
                            "reproducing the ETP's names)")
    group.add_argument("--docstring", action="store_true",
                       help="prefix each declaration with a /-- … -/ doc comment "
                            "carrying the node number and formal text")


# (input, node, expected declaration with the default style). Chosen to pin the
# decisions that matter: nesting on each side, repeated variables, binder order,
# an operator-free law, and the maximum-order shape. Nodes are real: 1, 2, 3, 8
# from Equations/Basic.lean; 43 and 4512 as documented in ../latex.
_CASES = (
    ("x ◇ y = y ◇ x", 43,
     "abbrev Equation43 (G : Type u) [Magma G] : Prop := ∀ x y : G, x ◇ y = y ◇ x"),
    ("x = x", 1,
     "abbrev Equation1 (G : Type u) [Magma G] : Prop := ∀ x : G, x = x"),
    ("x = y", 2,
     "abbrev Equation2 (G : Type u) [Magma G] : Prop := ∀ x y : G, x = y"),
    ("x = x ◇ x", 3,
     "abbrev Equation3 (G : Type u) [Magma G] : Prop := ∀ x : G, x = x ◇ x"),
    ("x = x ◇ (x ◇ x)", 8,
     "abbrev Equation8 (G : Type u) [Magma G] : Prop := ∀ x : G, x = x ◇ (x ◇ x)"),
    ("x ◇ (y ◇ z) = (x ◇ y) ◇ z", 4512,
     "abbrev Equation4512 (G : Type u) [Magma G] : Prop "
     ":= ∀ x y z : G, x ◇ (y ◇ z) = (x ◇ y) ◇ z"),
    ("a * (b * c) = (a * b) * c", None,
     "abbrev EquationUnknown (G : Type u) [Magma G] : Prop "
     ":= ∀ a b c : G, a ◇ (b ◇ c) = (a ◇ b) ◇ c"),
    ("(x ◇ x) ◇ (x ◇ x) = x", None,
     "abbrev EquationUnknown (G : Type u) [Magma G] : Prop "
     ":= ∀ x : G, (x ◇ x) ◇ (x ◇ x) = x"),
)

# The anonymous form: same statement, no name — and hence no node number
# anywhere in the string, whether or not a node is known.
_EXAMPLE_CASES = (
    ("x ◇ y = y ◇ x", 43,
     "example (G : Type u) [Magma G] : Prop := ∀ x y : G, x ◇ y = y ◇ x"),
    ("x = x ◇ (x ◇ x)", 8,
     "example (G : Type u) [Magma G] : Prop := ∀ x : G, x = x ◇ (x ◇ x)"),
    ("a * (b * c) = (a * b) * c", None,
     "example (G : Type u) [Magma G] : Prop := ∀ a b c : G, a ◇ (b ◇ c) = (a ◇ b) ◇ c"),
)


def selftest() -> None:
    """Check the rendering cases and the round trip; exit non-zero on failure."""
    failures = 0
    for text, node, expected in _CASES:
        got = lean_decl(parse_equation(text), node=node)
        ok = got == expected
        failures += not ok
        print(f"[{'ok ' if ok else 'FAIL'}] {text!r} -> {got!r}"
              + ("" if ok else f"  expected {expected!r}"))

    example_style = LeanStyle(decl="example")
    for text, node, expected in _EXAMPLE_CASES:
        got = lean_decl(parse_equation(text), example_style, node=node)
        ok = got == expected
        failures += not ok
        print(f"[{'ok ' if ok else 'FAIL'}] example {text!r} -> {got!r}"
              + ("" if ok else f"  expected {expected!r}"))

    try:
        LeanStyle(decl="example", docstring=True)
    except ValueError:
        print("[ok ] example + docstring is refused")
    else:
        failures += 1
        print("[FAIL] example + docstring was accepted (would leak the node number)")

    # Round trip under every style, including the docstring form (whose doc
    # line `read_back` must skip) and a non-default prefix.
    styles = [
        LeanStyle(),
        LeanStyle(decl="def"),
        LeanStyle(decl="example"),
        LeanStyle(universe="star"),
        LeanStyle(universe="zero"),
        LeanStyle(prefix="ETPLaw"),
        LeanStyle(docstring=True),
        LeanStyle(decl="def", universe="star", prefix="L", docstring=True),
    ]
    for style in styles:
        for text, _node, _expected in _CASES:
            ok = verify_round_trip(text, style)
            failures += not ok
            if not ok:
                print(f"[FAIL] round trip {text!r} under {style}")
    print(f"[ok ] round trip: {len(styles)} styles x {len(_CASES)} equations")

    for bad, expected_error in (("a * b * c = c", "parse-failure"),
                                ("a * b = b + a", "outside-fragment"),
                                ("fun ◇ y = y ◇ fun", "lean-unrepresentable"),
                                ("G ◇ y = y ◇ G", "lean-unrepresentable")):
        result = analyze(bad)
        ok = not result["ok"] and result["error"] == expected_error
        failures += not ok
        print(f"[{'ok ' if ok else 'FAIL'}] {bad!r} -> {result.get('error')}")

    print("selftest:", "all passed" if not failures else f"{failures} failures")
    raise SystemExit(1 if failures else 0)


def main() -> None:
    """CLI entry point: render each argument, or run the selftest."""
    parser = argparse.ArgumentParser(
        description="Convert ETP magma equations to Lean 4 declarations (no model involved)."
    )
    parser.add_argument("equations", nargs="*",
                        help="equation strings and/or ETP equation numbers")
    parser.add_argument("--json", action="store_true",
                        help="emit a JSON array of records instead of text")
    parser.add_argument("--selftest", action="store_true")
    add_style_args(parser)
    args = parser.parse_args()

    if args.selftest:
        selftest()
    if not args.equations:
        parser.error("give at least one equation or ETP number (or use --selftest)")

    style = style_from_args(args)
    records = [analyze(text, style, node) for text, node in map(_resolve, args.equations)]

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
        print(f"lean:   {record['lean']}")
        node = record["node"]
        where = (
            f"Equation {node}" + ("" if record["canonical"] else " (up to renaming/orientation)")
            if node is not None else "not in the catalogue"
        )
        print(f"node:   {where}")
        print(f"order:  {record['order']}   variables: {', '.join(record['variables'])}\n")
    if any(not r["ok"] for r in records):
        raise SystemExit(1)


if __name__ == "__main__":
    main()


# Exported for `build_catalogue.py` and any other consumer.
__all__ = [
    "CARRIER",
    "DECLS",
    "DEFAULT_STYLE",
    "OP",
    "ORACLE_DIR",
    "UNIVERSES",
    "LeanStyle",
    "Unrepresentable",
    "add_style_args",
    "analyze",
    "equation_variables",
    "lean_decl",
    "lean_name",
    "lean_signature",
    "lean_statement",
    "lean_term",
    "lean_var",
    "lookup_node",
    "read_back",
    "style_from_args",
    "to_lean",
    "verify_round_trip",
]
