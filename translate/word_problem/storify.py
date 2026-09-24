"""ETP formal equation -> the same law dressed as a word problem.

    x ◇ (y ◇ z) = (x ◇ y) ◇ z

    A workshop welder takes two parts, in a definite order, and fuses them into
    one new part. Feeding the same two parts in the opposite order, or grouping
    a sequence of welds differently, may give a different part.

    Claim: for any parts x, y and z, welding x to the part made by welding y to
    z gives the same part as welding the part made by welding x to y to z.

The operation becomes a physical action and the law becomes a claim about it.
Nothing else changes: the tree, the variables, and their order are all
preserved exactly, so this is a control on *framing* rather than a new
notation. A drop in accuracy here is attributable to the narrative dressing
alone.

## Deterministic, not written by a model

`../nl/` already occupies the model-written-prose slot, and its output is
fluent but lossy and unrepeatable. This module is a fixed template: the same
law always produces the same paragraph, byte for byte, and the paragraph reads
back to the law it came from. That is what lets it sit alongside the other
mechanical catalogues rather than needing its own grading story.

## The scenario paragraph is constant

The first paragraph is byte-identical for all 4694 laws. It has to be: it is
there to stop a reader assuming the operation is commutative or associative —
neither holds for a magma — and if it varied with the law it would leak
information about the law. The reader checks it verbatim, so a drift in the
boilerplate is an error rather than a silent change in what the catalogue
means.

## Nesting

Two phrasings of one operation, chosen so the sentence reads:

    at the root of a side   welding A to B
    nested inside another   the part made by welding A to B

Both are unambiguous for the same reason `../text2/` is — the grammar
`desc := VAR | "the part made by welding" desc "to" desc` is LL(1), since the
first word decides the production and each argument is self-delimiting. What it
costs is the same too: at order 4 the reader must count to see which `to`
closes which `welding`, which is why `../ssa/` exists as the flattened
alternative.

CLI:  python3 storify.py 4512 | python3 storify.py --selftest
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _catalogue import (  # noqa: E402
    CANONICAL_OP, Equation, ParseFailure, Representation, Var, parse_equation,
    single_main, variables,
)

SCENARIO = (
    "A workshop welder takes two parts, in a definite order, and fuses them into "
    "one new part. Feeding the same two parts in the opposite order, or grouping "
    "a sequence of welds differently, may give a different part."
)
CLAIM = "Claim: "
NESTED = "the part made by welding"
ROOT = "welding"
CONNECTOR = "to"
LINK = "gives the same part as"

_NESTED_WORDS = NESTED.split()


def _describe(term) -> str:
    """A nested operation, as a noun phrase naming the part it produces."""
    if isinstance(term, Var):
        return term.name
    return (f"{NESTED} {_describe(term.left)} {CONNECTOR} "
            f"{_describe(term.right)}")


def _side(term) -> str:
    """One side of the claim: a verb phrase at the root, a name if it is a leaf."""
    if isinstance(term, Var):
        return term.name
    return f"{ROOT} {_describe(term.left)} {CONNECTOR} {_describe(term.right)}"


def _quantifier(names: list[str]) -> str:
    """`for any parts x, y and z` — singular when there is only one."""
    if len(names) == 1:
        return f"for any part {names[0]}"
    return f"for any parts {', '.join(names[:-1])} and {names[-1]}"


def render(equation: Equation) -> str:
    """The constant scenario, a blank line, then the claim."""
    claim = (f"{CLAIM}{_quantifier(variables(equation))}, {_side(equation.lhs)} "
             f"{LINK} {_side(equation.rhs)}.")
    return f"{SCENARIO}\n\n{claim}"


class _Reader:
    """Recursive descent over the words of one side of the claim.

    Rebuilds canonical infix text rather than a syntax tree, so the tree still
    comes from the oracle's `parse_equation`; this only recovers the structure.
    """

    def __init__(self, tokens: list[str]):
        self.tokens = tokens
        self.position = 0

    def _name(self) -> str:
        if self.position >= len(self.tokens):
            raise ParseFailure("the claim ends where a part was expected")
        token = self.tokens[self.position]
        if not token.isalnum():
            raise ParseFailure(f"not the name of a part: {token!r}")
        self.position += 1
        return token

    def _eat(self, word: str) -> None:
        if self.tokens[self.position:self.position + 1] != [word]:
            found = self.tokens[self.position:self.position + 1] or ["end of claim"]
            raise ParseFailure(f"expected {word!r}, found {found[0]!r}")
        self.position += 1

    def describe(self) -> str:
        """A nested description; compound results are parenthesized."""
        if self.tokens[self.position:self.position + len(_NESTED_WORDS)] == _NESTED_WORDS:
            self.position += len(_NESTED_WORDS)
            left = self.describe()
            self._eat(CONNECTOR)
            right = self.describe()
            return f"({left} {CANONICAL_OP} {right})"
        return self._name()

    def side(self) -> str:
        """A whole side, consuming every token it was given."""
        if self.tokens[:1] == [ROOT]:
            self.position += 1
            left = self.describe()
            self._eat(CONNECTOR)
            right = self.describe()
            result = f"{left} {CANONICAL_OP} {right}"
        else:
            result = self._name()
        if self.position != len(self.tokens):
            leftover = " ".join(self.tokens[self.position:])
            raise ParseFailure(f"unread words at the end of a side: {leftover!r}")
        return result


def _read_quantifier(text: str) -> list[str]:
    """Recover the quantified names, checking singular/plural agreement."""
    for prefix, plural in (("for any parts ", True), ("for any part ", False)):
        if text.startswith(prefix):
            body = text[len(prefix):]
            break
    else:
        raise ParseFailure(f"malformed quantifier: {text!r}")
    if " and " in body:
        head, last = body.rsplit(" and ", 1)
        names = [name.strip() for name in head.split(",")] + [last.strip()]
    else:
        names = [body.strip()]
    if plural != (len(names) > 1):
        raise ParseFailure(
            f"{len(names)} name(s) quantified with the "
            f"{'plural' if plural else 'singular'} form"
        )
    if len(names) != len(set(names)):
        raise ParseFailure(f"a part is named twice: {names}")
    return names


def read_back(text: str) -> Equation:
    """Strip the scenario and the claim frame, then read both sides.

    The scenario is compared verbatim rather than skipped. It carries no
    information about the law, but it is what tells a reader the operation is
    neither commutative nor associative, and a catalogue that had quietly lost
    it would be saying something different from what it claims to say.
    """
    body = text.strip()
    if not body.startswith(SCENARIO):
        raise ParseFailure("the scenario paragraph is missing or altered")
    rest = body[len(SCENARIO):].strip()
    if not rest.startswith(CLAIM):
        raise ParseFailure(f"the second paragraph must start with {CLAIM!r}")
    rest = rest[len(CLAIM):]
    if not rest.endswith("."):
        raise ParseFailure("the claim must end with a full stop")
    rest = rest[:-1]

    if rest.count(LINK) != 1:
        raise ParseFailure(f"expected exactly one {LINK!r}, found {rest.count(LINK)}")
    left, right = rest.split(f" {LINK} ")
    if ", " not in left:
        raise ParseFailure("the claim has no quantifier")
    quantifier, lhs_text = left.rsplit(", ", 1)

    names = _read_quantifier(quantifier)
    lhs = _Reader(lhs_text.split()).side()
    rhs = _Reader(right.split()).side()
    equation = parse_equation(f"{lhs} = {rhs}")
    used = variables(equation)
    if names != used:
        raise ParseFailure(
            f"quantified parts {names} are not the ones used, in order, {used}"
        )
    return equation


def representation(args=None) -> Representation:
    """The `Representation` this directory exports."""
    return Representation(
        name="word_problem", key="word_problem", render=render, read_back=read_back,
        multiline=True, blurb="a word problem about a workshop welder",
        style={"form": "nested prose", "scenario": "constant across all laws",
               "operation": ROOT, "nested_phrase": NESTED, "connector": CONNECTOR,
               "link": LINK},
    )


_CASES = (
    ("x = x", f"{SCENARIO}\n\nClaim: for any part x, x gives the same part as x."),
    ("x ◇ y = y ◇ x",
     f"{SCENARIO}\n\nClaim: for any parts x and y, welding x to y gives the same "
     "part as welding y to x."),
    ("x ◇ (y ◇ z) = (x ◇ y) ◇ z",
     f"{SCENARIO}\n\nClaim: for any parts x, y and z, welding x to the part made "
     "by welding y to z gives the same part as welding the part made by welding "
     "x to y to z."),
)

_BAD = (
    (f"Claim: for any part x, x {LINK} x.", "no scenario paragraph"),
    (f"{SCENARIO}\n\nfor any part x, x {LINK} x.", "no 'Claim:' marker"),
    (f"{SCENARIO}\n\nClaim: for any part x, x {LINK} x", "no full stop"),
    (f"{SCENARIO}\n\nClaim: for any part x, x {LINK} y.",
     "a part used but not quantified"),
    (f"{SCENARIO}\n\nClaim: for any parts x, x {LINK} x.",
     "the plural form with one name"),
    (f"{SCENARIO}\n\nClaim: for any parts x and y, welding x to {LINK} y.",
     "an operation missing its second part"),
    (f"{SCENARIO}\n\nClaim: for any parts x and y, welding x to y z {LINK} "
     "welding y to x.", "an unread word at the end of a side"),
    (f"{SCENARIO}\n\nClaim: for any part x, x {LINK} x {LINK} x.",
     "two link phrases"),
)

if __name__ == "__main__":
    single_main(representation, _CASES, _BAD)
