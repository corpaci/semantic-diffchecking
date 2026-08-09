#!/usr/bin/env python3
"""Build the judge-LM pair dataset from the ETP implication matrix.

Reads the oracle's matrix.bin + equations.txt, computes equivalence classes,
splits BY CLASS (never by pair), samples balanced relation pairs with surface
augmentation, and writes train/pairs_val/classes_val/test JSONL.

Labels (4-way): equivalent | weaker | stronger | incomparable
  For a pair (A, B) the label describes B relative to A, matching the
  oracle's convention (weaker = B drops constraints).
  'unknown' is not a trainable class (190 cells in the snapshot); unresolved
  pairs are simply never sampled.

Splits:
  - classes with > PIN_SIZE members are pinned to train (the x = y monster
    class would otherwise remove a third of the catalogue from training)
  - remaining classes: TEST_FRAC to test, VAL_FRAC to classes_val, rest train
  - pairs_val: unseen PAIRS of train-class laws (interpolation measure)
  - classes_val/test: pairs where at least one law is from a held-out class
    (novel-theory measure). The pairs_val vs classes_val accuracy gap is the
    memorization measurement.

Usage:
  ETP_EQUATIONS=... python3 build_pair_dataset.py --out data/
  (defaults assume the semantic-diffchecking-repo oracle layout)
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sys
from collections import Counter, defaultdict

ORACLE_DIR = os.path.expanduser("~/Documents/semantic-diffchecking-repo/oracle")
sys.path.insert(0, ORACLE_DIR)
os.environ.setdefault("ETP_EQUATIONS", os.path.join(ORACLE_DIR, "data", "equations.txt"))

from normalizer import INFIX_OPS, Equation, Op, Var, parse_equation  # noqa: E402

MATRIX_BIN = os.path.join(ORACLE_DIR, "data", "matrix.bin")
META_JSON = os.path.join(ORACLE_DIR, "data", "matrix_meta.json")

PROOF_FALSE, PROOF_TRUE = 0, 1

# Only symbols the oracle's own tokenizer accepts (NOT ascii '.', which it
# rejects) — keeps every augmented rendering round-trippable through mapper.
OP_SYMBOLS = ["*", "·", "@", "+"]
assert all(s in INFIX_OPS for s in OP_SYMBOLS)
VAR_POOLS = [
    list("xyzwuvst"),
    list("abcdefgh"),
    list("pqrstuvw"),
    list("mnkljihg"),
]


def render(term, mapping, op, top=True):
    if isinstance(term, Var):
        return mapping[term.name]
    s = f"{render(term.left, mapping, op, False)} {op} {render(term.right, mapping, op, False)}"
    return s if top else f"({s})"


def augment(eq: Equation, rng: random.Random) -> str:
    """Render a parsed law with random variable names, op symbol, orientation."""
    varnames: list = []
    eq.lhs.variables(varnames)
    eq.rhs.variables(varnames)
    pool = rng.choice(VAR_POOLS)[:]
    rng.shuffle(pool)
    mapping = {v: pool[i] for i, v in enumerate(varnames)}
    op = rng.choice(OP_SYMBOLS)
    lhs = render(eq.lhs, mapping, op)
    rhs = render(eq.rhs, mapping, op)
    if rng.random() < 0.5:
        lhs, rhs = rhs, lhs
    return f"{lhs} = {rhs}"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="data")
    ap.add_argument("--per-class-train", type=int, default=60_000,
                    help="examples per relation label in train")
    ap.add_argument("--per-class-eval", type=int, default=2_000,
                    help="examples per relation label in each eval split")
    ap.add_argument("--pin-size", type=int, default=50,
                    help="classes larger than this are pinned to train")
    ap.add_argument("--test-frac", type=float, default=0.15)
    ap.add_argument("--val-frac", type=float, default=0.10)
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()
    rng = random.Random(args.seed)

    with open(META_JSON, encoding="utf-8") as f:
        n = json.load(f)["n"]
    with open(MATRIX_BIN, "rb") as f:
        buf = f.read()
    with open(os.environ["ETP_EQUATIONS"], encoding="utf-8") as f:
        laws = [ln.strip() for ln in f.read().splitlines() if ln.strip()]
    assert len(laws) == n
    asts = [parse_equation(law) for law in laws]

    # --- equivalence classes (union-find over mutual proof_true) -------------
    parent = list(range(n))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for i in range(n):
        base = i * n
        for j in range(i + 1, n):
            if buf[base + j] == PROOF_TRUE and buf[j * n + i] == PROOF_TRUE:
                ri, rj = find(i), find(j)
                if ri != rj:
                    parent[rj] = ri
    members = defaultdict(list)
    for i in range(n):
        members[find(i)].append(i)
    classes = list(members.values())
    print(f"{n} laws, {len(classes)} equivalence classes")

    # --- split by class ------------------------------------------------------
    pinned = [c for c in classes if len(c) > args.pin_size]
    free = [c for c in classes if len(c) <= args.pin_size]
    rng.shuffle(free)
    n_test = int(len(free) * args.test_frac)
    n_val = int(len(free) * args.val_frac)
    test_classes = free[:n_test]
    val_classes = free[n_test:n_test + n_val]
    train_classes = free[n_test + n_val:] + pinned

    def lawset(cs):
        return sorted(i for c in cs for i in c)

    train_laws = lawset(train_classes)
    val_laws = lawset(val_classes)
    test_laws = lawset(test_classes)
    print(f"classes  train/val/test: {len(train_classes)}/{len(val_classes)}/{len(test_classes)}"
          f"  (pinned to train: {len(pinned)})")
    print(f"laws     train/val/test: {len(train_laws)}/{len(val_laws)}/{len(test_laws)}")

    cls_of = {}
    for c in classes:
        r = find(c[0])
        for i in c:
            cls_of[i] = r

    def relation(a: int, b: int):
        """Label of b relative to a, or None if unresolved/uninformative."""
        fwd, bwd = buf[a * n + b], buf[b * n + a]
        if fwd == PROOF_TRUE and bwd == PROOF_TRUE:
            return "equivalent"
        if fwd == PROOF_TRUE and bwd == PROOF_FALSE:
            return "weaker"
        if fwd == PROOF_FALSE and bwd == PROOF_TRUE:
            return "stronger"
        if fwd == PROOF_FALSE and bwd == PROOF_FALSE:
            return "incomparable"
        return None  # conjecture / open: never sampled

    def example(a: int, b: int, label: str, tier: str):
        return {
            "text_a": augment(asts[a], rng),
            "text_b": augment(asts[b], rng),
            "label": label,
            "node_a": a + 1,
            "node_b": b + 1,
            "tier": tier,
        }

    def sample_split(pool_a, pool_b, per_class, cross_split):
        """Sample `per_class` examples per label. cross_split: at least one
        side must come from pool_b (the held-out laws)."""
        out = []
        eq_classes_here = [c for c in classes
                           if len(c) >= 2 and all(i in pool_set for i in c)]
        pool_set_a, pool_set_b = set(pool_a), set(pool_b)
        # equivalent: half same-node augmented (easy), half cross-node (hard)
        n_easy = per_class // 2
        easy_src = pool_b if cross_split else pool_a
        for _ in range(n_easy):
            a = rng.choice(easy_src)
            out.append(example(a, a, "equivalent", "same-node"))
        made, guard = 0, 0
        while made < per_class - n_easy and guard < per_class * 200:
            guard += 1
            c = rng.choice(multi_classes)
            a, b = rng.sample(c, 2)
            if cross_split and (a not in pool_set_b and b not in pool_set_b):
                continue
            if not cross_split and (a not in pool_set_a or b not in pool_set_a):
                continue
            out.append(example(a, b, "equivalent", "cross-node"))
            made += 1
        # directional + incomparable by rejection sampling
        want = {"weaker": per_class, "stronger": per_class, "incomparable": per_class}
        got = Counter()
        guard = 0
        while any(got[k] < want[k] for k in want) and guard < 5_000_000:
            guard += 1
            if cross_split:
                a = rng.choice(pool_b if rng.random() < 0.5 else pool_a)
                b = rng.choice(pool_b if a in pool_set_a else (pool_a + pool_b))
            else:
                a, b = rng.choice(pool_a), rng.choice(pool_a)
            if a == b:
                continue
            lab = relation(a, b)
            if lab in want and got[lab] < want[lab]:
                out.append(example(a, b, lab, "graph"))
                got[lab] += 1
        rng.shuffle(out)
        return out

    global multi_classes, pool_set
    multi_classes = [c for c in classes if len(c) >= 2]
    pool_set = set(range(n))

    os.makedirs(args.out, exist_ok=True)
    splits = {
        "train": sample_split(train_laws, train_laws, args.per_class_train, False),
        "pairs_val": sample_split(train_laws, train_laws, args.per_class_eval, False),
        "classes_val": sample_split(train_laws, val_laws, args.per_class_eval, True),
        "test": sample_split(train_laws, test_laws, args.per_class_eval, True),
    }
    manifest = {"seed": args.seed, "n_laws": n, "n_classes": len(classes),
                "train_classes": len(train_classes), "val_classes": len(val_classes),
                "test_classes": len(test_classes), "pin_size": args.pin_size,
                "source": "2024-11-10-outcomes snapshot via oracle/build_matrix.py"}
    for name, rows in splits.items():
        path = os.path.join(args.out, f"{name}.jsonl")
        with open(path, "w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        dist = Counter(r["label"] for r in rows)
        tiers = Counter(r["tier"] for r in rows if r["label"] == "equivalent")
        print(f"{name:12s} {len(rows):7d} rows  {dict(dist)}  equiv tiers {dict(tiers)}")
    with open(os.path.join(args.out, "manifest.json"), "w") as f:
        json.dump(manifest, f, indent=2)
    print("wrote", args.out)


if __name__ == "__main__":
    main()
