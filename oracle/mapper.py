"""Map a (possibly messy) equation string to an ETP node.

The ETP catalogue (data/equations.txt, line N = Equation N) is exhaustive for
identities with at most 4 operation symbols, up to variable renaming and
orientation of '='. So after normalization:

  - order <= 4 and key found     -> MAPPED (this is the only success case)
  - order <= 4 and key missing   -> impossible for a genuine identity; reported
                                    as INTERNAL_ERROR (i.e. a normalizer bug)
  - order  > 4                   -> OUTSIDE_FRAGMENT (a real magma law, but the
                                    implication graph cannot speak about it)
  - unreadable / not an identity -> PARSE_FAILURE / OUTSIDE_FRAGMENT
"""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass, field

from normalizer import (
    Equation,
    OutsideFragment,
    ParseFailure,
    canonical_key,
    normalize,
    parse_equation,
)


# The only file from the ETP repo this module needs is the equation catalogue
# `equations.txt`. You do NOT need to clone the whole repo — download that one
# file anywhere and point at it. Resolution order for its location:
#   1. ETP_EQUATIONS       — a direct path to equations.txt (preferred);
#   2. $ETP_ROOT/data/equations.txt — if you happen to have a full checkout;
#   3. ~/equational_theories/data/equations.txt — the default checkout path.
# You can also pass the path explicitly to NodeMapper(equations_path=...),
# which overrides all of the above.
ETP_ROOT = os.environ.get("ETP_ROOT", os.path.expanduser("~/equational_theories"))
EQUATIONS_TXT = os.environ.get(
    "ETP_EQUATIONS", os.path.join(ETP_ROOT, "data", "equations.txt")
)

MAX_ORDER = 4  # the catalogue enumerates all laws with <= 4 op symbols


@dataclass
class MapResult:
    """Outcome of trying to map one equation string to an ETP node.

    A single record capturing every branch of `NodeMapper.map`, so callers can
    both act on the result (via `status`/`node`) and report it (via
    `normalized`/`order`/`reason`) without exceptions crossing the boundary.

    Fields:
      status      one of: "mapped", "parse-failure", "outside-fragment",
                  "internal-error" — the discriminant for everything else.
      input_text  the original string, kept verbatim for logging/datasets.
      normalized  canonical rendering (variables renamed, operator = ◇), when
                  the text parsed; None on a parse failure.
      node        1-based ETP equation number, set only when status="mapped".
      order       operation-symbol count, when known.
      reason      human-readable explanation for any non-mapped status.
      equation    the parsed AST; carried for downstream use (e.g. the oracle)
                  but `repr=False` so it stays out of logs and JSON dumps.
    """

    status: str                      # mapped | parse-failure | outside-fragment | internal-error
    input_text: str
    normalized: str | None = None    # canonical rendering (variables renamed, op = ◇)
    node: int | None = None          # ETP equation number (1-based), if mapped
    order: int | None = None         # number of operation symbols
    reason: str | None = None
    equation: Equation | None = field(default=None, repr=False)

    @property
    def mapped(self) -> bool:
        """True iff the string resolved to a catalogue node — the one success
        case, and the precondition for reading `node`."""
        return self.status == "mapped"

    def to_dict(self) -> dict:
        """A JSON-serializable view of this result, for piping to other tools."""
        return {
            "status": self.status,
            "input_text": self.input_text,
            "normalized": self.normalized,
            "node": self.node,
            "order": self.order,
            "reason": self.reason,
        }


class NodeMapper:
    """An in-memory index of the ETP catalogue for equation ↔ node lookup.

    Loads `equations.txt` once and builds a canonical-key → node-number map, so
    that any incoming equation string can be resolved to its ETP equation
    number in O(1). Holds two structures: `laws` (node number → the law's text)
    and `key_to_node` (canonical key → node number). Constructing one reads the
    file and validates it; reuse a single instance rather than rebuilding.
    """

    def __init__(self, equations_path: str = EQUATIONS_TXT):
        self.equations_path = equations_path
        self.laws: list[str] = []          # laws[i] = text of Equation i+1
        self.key_to_node: dict[str, int] = {}
        self._build()

    def _build(self) -> None:
        """Read the catalogue and populate `laws` and `key_to_node`.

        Line N of the file is Equation N. Each law is parsed and reduced to a
        canonical key; the keys are asserted to be unique, which is a real
        integrity check on both the file and our normalizer — the catalogue is
        de-duplicated up to renaming and orientation, so a collision would mean
        our `canonical_key` conflates two genuinely different laws.
        """
        if not os.path.exists(self.equations_path):
            raise SystemExit(
                f"equation catalogue not found: {self.equations_path}\n"
                "You do not need the whole equational_theories repo — download "
                "just data/equations.txt and either place it at that path, set "
                "ETP_EQUATIONS=/path/to/equations.txt, or pass "
                "NodeMapper(equations_path=...)."
            )
        with open(self.equations_path, encoding="utf-8") as f:
            lines = f.read().splitlines()
        while lines and not lines[-1].strip():
            lines.pop()  # a trailing newline / blank tail is harmless
        for lineno, line in enumerate(lines, start=1):
            law = line.strip()
            if not law:
                # Both `laws` (index = node - 1) and `key_to_node` (value =
                # line number) assume line N = Equation N. Skipping an interior
                # blank line would silently skew the two against each other, so
                # refuse the file instead.
                raise RuntimeError(
                    f"blank line {lineno} in {self.equations_path}: the "
                    "catalogue must hold exactly one law per line (line N = "
                    "Equation N)"
                )
            self.laws.append(law)
            key = canonical_key(parse_equation(law))
            dup = self.key_to_node.get(key)
            if dup is not None:
                raise RuntimeError(
                    f"canonical-key collision: Equation {dup} and Equation "
                    f"{lineno} both normalize to {key!r}"
                )
            self.key_to_node[key] = lineno

    def law_text(self, node: int) -> str:
        """Return the catalogue text of Equation `node` (1-based).

        The inverse direction of `map`: node number → law string. Used to turn
        an ETP number the user passed back into an equation to display or to
        re-map (e.g. `Equation 43` → `x ◇ y = y ◇ x`).
        """
        return self.laws[node - 1]

    def map(self, text: str) -> MapResult:
        """Resolve one equation string to a MapResult (parse → normalize →
        look up), never raising.

        The four outcomes, mirroring the module docstring:
          - parses, order ≤ 4, key found → status "mapped" with `node`;
          - parses, order > 4 → "outside-fragment" (a real law, too big for the
            catalogue, so the implication graph cannot address it);
          - parses, order ≤ 4, key *not* found → "internal-error", because the
            catalogue is exhaustive at that size, so a miss means our normalizer
            is wrong, not that a new law was found;
          - unreadable / not an identity → "parse-failure" or
            "outside-fragment", propagated from the parser's exception type.
        Exceptions from parsing are caught and turned into result records so
        callers can branch on `status` instead of handling errors.
        """
        try:
            eq = parse_equation(text)
        except ParseFailure as e:
            return MapResult("parse-failure", text, reason=str(e))
        except OutsideFragment as e:
            return MapResult("outside-fragment", text, reason=str(e))

        norm = normalize(eq)
        order = eq.size()
        if order > MAX_ORDER:
            return MapResult(
                "outside-fragment", text, normalized=norm.render(), order=order,
                reason=f"valid magma identity, but order {order} > {MAX_ORDER}: "
                       "not in the ETP catalogue", equation=eq,
            )
        node = self.key_to_node.get(canonical_key(eq))
        if node is None:
            # The catalogue is exhaustive for order <= 4, so this indicates a
            # normalizer bug, not a new law.
            return MapResult(
                "internal-error", text, normalized=norm.render(), order=order,
                reason="order <= 4 identity missing from the exhaustive "
                       "catalogue — normalizer bug, please report", equation=eq,
            )
        return MapResult(
            "mapped", text, normalized=norm.render(), order=order, node=node,
            equation=eq,
        )


def main() -> None:
    """CLI: map each equation given on the command line to an ETP node.

    With `--json` it prints a JSON array of records (one per input) suitable for
    piping into another program; each record is `MapResult.to_dict()` plus a
    `law` field carrying the catalogue text when the input mapped. Without
    `--json` it prints a human-readable line per input. Reads the same
    `ETP_EQUATIONS` / `ETP_ROOT` configuration as the rest of the package.
    """
    ap = argparse.ArgumentParser(description="map equations to ETP nodes")
    ap.add_argument("equations", nargs="+", help="equation string(s) to map")
    ap.add_argument("--json", action="store_true",
                    help="emit a JSON array of records instead of text")
    args = ap.parse_args()

    m = NodeMapper()

    if args.json:
        records = []
        for arg in args.equations:
            r = m.map(arg)
            rec = r.to_dict()
            # Include the catalogue law text for mapped inputs, so a consumer
            # gets both the node number and its canonical equation.
            rec["law"] = m.law_text(r.node) if r.mapped else None
            records.append(rec)
        print(json.dumps(records, ensure_ascii=False, indent=2))
        return

    print(f"loaded {len(m.laws)} laws, {len(m.key_to_node)} unique canonical keys")
    for arg in args.equations:
        r = m.map(arg)
        print(f"{arg!r} -> {r.status}"
              + (f" Equation {r.node} [{m.law_text(r.node)}]" if r.mapped else f" ({r.reason})"))


if __name__ == "__main__":
    main()
