"""Why does the control arm fail? Isolating the mechanism.

`etp_canonical` shows the model the law verbatim in the answer format and scores
49.6% — 12th of 18 (ANALYSIS.md §2). Three explanations are consistent with that:

  H1  the instruction "Recover the identity itself" implies a transformation;
  H2  the magma preamble frames this as a task, so the model performs one;
  H3  it is specific to being shown the answer in the answer's own notation.

This is a 2x2 over the first two, on two representations. `etp_canonical` is
where the effect lives; `latex` is the comparison arm — a genuine translation
task, where an anti-transformation instruction should do little. If H3 is what
matters, the manipulations move `etp_canonical` and leave `latex` alone.

    baseline      the prompt used in the main run
    no_transform  + an explicit "write exactly the identity shown, do not derive,
                    generalise or transform it"
    bare_frame    - the magma preamble paragraph
    both          both changes

    python3 probe_control.py --dry-run | --run | --report
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
sys.path.insert(0, str(HERE))
import run_experiment as RX          # noqa: E402
import grade as GR                   # noqa: E402

OUT = HERE / "control_probe"
REPS = ["etp_canonical", "latex"]
MODEL_IDS = ["mistralai/mistral-small-3.2-24b-instruct", "qwen/qwen3-30b-a3b-instruct-2507",
             "microsoft/phi-4", "meta-llama/llama-4-maverick", "x-ai/grok-4.20",
             "google/gemini-2.5-flash", "openai/gpt-5.2"]
CONDITIONS = ["baseline", "no_transform", "bare_frame", "both"]

PREAMBLE = ("The identity involves one binary operation and holds for all values of its\n"
            "variables. The operation is on an arbitrary set: it is not assumed to be\n"
            "associative or commutative, and there is no identity element.\n\n")
NO_TRANSFORM = ("- Write exactly the identity shown below. Do not derive a consequence of\n"
                "  it, do not generalise it, and do not transform it in any way.\n")


def variants(frame: str) -> dict[str, str]:
    """The four prompt frames."""
    assert PREAMBLE in frame, "frame.txt preamble moved"
    anchor = "- Output only the identity"
    with_rule = frame.replace(anchor, NO_TRANSFORM + anchor, 1)
    return {
        "baseline": frame,
        "no_transform": with_rule,
        "bare_frame": frame.replace(PREAMBLE, ""),
        "both": with_rule.replace(PREAMBLE, ""),
    }


def build(frame: str, note: str, body: str) -> str:
    text = frame.replace("{note}", note).replace("{body}", body)
    while "\n\n\n" in text:
        text = text.replace("\n\n\n", "\n\n")
    return text


def setup():
    frame = (HERE / "frame.txt").read_text(encoding="utf-8")
    notes = {r: (HERE / r / "note.txt").read_text(encoding="utf-8").strip() for r in REPS}
    _, _, cat = RX.load_inputs()
    nodes = json.loads((HERE / "sample.json").read_text())["repeat_nodes"]
    return variants(frame), notes, cat, nodes


def run() -> None:
    frames, notes, cat, nodes = setup()
    models = [m for m in RX.MODELS if m["id"] in MODEL_IDS]
    OUT.mkdir(exist_ok=True)
    client = RX.openrouter.make_client(RX.openrouter.load_api_key())
    tasks = [(rep, cond, n) for rep in REPS for cond in CONDITIONS for n in nodes]

    def run_model(model):
        path = OUT / f"{model['slug']}.jsonl"
        done = set()
        if path.exists():
            for line in path.read_text(encoding="utf-8").splitlines():
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if "rep" in row and "error" not in row:
                    done.add((row["rep"], row["condition"], row["node"]))
        todo = [t for t in tasks if t not in done]
        lock, counters = threading.Lock(), {"done": 0, "cost": 0.0, "error": 0}
        handle = path.open("a", encoding="utf-8")

        def one(task):
            rep, cond, node = task
            prompt = build(frames[cond], notes[rep], cat[rep][node])
            result = RX.send(client, model, prompt, 0)
            with lock:
                handle.write(json.dumps({"rep": rep, "condition": cond, "node": node,
                                         "model": model["id"], "tier": model["tier"],
                                         **result}, ensure_ascii=False) + "\n")
                handle.flush()
                counters["done"] += 1
                counters["cost"] += result.get("cost") or 0
                counters["error"] += "error" in result
                if counters["done"] % 400 == 0 or counters["done"] == len(todo):
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
    import numpy as np
    from analyze import holm, mcnemar_exact
    oracle = SemanticOracle()
    by = defaultdict(dict)
    rows = 0
    for path in sorted(OUT.glob("*.jsonl")):
        latest = {}
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            if "rep" not in r:
                continue
            key = (r["rep"], r["condition"], r["node"])
            if key not in latest or "error" in latest[key]:
                latest[key] = r
        for r in latest.values():
            rows += 1
            if "error" in r or r.get("filtered"):
                continue
            ident, _, _ = GR.extract(oracle, r.get("content", ""))
            outcome, _ = GR.outcome_for(oracle, r["node"], ident)
            by[(r["model"], r["rep"], r["condition"])][r["node"]] = int(outcome == "equivalent")

    print(f"{rows:,} rows\n")
    stats = {}
    for mid in MODEL_IDS:
        raw, keys = [], []
        for rep in REPS:
            base = by[(mid, rep, "baseline")]
            for cond in CONDITIONS[1:]:
                oth = by[(mid, rep, cond)]
                common = sorted(set(base) & set(oth))
                a = np.array([base[n] for n in common]); b = np.array([oth[n] for n in common])
                raw.append(mcnemar_exact(a, b)); keys.append((rep, cond))
        adj = holm([r[2] for r in raw])
        for (rep, cond), r, q in zip(keys, raw, adj):
            stats[f"{mid}|{rep}|{cond}"] = {"p_holm": q}
    star = lambda q: "***" if q < .001 else "**" if q < .01 else "*" if q < .05 else "ns"

    for rep in REPS:
        print(f"=== {rep} ===")
        print(f"{'model':24} " + " ".join(f"{c:>13}" for c in CONDITIONS))
        for mid in MODEL_IDS:
            cells = []
            for cond in CONDITIONS:
                d = by[(mid, rep, cond)]
                acc = sum(d.values()) / len(d) * 100 if d else float("nan")
                mark = "" if cond == "baseline" else star(stats[f"{mid}|{rep}|{cond}"]["p_holm"])
                cells.append(f"{acc:8.1f}%{mark:>4}")
            print(f"{mid.split('/')[-1]:24} " + " ".join(cells))
        print()
    figure(by)
    (OUT / "control_probe_summary.json").write_text(json.dumps(
        {"accuracy": {f"{m}|{r}|{c}": {"k": sum(by[(m, r, c)].values()), "n": len(by[(m, r, c)])}
                      for m in MODEL_IDS for r in REPS for c in CONDITIONS},
         "mcnemar": stats}, indent=2) + "\n")
    print(f"wrote {OUT/'control_probe_summary.json'}")


def figure(by) -> None:
    """Two panels: the control arm and a translation arm, under each condition."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np
    from analyze import GRID, INK, INK_2, SERIES, SURFACE
    plt.rcParams.update({"figure.facecolor": SURFACE, "axes.facecolor": SURFACE,
                         "savefig.facecolor": SURFACE, "font.size": 9, "text.color": INK,
                         "axes.labelcolor": INK, "xtick.color": INK_2,
                         "ytick.color": INK_2, "axes.edgecolor": GRID})
    colors = {"baseline": INK_2, "no_transform": SERIES[0],
              "bare_frame": SERIES[4], "both": SERIES[2]}
    labels = [m.split("/")[-1].replace("-instruct-2507", "").replace("-3.2-24b-instruct", "")
              for m in MODEL_IDS]
    fig, axes = plt.subplots(1, 2, figsize=(14, 4.6), sharey=True)
    for ax, rep in zip(axes, REPS):
        x = np.arange(len(MODEL_IDS))
        for i, cond in enumerate(CONDITIONS):
            vals = []
            for mid in MODEL_IDS:
                d = by[(mid, rep, cond)]
                vals.append(sum(d.values()) / len(d) * 100 if d else float("nan"))
            ax.bar(x + (i - 1.5) * 0.21, vals, 0.2, color=colors[cond],
                   label=cond if rep == REPS[0] else None)
            for xi, v in zip(x, vals):
                if not np.isnan(v):
                    ax.text(xi + (i - 1.5) * 0.21, v + 1.5, f"{v:.0f}", ha="center",
                            fontsize=6.2, color=INK)
        ax.set_title(f"{rep}" + ("  (control arm)" if rep == "etp_canonical"
                                 else "  (translation arm)"), fontweight="bold")
        ax.set_xticks(x, labels, rotation=32, ha="right", fontsize=7.5)
        ax.set_ylim(0, 112); ax.grid(axis="y", color=GRID, lw=0.6); ax.set_axisbelow(True)
    axes[0].set_ylabel("accuracy (% equivalent)")
    axes[0].legend(frameon=True, framealpha=0.95, edgecolor=GRID, fontsize=8,
                   loc="upper left", title="prompt condition")
    fig.suptitle("One anti-transformation instruction, 150 laws per bar",
                 fontweight="bold", y=1.02)
    fig.tight_layout()
    fig.savefig(HERE / "figures" / "12-control-probe.png", dpi=170, bbox_inches="tight")
    plt.close(fig)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--run", action="store_true"); ap.add_argument("--report", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    if a.dry_run:
        frames, notes, cat, nodes = setup()
        for c in CONDITIONS:
            print("=" * 70, f"\n{c.upper()}\n" + "=" * 70)
            print(build(frames[c], notes["etp_canonical"], cat["etp_canonical"][nodes[0]]))
        return
    if a.run:
        run()
    if a.report:
        report()
    if not (a.run or a.report):
        ap.error("give --run, --report or --dry-run")


if __name__ == "__main__":
    main()
