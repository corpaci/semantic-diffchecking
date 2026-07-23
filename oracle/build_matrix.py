"""ETP outcomes.json -> compact binary implication matrix.

The ETP data drop `data/<date>-outcomes.json.zip` in the equational_theories
repo holds a 4694 x 4694 matrix where entry [i][j] is the status of the
implication  Equation(i+1) ==> Equation(j+1)  (row = hypothesis, column =
conclusion; same convention as scripts/generate_edgelist_csv.py upstream).

Status byte values (see STATUS_NAMES):
  0 proof_false       refuted by a verified counterexample   -> implication FALSE
  1 proof_true        established by a Lean proof            -> implication TRUE
  2 conjecture_false  believed false, not verified           -> UNKNOWN to the oracle
  3 conjecture_true   believed true, not verified            -> UNKNOWN to the oracle
  4 unknown           open                                   -> UNKNOWN

("explicit" vs "implicit" — stated directly vs derived by transitivity —
is collapsed: both are proofs.)

Usage:
    python3 build_matrix.py [path/to/outcomes.json(.zip)]
"""

from __future__ import annotations

import io
import json
import os
import sys
import zipfile

from mapper import ETP_ROOT


# The only file this build step needs from the ETP repo is the outcomes matrix
# `<date>-outcomes.json(.zip)`. No full checkout required — download that one
# file and point at it. Resolution order (highest priority first):
#   1. the command-line argument, if given;
#   2. ETP_OUTCOMES — a direct path to the outcomes .json or .json.zip;
#   3. $ETP_ROOT/data/2024-11-10-outcomes.json.zip — a full checkout;
#   4. the default checkout path under ~/equational_theories.
DEFAULT_OUTCOMES = os.environ.get(
    "ETP_OUTCOMES", os.path.join(ETP_ROOT, "data", "2024-11-10-outcomes.json.zip")
)
DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
MATRIX_BIN = os.path.join(DATA_DIR, "matrix.bin")
META_JSON = os.path.join(DATA_DIR, "matrix_meta.json")

STATUS_NAMES = ["proof_false", "proof_true", "conjecture_false", "conjecture_true", "unknown"]

_OUTCOME_TO_BYTE = {
    "explicit_proof_false": 0,
    "implicit_proof_false": 0,
    "explicit_proof_true": 1,
    "implicit_proof_true": 1,
    "explicit_conjecture_false": 2,
    "implicit_conjecture_false": 2,
    "explicit_conjecture_true": 3,
    "implicit_conjecture_true": 3,
    "unknown": 4,
}


def load_outcomes(path: str) -> dict:
    """Load the ETP outcomes JSON, transparently handling a `.zip` wrapper."""
    if path.endswith(".zip"):
        with zipfile.ZipFile(path) as z:
            inner = [n for n in z.namelist() if n.endswith(".json")]
            if len(inner) != 1:
                raise SystemExit(f"expected exactly one .json inside {path}, found {inner}")
            with z.open(inner[0]) as f:
                return json.load(io.TextIOWrapper(f, encoding="utf-8"))
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def main() -> None:
    """Convert the outcomes JSON into `data/matrix.bin` + `matrix_meta.json`."""
    src = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_OUTCOMES
    if not os.path.exists(src):
        raise SystemExit(
            f"outcomes file not found: {src}\n"
            "You do not need the whole equational_theories repo — download just "
            "the outcomes file (e.g. data/2024-11-10-outcomes.json.zip) and pass "
            "it as an argument (`python3 build_matrix.py /path/to/outcomes.json.zip`) "
            "or set ETP_OUTCOMES=/path/to/outcomes.json.zip."
        )
    print(f"loading {src} (large; takes a minute) ...")
    data = load_outcomes(src)

    eqs = data["equations"]
    outcomes = data["outcomes"]
    n = len(eqs)
    assert len(outcomes) == n and all(len(row) == n for row in outcomes[:5])
    assert eqs[0] == "Equation1" and eqs[n - 1] == f"Equation{n}", "unexpected ordering"

    buf = bytearray(n * n)
    counts = [0] * len(STATUS_NAMES)
    for i, row in enumerate(outcomes):
        base = i * n
        for j, outcome in enumerate(row):
            b = _OUTCOME_TO_BYTE[outcome]
            buf[base + j] = b
            counts[b] += 1

    # Sanity of the direction convention:
    #   Equation 2 (x = y) implies every law  -> row 1 all TRUE
    #   Equation 1 (x = x) is implied by every law -> column 0 all TRUE
    assert all(buf[1 * n + j] == 1 for j in range(n)), "row for Eq2 not all proof_true"
    assert all(buf[i * n + 0] == 1 for i in range(n)), "column for Eq1 not all proof_true"

    os.makedirs(DATA_DIR, exist_ok=True)
    with open(MATRIX_BIN, "wb") as f:
        f.write(buf)
    with open(META_JSON, "w", encoding="utf-8") as f:
        json.dump(
            {
                "n": n,
                "source": os.path.basename(src),
                "orientation": "byte at [i*n + j] = status of Equation(i+1) => Equation(j+1)",
                "status_names": STATUS_NAMES,
                "counts": dict(zip(STATUS_NAMES, counts)),
            },
            f,
            indent=2,
        )

    print(f"wrote {MATRIX_BIN} ({n}x{n} = {n*n:,} bytes)")
    for name, c in zip(STATUS_NAMES, counts):
        print(f"  {name:18s} {c:>12,}")


if __name__ == "__main__":
    main()
