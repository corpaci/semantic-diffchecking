"""Dose-response: does variable-merging rise with visual confusability?

ANALYSIS.md §3 reports that on `confusable_vars`, 93.7% of `weaker` answers use
fewer distinct variables than the law shown — models collapse `l`, `I`, `ll` into
one variable, and merging universally-quantified variables yields a strictly
weaker law. That is one adversarial naming scheme. This turns it into a curve.

Six naming schemes, identical structure throughout — only the identifiers change:

    canonical   x y z w u v          the catalogue's own names
    alpha       a b c d e f          distinct, different letters
    indexed     v1 v2 v3 v4 v5 v6    distinct, multi-character, shared prefix
    confusable  l I ll lI Il II      the scheme used in the main run
    repeat      l ll lll llll ...    ASCII, differing only in length
    homoglyph   a а e е o о          Latin/Cyrillic pairs, differing only in codepoint

The prediction is that accuracy falls and the merge rate rises monotonically.
Note the oracle's parser rejects non-ASCII identifiers, so the `homoglyph`
rendering cannot be round-trip checked; it is correct by construction
(deterministic substitution on an already-verified syntax tree). Answers are
unaffected — the output contract asks for lowercase ASCII letters — but a model
that echoes the Cyrillic glyphs will score `unparseable`, which is itself a
result and is reported separately.

    python3 dose_confusable.py --dry-run | --run | --report
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(REPO / "translate"))
sys.path.insert(0, str(REPO / "translate" / "confusable_vars"))
import run_experiment as RX          # noqa: E402
import grade as GR                   # noqa: E402
from confusify import renderer       # noqa: E402  the same renderer the catalogue used

OUT = HERE / "dose_confusable"
MODEL_IDS = ["mistralai/mistral-small-3.2-24b-instruct", "qwen/qwen3-30b-a3b-instruct-2507",
             "meta-llama/llama-4-maverick", "google/gemini-2.5-flash",
             "openai/gpt-5.2", "anthropic/claude-opus-5"]
SCHEMES = {
    "canonical":  ("x", "y", "z", "w", "u", "v"),
    "alpha":      ("a", "b", "c", "d", "e", "f"),
    "indexed":    ("v1", "v2", "v3", "v4", "v5", "v6"),
    "confusable": ("l", "I", "ll", "lI", "Il", "II"),
    "repeat":     ("l", "ll", "lll", "llll", "lllll", "llllll"),
    "homoglyph":  ("a", "а", "e", "е", "o", "о"),
}
LEVELS = list(SCHEMES)


def setup():
    frame = (HERE / "frame.txt").read_text(encoding="utf-8")
    note = (HERE / "confusable_vars" / "note.txt").read_text(encoding="utf-8").strip()
    sample = json.loads((HERE / "sample.json").read_text())
    laws = {r["node"]: r for r in sample["equations"]}
    nodes = sample["repeat_nodes"]
    sys.path.insert(0, str(REPO / "oracle"))
    from normalizer import parse_equation
    bodies = {level: {n: renderer(SCHEMES[level])(parse_equation(laws[n]["formal"]))
                      for n in nodes} for level in LEVELS}
    return frame, note, bodies, nodes, laws


def build(frame, note, body):
    text = frame.replace("{note}", note).replace("{body}", body)
    while "\n\n\n" in text:
        text = text.replace("\n\n\n", "\n\n")
    return text


def run() -> None:
    frame, note, bodies, nodes, _ = setup()
    models = [m for m in RX.MODELS if m["id"] in MODEL_IDS]
    OUT.mkdir(exist_ok=True)
    client = RX.openrouter.make_client(RX.openrouter.load_api_key())
    tasks = [(lvl, n) for lvl in LEVELS for n in nodes]

    def run_model(model):
        path = OUT / f"{model['slug']}.jsonl"
        done = set()
        if path.exists():
            for line in path.read_text(encoding="utf-8").splitlines():
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if "level" in row and "error" not in row:
                    done.add((row["level"], row["node"]))
        todo = [t for t in tasks if t not in done]
        lock, counters = threading.Lock(), {"done": 0, "cost": 0.0, "error": 0}
        handle = path.open("a", encoding="utf-8")

        def one(task):
            level, node = task
            result = RX.send(client, model, build(frame, note, bodies[level][node]), 0)
            with lock:
                handle.write(json.dumps({"level": level, "node": node, "model": model["id"],
                                         "tier": model["tier"], **result},
                                        ensure_ascii=False) + "\n")
                handle.flush()
                counters["done"] += 1
                counters["cost"] += result.get("cost") or 0
                counters["error"] += "error" in result
                if counters["done"] % 300 == 0 or counters["done"] == len(todo):
                    print(f"[{model['slug']:22}] {counters['done']:5,}/{len(todo):,} "
                          f"${counters['cost']:.2f} err={counters['error']}", flush=True)

        if todo:
            with ThreadPoolExecutor(max_workers=model["conc"]) as pool:
                list(pool.map(one, todo))
        handle.close()
        return {"model": model["id"], "new": len(todo), **counters}

    started = time.time()
    with ThreadPoolExecutor(max_workers=len(models)) as pool:
        out = list(pool.map(run_model, models))
    for s in out:
        print(f"{s['model']:42} {s['new']:6,} err={s['error']} ${s['cost']:.3f}")
    print(f"total ${sum(s['cost'] for s in out):.2f} in {(time.time()-started)/60:.1f} min")


def report() -> None:
    from oracle import SemanticOracle
    from normalizer import parse_equation
    oracle = SemanticOracle()
    _, _, _, _, laws = setup()

    def distinct(text):
        eq = parse_equation(text); names = []
        eq.lhs.variables(names); eq.rhs.variables(names)
        return len(names)

    acc = defaultdict(lambda: [0, 0])
    merge = defaultdict(lambda: [0, 0])
    outcomes = defaultdict(lambda: defaultdict(int))
    for path in sorted(OUT.glob("*.jsonl")):
        latest = {}
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            if "level" not in r:
                continue
            key = (r["level"], r["node"])
            if key not in latest or "error" in latest[key]:
                latest[key] = r
        for r in latest.values():
            mid, lvl = r["model"], r["level"]
            if "error" in r or r.get("filtered"):
                outcomes[(mid, lvl)]["error"] += 1
                continue
            ident, _, _ = GR.extract(oracle, r.get("content", ""))
            outcome, _ = GR.outcome_for(oracle, r["node"], ident)
            outcomes[(mid, lvl)][outcome] += 1
            acc[(mid, lvl)][0] += outcome == "equivalent"
            acc[(mid, lvl)][1] += 1
            if outcome != "equivalent" and ident:
                try:
                    got = distinct(ident)
                except Exception:
                    continue
                merge[(mid, lvl)][0] += got < laws[r["node"]]["variables"]
                merge[(mid, lvl)][1] += 1

    print("accuracy by naming scheme (150 laws each)\n")
    print(f"{'model':24} " + " ".join(f"{l:>11}" for l in LEVELS))
    for mid in MODEL_IDS:
        cells = [acc[(mid, l)] for l in LEVELS]
        print(f"{mid.split('/')[-1]:24} " + " ".join(
            f"{(c[0]/c[1]*100 if c[1] else float('nan')):10.1f}%" for c in cells))

    print("\nshare of wrong answers that MERGE variables (fewer distinct than shown)\n")
    print(f"{'model':24} " + " ".join(f"{l:>11}" for l in LEVELS))
    for mid in MODEL_IDS:
        cells = [merge[(mid, l)] for l in LEVELS]
        print(f"{mid.split('/')[-1]:24} " + " ".join(
            f"{(c[0]/c[1]*100 if c[1] else float('nan')):10.1f}%" for c in cells))

    print(f"\npooled over models: {'level':12} {'accuracy':>10} {'merge rate':>12} "
          f"{'unparseable':>12}")
    pooled = {}
    for lvl in LEVELS:
        a = [sum(acc[(m, lvl)][0] for m in MODEL_IDS), sum(acc[(m, lvl)][1] for m in MODEL_IDS)]
        g = [sum(merge[(m, lvl)][0] for m in MODEL_IDS), sum(merge[(m, lvl)][1] for m in MODEL_IDS)]
        u = sum(outcomes[(m, lvl)]["unparseable"] for m in MODEL_IDS)
        tot = sum(sum(outcomes[(m, lvl)].values()) for m in MODEL_IDS)
        pooled[lvl] = {"acc": a, "merge": g, "unparseable": u, "n": tot}
        print(f"{'':20} {lvl:12} {a[0]/a[1]*100:9.1f}% "
              f"{(g[0]/g[1]*100 if g[1] else float('nan')):11.1f}% {u/tot*100:11.1f}%")

    figure(acc, merge, pooled)
    (OUT / "dose_summary.json").write_text(json.dumps(
        {"levels": LEVELS, "schemes": {k: list(v) for k, v in SCHEMES.items()},
         "pooled": pooled,
         "accuracy": {f"{m}|{l}": {"k": acc[(m, l)][0], "n": acc[(m, l)][1]}
                      for m in MODEL_IDS for l in LEVELS},
         "merge": {f"{m}|{l}": {"k": merge[(m, l)][0], "n": merge[(m, l)][1]}
                   for m in MODEL_IDS for l in LEVELS}}, indent=2) + "\n")
    print(f"\nwrote {OUT/'dose_summary.json'}")


def figure(acc, merge, pooled) -> None:
    """Accuracy falling and merge rate rising across the confusability gradient."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np
    from analyze import GRID, INK, INK_2, SERIES, SURFACE
    plt.rcParams.update({"figure.facecolor": SURFACE, "axes.facecolor": SURFACE,
                         "savefig.facecolor": SURFACE, "font.size": 9, "text.color": INK,
                         "axes.labelcolor": INK, "xtick.color": INK_2,
                         "ytick.color": INK_2, "axes.edgecolor": GRID})
    x = np.arange(len(LEVELS))
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13.5, 4.8))
    for i, mid in enumerate(MODEL_IDS):
        vals = [(acc[(mid, l)][0] / acc[(mid, l)][1] * 100) if acc[(mid, l)][1] else np.nan
                for l in LEVELS]
        ax1.plot(x, vals, "o-", ms=4, lw=1.3, alpha=0.65,
                 color=(SERIES + ["#c2185b"])[i], label=mid.split("/")[-1][:18])
    ax1.plot(x, [pooled[l]["acc"][0] / pooled[l]["acc"][1] * 100 for l in LEVELS],
             "o-", ms=7, lw=2.8, color=INK, label="pooled", zorder=5)
    ax1.set_ylabel("accuracy (% equivalent)")
    ax1.set_title("Accuracy falls as identifiers become confusable", fontweight="bold")
    ax1.legend(frameon=False, fontsize=7, ncol=2)

    merged = [pooled[l]["merge"][0] / pooled[l]["merge"][1] * 100 for l in LEVELS]
    ax2.plot(x, merged, "o-", ms=7, lw=2.8, color=SERIES[1])
    for xi, v in zip(x, merged):
        ax2.text(xi, v + 2.5, f"{v:.0f}%", ha="center", fontsize=8, color=INK)
    ax2.set_ylabel("share of wrong answers that merge variables", color=SERIES[1])
    ax2.set_ylim(0, 112)
    ax2.set_title("...and the errors become variable merges", fontweight="bold")
    for ax in (ax1, ax2):
        ax.set_xticks(x, LEVELS, rotation=25, ha="right")
        ax.grid(axis="y", color=GRID, lw=0.6); ax.set_axisbelow(True)
    fig.suptitle("Confusability dose-response: structure held constant, identifiers varied",
                 fontweight="bold", y=1.02)
    fig.tight_layout()
    fig.savefig(HERE / "figures" / "13-dose-response.png", dpi=170, bbox_inches="tight")
    plt.close(fig)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--run", action="store_true"); ap.add_argument("--report", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    if a.dry_run:
        frame, note, bodies, nodes, laws = setup()
        n = nodes[3]
        print(f"Equation {n}: {laws[n]['formal']}   ({laws[n]['variables']} distinct variables)\n")
        for lvl in LEVELS:
            print(f"  {lvl:12} {bodies[lvl][n]}")
        print(f"\n{len(LEVELS)*len(nodes)} tasks per model x {len(MODEL_IDS)} models = "
              f"{len(LEVELS)*len(nodes)*len(MODEL_IDS):,} calls")
        return
    if a.run:
        run()
    if a.report:
        report()
    if not (a.run or a.report):
        ap.error("give --run, --report or --dry-run")


if __name__ == "__main__":
    main()
