"""ETP formal equation -> deterministic English text. Pure syntax, no model involved.

An ETP law is a tiny, fully specified object — one binary operation, variables,
and an equality — so turning it into words is a structural rewrite of its parse
tree, not a translation. Nothing here is a judgement call at run time: the same
equation always yields the same sentence, byte for byte.

This is deliberately *not* the same thing as `../nl/`, which asks a model to
describe a law in prose. That representation is fluent and lossy; this one is
mechanical and exactly invertible. Having both lets the project separate "the
model misread the notation" from "the model misread the mathematics".

The parse tree comes from [`../../oracle/normalizer.py`](../../oracle/normalizer.py):
`parse_equation` yields `Equation(lhs, rhs)` over `Op(left, right)` and
`Var(name)` nodes, and this module walks that tree. Reusing the oracle's parser
rather than writing a second one is deliberate — a private parser here could
disagree with the one the semantic oracle uses, and then a text rendering would
no longer be evidence about the same equation.

## The rendering, in one line

Read the canonical form aloud. Every symbol becomes one word or phrase:

    ◇  ->  diamond          (  ->  open bracket
    =  ->  equals           )  ->  close bracket

    x ◇ (y ◇ z) = x   ->   x diamond open bracket y diamond z close bracket equals x

Brackets appear exactly where the canonical form has them — around every nested
operation, never around a whole side — so the word sequence pins down one tree
and no other. That is the entire specification, which is why it is easy to
believe and cheap to check.

## Why bracket words, and not something more elegant

Three schemes were considered for the nesting, which is the only genuinely open
question in a rendering this small:

  1. **Bracket words** (chosen) — `x diamond open bracket y diamond z close
     bracket equals x`. Verbose, but it is how a person reads a formula out
     loud, the reader never has to hold anything in their head, and it inverts
     by substitution.

  2. **Prefix noun phrases** — `the diamond of x and the diamond of y and z
     equals x`. Formally this is fine: the grammar `T := var | "the diamond of"
     T "and" T` is unambiguous, so no two trees collide. But recovering the
     tree means counting arities to work out which `and` closes which `of`, and
     at ETP's order 4 that gets ugly fast: `(x ◇ y) ◇ (z ◇ w)` becomes `the
     diamond of the diamond of x and y and the diamond of z and w`, five words
     of which three are `and`. This project measures whether models preserve
     meaning across representations; a notation whose correct reading requires
     arity bookkeeping would measure the notation instead.

  3. **Spoken "quantity"** — `x diamond the quantity y diamond z`. This is the
     usual dictation shorthand and it is genuinely ambiguous: there is no
     closing marker, so at depth two the reader cannot tell where the group
     ends. Rejected outright.

The cost of (1) is length; at order 4 the longest law is still one line.

## Why `diamond` and not `times`

The ETP operation is an arbitrary binary operation on an arbitrary set. It is
not associative, not commutative, and has no identity — so calling it "times"
would quietly import three properties it does not have, and a reader who
believed the word would answer implication questions wrongly for reasons that
belong to this file rather than to their algebra. `diamond` names the symbol
the catalogue itself uses (◇), carries no algebraic baggage, and keeps this
representation aligned with `\\diamond` in `../latex/` and `∘` in `../lean/`.

`--operator-word times` is available for when a plainer reading is wanted, and
the choice is recorded in the catalogue's `meta.style` either way.

## Round-tripping

Everything emitted here reads back to the equation it came from: `to_equation`
substitutes the words back to symbols and hands the result to the oracle's own
parser, and `verify_round_trip` checks the resulting tree against the original
structurally (AST equality, not string equality). That is the check that makes
a rendering trustworthy — it catches a dropped bracket or a mis-nested subterm,
which is precisely the failure that still *looks* like a plausible equation.
`build_catalogue.py` runs it over all 4694 laws.

CLI:
    python3 textify.py "x ◇ (y ◇ z) = (x ◇ y) ◇ z"
    python3 textify.py 43 4512 --brackets parenthesis
    python3 textify.py --operator-word times --quantify 43
    python3 textify.py --selftest
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
    parse_equation,
)

# Bracket vocabularies. "bracket" is the default because it is the shorter word
# and the one the project's own notes reach for; "parenthesis" is offered
# because in American usage "bracket" more often means `[`, and a reader who
# takes it that way would still get the grouping right but would picture the
# wrong symbol.
BRACKET_WORDS = {
    "bracket": ("open bracket", "close bracket"),
    "parenthesis": ("open parenthesis", "close parenthesis"),
}

# Operator words that have been checked to tokenize cleanly (single- or
# multi-word, no collision with the bracket or equality vocabulary, no letter
# that could be mistaken for a variable). Any other string is accepted too, and
# validated by `TextStyle.__post_init__`.
KNOWN_OPERATOR_WORDS = ("diamond", "times", "combined with", "op")


class TextStyleError(ValueError):
    """A `TextStyle` whose vocabulary could not be read back unambiguously."""


@dataclass(frozen=True)
class TextStyle:
    """How an equation is verbalized. Every field is recorded in the output.

    Fields:
      operator_word  the word for the magma operation (default `diamond`; see
                     the module docstring for why not `times`).
      brackets       which bracket vocabulary to use: `bracket` (default) or
                     `parenthesis`.
      equals_word    the word for `=` (default `equals`).
      quantify       prefix an explicit `for all x y z, ` over the law's
                     variables. ETP laws are universally quantified implicitly;
                     make it visible when the surrounding prose does not
                     already say so.
    """

    operator_word: str = "diamond"
    brackets: str = "bracket"
    equals_word: str = "equals"
    quantify: bool = False

    def __post_init__(self):
        if self.brackets not in BRACKET_WORDS:
            raise TextStyleError(
                f"brackets must be one of {tuple(BRACKET_WORDS)}, got {self.brackets!r}"
            )
        for field, value in (("operator_word", self.operator_word),
                             ("equals_word", self.equals_word)):
            if not value.strip():
                raise TextStyleError(f"{field} must be a non-empty phrase")
            if not re.fullmatch(r"[a-z]+(?: [a-z]+)*", value):
                raise TextStyleError(
                    f"{field} must be lowercase words separated by single spaces, "
                    f"got {value!r} — anything else would not survive the read-back"
                )
            if any(len(word) == 1 for word in value.split()):
                # A one-letter word is indistinguishable from a variable once
                # the sentence is tokenized, so the read-back would silently
                # produce a different tree.
                raise TextStyleError(
                    f"{field} must not contain a one-letter word ({value!r}): it "
                    "would be read back as a variable"
                )
        # The four vocabularies are substituted independently on the way back,
        # so no phrase may contain another as a whole word.
        phrases = {"operator_word": self.operator_word, "equals_word": self.equals_word,
                   "open": self.open_words, "close": self.close_words}
        for a_name, a in phrases.items():
            for b_name, b in phrases.items():
                if a_name != b_name and re.search(rf"\b{re.escape(b)}\b", a):
                    raise TextStyleError(
                        f"{a_name} ({a!r}) contains {b_name} ({b!r}); the read-back "
                        "substitutes one phrase at a time and would corrupt it"
                    )

    @property
    def open_words(self) -> str:
        """The phrase that opens a nested group."""
        return BRACKET_WORDS[self.brackets][0]

    @property
    def close_words(self) -> str:
        """The phrase that closes a nested group."""
        return BRACKET_WORDS[self.brackets][1]


DEFAULT_STYLE = TextStyle()


def text_term(term: Var | Op, style: TextStyle = DEFAULT_STYLE, *, top: bool = True) -> str:
    """Verbalize one side of an equation.

    `top` marks the root of a term: the outermost operation needs no brackets,
    every nested one does. This mirrors `Op.render` in the normalizer exactly,
    so the words and the canonical text agree on structure by construction
    rather than by coincidence.
    """
    if isinstance(term, Var):
        return term.name
    inner = (
        f"{text_term(term.left, style, top=False)} {style.operator_word} "
        f"{text_term(term.right, style, top=False)}"
    )
    return inner if top else f"{style.open_words} {inner} {style.close_words}"


def text_body(equation: Equation, style: TextStyle = DEFAULT_STYLE) -> str:
    """Verbalize the identity itself, without the quantifier prefix."""
    return (
        f"{text_term(equation.lhs, style)} {style.equals_word} "
        f"{text_term(equation.rhs, style)}"
    )


def quantifier_prefix(equation: Equation, style: TextStyle = DEFAULT_STYLE) -> str:
    """`for all x y z, ` over the equation's variables, in first-appearance order.

    The variables are separated by spaces rather than commas, following
    `../latex/latexify.py`: the oracle's `strip_noise` recognises a quantifier
    prefix ending at the first `,`, `.`, or `:`, and its variable-list pattern
    is non-greedy, so `for all x, y, z, ` would be stripped back only as far as
    `for all x,` and leave `y, z,` in front of the equation.
    """
    names: list[str] = []
    equation.lhs.variables(names)
    equation.rhs.variables(names)
    if not names:
        return ""
    return f"for all {' '.join(names)}, "


def text_equation(equation: Equation, style: TextStyle = DEFAULT_STYLE) -> str:
    """Verbalize a parsed `Equation` in the given style."""
    body = text_body(equation, style)
    return (quantifier_prefix(equation, style) + body) if style.quantify else body


def to_text(text: str, style: TextStyle = DEFAULT_STYLE) -> str:
    """Parse an equation string and verbalize it.

    Raises `ParseFailure` / `OutsideFragment` from the oracle's parser for
    input that is not a single-operation magma identity — the same two error
    types the rest of the project branches on. Use `analyze` for a
    never-raising version.
    """
    return text_equation(parse_equation(text), style)


# -- reading the words back ---------------------------------------------------

# Substituted longest phrase first so that a multi-word operator (`combined
# with`) is consumed before any of its words could be matched on its own.
_SYMBOL_FOR = {"open": " ( ", "close": " ) ", "operator": " ◇ ", "equals": " = "}


def to_equation(sentence: str, style: TextStyle = DEFAULT_STYLE) -> Equation:
    """Read a verbalized equation back into the oracle's syntax tree.

    Each vocabulary phrase is substituted back to its symbol and the result is
    handed to `normalizer.parse_equation`, which also disposes of the `for all
    …,` prefix via its own `strip_noise`. Deliberately not a second grammar:
    the tree this returns is produced by the same parser the semantic oracle
    uses, so a successful round trip is evidence about that parser's reading,
    not about a private one written to agree with itself.

    Raises the parser's `ParseFailure` / `OutsideFragment` if the sentence is
    not a verbalization of a magma identity in this style.
    """
    phrases = [
        (style.open_words, _SYMBOL_FOR["open"]),
        (style.close_words, _SYMBOL_FOR["close"]),
        (style.operator_word, _SYMBOL_FOR["operator"]),
        (style.equals_word, _SYMBOL_FOR["equals"]),
    ]
    working = sentence
    for phrase, symbol in sorted(phrases, key=lambda pair: -len(pair[0])):
        working = re.sub(rf"\b{re.escape(phrase)}\b", symbol, working)
    return parse_equation(working)


def verify_round_trip(text: str, style: TextStyle = DEFAULT_STYLE) -> bool:
    """Whether the verbalization of `text` reads back to the same equation.

    Structural equality of the parse trees, not string equality: the ASTs are
    frozen dataclasses, so `==` compares shape and variable names exactly.
    Returns False (rather than raising) if the sentence cannot be read at all.
    """
    equation = parse_equation(text)
    try:
        reread = to_equation(text_equation(equation, style), style)
    except (ParseFailure, OutsideFragment):
        return False
    return reread == equation


def analyze(text: str, style: TextStyle = DEFAULT_STYLE) -> dict:
    """Parse + verbalize, returning errors as data rather than exceptions.

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
        "text": text_equation(equation, style),
        "order": equation.size(),
        "variables": names,
    }


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


def style_from_args(args) -> TextStyle:
    """Build a `TextStyle` from parsed CLI flags."""
    try:
        return TextStyle(
            operator_word=args.operator_word,
            brackets=args.brackets,
            equals_word=args.equals_word,
            quantify=args.quantify,
        )
    except TextStyleError as exc:
        raise SystemExit(str(exc)) from None


def add_style_args(parser: argparse.ArgumentParser) -> None:
    """Register the style flags shared by this CLI and `build_catalogue.py`."""
    group = parser.add_argument_group("text style")
    group.add_argument("--operator-word", default="diamond",
                       help="word for the operation (default diamond); tested: "
                            + ", ".join(KNOWN_OPERATOR_WORDS))
    group.add_argument("--brackets", choices=tuple(BRACKET_WORDS), default="bracket",
                       help="bracket vocabulary for nested groups (default bracket)")
    group.add_argument("--equals-word", default="equals",
                       help="word for = (default equals)")
    group.add_argument("--quantify", action="store_true",
                       help="prefix an explicit 'for all x y z,' over the variables")


# (input, expected text with the default style). Chosen to pin the decisions
# that matter: no operation at all, one operation, nesting on each side,
# repeated variables, and the maximum-order shapes.
_CASES = (
    ("x = x", "x equals x"),
    ("x = y", "x equals y"),
    ("x ◇ y = y ◇ x", "x diamond y equals y diamond x"),
    ("x = x ◇ y", "x equals x diamond y"),
    ("x ◇ (y ◇ z) = x",
     "x diamond open bracket y diamond z close bracket equals x"),
    ("x ◇ (y ◇ z) = (x ◇ y) ◇ z",
     "x diamond open bracket y diamond z close bracket equals "
     "open bracket x diamond y close bracket diamond z"),
    ("a * (b * c) = (a * b) * c",
     "a diamond open bracket b diamond c close bracket equals "
     "open bracket a diamond b close bracket diamond c"),
    ("(x ◇ x) ◇ (x ◇ x) = x",
     "open bracket x diamond x close bracket diamond "
     "open bracket x diamond x close bracket equals x"),
    ("x = (y ◇ x) ◇ (y ◇ (y ◇ x))",
     "x equals open bracket y diamond x close bracket diamond open bracket y diamond "
     "open bracket y diamond x close bracket close bracket"),
)


def selftest() -> None:
    """Check the rendering cases and the round trip; exit non-zero on failure."""
    failures = 0
    for text, expected in _CASES:
        got = to_text(text)
        ok = got == expected
        failures += not ok
        print(f"[{'ok ' if ok else 'FAIL'}] {text!r} -> {got!r}"
              + ("" if ok else f"\n       expected {expected!r}"))

    styles = [
        TextStyle(),
        TextStyle(brackets="parenthesis"),
        TextStyle(operator_word="times"),
        TextStyle(operator_word="combined with"),
        TextStyle(operator_word="op", equals_word="is equal to"),
        TextStyle(quantify=True),
        TextStyle(operator_word="combined with", brackets="parenthesis",
                  equals_word="is the same as", quantify=True),
    ]
    for style in styles:
        for text, _ in _CASES:
            ok = verify_round_trip(text, style)
            failures += not ok
            if not ok:
                print(f"[FAIL] round trip {text!r} under {style}")
    print(f"[ok ] round trip: {len(styles)} styles x {len(_CASES)} equations")

    # The quantified form must be stripped back correctly, not merely parsed:
    # a mis-stripped prefix would leave a stray variable and change the tree.
    quantified = to_text("x ◇ (y ◇ z) = z", TextStyle(quantify=True))
    ok = quantified.startswith("for all x y z, ")
    failures += not ok
    print(f"[{'ok ' if ok else 'FAIL'}] quantified: {quantified!r}")

    # Styles that could not be read back must be refused at construction.
    for bad, why in (
        (dict(operator_word="x"), "one-letter operator word"),
        (dict(operator_word="open bracket times"), "operator word contains a bracket phrase"),
        (dict(brackets="braces"), "unknown bracket vocabulary"),
        (dict(equals_word="Equals"), "non-lowercase equality word"),
        (dict(operator_word=""), "empty operator word"),
    ):
        try:
            TextStyle(**bad)
        except TextStyleError:
            print(f"[ok ] rejected: {why}")
        else:
            failures += 1
            print(f"[FAIL] accepted a style that cannot round-trip: {why} ({bad})")

    for bad, expected_error in (("a * b * c = c", "parse-failure"),
                                ("a * b = b + a", "outside-fragment")):
        result = analyze(bad)
        ok = not result["ok"] and result["error"] == expected_error
        failures += not ok
        print(f"[{'ok ' if ok else 'FAIL'}] {bad!r} -> {result.get('error')}")

    print("selftest:", "all passed" if not failures else f"{failures} failures")
    raise SystemExit(1 if failures else 0)


def main() -> None:
    """CLI entry point: verbalize each argument, or run the selftest."""
    parser = argparse.ArgumentParser(
        description="Convert ETP magma equations to deterministic English text "
                    "(no model involved)."
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
        print(f"text:   {record['text']}")
        print(f"order:  {record['order']}   variables: {', '.join(record['variables'])}\n")
    if any(not r["ok"] for r in records):
        raise SystemExit(1)


if __name__ == "__main__":
    main()


# Exported for `build_catalogue.py` and any other consumer.
__all__ = [
    "BRACKET_WORDS",
    "DEFAULT_STYLE",
    "KNOWN_OPERATOR_WORDS",
    "ORACLE_DIR",
    "TextStyle",
    "TextStyleError",
    "add_style_args",
    "analyze",
    "quantifier_prefix",
    "style_from_args",
    "text_body",
    "text_equation",
    "text_term",
    "to_equation",
    "to_text",
    "verify_round_trip",
]
