"""The formal semantic oracle.

Given an intended equation and a generated equation (raw strings or ETP
equation numbers), map both to ETP nodes and read the PROVEN relation off the
resolved implication matrix (built by build_matrix.py):

    label            forward (intended => generated)   backward (generated => intended)
    equivalent       proved TRUE                       proved TRUE
    weaker           proved TRUE                       proved FALSE
    stronger         proved FALSE                      proved TRUE
    incomparable     proved FALSE                      proved FALSE
    unknown          any direction not settled by a proof or a counterexample

"weaker"/"stronger" describe the GENERATED equation relative to the intended
one (weaker = the LLM under-specified, stronger = it over-specified).

Per the ground rules, conjectures and open cases are never treated as
evidence: anything short of a Lean proof / verified counterexample in both
directions yields "unknown" (with the partial evidence reported).

CLI:
    python3 oracle.py --intended "x ◇ y = y ◇ x" --generated "a*(b*c)=(a*b)*c"
    python3 oracle.py --intended 43 --generated "p * q = q * p"
    python3 oracle.py --selftest
"""

from __future__ import annotations

import argparse
import json
import mmap
import os
from dataclasses import asdict, dataclass

from build_matrix import MATRIX_BIN, META_JSON, STATUS_NAMES
from mapper import MapResult, NodeMapper

# Byte values in the matrix for the two *proven* statuses. Anything that is
# neither a proof-true nor a proof-false (i.e. a conjecture or an open cell) is
# deliberately not named here: it falls through to the "unknown" branch, which
# is how the ground rule "no proof/counterexample ⇒ unknown" is enforced.
PROOF_FALSE, PROOF_TRUE = 0, 1


@dataclass
class Verdict:
    """The oracle's full judgment on one (intended, generated) pair.

    Self-contained record of both the conclusion and the evidence for it, ready
    to serialize into a dataset row. `intended`/`generated` are the two sides'
    MapResults (as plain dicts, AST stripped); `forward`/`backward` are the raw
    implication statuses read from the matrix (present only when both sides
    mapped); `evidence` explains a resolved verdict, while `notes` explains an
    unresolved / off-graph one.

    `label` is the headline relation, one of:
      equivalent / weaker / stronger / incomparable  — resolved by the graph,
      unknown                                         — in-fragment but the
                                                        graph did not settle it,
      outside-fragment / parse-failure / internal-error
                                                      — a side never mapped.
    weaker/stronger are stated from the *generated* equation's point of view.
    """

    label: str                     # equivalent | weaker | stronger | incomparable |
                                   # unknown | outside-fragment | parse-failure | internal-error
    intended: dict
    generated: dict
    forward: str | None = None     # status of intended => generated
    backward: str | None = None    # status of generated => intended
    evidence: str | None = None
    notes: str | None = None


class SemanticOracle:
    """The formal semantic oracle: the resolved ETP implication graph wrapped
    in an equation-to-equation comparison API.

    Holds three things after construction: the metadata (`meta`, `n`), the
    implication matrix memory-mapped read-only (`matrix` — so the 22 MB file is
    paged in lazily rather than copied into the heap), and a `NodeMapper` for
    resolving inputs. Its public surface is `implication_status` (one raw graph
    edge) and `compare` (the full labeled verdict).
    """

    def __init__(self):
        """Load the prebuilt matrix and metadata and open the node mapper.

        Exits with an instruction to run `build_matrix.py` if the matrix has
        not been generated yet — the graph data is a required, separately-built
        artifact, not something reconstructed on the fly.
        """
        if not (os.path.exists(MATRIX_BIN) and os.path.exists(META_JSON)):
            raise SystemExit(
                f"missing {MATRIX_BIN}\nrun `python3 build_matrix.py` once to build it"
            )
        with open(META_JSON, encoding="utf-8") as f:
            self.meta = json.load(f)
        self.n = self.meta["n"]
        f = open(MATRIX_BIN, "rb")
        self.matrix = mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ)
        self.mapper = NodeMapper()

    # -- raw matrix access ---------------------------------------------------

    def implication_status(self, hypothesis: int, conclusion: int) -> str:
        """Look up one directed edge: the status of
        `Equation(hypothesis) => Equation(conclusion)`.

        Indexes the flat row-major matrix at `(hypothesis-1)*n + (conclusion-1)`
        and maps the byte back to its status name. Equation numbers are 1-based
        (matching the catalogue); out-of-range numbers raise ValueError. This is
        the single point where the raw graph is read.
        """
        if not (1 <= hypothesis <= self.n and 1 <= conclusion <= self.n):
            raise ValueError(f"equation numbers must be in 1..{self.n}")
        return STATUS_NAMES[self.matrix[(hypothesis - 1) * self.n + (conclusion - 1)]]

    # -- the oracle ----------------------------------------------------------

    def _resolve(self, spec: "str | int") -> MapResult:
        """Normalize either kind of input spec into a MapResult.

        A spec may be an ETP equation number (int, or a digit string) or a raw
        equation string. Numbers are range-checked and turned into their
        catalogue text before mapping (so the returned MapResult always carries
        a parsed AST and normalized form); everything else is handed straight to
        the node mapper. Lets `compare` treat both input styles uniformly.
        """
        if isinstance(spec, int) or (isinstance(spec, str) and spec.strip().isdigit()):
            node = int(spec)
            if not 1 <= node <= self.n:
                return MapResult("parse-failure", str(spec),
                                 reason=f"equation number out of range 1..{self.n}")
            return self.mapper.map(self.mapper.law_text(node))
        return self.mapper.map(spec)

    def compare(self, intended: "str | int", generated: "str | int") -> Verdict:
        """The oracle's main entry point: label the semantic relation between
        an intended and a generated equation.

        Resolves both sides, then:
          1. If either side failed to map to a node, the graph cannot speak, so
             the verdict carries that side's failure status directly (and a note
             pointing to the Lean / finite-magma fallbacks that would be needed
             to resolve it otherwise).
          2. Otherwise read both directed edges and combine them into a
             relation via the truth table below. Only genuine proofs and
             counterexamples resolve a relation; any unsettled edge yields
             "unknown".
        Returns a fully-populated Verdict; never raises for ordinary bad input.
        """
        ri, rg = self._resolve(intended), self._resolve(generated)
        sides = {"intended": _public(ri), "generated": _public(rg)}

        # Case 1: a side that never mapped to a node is off-graph. Report which
        # side and why, rather than guessing a relation.
        for r in (ri, rg):
            if not r.mapped:
                which = "intended" if r is ri else "generated"
                return Verdict(
                    label=r.status, **sides,
                    notes=f"{which} equation: {r.reason}. The implication-graph "
                          "oracle cannot speak; fall back to Lean / finite-magma "
                          "search, else label unknown.",
                )

        # Case 2: both mapped. Read the two directed edges and index them as a
        # (forward, backward) pair of status codes to drive the truth table.
        fwd = self.implication_status(ri.node, rg.node)
        bwd = self.implication_status(rg.node, ri.node)
        fb = (STATUS_NAMES.index(fwd), STATUS_NAMES.index(bwd))

        # Truth table over (intended=>generated, generated=>intended). The
        # same-node shortcut avoids depending on the diagonal being populated.
        if ri.node == rg.node:
            label, evidence = "equivalent", f"both map to Equation {ri.node}"
        elif fb == (PROOF_TRUE, PROOF_TRUE):
            label = "equivalent"
            evidence = f"Lean proofs of Eq{ri.node} => Eq{rg.node} and Eq{rg.node} => Eq{ri.node}"
        elif fb == (PROOF_TRUE, PROOF_FALSE):
            label = "weaker"
            evidence = (f"Lean proof of Eq{ri.node} => Eq{rg.node}; "
                        f"counterexample magma refutes Eq{rg.node} => Eq{ri.node}")
        elif fb == (PROOF_FALSE, PROOF_TRUE):
            label = "stronger"
            evidence = (f"Lean proof of Eq{rg.node} => Eq{ri.node}; "
                        f"counterexample magma refutes Eq{ri.node} => Eq{rg.node}")
        elif fb == (PROOF_FALSE, PROOF_FALSE):
            label = "incomparable"
            evidence = "counterexample magmas refute the implication in both directions"
        else:
            # At least one edge is a conjecture or still open — not proof-backed
            # in both directions, so per the ground rules we refuse to commit.
            label = "unknown"
            evidence = f"not fully resolved: forward={fwd}, backward={bwd}"

        return Verdict(label=label, **sides, forward=fwd, backward=bwd, evidence=evidence)


def _public(r: MapResult) -> dict:
    """Convert a MapResult to a serialization-safe dict for embedding in a
    Verdict — drops the `equation` AST, which is internal and not JSON-friendly,
    keeping only the reportable fields."""
    d = asdict(r)
    d.pop("equation", None)
    return d


# -----------------------------------------------------------------------------


def selftest(oracle: SemanticOracle) -> None:
    """Run a small battery of known pairs through `compare` and exit non-zero on
    any mismatch.

    Doubles as executable documentation of every verdict category: normalization
    invariance (renaming + orientation → equivalent), the four graph relations,
    and each off-graph rejection (ambiguous chain, two operators, chained `=`,
    over-order identity). An `expected` of None means "don't assert the label,
    just exercise the path" — used where the interesting thing is that it runs
    without error. Intended to be invoked via `--selftest`.
    """
    cases = [
        # (intended, generated, expected label)
        ("x ◇ y = y ◇ x", "a * b = b * a", "equivalent"),        # renaming + symbol
        ("x ◇ y = y ◇ x", "b * a = a * b", "equivalent"),        # + orientation flip
        (43, "a * (b * c) = (a * b) * c", "incomparable"),        # commutativity vs associativity
        (2, "p * q = q * p", "weaker"),                           # x=y implies commutativity
        (43, "x = x", "weaker"),                                  # everything implies Eq1
        (43, "p = q", "stronger"),                                # x=y is the strongest law
        (3, "x = x ◇ (x ◇ x)", None),                             # idempotence vs Eq8: read off
        (43, "a * b * c = c", "parse-failure"),                   # ambiguous chain
        (43, "a * b = b + a", "outside-fragment"),                # two operations
        (43, "x * y = y * x = x", "outside-fragment"),            # chained equality
        (43, "e * x = x", None),                                  # 'e' is formally just a variable
        (4512, "x*(y*(z*w)) = ((x*y)*z)*w", "outside-fragment"),  # order 6 identity
    ]
    failures = 0
    for intended, generated, expected in cases:
        v = oracle.compare(intended, generated)
        ok = expected is None or v.label == expected
        failures += not ok
        mark = "ok " if ok else "FAIL"
        print(f"[{mark}] intended={intended!r} generated={generated!r} -> {v.label}"
              + (f" (expected {expected})" if not ok else "")
              + (f" | {v.evidence}" if v.evidence else f" | {v.notes}"))
    print("selftest:", "all passed" if not failures else f"{failures} failures")
    raise SystemExit(1 if failures else 0)


def main() -> None:
    """CLI entry point: parse args, build the oracle, and either run the
    selftest or compare one intended/generated pair.

    Emits either a JSON Verdict (`--json`, for piping into a dataset) or a
    human-readable summary showing how each side resolved, both implication
    directions, and the final verdict with its evidence.
    """
    ap = argparse.ArgumentParser(description="ETP formal semantic oracle")
    ap.add_argument("--intended", help="intended equation (string or ETP number)")
    ap.add_argument("--generated", help="generated equation (string or ETP number)")
    ap.add_argument("--json", action="store_true", help="emit verdict as JSON")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()

    oracle = SemanticOracle()
    if args.selftest:
        selftest(oracle)
    if not (args.intended and args.generated):
        ap.error("--intended and --generated are required (or use --selftest)")

    v = oracle.compare(args.intended, args.generated)
    if args.json:
        print(json.dumps(asdict(v), ensure_ascii=False, indent=2))
    else:
        for side in ("intended", "generated"):
            info = getattr(v, side)
            desc = (f"Equation {info['node']}  [{info['normalized']}]"
                    if info["status"] == "mapped" else f"{info['status']}: {info['reason']}")
            print(f"{side:>9}: {info['input_text']!r} -> {desc}")
        if v.forward:
            print(f"  forward: intended => generated : {v.forward}")
            print(f" backward: generated => intended : {v.backward}")
        print(f"  verdict: {v.label.upper()}"
              + (f"  ({v.evidence})" if v.evidence else "")
              + (f"\n     note: {v.notes}" if v.notes else ""))


if __name__ == "__main__":
    main()
