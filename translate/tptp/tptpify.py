"""ETP formal equation -> TPTP first-order form (the dialect Vampire reads).

    x ◇ (y ◇ z) = (x ◇ y) ◇ z

    fof(law, axiom, ![X,Y,Z] : op(X,op(Y,Z)) = op(op(X,Y),Z)).

TPTP is the format this project's own ground truth came out of: the ETP's
implication data is Vampire output, and Vampire eats exactly this. That makes it
the most operationally realistic rendering in `translate/`, and also the one
most likely to be dense in pretraining data — plenty of TPTP files are famous —
so it doubles as a contamination probe.

The formula is named `law`, never `law4512`. An ETP node number in the text
would hand over the answer, which is the same reason `../lean/` strips it.

Variables are upper-cased because TPTP requires it; the oracle normalizes
variable names anyway, and the reader lower-cases nothing — it simply parses,
since `normalizer` already accepts both `op(a,b)` functional notation and
upper-case identifiers.

CLI:  python3 tptpify.py 4512 | python3 tptpify.py --selftest
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _catalogue import (  # noqa: E402
    Equation, ParseFailure, Representation, Var, parse_equation, single_main,
    variables,
)

FORMULA_NAME = "law"
FUNCTION = "op"

_FOF = re.compile(r"^fof\(\s*[A-Za-z0-9_]+\s*,\s*axiom\s*,\s*(?P<body>.*)\)\.$", re.S)
_QUANTIFIER = re.compile(r"^!\[(?P<vars>[^\]]*)\]\s*:\s*(?P<matrix>.*)$", re.S)


def _functional(term) -> str:
    if isinstance(term, Var):
        return term.name.upper()
    return f"{FUNCTION}({_functional(term.left)},{_functional(term.right)})"


def render(equation: Equation) -> str:
    """Emit one `fof(...)` axiom, universally quantified over its variables."""
    quantified = ",".join(name.upper() for name in variables(equation))
    return (f"fof({FORMULA_NAME}, axiom, ![{quantified}] : "
            f"{_functional(equation.lhs)} = {_functional(equation.rhs)}).")


def read_back(text: str) -> Equation:
    """Strip the `fof` wrapper and the quantifier, then parse the matrix.

    The quantified variables are checked against the ones the matrix actually
    uses. Without that the quantifier would be free to disagree with the body
    and nothing would notice, since it is discarded before parsing.
    """
    outer = _FOF.match(text.strip())
    if not outer:
        raise ParseFailure("not a single fof(name, axiom, ...) formula")
    inner = _QUANTIFIER.match(outer.group("body").strip())
    if not inner:
        raise ParseFailure("the formula must be universally quantified with ![...]")
    declared = [name.strip().lower()
                for name in inner.group("vars").split(",") if name.strip()]
    if len(declared) != len(set(declared)):
        raise ParseFailure(f"a variable is quantified twice: {declared}")
    # Upper-casing is injective on the catalogue's single-letter variables, so
    # undoing it here keeps the round trip an exact tree match rather than a
    # weaker up-to-renaming one.
    equation = parse_equation(inner.group("matrix").lower())
    used = variables(equation)
    if sorted(declared) != sorted(used):
        raise ParseFailure(
            f"quantified variables {sorted(declared)} do not match the ones used "
            f"{sorted(used)}"
        )
    return equation


def representation(args=None) -> Representation:
    """The `Representation` this directory exports."""
    return Representation(
        name="tptp", key="tptp", render=render, read_back=read_back,
        blurb="TPTP first-order form (fof)",
        style={"language": "fof", "role": "axiom", "formula_name": FORMULA_NAME,
               "function": FUNCTION, "variables": "upper-case",
               "node_in_representation": False},
    )


_CASES = (
    ("x = x", "fof(law, axiom, ![X] : X = X)."),
    ("x ◇ y = y ◇ x", "fof(law, axiom, ![X,Y] : op(X,Y) = op(Y,X))."),
    ("x ◇ (y ◇ z) = (x ◇ y) ◇ z",
     "fof(law, axiom, ![X,Y,Z] : op(X,op(Y,Z)) = op(op(X,Y),Z))."),
)

_BAD = (
    ("op(X,Y) = op(Y,X).", "no fof wrapper"),
    ("fof(law, axiom, op(X,Y) = op(Y,X)).", "no quantifier"),
    ("fof(law, axiom, ![X] : op(X,Y) = op(Y,X)).", "a variable used but not quantified"),
    ("fof(law, axiom, ![X,Y,Z] : op(X,Y) = op(Y,X)).", "a variable quantified but unused"),
    ("fof(law, conjecture, ![X] : X = X).", "the wrong formula role"),
)

if __name__ == "__main__":
    single_main(representation, _CASES, _BAD)
