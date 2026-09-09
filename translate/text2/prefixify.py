"""ETP formal equation -> deterministic English text, bracket-free. No model involved.

The companion to [`../text/`](../text/). Both directories verbalize the same
4694 laws mechanically and invertibly; they differ in exactly one decision —
how the grouping is encoded.

    x ◇ (y ◇ z) = x

    ../text/   x diamond open bracket y diamond z close bracket equals x
    here       the diamond of x and the diamond of y and z equals x

`../text/` spells the parentheses out as words. This module removes them
entirely: each operation becomes a noun phrase that names its two arguments,
`the diamond of A and B`, so the tree is carried by the phrasing rather than by
delimiters. Nothing else changes — same catalogue, same node numbering, same
verification, same output shape — which is what makes the pair usable as a
controlled contrast: two English renderings of identical content, differing
only in how a reader must recover the structure.

## Why this is unambiguous

The grammar is

    term  :=  VAR  |  "the" OPERATOR "of" term "and" term

and it is LL(1): the first token decides the production (`the` opens a phrase,
anything else is a variable), and each sub-term is self-delimiting because the
operation's arity is fixed at two. So no two distinct trees produce the same
sentence, and the reader below needs no backtracking.

What it costs is that a *reader* must count arities to see which `and` closes
which `of`. At ETP's order 4 that is real work — `(x ◇ y) ◇ (z ◇ w)` becomes

    the diamond of the diamond of x and y and the diamond of z and w

in which three of the words are `and`. That difficulty is the point of having
both representations rather than an argument against this one; `../text/`
documents the same trade-off from the other side.

## Why `diamond` and not `times`

The ETP operation is an arbitrary binary operation on an arbitrary set: not
associative, not commutative, no identity. Calling it "times" would quietly
import three properties it does not have, and a reader who believed the word
would answer implication questions wrongly for reasons belonging to this file
rather than to their algebra. `diamond` names the symbol the catalogue itself
uses (◇) and keeps this aligned with `../text/` and with `\\diamond` in
`../latex/`. `--operator-word product` reads more naturally as English (`the
product of x and y`) and is available when that is wanted; the choice is
recorded in the catalogue's `meta.style` either way.

## Parsing, in both directions

Forward, the parse tree comes from [`../../oracle/normalizer.py`](../../oracle/normalizer.py)
— reusing the oracle's parser rather than writing a second one is deliberate,
since a private parser could disagree with the one the semantic oracle uses and
then a rendering would no longer be evidence about the same equation.

Backward, `to_equation` reads the words with a small recursive-descent pass
that rebuilds the *canonical infix string* — brackets and all — and hands that
to the oracle's `parse_equation`. So the tree that comes back is still produced
by the oracle's parser; this module only recovers the structure, and if it
recovered the wrong structure the round trip would fail loudly.

CLI:
    python3 prefixify.py "x ◇ (y ◇ z) = (x ◇ y) ◇ z"
    python3 prefixify.py 43 4512 --operator-word product
    python3 prefixify.py --quantify 43
    python3 prefixify.py --selftest
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
    CANONICAL_OP,
    Equation,
    Op,
    OutsideFragment,
    ParseFailure,
    Var,
    parse_equation,
)

# Operator words checked to read naturally in `the ___ of A and B` and to
# tokenize cleanly. Any other lowercase word is accepted and validated by
# `PrefixStyle.__post_init__`.
KNOWN_OPERATOR_WORDS = ("diamond", "product", "combination", "operation")

# The quantifier prefix `--quantify` emits, and the pattern that removes it on
# the way back. Space-separated variables, following `../text/` and
# `../latex/`: a comma-separated list would be cut short by the oracle's own
# non-greedy quantifier stripper, and this reader keeps the same shape so the
# two representations stay directly comparable.
_QUANTIFIER = re.compile(r"^for all(?: [a-z]+)+,\s*")


class PrefixStyleError(ValueError):
    """A `PrefixStyle` whose vocabulary could not be read back unambiguously."""


@dataclass(frozen=True)
class PrefixStyle:
    """How an equation is verbalized. Every field is recorded in the output.

    Fields:
      operator_word  the noun naming the operation, used as `the ___ of`
                     (default `diamond`; see the module docstring for why not
                     `times`).
      connector      the word joining the two arguments (default `and`).
      equals_word    the phrase for `=` (default `equals`).
      quantify       prefix an explicit `for all x y z, ` over the law's
                     variables. ETP laws are universally quantified implicitly;
                     make it visible when the surrounding prose does not
                     already say so.
    """

    operator_word: str = "diamond"
    connector: str = "and"
    equals_word: str = "equals"
    quantify: bool = False

    def __post_init__(self):
        for field, value in (("operator_word", self.operator_word),
                             ("connector", self.connector),
                             ("equals_word", self.equals_word)):
            if not value.strip():
                raise PrefixStyleError(f"{field} must be a non-empty phrase")
            if not re.fullmatch(r"[a-z]+(?: [a-z]+)*", value):
                raise PrefixStyleError(
                    f"{field} must be lowercase words separated by single spaces, "
                    f"got {value!r} — anything else would not survive the read-back"
                )
            if any(len(word) == 1 for word in value.split()):
                # A one-letter word is indistinguishable from a variable once
                # the sentence is tokenized, so the read-back would silently
                # produce a different tree.
                raise PrefixStyleError(
                    f"{field} must not contain a one-letter word ({value!r}): it "
                    "would be read back as a variable"
                )
        if len(self.connector.split()) != 1:
            # The reader matches the connector as a single token between two
            # self-delimiting sub-terms; a multi-word connector is not needed
            # by anything and would complicate that for no gain.
            raise PrefixStyleError(f"connector must be a single word, got {self.connector!r}")

        # LL(1) requires the three tokens that can appear at a decision point
        # to be distinct: `the` opens an operation phrase, and after a complete
        # sub-term the next token is either the connector or the start of the
        # equality phrase.
        signals = {"phrase opener": "the",
                   "connector": self.connector,
                   "equals_word": self.equals_word.split()[0]}
        for a_name, a in signals.items():
            for b_name, b in signals.items():
                if a_name < b_name and a == b:
                    raise PrefixStyleError(
                        f"{a_name} and {b_name} both begin with {a!r}; the reader "
                        "could not tell them apart"
                    )
        if self.operator_word in {"the", "of"}:
            raise PrefixStyleError(
                f"operator_word must not be {self.operator_word!r}: it would collide "
                "with the fixed words of the phrase `the ___ of`"
            )

    @property
    def open_phrase(self) -> str:
        """The phrase that introduces an operation, e.g. `the diamond of`."""
        return f"the {self.operator_word} of"


DEFAULT_STYLE = PrefixStyle()


def text_term(term: Var | Op, style: PrefixStyle = DEFAULT_STYLE) -> str:
    """Verbalize one side of an equation.

    Unlike the bracketed rendering in `../text/`, there is no `top` parameter:
    an operation is phrased identically wherever it sits, because the phrase
    itself delimits its two arguments. That is the whole difference between the
    two representations, and it is why this function has no special case.
    """
    if isinstance(term, Var):
        return term.name
    return (
        f"{style.open_phrase} {text_term(term.left, style)} "
        f"{style.connector} {text_term(term.right, style)}"
    )


def text_body(equation: Equation, style: PrefixStyle = DEFAULT_STYLE) -> str:
    """Verbalize the identity itself, without the quantifier prefix."""
    return (
        f"{text_term(equation.lhs, style)} {style.equals_word} "
        f"{text_term(equation.rhs, style)}"
    )


def quantifier_prefix(equation: Equation, style: PrefixStyle = DEFAULT_STYLE) -> str:
    """`for all x y z, ` over the equation's variables, in first-appearance order.

    Space-separated rather than comma-separated; see `_QUANTIFIER` for why.
    """
    names: list[str] = []
    equation.lhs.variables(names)
    equation.rhs.variables(names)
    if not names:
        return ""
    return f"for all {' '.join(names)}, "


def text_equation(equation: Equation, style: PrefixStyle = DEFAULT_STYLE) -> str:
    """Verbalize a parsed `Equation` in the given style."""
    body = text_body(equation, style)
    return (quantifier_prefix(equation, style) + body) if style.quantify else body


def to_text(text: str, style: PrefixStyle = DEFAULT_STYLE) -> str:
    """Parse an equation string and verbalize it.

    Raises `ParseFailure` / `OutsideFragment` from the oracle's parser for
    input that is not a single-operation magma identity — the same two error
    types the rest of the project branches on. Use `analyze` for a
    never-raising version.
    """
    return text_equation(parse_equation(text), style)


# -- reading the words back ---------------------------------------------------


class _Reader:
    """Recursive-descent reader over the words of a verbalized equation.

    Rebuilds the canonical *infix* string (with parentheses) rather than a
    syntax tree, so the tree is still built by the oracle's `parse_equation`
    — see the module docstring. Compound sub-terms are always parenthesized,
    including at the root of a side: the oracle's parser drops redundant outer
    parentheses, so there is no need for a `top` special case here either.

    Raises `ParseFailure` (the oracle's own type) on anything unreadable, so
    callers branch on the same exceptions as everywhere else in the project.
    """

    def __init__(self, tokens: list[str], style: PrefixStyle):
        self.tokens = tokens
        self.style = style
        self.pos = 0
        self.opener = style.open_phrase.split()
        self.equals = style.equals_word.split()

    def _fail(self, expected: str) -> ParseFailure:
        seen = self.tokens[self.pos] if self.pos < len(self.tokens) else "end of sentence"
        return ParseFailure(f"expected {expected} at word {self.pos + 1}, found {seen!r}")

    def _at(self, words: list[str]) -> bool:
        """Whether the given word sequence starts at the cursor."""
        return self.tokens[self.pos:self.pos + len(words)] == words

    def _eat(self, words: list[str], what: str) -> None:
        """Consume the given word sequence, or fail."""
        if not self._at(words):
            raise self._fail(f"{what} ({' '.join(words)!r})")
        self.pos += len(words)

    def term(self) -> str:
        """Read one term, returning it as canonical infix text."""
        if self.pos >= len(self.tokens):
            raise self._fail("a term")
        if self._at(self.opener):
            self.pos += len(self.opener)
            left = self.term()
            self._eat([self.style.connector], "the connector")
            right = self.term()
            return f"({left} {CANONICAL_OP} {right})"
        token = self.tokens[self.pos]
        if not token.isalpha():
            raise self._fail("a variable")
        self.pos += 1
        return token

    def equation(self) -> str:
        """Read the whole equation, returning it as canonical infix text."""
        lhs = self.term()
        self._eat(self.equals, "the equality phrase")
        rhs = self.term()
        if self.pos != len(self.tokens):
            raise ParseFailure(
                f"trailing words after the equation: "
                f"{' '.join(self.tokens[self.pos:])!r}"
            )
        return f"{lhs} = {rhs}"


def to_equation(sentence: str, style: PrefixStyle = DEFAULT_STYLE) -> Equation:
    """Read a verbalized equation back into the oracle's syntax tree.

    The `for all …,` prefix is removed first (this grammar has no production
    for it), the words are then read into canonical infix text, and that text
    is parsed by `normalizer.parse_equation`. Deliberately not a second
    grammar for equations: the tree returned is produced by the same parser the
    semantic oracle uses, so a successful round trip is evidence about that
    parser's reading, not about a private one written to agree with itself.

    Raises the parser's `ParseFailure` / `OutsideFragment` if the sentence is
    not a verbalization of a magma identity in this style.
    """
    body = _QUANTIFIER.sub("", sentence.strip())
    tokens = body.split()
    if not tokens:
        raise ParseFailure("empty sentence")
    return parse_equation(_Reader(tokens, style).equation())


def verify_round_trip(text: str, style: PrefixStyle = DEFAULT_STYLE) -> bool:
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


def analyze(text: str, style: PrefixStyle = DEFAULT_STYLE) -> dict:
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


def style_from_args(args) -> PrefixStyle:
    """Build a `PrefixStyle` from parsed CLI flags."""
    try:
        return PrefixStyle(
            operator_word=args.operator_word,
            connector=args.connector,
            equals_word=args.equals_word,
            quantify=args.quantify,
        )
    except PrefixStyleError as exc:
        raise SystemExit(str(exc)) from None


def add_style_args(parser: argparse.ArgumentParser) -> None:
    """Register the style flags shared by this CLI and `build_catalogue.py`."""
    group = parser.add_argument_group("text style")
    group.add_argument("--operator-word", default="diamond",
                       help="noun for the operation, used as 'the ___ of' "
                            "(default diamond); tested: "
                            + ", ".join(KNOWN_OPERATOR_WORDS))
    group.add_argument("--connector", default="and",
                       help="word joining the two arguments (default and)")
    group.add_argument("--equals-word", default="equals",
                       help="phrase for = (default equals)")
    group.add_argument("--quantify", action="store_true",
                       help="prefix an explicit 'for all x y z,' over the variables")


# (input, expected text with the default style). Chosen to pin the decisions
# that matter: no operation at all, one operation, nesting on each side, the
# case from the module docstring, and the maximum-order shapes — including the
# three-`and` sentence that motivates having `../text/` as well.
_CASES = (
    ("x = x", "x equals x"),
    ("x = y", "x equals y"),
    ("x ◇ y = y ◇ x", "the diamond of x and y equals the diamond of y and x"),
    ("x = x ◇ y", "x equals the diamond of x and y"),
    ("x ◇ (y ◇ z) = x", "the diamond of x and the diamond of y and z equals x"),
    ("x ◇ (y ◇ z) = (x ◇ y) ◇ z",
     "the diamond of x and the diamond of y and z equals "
     "the diamond of the diamond of x and y and z"),
    ("a * (b * c) = (a * b) * c",
     "the diamond of a and the diamond of b and c equals "
     "the diamond of the diamond of a and b and c"),
    ("(x ◇ y) ◇ (z ◇ w) = x",
     "the diamond of the diamond of x and y and the diamond of z and w equals x"),
    ("x = (y ◇ x) ◇ (y ◇ (y ◇ x))",
     "x equals the diamond of the diamond of y and x and the diamond of y and "
     "the diamond of y and x"),
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
        PrefixStyle(),
        PrefixStyle(operator_word="product"),
        PrefixStyle(operator_word="combination", connector="with"),
        PrefixStyle(equals_word="is equal to"),
        PrefixStyle(quantify=True),
        PrefixStyle(operator_word="operation", connector="plus",
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
    quantified = to_text("x ◇ (y ◇ z) = z", PrefixStyle(quantify=True))
    ok = quantified.startswith("for all x y z, ")
    failures += not ok
    print(f"[{'ok ' if ok else 'FAIL'}] quantified: {quantified!r}")

    # Sentences the grammar must refuse, rather than silently misread. The
    # first two are the shapes that would exist if the grammar really were
    # ambiguous; that they fail is the practical form of the LL(1) claim.
    for bad, why in (
        ("the diamond of x and y and z equals x", "an extra argument"),
        ("the diamond of x equals x", "a missing argument"),
        ("the diamond of x and y", "no equality"),
        ("x equals the diamond of x and y and", "a dangling connector"),
    ):
        try:
            to_equation(bad)
        except (ParseFailure, OutsideFragment) as exc:
            print(f"[ok ] refused: {why:<22} ({str(exc)[:50]})")
        else:
            failures += 1
            print(f"[FAIL] accepted a malformed sentence: {why} ({bad!r})")

    # Styles that could not be read back must be refused at construction.
    for bad, why in (
        (dict(operator_word="x"), "one-letter operator word"),
        (dict(connector="the"), "connector collides with the phrase opener"),
        (dict(equals_word="and"), "equality phrase collides with the connector"),
        (dict(operator_word="the"), "operator word collides with the phrase opener"),
        (dict(connector="and then"), "multi-word connector"),
        (dict(equals_word="Equals"), "non-lowercase equality word"),
    ):
        try:
            PrefixStyle(**bad)
        except PrefixStyleError:
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
        description="Convert ETP magma equations to deterministic bracket-free "
                    "English text (no model involved)."
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
    "DEFAULT_STYLE",
    "KNOWN_OPERATOR_WORDS",
    "ORACLE_DIR",
    "PrefixStyle",
    "PrefixStyleError",
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
