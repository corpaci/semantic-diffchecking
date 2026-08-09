"""ETP formal equation -> LaTeX. Pure syntax, no model involved.

An ETP law is a tiny, fully specified object — one binary operation, variables,
and an equality — so turning it into LaTeX is a structural rewrite of its parse
tree, not a translation. There is nothing here for a language model to guess at,
and having one guess would introduce exactly the failure this project measures.

The parse tree comes from [`../../oracle/normalizer.py`](../../oracle/normalizer.py):
`parse_equation` yields `Equation(lhs, rhs)` over `Op(left, right)` and
`Var(name)` nodes, and this module walks that tree. Reusing the oracle's parser
rather than writing a second one is deliberate — a private parser here could
disagree with the one the semantic oracle uses, and then a LaTeX rendering would
no longer be evidence about the same equation.

## Parenthesization

Every nested operator is parenthesized, on both sides:

    Op(x, Op(y, z))  ->  x \\diamond (y \\diamond z)
    Op(Op(x, y), z)  ->  (x \\diamond y) \\diamond z

No parentheses are omitted by an associativity convention, because the magma
operation is not associative: `x ◇ y ◇ z` would be genuinely ambiguous, and a
reader who resolved it left-to-right would be reading a different law. This
matches the ETP catalogue's own notation.

## Round-tripping

Everything emitted here parses back to the equation it came from — the oracle's
`strip_noise` already understands `\\diamond`, `$…$`, `\\left`/`\\right`, and
`\\mathit{…}`. `verify_round_trip` checks that structurally (AST equality, not
string equality), which is what `build_catalogue.py` runs over all 4694 laws.

CLI:
    python3 latexify.py "x ◇ (y ◇ z) = (x ◇ y) ◇ z"
    python3 latexify.py 43 4512 --delimiters inline
    python3 latexify.py --operator "\\circ" --quantify 43
    python3 latexify.py --selftest
"""

from __future__ import annotations

import argparse
import json
import os
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
    parse_equation,
)

# Operator commands that are safe to use for the magma operation: each is a
# binary-operator-class symbol in LaTeX, so spacing around it comes out right
# with no \mathbin wrapper. `\diamond` is the default because it is what the
# catalogue's own ◇ denotes.
KNOWN_OPERATORS = (r"\diamond", r"\circ", r"\cdot", r"\ast", r"\star", r"\bullet", r"\otimes")

DELIMITERS = ("none", "inline", "display", "equation")


@dataclass(frozen=True)
class LatexStyle:
    """How an equation is rendered. Every field is recorded in the output.

    Fields:
      operator     the LaTeX command for the magma operation (default
                   `\\diamond`, matching the catalogue's ◇).
      delimiters   "none" (a bare formula, for embedding), "inline" (`$…$`),
                   "display" (`\\[…\\]`), or "equation" (an `equation`
                   environment, which is what takes a `\\label`).
      label        label for the `equation` environment; ignored otherwise.
      auto_size    use `\\left(…\\right)` instead of plain parentheses. Off by
                   default: at ETP's maximum order of 4 the nesting is shallow,
                   and fixed-size parentheses set more tightly.
      quantify     prefix the explicit `\\forall` over the law's variables. ETP
                   laws are universally quantified implicitly; make it visible
                   when the surrounding prose does not already say so.
      mathbin      wrap the operator in `\\mathbin{…}`. Only needed for a custom
                   `operator` string that is not already a binary-operator
                   symbol (e.g. a `\\mathsf{op}` macro), where LaTeX would
                   otherwise set it with the wrong spacing.
    """

    operator: str = r"\diamond"
    delimiters: str = "none"
    label: str | None = None
    auto_size: bool = False
    quantify: bool = False
    mathbin: bool = False

    def __post_init__(self):
        if self.delimiters not in DELIMITERS:
            raise ValueError(f"delimiters must be one of {DELIMITERS}, got {self.delimiters!r}")
        if not self.operator.strip():
            raise ValueError("operator must be a non-empty LaTeX snippet")

    @property
    def op(self) -> str:
        """The operator as it appears between two terms."""
        return rf"\mathbin{{{self.operator}}}" if self.mathbin else self.operator


DEFAULT_STYLE = LatexStyle()


def latex_var(name: str) -> str:
    """Render one variable name.

    Single letters are already correct as math italics. A multi-character name
    would be set as a product of its letters (`abc` as a·b·c), so it gets
    `\\mathit{…}`; the ETP catalogue only ever uses single letters, but the
    parser accepts longer identifiers from other sources.
    """
    return name if len(name) == 1 else rf"\mathit{{{name}}}"


def latex_term(term: Var | Op, style: LatexStyle = DEFAULT_STYLE, *, top: bool = True) -> str:
    """Render one side of an equation.

    `top` marks the root of a term: the outermost operator needs no
    parentheses, every nested one does. This mirrors `Op.render` in the
    normalizer, so the LaTeX and the canonical text agree on structure.
    """
    if isinstance(term, Var):
        return latex_var(term.name)
    inner = (
        f"{latex_term(term.left, style, top=False)} {style.op} "
        f"{latex_term(term.right, style, top=False)}"
    )
    if top:
        return inner
    return rf"\left( {inner} \right)" if style.auto_size else f"({inner})"


def latex_body(equation: Equation, style: LatexStyle = DEFAULT_STYLE) -> str:
    """Render the formula itself, without math delimiters or quantifier."""
    return f"{latex_term(equation.lhs, style)} = {latex_term(equation.rhs, style)}"


def quantifier_prefix(equation: Equation) -> str:
    """`\\forall x y z: ` over the equation's variables, in first-appearance order.

    Two spellings here are chosen to keep the output re-readable by this
    project's own parser, which is what lets `verify_round_trip` cover this
    style too — worth more than marginally better spacing:

      * a plain `:` rather than `\\colon`, because the oracle's `strip_noise`
        recognises a quantifier prefix ending in `,`, `.`, or `:`, not one
        ending in a LaTeX command;
      * variables separated by spaces rather than commas, because that
        stripper's variable-list pattern is non-greedy and would stop at the
        first comma, leaving `y, z: …` behind.
    """
    names: list[str] = []
    equation.lhs.variables(names)
    equation.rhs.variables(names)
    if not names:
        return ""
    return rf"\forall {' '.join(latex_var(n) for n in names)}: "


def wrap(body: str, style: LatexStyle) -> str:
    """Apply the chosen math delimiters to a rendered formula."""
    if style.delimiters == "inline":
        return f"${body}$"
    if style.delimiters == "display":
        return rf"\[{body}\]"
    if style.delimiters == "equation":
        label = rf"\label{{{style.label}}}" if style.label else ""
        return f"\\begin{{equation}}{label}\n  {body}\n\\end{{equation}}"
    return body


def latex_equation(equation: Equation, style: LatexStyle = DEFAULT_STYLE) -> str:
    """Render a parsed `Equation` to LaTeX in the given style."""
    body = latex_body(equation, style)
    if style.quantify:
        body = quantifier_prefix(equation) + body
    return wrap(body, style)


def to_latex(text: str, style: LatexStyle = DEFAULT_STYLE) -> str:
    """Parse an equation string and render it to LaTeX.

    Raises `ParseFailure` / `OutsideFragment` from the oracle's parser for
    input that is not a single-operation magma identity — the same two error
    types the rest of the project branches on. Use `analyze` for a
    never-raising version.
    """
    return latex_equation(parse_equation(text), style)


def analyze(text: str, style: LatexStyle = DEFAULT_STYLE) -> dict:
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

    names: list[str] = []
    equation.lhs.variables(names)
    equation.rhs.variables(names)
    return {
        "input": text,
        "ok": True,
        "formal": equation.render(),
        "latex": latex_equation(equation, style),
        "order": equation.size(),
        "variables": names,
    }


def readable_style(style: LatexStyle) -> LatexStyle:
    """The variant of `style` that the oracle's parser can read back.

    Two of the options are not invertible by `strip_noise`: an `equation`
    environment (it is document structure, not math wrapping) and a `\\mathbin{}`
    wrapper or an operator macro outside the stripper's known table. Both are
    neutralized here so the round trip still runs.

    What that costs is worth being precise about: the check then verifies the
    *structure* — parenthesization, variable placement, orientation, `=` sides —
    which is the part that can be silently wrong. The operator's spelling is a
    literal substitution into that structure, and it is `pdflatex` (see
    `build_catalogue.py --tex`) that validates an unusual operator macro.
    """
    return LatexStyle(
        operator=r"\diamond",
        delimiters="none" if style.delimiters == "equation" else style.delimiters,
        auto_size=style.auto_size,
        quantify=style.quantify,
    )


def verify_round_trip(text: str, style: LatexStyle = DEFAULT_STYLE) -> bool:
    """Whether the LaTeX for `text` parses back to the same equation.

    Structural equality of the parse trees, not string equality: the ASTs are
    frozen dataclasses, so `==` compares shape and variable names exactly. This
    is the check that makes a rendering trustworthy — it catches a dropped
    parenthesis or a mis-nested subterm, which is precisely the kind of error
    that still *looks* like a plausible equation.

    Rendered through `readable_style`; see there for what is and is not covered.
    Returns False (rather than raising) if the output cannot be parsed at all.
    """
    equation = parse_equation(text)
    try:
        reparsed = parse_equation(latex_equation(equation, readable_style(style)))
    except (ParseFailure, OutsideFragment):
        return False
    return reparsed == equation


# -- CLI ----------------------------------------------------------------------


def _resolve(spec: str) -> str:
    """Expand an ETP equation number to its catalogue text; pass text through.

    A bare integer means "Equation N", the same convention as `oracle.py
    --intended`. The catalogue is loaded lazily so the renderer stays usable
    with no ETP data present.
    """
    if not spec.strip().isdigit():
        return spec
    from mapper import NodeMapper

    mapper = _resolve.mapper = getattr(_resolve, "mapper", None) or NodeMapper()
    node = int(spec)
    if not 1 <= node <= len(mapper.laws):
        raise SystemExit(f"ETP equation number out of range 1..{len(mapper.laws)}: {node}")
    return mapper.law_text(node)


def style_from_args(args) -> LatexStyle:
    """Build a `LatexStyle` from parsed CLI flags."""
    try:
        return LatexStyle(
            operator=args.operator,
            delimiters=args.delimiters,
            label=args.label,
            auto_size=args.auto_size,
            quantify=args.quantify,
            mathbin=args.mathbin,
        )
    except ValueError as exc:
        raise SystemExit(str(exc)) from None


def add_style_args(parser: argparse.ArgumentParser) -> None:
    """Register the style flags shared by this CLI and `build_catalogue.py`."""
    group = parser.add_argument_group("latex style")
    group.add_argument("--operator", default=r"\diamond",
                       help=r"LaTeX command for the operation (default \diamond); "
                            f"tested: {' '.join(KNOWN_OPERATORS)}")
    group.add_argument("--delimiters", choices=DELIMITERS, default="none",
                       help="math delimiters to wrap the formula in (default none)")
    group.add_argument("--label", default=None,
                       help="label for --delimiters equation")
    group.add_argument("--auto-size", action="store_true",
                       help=r"use \left( \right) instead of plain parentheses")
    group.add_argument("--quantify", action="store_true",
                       help=r"prefix an explicit \forall over the variables")
    group.add_argument("--mathbin", action="store_true",
                       help=r"wrap the operator in \mathbin{} (for custom macros)")


# (input, expected LaTeX with the default style). Chosen to pin the decisions
# that matter: nesting on each side, repeated variables, an operator-free law,
# and the maximum-order shape.
_CASES = (
    ("x ◇ y = y ◇ x", r"x \diamond y = y \diamond x"),
    ("x = x", "x = x"),
    ("x = y", "x = y"),
    ("x = x ◇ x", r"x = x \diamond x"),
    ("x ◇ (y ◇ z) = (x ◇ y) ◇ z", r"x \diamond (y \diamond z) = (x \diamond y) \diamond z"),
    ("x = (x ◇ y) ◇ z", r"x = (x \diamond y) \diamond z"),
    ("a * (b * c) = (a * b) * c", r"a \diamond (b \diamond c) = (a \diamond b) \diamond c"),
    ("(x ◇ x) ◇ (x ◇ x) = x", r"(x \diamond x) \diamond (x \diamond x) = x"),
)


def selftest() -> None:
    """Check the rendering cases and the round trip; exit non-zero on failure."""
    failures = 0
    for text, expected in _CASES:
        got = to_latex(text)
        ok = got == expected
        failures += not ok
        print(f"[{'ok ' if ok else 'FAIL'}] {text!r} -> {got!r}"
              + ("" if ok else f"  expected {expected!r}"))

    # Round trip under every style, including the two that are only verifiable
    # through `readable_style` (the equation environment and a \mathbin-wrapped
    # custom operator).
    styles = [
        LatexStyle(),
        LatexStyle(delimiters="inline"),
        LatexStyle(delimiters="display"),
        LatexStyle(operator=r"\circ"),
        LatexStyle(operator=r"\cdot", auto_size=True),
        LatexStyle(quantify=True),
        LatexStyle(delimiters="equation", label="eq:demo"),
        LatexStyle(operator=r"\mathsf{op}", mathbin=True),
        LatexStyle(operator=r"\star", delimiters="display", auto_size=True, quantify=True),
    ]
    for style in styles:
        for text, _ in _CASES:
            ok = verify_round_trip(text, style)
            failures += not ok
            if not ok:
                print(f"[FAIL] round trip {text!r} under {style}")
    print(f"[ok ] round trip: {len(styles)} styles x {len(_CASES)} equations")

    for bad, expected_error in (("a * b * c = c", "parse-failure"),
                                ("a * b = b + a", "outside-fragment")):
        result = analyze(bad)
        ok = not result["ok"] and result["error"] == expected_error
        failures += not ok
        print(f"[{'ok ' if ok else 'FAIL'}] {bad!r} -> {result.get('error')}")

    print("selftest:", "all passed" if not failures else f"{failures} failures")
    raise SystemExit(1 if failures else 0)


def main() -> None:
    """CLI entry point: render each argument, or run the selftest."""
    parser = argparse.ArgumentParser(
        description="Convert ETP magma equations to LaTeX (no model involved)."
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
    records = [analyze(_resolve(spec), style) for spec in args.equations]

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
        print(f"latex:  {record['latex']}")
        print(f"order:  {record['order']}   variables: {', '.join(record['variables'])}\n")
    if any(not r["ok"] for r in records):
        raise SystemExit(1)


if __name__ == "__main__":
    main()


# Exported for `build_catalogue.py` and any other consumer.
__all__ = [
    "DEFAULT_STYLE",
    "DELIMITERS",
    "KNOWN_OPERATORS",
    "LatexStyle",
    "ORACLE_DIR",
    "add_style_args",
    "analyze",
    "latex_body",
    "latex_equation",
    "latex_term",
    "latex_var",
    "readable_style",
    "style_from_args",
    "to_latex",
    "verify_round_trip",
]
