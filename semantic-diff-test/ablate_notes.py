"""Ablation: how much of the representation effect is carried by my notation note?

The headline claim in ANALYSIS.md is a minimal pair — `text2` (68.5%) against
`polish` (16.9%), the same prefix order with the English scaffolding removed.
The obvious objection is that the gap is an artifact of the notes I wrote, since
those are the one authored, per-representation part of the prompt. This measures
that directly.

Three conditions on the same laws, models and frame:

    none      the note is removed entirely
    current   the note used in the main run (27-39 tokens)
    generous  a deliberately helpful note: the reading rule spelled out, plus a
              worked micro-example

If the `text2`/`polish` gap survives `none`, the effect belongs to the notation.
If `generous` closes it, the difficulty is explicable rather than intrinsic —
which is a different and also useful finding.

Four representations (the minimal pair, the extreme case, and a high-band
symbolic control), four models spanning small to frontier, and the 150-equation
repeat-arm subset, which is already a proportional stratified sample.

    python3 ablate_notes.py --dry-run
    python3 ablate_notes.py --run
    python3 ablate_notes.py --report
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

import run_experiment as RX          # noqa: E402  transport, model configs, send()
import grade as GR                   # noqa: E402  extraction ladder + oracle bucketing

OUT = HERE / "ablation"
REPS = ["text2", "polish", "rpn", "latex"]
MODEL_IDS = ["qwen/qwen3-30b-a3b-instruct-2507", "google/gemini-2.5-flash",
             "openai/gpt-5.2", "anthropic/claude-opus-5"]
CONDITIONS = ["none", "current", "placebo", "generous"]

# Length-matched placebo. The generous notes are 76-101 tokens against 27-35 for
# the current ones, so "generous beats current" confounds content with length.
# The placebo pads the *current* note to the generous note's token count using
# sentences that are true, on-topic, and carry no information about how to read
# the notation. Nothing here is an instruction: the control probe (§8) showed
# that a single anti-transformation sentence is worth up to +73 points, so any
# imperative in the padding would contaminate the comparison.
PADDING = [
    "The operation combines exactly two arguments, and its result is again a value "
    "of the same kind.",
    "The same operation is used at every point in the expression.",
    "The identity is stated once, and it holds for every assignment of values to "
    "its variables.",
    "Nothing in the expression below is abbreviated or elided.",
    "The expression uses no convention beyond the one described above.",
    "This is one identity, not a system of several.",
    "The operation has no special cases, and the same reading applies throughout.",
]


def pad_to(note: str, target: int) -> str:
    """Extend `note` with inert sentences until it is `target` tokens long."""
    import tiktoken
    enc = tiktoken.get_encoding("cl100k_base")
    text = note
    for sentence in PADDING:
        if len(enc.encode(text)) >= target:
            break
        candidate = f"{text} {sentence}"
        # Stop at whichever of "before" and "after" is closer to the target, so
        # the padding never ends mid-clause; a visibly broken sentence would be
        # a manipulation of its own.
        if abs(len(enc.encode(candidate)) - target) > abs(len(enc.encode(text)) - target):
            break
        text = candidate
    return text

# Deliberately helpful notes: the reading rule stated explicitly plus one worked
# micro-example. Constant across all 150 laws, and free of digits so no prompt
# can leak an equation number.
GENEROUS = {
    "text2":
        "Each operation is the phrase 'the diamond of A and B', where A is the left "
        "argument and B the right. Variables are single lowercase letters. The phrases "
        "nest: in 'the diamond of x and the diamond of y and z', the left argument is x "
        "and the right argument is the whole inner phrase. Resolve the outermost phrase "
        "first, then each argument in turn.",
    "polish":
        "This is Polish, or prefix, notation. The leading '=' takes the two terms that "
        "follow it as the left and right sides. Each '◇' takes the two terms that follow "
        "it as its left and right arguments. Variables are single lowercase letters. For "
        "example, '= ◇ x y z' means (x ◇ y) = z, because the '=' takes '◇ x y' as its "
        "first term and 'z' as its second. Every symbol consumes exactly two following "
        "terms.",
    "rpn":
        "This is reverse Polish, or postfix, notation. Read left to right keeping a "
        "stack: a variable is pushed; a '◇' pops the two most recent values and pushes "
        "their combination, the earlier-pushed value being the left argument; the final "
        "'=' pops two values to form the two sides. Variables are single lowercase "
        "letters. For example, 'x y ◇ z =' means (x ◇ y) = z.",
    "latex":
        "This is LaTeX. The operation is written \\diamond between its two arguments, so "
        "'x \\diamond y' has x on the left and y on the right. Variables are single "
        "letters. Parentheses show grouping: 'x \\diamond (y \\diamond z)' has x on the "
        "left and the whole parenthesised expression on the right. Resolve the outermost "
        "operation first.",
}


def notes() -> dict[str, dict[str, str]]:
    """`{representation: {condition: note}}`."""
    import tiktoken
    enc = tiktoken.get_encoding("cl100k_base")
    table = {}
    for rep in REPS:
        current = (HERE / rep / "note.txt").read_text(encoding="utf-8").strip()
        table[rep] = {"none": "", "current": current,
                      "placebo": pad_to(current, len(enc.encode(GENEROUS[rep]))),
                      "generous": GENEROUS[rep]}
    return table


def build_prompt(frame: str, note: str, body: str) -> str:
    """Assemble one prompt, collapsing the gap left by an empty note."""
    text = frame.replace("{note}", note).replace("{body}", body)
    while "\n\n\n" in text:
        text = text.replace("\n\n\n", "\n\n")
    return text


def catalogues() -> dict[str, dict[int, str]]:
    _, _, cat = RX.load_inputs()
    return cat


def tasks() -> list[tuple]:
    sample = json.loads((HERE / "sample.json").read_text())
    nodes = sample["repeat_nodes"]
    return [(rep, cond, node) for rep in REPS for cond in CONDITIONS for node in nodes]


def path_for(model_slug: str) -> Path:
    return OUT / f"{model_slug}.jsonl"


def run() -> None:
    frame = (HERE / "frame.txt").read_text(encoding="utf-8")
    note_table, cat = notes(), catalogues()
    models = [m for m in RX.MODELS if m["id"] in MODEL_IDS]
    assert len(models) == len(MODEL_IDS), "a model id did not match run_experiment.MODELS"
    OUT.mkdir(exist_ok=True)
    client = RX.openrouter.make_client(RX.openrouter.load_api_key())
    all_tasks = tasks()

    def run_model(model: dict) -> dict:
        path = path_for(model["slug"])
        done = set()
        if path.exists():
            for line in path.read_text(encoding="utf-8").splitlines():
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if "rep" in row and "error" not in row:
                    done.add((row["rep"], row["condition"], row["node"]))
        todo = [t for t in all_tasks if t not in done]
        lock = threading.Lock()
        counters = {"done": 0, "cost": 0.0, "error": 0}
        handle = path.open("a", encoding="utf-8")

        def one(task):
            rep, cond, node = task
            prompt = build_prompt(frame, note_table[rep][cond], cat[rep][node])
            result = RX.send(client, model, prompt, 0)
            row = {"rep": rep, "condition": cond, "node": node, "model": model["id"],
                   "tier": model["tier"], **result}
            with lock:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
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
        return {"model": model["id"], "new": len(todo), "skipped": len(done), **counters}

    started = time.time()
    with ThreadPoolExecutor(max_workers=len(models)) as pool:
        summaries = list(pool.map(run_model, models))
    print(f"\n{'model':42} {'new':>7} {'skipped':>8} {'err':>5} {'cost':>8}")
    for s in summaries:
        print(f"{s['model']:42} {s['new']:7,} {s['skipped']:8,} {s['error']:5} ${s['cost']:7.3f}")
    print(f"total ${sum(s['cost'] for s in summaries):.2f} in {(time.time()-started)/60:.1f} min")


def report() -> None:
    """Grade the ablation rows and print the contrast that matters."""
    from oracle import SemanticOracle
    oracle = SemanticOracle()
    rows = []
    for path in sorted(OUT.glob("*.jsonl")):
        latest = {}
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if "rep" not in row:
                continue
            key = (row["rep"], row["condition"], row["node"])
            if key not in latest or "error" in latest[key]:
                latest[key] = row
        for row in latest.values():
            if "error" in row or row.get("filtered"):
                outcome = "error"
            else:
                identity, _, _ = GR.extract(oracle, row.get("content", ""))
                outcome, _ = GR.outcome_for(oracle, row["node"], identity)
            rows.append({**row, "outcome": outcome, "correct": outcome == "equivalent"})

    note_table = notes()
    acc = defaultdict(lambda: [0, 0])
    for r in rows:
        if r["outcome"] != "error":
            cell = acc[(r["model"], r["rep"], r["condition"])]
            cell[0] += r["correct"]; cell[1] += 1

    print(f"{len(rows):,} ablation rows\n")
    print("note length (tokens):")
    import tiktoken
    enc = tiktoken.get_encoding("cl100k_base")
    for rep in REPS:
        lens = {c: len(enc.encode(note_table[rep][c])) for c in CONDITIONS}
        print(f"  {rep:10} " + "  ".join(f"{c}={lens[c]:3}" for c in CONDITIONS))

    print(f"\naccuracy by model × representation × note condition (n=150 each)\n")
    print(f"{'model':24} {'rep':10} " + " ".join(f"{c:>9}" for c in CONDITIONS)
          + "   placebo−current  generous−placebo")
    for mid in MODEL_IDS:
        for rep in REPS:
            vals = []
            for c in CONDITIONS:
                k, n = acc[(mid, rep, c)]
                vals.append(k / n * 100 if n else float("nan"))
            print(f"{mid.split('/')[-1]:24} {rep:10} "
                  + " ".join(f"{v:8.1f}%" for v in vals)
                  + f"   {vals[2]-vals[1]:+13.1f} {vals[3]-vals[2]:+17.1f}")

    print("\nthe minimal pair, text2 − polish, under each note condition:")
    print(f"{'model':24} " + " ".join(f"{c:>12}" for c in CONDITIONS))
    for mid in MODEL_IDS:
        gaps = []
        for c in CONDITIONS:
            a = acc[(mid, "text2", c)]; b = acc[(mid, "polish", c)]
            gaps.append((a[0]/a[1] - b[0]/b[1]) * 100 if a[1] and b[1] else float("nan"))
        print(f"{mid.split('/')[-1]:24} " + " ".join(f"{g:+11.1f}" for g in gaps))

    # paired tests: the three conditions are shown the same 150 laws, so
    # McNemar is the right test and Holm bounds the family within each model.
    import numpy as np
    from analyze import holm, mcnemar_exact, wilson
    by_node = defaultdict(dict)
    for r in rows:
        if r["outcome"] != "error":
            by_node[(r["model"], r["rep"], r["condition"])][r["node"]] = int(r["correct"])
    stats = {}
    for mid in MODEL_IDS:
        raw, keys = [], []
        for rep in REPS:
            cur = by_node[(mid, rep, "current")]
            for other in ("none", "placebo", "generous"):
                oth = by_node[(mid, rep, other)]
                common = sorted(set(cur) & set(oth))
                a = np.array([cur[n] for n in common])
                b = np.array([oth[n] for n in common])
                raw.append(mcnemar_exact(a, b)); keys.append((rep, other))
        adjusted = holm([r[2] for r in raw])
        for (rep, other), r, adj in zip(keys, raw, adjusted):
            stats[f"{mid}|{rep}|{other}"] = {"b01": r[0], "b10": r[1],
                                             "p": r[2], "p_holm": adj}
    print("\npaired McNemar vs the current note (Holm-corrected within model):")
    for mid in MODEL_IDS:
        for rep in REPS:
            marks = []
            for other in ("none", "placebo", "generous"):
                q = stats[f"{mid}|{rep}|{other}"]["p_holm"]
                marks.append("***" if q < .001 else "**" if q < .01 else "*" if q < .05 else "ns")
            print(f"  {mid.split('/')[-1]:24} {rep:8} none {marks[0]:>3}   "
                  f"placebo {marks[1]:>3}   generous {marks[2]:>3}")
    figure(acc, stats)

    out = OUT / "ablation_summary.json"
    out.write_text(json.dumps({
        "n_rows": len(rows),
        "accuracy": {f"{m}|{r}|{c}": {"k": v[0], "n": v[1]}
                     for (m, r, c), v in acc.items()},
        "note_tokens": {rep: {c: len(enc.encode(note_table[rep][c])) for c in CONDITIONS}
                        for rep in REPS},
        "mcnemar": stats,
    }, indent=2) + "\n")
    print(f"\nwrote {out}")


def figure(acc, stats) -> None:
    """One panel per representation: accuracy under each note condition."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np
    from analyze import GRID, INK, INK_2, SERIES, SURFACE

    plt.rcParams.update({"figure.facecolor": SURFACE, "axes.facecolor": SURFACE,
                         "savefig.facecolor": SURFACE, "font.size": 9, "text.color": INK,
                         "axes.labelcolor": INK, "xtick.color": INK_2,
                         "ytick.color": INK_2, "axes.edgecolor": GRID})
    colors = {"none": INK_2, "current": SERIES[0], "placebo": SERIES[4],
              "generous": SERIES[2]}
    fig, axes = plt.subplots(1, len(REPS), figsize=(15, 4.4), sharey=True)
    labels = [m.split("/")[-1].replace("-instruct-2507", "") for m in MODEL_IDS]
    for ax, rep in zip(axes, REPS):
        x = np.arange(len(MODEL_IDS))
        for i, cond in enumerate(CONDITIONS):
            vals = []
            for mid in MODEL_IDS:
                k, n = acc[(mid, rep, cond)]
                vals.append(k / n * 100 if n else float("nan"))
            ax.bar(x + (i - 1.5) * 0.21, vals, 0.2, color=colors[cond],
                   label=cond if rep == REPS[0] else None)
            for xi, v in zip(x, vals):
                if not np.isnan(v):
                    ax.text(xi + (i - 1.5) * 0.21, v + 1.5, f"{v:.0f}", ha="center",
                            fontsize=6.0, color=INK)
        ax.set_title(rep, fontweight="bold")
        ax.set_xticks(x, labels, rotation=35, ha="right", fontsize=7.5)
        ax.set_ylim(0, 108)
        ax.grid(axis="y", color=GRID, lw=0.6)
        ax.set_axisbelow(True)
    axes[0].set_ylabel("accuracy (% equivalent)")
    axes[0].legend(frameon=True, framealpha=0.95, edgecolor=GRID, fontsize=8,
                   loc="lower left", title="notation note")
    fig.suptitle("Removing, padding, or expanding the notation note "
                 "(150 laws per bar; placebo is length-matched to generous)",
                 fontweight="bold", y=1.02)
    fig.tight_layout()
    fig.savefig(HERE / "figures" / "11-note-ablation.png", dpi=170, bbox_inches="tight")
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--report", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if args.dry_run:
        frame = (HERE / "frame.txt").read_text(encoding="utf-8")
        nt, cat = notes(), catalogues()
        node = json.loads((HERE / "sample.json").read_text())["repeat_nodes"][0]
        for cond in CONDITIONS:
            print("=" * 70, f"\n{cond.upper()}  —  polish, Equation {node}\n" + "=" * 70)
            print(build_prompt(frame, nt["polish"][cond], cat["polish"][node]))
        print(f"\n{len(tasks())} tasks per model × {len(MODEL_IDS)} models = "
              f"{len(tasks())*len(MODEL_IDS):,} calls")
        return
    if args.run:
        run()
    if args.report:
        report()
    if not (args.run or args.report):
        parser.error("give --run, --report or --dry-run")


if __name__ == "__main__":
    main()
