"""ETP formal equation -> the same law under adversarial variable names.

    x ◇ (y ◇ z) = (x ◇ y) ◇ z

    confusable  l ◇ (I ◇ ll) = (l ◇ I) ◇ ll
    verbose     antecedent ◇ (mediator ◇ consequent)
                  = (antecedent ◇ mediator) ◇ consequent

Structurally identical to the catalogue's own notation; only the variable names
change. That is what makes it a control: the oracle grades reconstructions up
to renaming, so nothing about the *answer* depends on the names, and any drop
in accuracy is attributable to the naming alone.

`confusable` uses names built from `l`, `I` and `1` — glyphs that are hard to
tell apart in most fonts, so keeping two occurrences straight becomes visual
work. `verbose` uses long words that read like logical roles, which is the
opposite pressure: each name is easy to see and expensive to hold.

Because renaming is the whole point, this is the one catalogue here matched
`up-to-renaming` — the round trip compares normalized trees. That is the same
equivalence `../nl_test/` grades under, not a weakened check.

CLI:  python3 confusify.py 4512 --names verbose | python3 confusify.py --selftest
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _catalogue import (  # noqa: E402
    CANONICAL_OP, Equation, Representation, Var, parse_equation, single_main,
    variables,
)

# Both tables are ordered by first appearance and are at least as long as the
# six distinct variables any ETP law of order 4 can use.
NAME_SETS = {
    "confusable": ("l", "I", "ll", "lI", "Il", "II", "l1", "I1", "lll", "III", "llI", "lIl"),
    "verbose": ("antecedent", "mediator", "consequent", "auxiliary", "parameter",
                "argument", "operand", "subject", "residue", "quotient", "premise",
                "nucleus"),
}


def renderer(names: tuple[str, ...]):
    """Build a renderer that rewrites variables through `names`."""

    def render(equation: Equation) -> str:
        appearing = variables(equation)
        if len(appearing) > len(names):
            raise ValueError(f"{len(appearing)} variables but only {len(names)} names")
        mapping = {old: names[index] for index, old in enumerate(appearing)}

        def go(term, *, top: bool) -> str:
            if isinstance(term, Var):
                return mapping[term.name]
            inner = f"{go(term.left, top=False)} {CANONICAL_OP} {go(term.right, top=False)}"
            return inner if top else f"({inner})"

        return f"{go(equation.lhs, top=True)} = {go(equation.rhs, top=True)}"

    return render


def read_back(text: str) -> Equation:
    """Just parse it — the oracle's parser already accepts arbitrary identifiers.

    No un-renaming happens here, which is why this representation is matched
    up to renaming; see the module docstring.
    """
    return parse_equation(text)


def add_style_args(parser) -> None:
    """Register `--names`."""
    parser.add_argument("--names", choices=tuple(NAME_SETS), default="confusable",
                        help="which adversarial naming scheme to use (default confusable)")


def representation(args=None) -> Representation:
    """The `Representation` this directory exports."""
    scheme = getattr(args, "names", "confusable")
    return Representation(
        name="confusable_vars", key="confusable_vars",
        render=renderer(NAME_SETS[scheme]), read_back=read_back,
        match="up-to-renaming", blurb="infix notation under adversarial variable names",
        style={"names": scheme, "table": list(NAME_SETS[scheme]),
               "operator": CANONICAL_OP, "structure": "unchanged"},
    )


_CASES = (
    ("x = x", "l = l"),
    ("x ◇ y = y ◇ x", "l ◇ I = I ◇ l"),
    ("x ◇ (y ◇ z) = (x ◇ y) ◇ z", "l ◇ (I ◇ ll) = (l ◇ I) ◇ ll"),
)

_BAD = (
    ("l ◇ I ◇ ll = l", "an unparenthesized chain"),
    ("l ◇ (I ◇ ll)", "no equality"),
    ("l ◇ (I ◇ ll = l", "unbalanced parentheses"),
)

if __name__ == "__main__":
    single_main(representation, _CASES, _BAD, add_style_args)
