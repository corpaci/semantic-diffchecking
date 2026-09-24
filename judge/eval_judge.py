#!/usr/bin/env python3
"""Post-hoc evaluation of a trained ETP relation judge.

Answers what training-time accuracy cannot:
  1. confusion matrix + precision (training reports recall only)
  2. false-equivalence rate — the error that accepts a drifted translation
  3. `equivalent` split by tier: same-node (surface rewrite) vs cross-node (real)
  4. symmetry: label(A,B)=weaker must imply label(B,A)=stronger
  5. best-of-n ranking — does the judge rank a faithful candidate top?
  6. both-novel slice: rows where BOTH laws come from held-out classes

Runs on a laptop against the adapter; no GPU required.

  python3 eval_judge.py --adapter runs/judge-v0/adapter-final --data data
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sys
from collections import Counter, defaultdict

LABELS = ["equivalent", "weaker", "stronger", "incomparable"]
SWAP = {"equivalent": "equivalent", "weaker": "stronger",
        "stronger": "weaker", "incomparable": "incomparable"}
ORACLE_DIR = os.path.expanduser("~/Documents/semantic-diffchecking-repo/oracle")


def load_rows(path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(l) for l in f]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--adapter", default="runs/judge-v0/adapter-final")
    ap.add_argument("--base", default="google/gemma-2-2b")
    ap.add_argument("--data", default="data")
    ap.add_argument("--split", default="test")
    ap.add_argument("--batch", type=int, default=64)
    ap.add_argument("--limit", type=int, default=0, help="0 = all rows")
    ap.add_argument("--bon-anchors", type=int, default=200)
    ap.add_argument("--bon-n", type=int, default=32)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--out", default=None, help="write metrics JSON here")
    args = ap.parse_args()

    import torch
    from peft import PeftModel
    from transformers import AutoModelForCausalLM, AutoTokenizer

    dev = "mps" if torch.backends.mps.is_available() else (
        "cuda" if torch.cuda.is_available() else "cpu")
    print(f"device: {dev}")

    tok = AutoTokenizer.from_pretrained(args.adapter)
    label_ids = [tok(" " + l, add_special_tokens=False).input_ids[0] for l in LABELS]
    assert len(set(label_ids)) == 4, "label first-tokens collide; head is not 4-way"

    try:
        base = AutoModelForCausalLM.from_pretrained(
            args.base, dtype=torch.bfloat16, attn_implementation="eager")
    except TypeError:  # transformers < 5 spells it torch_dtype
        base = AutoModelForCausalLM.from_pretrained(
            args.base, torch_dtype=torch.bfloat16, attn_implementation="eager")
    model = PeftModel.from_pretrained(base, args.adapter).to(dev).eval()

    @torch.no_grad()
    def score(pairs):
        """pairs: [(text_a, text_b)] -> probs over LABELS, shape (n, 4)."""
        out = []
        for i in range(0, len(pairs), args.batch):
            chunk = pairs[i:i + args.batch]
            enc = [tok(f"A: {a}\nB: {b}\nRelation:", add_special_tokens=True).input_ids
                   for a, b in chunk]
            m = max(len(e) for e in enc)
            pad = tok.pad_token_id if tok.pad_token_id is not None else tok.eos_token_id
            ids = torch.tensor([e + [pad] * (m - len(e)) for e in enc], device=dev)
            att = torch.tensor([[1] * len(e) + [0] * (m - len(e)) for e in enc], device=dev)
            last = torch.tensor([len(e) - 1 for e in enc], device=dev)
            lg = model(input_ids=ids, attention_mask=att).logits
            lg = lg[torch.arange(lg.size(0), device=dev), last][:, label_ids]
            out.append(torch.softmax(lg.float(), -1).cpu())
            print(f"\r  scored {min(i + args.batch, len(pairs))}/{len(pairs)}",
                  end="", flush=True)
        print()
        return torch.cat(out)

    rows = load_rows(os.path.join(args.data, f"{args.split}.jsonl"))
    if args.limit:
        rows = rows[:args.limit]
    train_nodes = {r["node_a"] for r in load_rows(os.path.join(args.data, "train.jsonl"))} | \
                  {r["node_b"] for r in load_rows(os.path.join(args.data, "train.jsonl"))}
    print(f"{len(rows)} rows from {args.split}.jsonl")

    print("scoring forward direction...")
    probs = score([(r["text_a"], r["text_b"]) for r in rows])
    pred = probs.argmax(-1).tolist()
    gold = [LABELS.index(r["label"]) for r in rows]
    conf = probs.max(-1).values.tolist()

    R = {}
    n = len(rows)
    R["n"] = n
    R["accuracy"] = sum(p == g for p, g in zip(pred, gold)) / n

    # ---- confusion matrix, precision, recall -------------------------------
    cm = [[0] * 4 for _ in range(4)]
    for p, g in zip(pred, gold):
        cm[g][p] += 1
    R["confusion"] = {LABELS[g]: {LABELS[p]: cm[g][p] for p in range(4)} for g in range(4)}
    R["per_label"] = {}
    for i, lab in enumerate(LABELS):
        tp = cm[i][i]
        fn = sum(cm[i]) - tp
        fp = sum(cm[g][i] for g in range(4)) - tp
        R["per_label"][lab] = {
            "recall": tp / (tp + fn) if tp + fn else None,
            "precision": tp / (tp + fp) if tp + fp else None,
            "support": sum(cm[i]),
        }

    # ---- the dangerous error ------------------------------------------------
    non_eq = [i for i in range(n) if gold[i] != 0]
    false_eq = [i for i in non_eq if pred[i] == 0]
    R["false_equivalence"] = {
        "rate": len(false_eq) / len(non_eq),
        "count": len(false_eq),
        "of_non_equivalent": len(non_eq),
        "by_true_label": dict(Counter(LABELS[gold[i]] for i in false_eq)),
        "mean_confidence": sum(conf[i] for i in false_eq) / len(false_eq) if false_eq else None,
    }
    miss_eq = [i for i in range(n) if gold[i] == 0 and pred[i] != 0]
    R["missed_equivalence"] = {
        "rate": len(miss_eq) / max(1, sum(1 for g in gold if g == 0)),
        "into": dict(Counter(LABELS[pred[i]] for i in miss_eq)),
    }

    # ---- tier split: is `equivalent` inflated by same-node rows? ------------
    R["by_tier"] = {}
    for tier in ["same-node", "cross-node", "graph"]:
        idx = [i for i in range(n) if rows[i]["tier"] == tier]
        if idx:
            R["by_tier"][tier] = {
                "n": len(idx),
                "accuracy": sum(pred[i] == gold[i] for i in idx) / len(idx),
            }

    # ---- novelty slice ------------------------------------------------------
    R["by_novelty"] = {}
    buckets = defaultdict(list)
    for i, r in enumerate(rows):
        a_new = r["node_a"] not in train_nodes
        b_new = r["node_b"] not in train_nodes
        buckets["both novel" if a_new and b_new else
                ("one novel" if a_new or b_new else "neither novel")].append(i)
    for k, idx in buckets.items():
        R["by_novelty"][k] = {"n": len(idx),
                              "accuracy": sum(pred[i] == gold[i] for i in idx) / len(idx)}

    # ---- calibration --------------------------------------------------------
    right = [conf[i] for i in range(n) if pred[i] == gold[i]]
    wrong = [conf[i] for i in range(n) if pred[i] != gold[i]]
    R["calibration"] = {
        "mean_conf_correct": sum(right) / len(right) if right else None,
        "mean_conf_wrong": sum(wrong) / len(wrong) if wrong else None,
        "wrong_above_0.9_conf": sum(1 for c in wrong if c > 0.9) / len(wrong) if wrong else None,
    }

    # ---- symmetry: label(B,A) must be the mirror of label(A,B) -------------
    print("scoring swapped direction...")
    sprobs = score([(r["text_b"], r["text_a"]) for r in rows])
    spred = sprobs.argmax(-1).tolist()
    agree = sum(1 for i in range(n) if LABELS[spred[i]] == SWAP[LABELS[pred[i]]])
    R["symmetry"] = {
        "consistent_rate": agree / n,
        "note": "fraction where the swapped prediction mirrors the forward prediction",
        "swapped_accuracy": sum(
            1 for i in range(n) if LABELS[spred[i]] == SWAP[rows[i]["label"]]) / n,
    }

    # ---- best-of-n ranking: the referee test --------------------------------
    bon = run_best_of_n(args, rows, train_nodes, score)
    if bon:
        R["best_of_n"] = bon

    report(R)
    out = args.out or os.path.join(os.path.dirname(args.adapter) or ".", "eval_report.json")
    with open(out, "w") as f:
        json.dump(R, f, indent=2)
    print(f"\nwrote {out}")


def run_best_of_n(args, rows, train_nodes, score):
    """Simulate best-of-n selection: one faithful candidate among n-1 drifted.

    The judge picks argmax P(equivalent). An exploitation event is a pick that
    is not actually equivalent to the anchor -- the thing top-1 accuracy on
    independent pairs cannot measure.
    """
    sys.path.insert(0, ORACLE_DIR)
    os.environ.setdefault("ETP_EQUATIONS", os.path.join(ORACLE_DIR, "data", "equations.txt"))
    try:
        from normalizer import parse_equation  # noqa: F401
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from build_pair_dataset import augment
        meta = json.load(open(os.path.join(ORACLE_DIR, "data", "matrix_meta.json")))
        nn = meta["n"]
        buf = open(os.path.join(ORACLE_DIR, "data", "matrix.bin"), "rb").read()
        laws = [l.strip() for l in
                open(os.environ["ETP_EQUATIONS"], encoding="utf-8").read().splitlines() if l.strip()]
        asts = [parse_equation(l) for l in laws]
    except Exception as e:
        print(f"\nbest-of-n skipped (oracle data unavailable): {str(e)[:120]}")
        return None

    rng = random.Random(args.seed)
    novel = sorted({r["node_a"] for r in rows if r["node_a"] not in train_nodes} |
                   {r["node_b"] for r in rows if r["node_b"] not in train_nodes})
    anchors = novel[:args.bon_anchors] if len(novel) >= args.bon_anchors else novel
    print(f"\nbest-of-n: {len(anchors)} anchors x {args.bon_n} candidates")

    flat, meta_rows = [], []
    for a in anchors:
        ai = a - 1
        anchor_txt = augment(asts[ai], rng)
        cands = [(augment(asts[ai], rng), True)]          # the faithful one
        tries = 0
        while len(cands) < args.bon_n and tries < args.bon_n * 40:
            tries += 1
            bi = rng.randrange(nn)
            if bi == ai:
                continue
            fwd, bwd = buf[ai * nn + bi], buf[bi * nn + ai]
            if fwd == 1 and bwd == 1:      # genuinely equivalent, skip as a distractor
                continue
            if fwd > 1 or bwd > 1:         # unresolved cell
                continue
            cands.append((augment(asts[bi], rng), False))
        for txt, faithful in cands:
            flat.append((anchor_txt, txt))
            meta_rows.append((a, faithful))

    p = score(flat)[:, 0].tolist()   # P(equivalent)
    groups = defaultdict(list)
    for (anchor, faithful), pe in zip(meta_rows, p):
        groups[anchor].append((pe, faithful))

    top1, mrr, margins = 0, 0.0, []
    for g in groups.values():
        g.sort(key=lambda x: -x[0])
        rank = next(i for i, (_, f) in enumerate(g) if f) + 1
        top1 += rank == 1
        mrr += 1 / rank
        faith = max(pe for pe, f in g if f)
        best_drift = max((pe for pe, f in g if not f), default=0.0)
        margins.append(faith - best_drift)
    k = len(groups)
    return {
        "anchors": k,
        "n_candidates": args.bon_n,
        "faithful_ranked_top1": top1 / k,
        "exploitation_rate": 1 - top1 / k,
        "mrr": mrr / k,
        "mean_margin": sum(margins) / k,
        "negative_margin_rate": sum(1 for m in margins if m < 0) / k,
    }


def report(R):
    p = print
    p("\n" + "=" * 66)
    p(f"OVERALL ACCURACY  {R['accuracy']:.4f}   (n={R['n']}, chance=0.25)")
    p("=" * 66)
    p("\nCONFUSION MATRIX   rows = truth, cols = predicted")
    p(f"{'':14s}" + "".join(f"{l[:9]:>11s}" for l in LABELS))
    for g in LABELS:
        p(f"{g:14s}" + "".join(f"{R['confusion'][g][x]:>11d}" for x in LABELS))
    p("\nPER-LABEL")
    p(f"{'label':14s}{'recall':>10s}{'precision':>11s}{'support':>9s}")
    for l in LABELS:
        d = R["per_label"][l]
        p(f"{l:14s}{d['recall']:>10.4f}{d['precision']:>11.4f}{d['support']:>9d}")
    fe = R["false_equivalence"]
    p(f"\nFALSE-EQUIVALENCE (the dangerous error)")
    p(f"  rate {fe['rate']:.4f}  ({fe['count']} of {fe['of_non_equivalent']} non-equivalent rows)")
    p(f"  by true label: {fe['by_true_label']}")
    if fe["mean_confidence"]:
        p(f"  mean confidence when it does this: {fe['mean_confidence']:.3f}")
    p(f"  missed equivalence (opposite error): {R['missed_equivalence']['rate']:.4f} "
      f"-> {R['missed_equivalence']['into']}")
    p("\nBY TIER  (same-node = identical law re-rendered)")
    for k, d in R["by_tier"].items():
        p(f"  {k:12s} n={d['n']:<6d} acc={d['accuracy']:.4f}")
    p("\nBY NOVELTY")
    for k, d in R["by_novelty"].items():
        p(f"  {k:14s} n={d['n']:<6d} acc={d['accuracy']:.4f}")
    c = R["calibration"]
    p(f"\nCALIBRATION")
    p(f"  mean confidence when correct {c['mean_conf_correct']:.3f} / when wrong "
      f"{c['mean_conf_wrong']:.3f}")
    p(f"  wrong answers held above 0.9 confidence: {c['wrong_above_0.9_conf']:.3f}")
    s = R["symmetry"]
    p(f"\nSYMMETRY  label(A,B) vs label(B,A)")
    p(f"  self-consistent {s['consistent_rate']:.4f}   swapped-direction accuracy "
      f"{s['swapped_accuracy']:.4f}")
    if "best_of_n" in R:
        b = R["best_of_n"]
        p(f"\nBEST-OF-{b['n_candidates']} RANKING   ({b['anchors']} novel anchors)")
        p(f"  faithful candidate ranked #1 : {b['faithful_ranked_top1']:.4f}")
        p(f"  EXPLOITATION RATE            : {b['exploitation_rate']:.4f}")
        p(f"  mean reciprocal rank         : {b['mrr']:.4f}")
        p(f"  mean margin (faithful - best drifted): {b['mean_margin']:+.4f}")
    p()


if __name__ == "__main__":
    main()
