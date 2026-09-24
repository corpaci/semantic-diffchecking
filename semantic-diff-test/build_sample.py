"""Draw the 500-equation sample for the reconstruction experiment.

Uniform sampling of the 4694 ETP laws would be misleading: 4284 of them are
order 4, so a uniform draw is ~91% order-4 and could say nothing about how
difficulty scales. This stratifies by order instead:

    order 1-2   44 of   44   census - the whole sub-population
    order 3    150 of  364   random
    order 4    306 of 4284   random

Nodes 1 (`x = x`) and 2 (`x = y`) are excluded. They are degenerate for
implication grading - every law implies `x = x`, and `x = y` implies every law -
so a verdict against them says nothing about meaning preservation. This is the
same exclusion `implications/` used.

A 150-equation subset is marked for the k=3 repeat arm, drawn proportionally
from the same strata (13/45/92), so the repeat measurement is not concentrated
in one difficulty band.

Because the strata are deliberately not proportional, every catalogue-wide
figure must be post-stratified; the weights are written into the output so the
analysis cannot forget.

    python3 build_sample.py            # -> sample.json
    python3 build_sample.py --check    # verify an existing sample.json
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "oracle"))

from mapper import NodeMapper  # noqa: E402
from normalizer import Op, Var, parse_equation  # noqa: E402

SEED = 20260830
EXCLUDED = (1, 2)
QUOTAS = {"low": None, "3": 150, "4": 306}      # None = census
REPEAT_QUOTAS = {"low": 13, "3": 45, "4": 92}   # 150 total, proportional
OUT = Path(__file__).parent / "sample.json"


def depth(term) -> int:
    """Nesting depth of a term; 0 for a bare variable."""
    return 0 if isinstance(term, Var) else 1 + max(depth(term.left), depth(term.right))


def stratum_of(order: int) -> str:
    """Which sampling stratum an order falls in."""
    return "3" if order == 3 else "4" if order == 4 else "low"


def build() -> dict:
    """Draw the sample deterministically from SEED."""
    mapper = NodeMapper()
    population: dict[str, list[dict]] = {"low": [], "3": [], "4": []}
    for index, law in enumerate(mapper.laws):
        node = index + 1
        if node in EXCLUDED:
            continue
        equation = parse_equation(law)
        names: list[str] = []
        equation.lhs.variables(names)
        equation.rhs.variables(names)
        order = equation.size()
        population[stratum_of(order)].append({
            "node": node, "formal": law, "order": order,
            "depth": max(depth(equation.lhs), depth(equation.rhs)),
            "variables": len(names),
        })

    rng = random.Random(SEED)
    chosen: list[dict] = []
    strata_meta = {}
    for name, rows in population.items():
        rows.sort(key=lambda r: r["node"])          # sample from a fixed order
        quota = QUOTAS[name] if QUOTAS[name] is not None else len(rows)
        picked = sorted(rng.sample(rows, quota), key=lambda r: r["node"])
        for row in picked:
            row["stratum"] = name
        chosen += picked
        strata_meta[name] = {
            "population": len(rows), "sampled": quota,
            "weight": len(rows) / quota,            # post-stratification weight
        }

    repeat_rng = random.Random(SEED + 1)
    repeats: list[int] = []
    for name, quota in REPEAT_QUOTAS.items():
        pool = [r["node"] for r in chosen if r["stratum"] == name]
        repeats += repeat_rng.sample(pool, quota)
    repeats.sort()

    chosen.sort(key=lambda r: r["node"])
    return {
        "meta": {
            "generator": "semantic-diff-test/build_sample.py",
            "source": mapper.equations_path,
            "seed": SEED,
            "excluded_nodes": list(EXCLUDED),
            "excluded_reason": "degenerate for implication grading",
            "strata": strata_meta,
            "count": len(chosen),
            "repeat_arm": {"k": 3, "count": len(repeats),
                           "quotas": REPEAT_QUOTAS, "seed": SEED + 1},
        },
        "equations": chosen,
        "repeat_nodes": repeats,
    }


def report(sample: dict) -> None:
    """Print the shape of a drawn sample."""
    rows = sample["equations"]
    print(f"{len(rows)} equations, seed {sample['meta']['seed']}", file=sys.stderr)
    for name, m in sample["meta"]["strata"].items():
        print(f"  stratum {name:4} {m['sampled']:4} of {m['population']:5}"
              f"   weight {m['weight']:6.2f}", file=sys.stderr)
    print("  order:      " + ", ".join(f"{o}:{n}" for o, n in
          sorted(Counter(r["order"] for r in rows).items())), file=sys.stderr)
    print("  depth:      " + ", ".join(f"{o}:{n}" for o, n in
          sorted(Counter(r["depth"] for r in rows).items())), file=sys.stderr)
    print("  variables:  " + ", ".join(f"{o}:{n}" for o, n in
          sorted(Counter(r["variables"] for r in rows).items())), file=sys.stderr)
    print(f"  repeat arm: {len(sample['repeat_nodes'])} equations (k=3)", file=sys.stderr)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true",
                        help="rebuild and confirm it matches the committed sample.json")
    args = parser.parse_args()

    sample = build()
    if args.check:
        existing = json.loads(OUT.read_text())
        same = (existing["equations"] == sample["equations"]
                and existing["repeat_nodes"] == sample["repeat_nodes"])
        print("sample.json reproduces exactly" if same else "MISMATCH", file=sys.stderr)
        raise SystemExit(0 if same else 1)

    OUT.write_text(json.dumps(sample, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report(sample)
    print(f"wrote {OUT}", file=sys.stderr)


if __name__ == "__main__":
    main()
