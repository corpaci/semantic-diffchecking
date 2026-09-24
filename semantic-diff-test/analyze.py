"""Score the graded rows into tables and figures.

Implements the analysis pre-specified in `PLAN.md` §10, fixed before the data
existed so the headline numbers were not chosen after seeing them.

    python3 analyze.py                 # -> results/{tables.md,summary.json}, figures/
"""

from __future__ import annotations

import json
import math
import sys
from collections import Counter, defaultdict
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from scipy import stats as sps

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(REPO / "oracle"))
FIG = HERE / "figures"
RES = HERE / "results"

# Validated categorical palette: all-pairs contrast checked, CVD-safe.
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#9b59b6", "#d4a017"]
SURFACE, INK, INK_2, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#dedcd6"
TIER_COLOR = {"small": SERIES[0], "medium": SERIES[1], "frontier": SERIES[2]}
# Open weights confirmed from OpenRouter's `hugging_face_id` field, which is
# populated for these and absent for the rest.
OPEN_WEIGHTS = {"mistralai/mistral-small-3.2-24b-instruct",
                "qwen/qwen3-30b-a3b-instruct-2507", "microsoft/phi-4",
                "meta-llama/llama-4-maverick", "deepseek/deepseek-v3.2"}
OUTCOMES = ["equivalent", "weaker", "stronger", "incomparable", "unknown",
            "off_catalogue", "unparseable", "content_filter", "error"]
# Reporting buckets for the loss table: everything that is not a graded verdict.
LOSS = {"off_catalogue", "unparseable", "content_filter", "error"}
# Denominator rule, corrected from PLAN.md §8. The plan excluded off_catalogue
# and unparseable from accuracy denominators; that was a mistake. Both are
# answers the model produced — a well-formed identity of order > 4, or text no
# identity could be read out of — so they are wrong, not missing, and excluding
# them would reward a model for failing loudly. Only calls that never returned a
# usable response are genuinely missing. The plan's rule also turns out to be
# unusable as written: at ~29% ungradeable, requiring all 162 cells gradeable
# leaves a common subset of zero equations.
MISSING = {"content_filter", "error"}
CONTROL = "etp_canonical"

plt.rcParams.update({
    "figure.facecolor": SURFACE, "axes.facecolor": SURFACE,
    "savefig.facecolor": SURFACE, "font.size": 9, "text.color": INK,
    "axes.labelcolor": INK, "xtick.color": INK_2, "ytick.color": INK_2,
    "axes.edgecolor": GRID, "grid.color": GRID, "axes.grid": False,
})


# -- statistics ---------------------------------------------------------------

def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float, float]:
    """Wilson score interval. NaN for n=0 so an unmeasured cell never plots as 0."""
    if n == 0:
        return (float("nan"),) * 3
    p = k / n
    d = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / d
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return p, max(0.0, centre - half), min(1.0, centre + half)


def cochran_q(table: np.ndarray) -> tuple[float, int, float]:
    """Cochran's Q over k matched binary conditions (rows = items)."""
    if table.ndim != 2:
        return float("nan"), 0, float("nan")
    n, k = table.shape
    if n == 0 or k < 2:
        return float("nan"), 0, float("nan")
    col, row = table.sum(0).astype(float), table.sum(1).astype(float)
    denominator = (k * row - row ** 2).sum()
    if denominator == 0:
        return 0.0, k - 1, 1.0
    q = (k - 1) * (k * (col ** 2).sum() - col.sum() ** 2) / denominator
    return q, k - 1, float(sps.chi2.sf(q, k - 1))


def mcnemar_exact(a: np.ndarray, b: np.ndarray) -> tuple[int, int, float]:
    """Exact McNemar on paired binary vectors; returns (b01, b10, p)."""
    b01 = int(((a == 0) & (b == 1)).sum())
    b10 = int(((a == 1) & (b == 0)).sum())
    if b01 + b10 == 0:
        return b01, b10, 1.0
    return b01, b10, float(sps.binomtest(b01, b01 + b10, 0.5).pvalue)


def holm(pvalues: list[float]) -> list[float]:
    """Holm-Bonferroni adjusted p-values, preserving input order."""
    order = sorted(range(len(pvalues)), key=lambda i: pvalues[i])
    adjusted = [0.0] * len(pvalues)
    running = 0.0
    for rank, index in enumerate(order):
        running = max(running, (len(pvalues) - rank) * pvalues[index])
        adjusted[index] = min(1.0, running)
    return adjusted


def equivalence_classes() -> dict[int, int]:
    """How many catalogue laws are provably equivalent to each node.

    A law like `x = y ◇ (…)`, with the left variable absent on the right, forces
    a one-element magma — and every other law that does the same is equivalent to
    it. On such items a wrong-looking answer is still graded `equivalent`, which
    is real but makes them easier. Recording the class size keeps that visible
    instead of letting it inflate the headline silently.
    """
    from build_matrix import MATRIX_BIN, STATUS_NAMES
    proof_true = STATUS_NAMES.index("proof_true")
    raw = np.fromfile(MATRIX_BIN, dtype=np.uint8)
    n = int(round(math.sqrt(raw.size)))
    matrix = raw.reshape(n, n)
    implies = matrix == proof_true
    both = implies & implies.T
    np.fill_diagonal(both, True)
    return {i + 1: int(both[i].sum()) for i in range(n)}


# -- loading ------------------------------------------------------------------

def load() -> tuple[list[dict], dict]:
    rows = json.loads((RES / "graded.json").read_text())
    sample = json.loads((HERE / "sample.json").read_text())
    sizes = equivalence_classes()
    for row in rows:
        row["eq_class"] = sizes.get(row["node"], 1)
    return rows, sample


def slug(model: str) -> str:
    return model.split("/")[-1]


# -- tables -------------------------------------------------------------------

def build(rows: list[dict], sample: dict) -> dict:
    """Every number the write-up quotes, computed once."""
    main = [r for r in rows if r["k"] == 0]
    models = sorted({r["model"] for r in main}, key=lambda m: (
        {"small": 0, "medium": 1, "frontier": 2}[
            next(r["tier"] for r in main if r["model"] == m)], m))
    reps = sorted({r["rep"] for r in main})
    tiers = {m: next(r["tier"] for r in main if r["model"] == m) for m in models}
    weights = {k: v["weight"] for k, v in sample["meta"]["strata"].items()}

    by_cell = defaultdict(dict)                 # (model, rep) -> {node: row}
    for r in main:
        by_cell[(r["model"], r["rep"])][r["node"]] = r

    nodes = sorted({r["node"] for r in main})
    common = [n for n in nodes
              if all(by_cell[(m, p)].get(n) and
                     by_cell[(m, p)][n]["outcome"] not in MISSING
                     for m in models for p in reps)]

    def acc(cell: dict, subset=None) -> tuple[int, int]:
        keys = subset if subset is not None else list(cell)
        used = [cell[n] for n in keys if n in cell]
        answered = [r for r in used if r["outcome"] not in MISSING]
        return sum(r["correct"] for r in answered), len(answered)

    summary = {
        "counts": {"rows": len(rows), "main": len(main),
                   "repeat": len(rows) - len(main), "models": len(models),
                   "reps": len(reps), "equations": len(nodes),
                   "common_subset": len(common)},
        "models": models, "reps": reps, "tiers": tiers,
        "cost_usd": round(sum(r.get("cost") or 0 for r in rows), 4),
    }

    # --- primary: accuracy per (model, rep), all gradeable and common subset
    grid, grid_common = {}, {}
    for m in models:
        for p in reps:
            k, n = acc(by_cell[(m, p)])
            grid[f"{m}|{p}"] = {"k": k, "n": n, "p": wilson(k, n)[0]}
            kc, nc = acc(by_cell[(m, p)], common)
            grid_common[f"{m}|{p}"] = {"k": kc, "n": nc, "p": wilson(kc, nc)[0]}
    summary["grid"], summary["grid_common"] = grid, grid_common

    # --- Cochran's Q per model over the 18 representations (common subset)
    cochran = {}
    for m in models:
        table = np.array([[int(by_cell[(m, p)][n]["correct"]) for p in reps]
                          for n in common], dtype=int)
        q, df, pv = cochran_q(table)
        cochran[m] = {"Q": q, "df": df, "p": pv}
    summary["cochran"] = cochran

    # --- McNemar: each representation against the control, Holm within model
    mcnemar = {}
    for m in models:
        base = np.array([int(by_cell[(m, CONTROL)][n]["correct"]) for n in common])
        others = [p for p in reps if p != CONTROL]
        raw = []
        for p in others:
            vec = np.array([int(by_cell[(m, p)][n]["correct"]) for n in common])
            raw.append(mcnemar_exact(base, vec))
        adjusted = holm([r[2] for r in raw])
        mcnemar[m] = {p: {"b01": r[0], "b10": r[1], "p": r[2], "p_holm": a}
                      for p, r, a in zip(others, raw, adjusted)}
    summary["mcnemar"] = mcnemar

    # --- pooled by representation, and post-stratified to the catalogue
    pooled, post = {}, {}
    for p in reps:
        used = [r for r in main if r["rep"] == p and r["outcome"] not in MISSING]
        pooled[p] = {"k": sum(r["correct"] for r in used), "n": len(used),
                     "ci": wilson(sum(r["correct"] for r in used), len(used))}
        num = den = 0.0
        for stratum, weight in weights.items():
            sub = [r for r in used if r["stratum"] == stratum]
            if sub:
                num += weight * sum(r["correct"] for r in sub)
                den += weight * len(sub)
        post[p] = num / den if den else float("nan")
    summary["pooled"], summary["post_stratified"] = pooled, post

    # --- verdict composition and loss
    summary["outcomes"] = {p: dict(Counter(r["outcome"] for r in main if r["rep"] == p))
                           for p in reps}
    summary["loss"] = {p: {"n": sum(1 for r in main if r["rep"] == p),
                           "lost": sum(1 for r in main if r["rep"] == p
                                       and r["outcome"] in LOSS),
                           "missing": sum(1 for r in main if r["rep"] == p
                                          and r["outcome"] in MISSING)} for p in reps}

    # --- difficulty, strictness, chattiness
    summary["by_stratum"] = {
        p: {s: (lambda u: {"k": sum(r["correct"] for r in u), "n": len(u)})(
               [r for r in main if r["rep"] == p and r["stratum"] == s
                and r["outcome"] not in MISSING])
            for s in ("low", "3", "4")} for p in reps}
    summary["by_eqclass"] = {}
    for label, lo, hi in (("1 (unique)", 1, 1), ("2-9", 2, 9), ("10+", 10, 10 ** 9)):
        used = [r for r in main if r["outcome"] not in MISSING and lo <= r["eq_class"] <= hi]
        summary["by_eqclass"][label] = {"k": sum(r["correct"] for r in used), "n": len(used)}
    summary["strict"] = {m: {"lenient": acc({r["node"]: r for r in main if r["model"] == m})[0],
                             "n": sum(1 for r in main if r["model"] == m
                                      and r["outcome"] not in MISSING)} for m in models}
    summary["strict_gap"] = {
        m: {"lenient": sum(r["correct"] for r in main if r["model"] == m),
            "strict": sum(r["correct"] and r["strict"] for r in main if r["model"] == m),
            "n": sum(1 for r in main if r["model"] == m)} for m in models}
    summary["visible_cot"] = {
        p: {"rate": (lambda u: sum(r["visible_cot"] for r in u) / len(u) if u else float("nan"))(
                [r for r in main if r["rep"] == p]),
            "tokens": (lambda u: float(np.median([r["completion_tokens"] or 0 for r in u]))
                       if u else float("nan"))([r for r in main if r["rep"] == p])}
        for p in reps}

    # --- repeat arm: how often the three samples agree
    rep_rows = [r for r in rows if r["node"] in set(sample["repeat_nodes"])]
    triples = defaultdict(dict)
    for r in rep_rows:
        triples[(r["model"], r["rep"], r["node"])][r["k"]] = r
    consistency = defaultdict(lambda: [0, 0])
    for (m, p, n), ks in triples.items():
        if len(ks) == 3:
            verdicts = {ks[i]["outcome"] for i in (0, 1, 2)}
            consistency[p][1] += 1
            consistency[p][0] += len(verdicts) == 1
    summary["repeat"] = {p: {"same": v[0], "n": v[1]} for p, v in consistency.items()}

    # --- resampling noise floor, and whether the ranking's gaps clear it.
    # The repeat arm is the only thing that can answer "would this ordering
    # survive a re-run?", and for most adjacent pairs the answer is no.
    acc_k = defaultdict(lambda: [0, 0])
    for r in rep_rows:
        if r["outcome"] not in MISSING:
            cell = acc_k[(r["model"], r["rep"], r["k"])]
            cell[0] += r["correct"]; cell[1] += 1
    spreads = []
    for m in models:
        for p in reps:
            vals = [acc_k[(m, p, k)][0] / acc_k[(m, p, k)][1] for k in (0, 1, 2)
                    if acc_k.get((m, p, k)) and acc_k[(m, p, k)][1]]
            if len(vals) == 3:
                spreads.append(max(vals) - min(vals))
    ordered = sorted(reps, key=lambda p: -pooled[p]["ci"][0])
    gaps = [{"above": a, "below": b,
             "gap": pooled[a]["ci"][0] - pooled[b]["ci"][0]}
            for a, b in zip(ordered, ordered[1:])]
    noise_median = float(np.median(spreads)) if spreads else float("nan")
    summary["noise"] = {
        "cells": len(spreads),
        "median": noise_median, "mean": float(np.mean(spreads)) if spreads else float("nan"),
        "p90": float(np.percentile(spreads, 90)) if spreads else float("nan"),
        "max": float(max(spreads)) if spreads else float("nan"),
        "adjacent_gaps": gaps,
        "gaps_below_noise": sum(1 for g in gaps if g["gap"] < noise_median),
        "total_span": pooled[ordered[0]]["ci"][0] - pooled[ordered[-1]]["ci"][0],
    }

    # --- difficulty covariates the plan named but the first pass omitted
    for field, key in (("depth", "by_depth"), ("variables", "by_variables")):
        buckets = defaultdict(lambda: [0, 0])
        for r in main:
            if r["outcome"] not in MISSING:
                cell = buckets[r[field]]
                cell[0] += r["correct"]; cell[1] += 1
        summary[key] = {str(k): {"k": v[0], "n": v[1]} for k, v in sorted(buckets.items())}

    # --- open- vs closed-weight, pre-registered as exploratory
    weights = defaultdict(lambda: [0, 0])
    for r in main:
        if r["outcome"] not in MISSING:
            cell = weights["open" if r["model"] in OPEN_WEIGHTS else "closed"]
            cell[0] += r["correct"]; cell[1] += 1
    summary["by_weights"] = {k: {"k": v[0], "n": v[1]} for k, v in weights.items()}

    summary["regression"] = fit_regression(main)
    return summary


def fit_regression(main: list[dict]) -> dict:
    """Logistic regression of correctness on representation, order and tier.

    Standard errors are clustered by equation: the 18 representations are shown
    the same 500 laws, so the rows are not independent and naive errors would be
    far too small. Coefficients are log-odds against `etp_canonical` (the
    control) and the small tier.
    """
    try:
        import pandas as pd
        import statsmodels.api as sm
    except ImportError:
        return {"fitted": False, "reason": "statsmodels/pandas not installed"}

    frame = pd.DataFrame([{"correct": int(r["correct"]), "rep": r["rep"],
                           "order": r["order"], "tier": r["tier"], "node": r["node"]}
                          for r in main if r["outcome"] not in MISSING])
    design = pd.get_dummies(frame[["rep", "tier"]], drop_first=False, dtype=float)
    design = design.drop(columns=[f"rep_{CONTROL}", "tier_small"])
    design["order"] = frame["order"].astype(float)
    design = sm.add_constant(design)
    model = sm.GLM(frame["correct"], design, family=sm.families.Binomial())
    fit = model.fit(cov_type="cluster", cov_kwds={"groups": frame["node"]})
    return {
        "fitted": True, "n": int(len(frame)), "clusters": int(frame["node"].nunique()),
        "coefficients": {name: {"beta": float(fit.params[name]),
                                "se": float(fit.bse[name]),
                                "p": float(fit.pvalues[name])}
                         for name in design.columns},
    }


# -- figures ------------------------------------------------------------------

def pct(x) -> str:
    return "—" if x is None or (isinstance(x, float) and math.isnan(x)) else f"{x*100:.1f}%"


def fig_heatmap(s: dict) -> None:
    models, reps = s["models"], s["reps"]
    order = sorted(reps, key=lambda p: -s["pooled"][p]["ci"][0])
    data = np.array([[s["grid"][f"{m}|{p}"]["p"] for p in order] for m in models], float)
    fig, ax = plt.subplots(figsize=(13, 5.4))
    im = ax.imshow(data, cmap="YlGnBu", vmin=0, vmax=max(0.05, np.nanmax(data)), aspect="auto")
    ax.set_xticks(range(len(order)), order, rotation=45, ha="right")
    ax.set_yticks(range(len(models)), [slug(m) for m in models])
    for i in range(len(models)):
        for j in range(len(order)):
            v = data[i, j]
            if not math.isnan(v):
                ax.text(j, i, f"{v*100:.0f}", ha="center", va="center", fontsize=7.5,
                        color="white" if v > np.nanmax(data) * 0.55 else INK)
    for tick, m in zip(ax.get_yticklabels(), models):
        tick.set_color(TIER_COLOR[s["tiers"][m]])
    ax.set_title("Reconstruction accuracy (% equivalent), model × representation",
                 fontweight="bold", pad=12)
    fig.colorbar(im, ax=ax, shrink=0.8, label="accuracy")
    fig.text(0.5, -0.03, "columns ordered by pooled accuracy; label colour = tier",
             ha="center", fontsize=8, color=INK_2)
    fig.tight_layout(); fig.savefig(FIG / "01-heatmap.png", dpi=170, bbox_inches="tight")
    plt.close(fig)


def fig_ranking(s: dict) -> None:
    reps = sorted(s["reps"], key=lambda p: s["pooled"][p]["ci"][0])
    p = [s["pooled"][r]["ci"][0] for r in reps]
    lo = [s["pooled"][r]["ci"][0] - s["pooled"][r]["ci"][1] for r in reps]
    hi = [s["pooled"][r]["ci"][2] - s["pooled"][r]["ci"][0] for r in reps]
    fig, ax = plt.subplots(figsize=(8.5, 6.4))
    colors = [SERIES[2] if r == CONTROL else SERIES[0] for r in reps]
    ax.barh(reps, p, xerr=[lo, hi], color=colors, height=0.68,
            error_kw={"ecolor": INK_2, "lw": 1, "capsize": 2.5})
    for i, r in enumerate(reps):
        ax.text(p[i] + hi[i] + 0.012, i, f"{p[i]*100:.1f}%", va="center", fontsize=8, color=INK)
    ax.set_xlim(0, min(1.0, max(p) + max(hi) + 0.09))
    ax.set_xlabel("accuracy pooled over all 9 models (Wilson 95% CI)")
    ax.set_title("Which representation survives the round trip?", fontweight="bold")
    ax.text(0.99, 0.02, "green = ETP control arm", transform=ax.transAxes,
            ha="right", fontsize=8, color=SERIES[2])
    fig.tight_layout(); fig.savefig(FIG / "02-ranking.png", dpi=170); plt.close(fig)


def fig_delta(s: dict) -> None:
    reps = [p for p in sorted(s["reps"], key=lambda p: s["pooled"][p]["ci"][0]) if p != CONTROL]
    fig, ax = plt.subplots(figsize=(10, 5.6))
    width = 0.8 / len(s["models"])
    for i, m in enumerate(s["models"]):
        base = s["grid"][f"{m}|{CONTROL}"]["p"]
        d = [s["grid"][f"{m}|{p}"]["p"] - base for p in reps]
        ax.bar(np.arange(len(reps)) + i * width - 0.4, d, width,
               color=TIER_COLOR[s["tiers"][m]], alpha=0.85,
               label=slug(m) if i % 3 == 0 else None)
    ax.axhline(0, color=INK, lw=1)
    ax.set_xticks(range(len(reps)), reps, rotation=45, ha="right")
    ax.set_ylabel("accuracy − control accuracy")
    ax.set_title("Cost of the notation, relative to being handed the equation",
                 fontweight="bold")
    handles = [plt.Rectangle((0, 0), 1, 1, color=c) for c in TIER_COLOR.values()]
    ax.legend(handles, TIER_COLOR.keys(), frameon=False, ncol=3, loc="lower left")
    fig.tight_layout(); fig.savefig(FIG / "03-delta-from-control.png", dpi=170); plt.close(fig)


def fig_outcomes(s: dict) -> None:
    reps = sorted(s["reps"], key=lambda p: -s["pooled"][p]["ci"][0])
    shown = ["equivalent", "weaker", "stronger", "incomparable", "unknown",
             "off_catalogue", "unparseable"]
    colors = [SERIES[2], SERIES[0], SERIES[3], SERIES[1], GRID, SERIES[4], INK_2]
    fig, ax = plt.subplots(figsize=(11, 5.4))
    bottom = np.zeros(len(reps))
    for outcome, color in zip(shown, colors):
        vals = np.array([s["outcomes"][p].get(outcome, 0) for p in reps], float)
        total = np.array([sum(s["outcomes"][p].values()) for p in reps], float)
        share = vals / total
        ax.bar(reps, share, bottom=bottom, color=color, label=outcome, width=0.72)
        bottom += share
    ax.set_xticks(range(len(reps)), reps, rotation=45, ha="right")
    ax.set_ylabel("share of responses")
    ax.set_ylim(0, 1)
    ax.set_title("Where the meaning goes when it is not preserved", fontweight="bold")
    ax.legend(frameon=False, ncol=4, fontsize=8, loc="upper center",
              bbox_to_anchor=(0.5, -0.28))
    fig.tight_layout(); fig.savefig(FIG / "04-outcomes.png", dpi=170, bbox_inches="tight")
    plt.close(fig)


def fig_difficulty(s: dict) -> None:
    reps = sorted(s["reps"], key=lambda p: -s["pooled"][p]["ci"][0])
    fig, ax = plt.subplots(figsize=(10.5, 5))
    labels = {"low": "order 1–2", "3": "order 3", "4": "order 4"}
    for i, (stratum, color) in enumerate(zip(("low", "3", "4"), SERIES)):
        y = []
        for p in reps:
            cell = s["by_stratum"][p][stratum]
            y.append(cell["k"] / cell["n"] if cell["n"] else float("nan"))
        ax.plot(range(len(reps)), y, "o-", color=color, ms=4, lw=1.6, label=labels[stratum])
    ax.set_xticks(range(len(reps)), reps, rotation=45, ha="right")
    ax.set_ylabel("accuracy")
    ax.set_title("Accuracy by law complexity", fontweight="bold")
    ax.legend(frameon=False, ncol=3)
    fig.tight_layout(); fig.savefig(FIG / "05-difficulty.png", dpi=170); plt.close(fig)


def fig_significance(s: dict) -> None:
    models, reps = s["models"], [p for p in s["reps"] if p != CONTROL]
    data = np.array([[-math.log10(max(s["mcnemar"][m][p]["p_holm"], 1e-12)) for p in reps]
                     for m in models])
    fig, ax = plt.subplots(figsize=(12, 4.6))
    im = ax.imshow(data, cmap="PuBu", aspect="auto", vmin=0, vmax=6)
    ax.set_xticks(range(len(reps)), reps, rotation=45, ha="right")
    ax.set_yticks(range(len(models)), [slug(m) for m in models])
    for i in range(len(models)):
        for j in range(len(reps)):
            mark = "***" if data[i, j] > 3 else "**" if data[i, j] > 2 else \
                   "*" if data[i, j] > 1.301 else ""
            if mark:
                ax.text(j, i, mark, ha="center", va="center", fontsize=8,
                        color="white" if data[i, j] > 3.5 else INK)
    ax.set_title("Does the notation change the verdict? McNemar vs the control, "
                 "Holm-corrected", fontweight="bold", pad=10)
    fig.colorbar(im, ax=ax, shrink=0.85, label="−log₁₀ adjusted p")
    fig.text(0.5, -0.06, "* p<0.05   ** p<0.01   *** p<0.001", ha="center",
             fontsize=8, color=INK_2)
    fig.tight_layout(); fig.savefig(FIG / "06-significance.png", dpi=170, bbox_inches="tight")
    plt.close(fig)


def fig_loss(s: dict) -> None:
    reps = sorted(s["reps"], key=lambda p: -s["loss"][p]["lost"] / max(s["loss"][p]["n"], 1))
    kinds = ["off_catalogue", "unparseable", "content_filter", "error"]
    colors = [SERIES[4], INK_2, SERIES[1], SERIES[3]]
    fig, ax = plt.subplots(figsize=(10.5, 4.8))
    bottom = np.zeros(len(reps))
    for kind, color in zip(kinds, colors):
        vals = np.array([s["outcomes"][p].get(kind, 0) / sum(s["outcomes"][p].values())
                         for p in reps])
        ax.bar(reps, vals, bottom=bottom, color=color, label=kind, width=0.72)
        bottom += vals
    for i, p in enumerate(reps):
        ax.text(i, bottom[i] + 0.006, f"{bottom[i]*100:.0f}%", ha="center",
                fontsize=7.5, color=INK)
    ax.set_xticks(range(len(reps)), reps, rotation=45, ha="right")
    ax.set_ylabel("share of responses")
    ax.set_title("Failure modes that are not a graded verdict "
                 "(off_catalogue and unparseable count as wrong, not missing)",
                 fontweight="bold", fontsize=10)
    ax.legend(frameon=False, ncol=4, fontsize=8)
    fig.tight_layout(); fig.savefig(FIG / "07-loss.png", dpi=170); plt.close(fig)


def fig_cot(s: dict) -> None:
    reps = sorted(s["reps"], key=lambda p: -s["visible_cot"][p]["rate"])
    rate = [s["visible_cot"][p]["rate"] for p in reps]
    toks = [s["visible_cot"][p]["tokens"] for p in reps]
    fig, ax = plt.subplots(figsize=(10.5, 4.8))
    ax.bar(reps, rate, color=SERIES[0], width=0.7, label="visible chain-of-thought rate")
    ax.set_ylabel("share of responses with text before the answer", color=SERIES[0])
    ax2 = ax.twinx()
    ax2.plot(range(len(reps)), toks, "o-", color=SERIES[1], ms=4, lw=1.6,
             label="median completion tokens")
    ax2.set_ylabel("median completion tokens", color=SERIES[1])
    ax2.grid(False)
    ax.set_xticks(range(len(reps)), reps, rotation=45, ha="right")
    ax.set_title("Which notations make models think out loud?", fontweight="bold")
    fig.tight_layout(); fig.savefig(FIG / "08-visible-cot.png", dpi=170); plt.close(fig)


def fig_repeat(s: dict) -> None:
    if not s.get("repeat"):
        return
    reps = sorted(s["repeat"], key=lambda p: s["repeat"][p]["same"] / max(s["repeat"][p]["n"], 1))
    y = [s["repeat"][p]["same"] / max(s["repeat"][p]["n"], 1) for p in reps]
    fig, ax = plt.subplots(figsize=(9, 5.4))
    ax.barh(reps, y, color=[SERIES[2] if p == CONTROL else SERIES[0] for p in reps], height=0.68)
    for i, v in enumerate(y):
        ax.text(v + 0.008, i, f"{v*100:.0f}%", va="center", fontsize=8, color=INK)
    ax.set_xlim(0, 1.06)
    ax.set_xlabel("share of items where all three samples gave the same verdict")
    ax.set_title("Repeat-arm stability (k=3, 150 equations, 9 models)", fontweight="bold")
    fig.tight_layout(); fig.savefig(FIG / "09-repeat.png", dpi=170); plt.close(fig)


def fig_strict(s: dict) -> None:
    models = s["models"]
    lenient = [s["strict_gap"][m]["lenient"] / s["strict_gap"][m]["n"] for m in models]
    strict = [s["strict_gap"][m]["strict"] / s["strict_gap"][m]["n"] for m in models]
    x = np.arange(len(models))
    fig, ax = plt.subplots(figsize=(9.5, 4.6))
    ax.bar(x - 0.2, lenient, 0.4, color=SERIES[0], label="lenient (answer extracted)")
    ax.bar(x + 0.2, strict, 0.4, color=SERIES[1], label="strict (answer alone)")
    for i in range(len(models)):
        ax.text(i - 0.2, lenient[i] + 0.008, f"{lenient[i]*100:.0f}", ha="center", fontsize=7.5)
        ax.text(i + 0.2, strict[i] + 0.008, f"{strict[i]*100:.0f}", ha="center", fontsize=7.5)
    ax.set_xticks(x, [slug(m) for m in models], rotation=30, ha="right")
    ax.set_ylabel("share of all responses correct")
    ax.set_title("Format compliance: how much accuracy depends on extraction",
                 fontweight="bold")
    ax.legend(frameon=False, ncol=2)
    fig.tight_layout(); fig.savefig(FIG / "10-strict-vs-lenient.png", dpi=170); plt.close(fig)


# -- tables.md ----------------------------------------------------------------

def write_tables(s: dict) -> None:
    L: list[str] = ["# Result tables\n"]
    c = s["counts"]
    L.append(f"{c['rows']:,} graded responses — {c['main']:,} main (k=0) and "
             f"{c['repeat']:,} repeat — over {c['models']} models × {c['reps']} "
             f"representations × {c['equations']} equations. Total spend "
             f"${s['cost_usd']:.2f}. Common subset: {c['common_subset']} equations.\n")

    L.append("\n## T1 Accuracy by representation, pooled over models\n")
    L.append("| representation | correct | n | accuracy | 95% CI | post-stratified |")
    L.append("|---|---|---|---|---|---|")
    for p in sorted(s["reps"], key=lambda p: -s["pooled"][p]["ci"][0]):
        v = s["pooled"][p]
        L.append(f"| `{p}` | {v['k']:,} | {v['n']:,} | {pct(v['ci'][0])} | "
                 f"{pct(v['ci'][1])}–{pct(v['ci'][2])} | {pct(s['post_stratified'][p])} |")

    L.append("\n## T2 Accuracy, model × representation\n")
    order = sorted(s["reps"], key=lambda p: -s["pooled"][p]["ci"][0])
    L.append("| model | " + " | ".join(f"`{p}`" for p in order) + " |")
    L.append("|" + "---|" * (len(order) + 1))
    for m in s["models"]:
        L.append(f"| {slug(m)} | " + " | ".join(
            pct(s["grid"][f'{m}|{p}']["p"]) for p in order) + " |")

    L.append("\n## T3 Does representation change the verdict? (Cochran's Q, common subset)\n")
    L.append("| model | tier | Q | df | p |")
    L.append("|---|---|---|---|---|")
    for m in s["models"]:
        v = s["cochran"][m]
        L.append(f"| {slug(m)} | {s['tiers'][m]} | {v['Q']:.1f} | {v['df']} | "
                 f"{'< 1e-12' if v['p'] < 1e-12 else format(v['p'], '.3g')} |")

    L.append("\n## T4 Each representation vs the control (McNemar, Holm-corrected)\n")
    L.append("| model | representation | control-only | rep-only | adjusted p |")
    L.append("|---|---|---|---|---|")
    for m in s["models"]:
        for p, v in sorted(s["mcnemar"][m].items(), key=lambda kv: kv[1]["p_holm"])[:6]:
            L.append(f"| {slug(m)} | `{p}` | {v['b10']} | {v['b01']} | {v['p_holm']:.3g} |")

    L.append("\n## T5 Outcome composition by representation\n")
    L.append("| representation | " + " | ".join(f"`{o}`" for o in OUTCOMES) + " |")
    L.append("|" + "---|" * (len(OUTCOMES) + 1))
    for p in sorted(s["reps"], key=lambda p: -s["pooled"][p]["ci"][0]):
        total = sum(s["outcomes"][p].values())
        L.append(f"| `{p}` | " + " | ".join(
            f"{s['outcomes'][p].get(o,0)/total*100:.1f}%" for o in OUTCOMES) + " |")

    L.append("\n## T6 Accuracy by law complexity\n")
    L.append("| representation | order 1–2 | order 3 | order 4 |")
    L.append("|---|---|---|---|")
    for p in sorted(s["reps"], key=lambda p: -s["pooled"][p]["ci"][0]):
        cells = []
        for stratum in ("low", "3", "4"):
            v = s["by_stratum"][p][stratum]
            cells.append(pct(v["k"] / v["n"]) if v["n"] else "—")
        L.append(f"| `{p}` | " + " | ".join(cells) + " |")

    L.append("\n## T7 Accuracy by equivalence-class size\n")
    L.append("A law whose ETP equivalence class is large is easier: several "
             "different-looking answers grade as `equivalent`.\n")
    L.append("| class size | correct | n | accuracy |")
    L.append("|---|---|---|---|")
    for label, v in s["by_eqclass"].items():
        L.append(f"| {label} | {v['k']:,} | {v['n']:,} | "
                 f"{pct(v['k']/v['n']) if v['n'] else '—'} |")

    L.append("\n## T8 Strict vs lenient scoring\n")
    L.append("| model | lenient | strict | gap |")
    L.append("|---|---|---|---|")
    for m in s["models"]:
        v = s["strict_gap"][m]
        L.append(f"| {slug(m)} | {pct(v['lenient']/v['n'])} | {pct(v['strict']/v['n'])} | "
                 f"{(v['lenient']-v['strict'])/v['n']*100:.1f} pp |")

    L.append("\n## T9 Non-verdict responses\n")
    L.append("`off_catalogue` and `unparseable` count as wrong answers; only "
             "`content_filter`/`error` are dropped from denominators.\n")
    L.append("| representation | n | not a verdict | share | truly missing |")
    L.append("|---|---|---|---|---|")
    for p in sorted(s["reps"], key=lambda p: -s["loss"][p]["lost"]):
        v = s["loss"][p]
        L.append(f"| `{p}` | {v['n']:,} | {v['lost']:,} | {v['lost']/v['n']*100:.1f}% | "
                 f"{v['missing']:,} |")

    if s.get("repeat"):
        L.append("\n## T10 Repeat-arm stability (k=3)\n")
        L.append("| representation | all three agree | n | share |")
        L.append("|---|---|---|---|")
        for p in sorted(s["repeat"], key=lambda p: s["repeat"][p]["same"] /
                        max(s["repeat"][p]["n"], 1)):
            v = s["repeat"][p]
            L.append(f"| `{p}` | {v['same']:,} | {v['n']:,} | "
                     f"{v['same']/max(v['n'],1)*100:.1f}% |")

    n = s["noise"]
    L.append("\n## T11 Resampling noise vs the ranking's gaps\n")
    L.append(f"Per-cell accuracy spread across the three repeat samples "
             f"({n['cells']} cells): median **{n['median']*100:.1f} pp**, mean "
             f"{n['mean']*100:.1f}, p90 {n['p90']*100:.1f}, max {n['max']*100:.1f}. "
             f"Total span of the ranking: {n['total_span']*100:.1f} pp. "
             f"**{n['gaps_below_noise']} of {len(n['adjacent_gaps'])} adjacent gaps "
             f"fall below the median noise**, so those orderings would not survive "
             f"a re-run.\n")
    L.append("| above | below | gap | clears noise? |")
    L.append("|---|---|---|---|")
    for g in n["adjacent_gaps"]:
        L.append(f"| `{g['above']}` | `{g['below']}` | {g['gap']*100:.1f} pp | "
                 f"{'yes' if g['gap'] >= n['median'] else '**no**'} |")

    L.append("\n## T12 Accuracy by nesting depth and variable count\n")
    L.append("| depth | accuracy | n | | distinct variables | accuracy | n |")
    L.append("|---|---|---|---|---|---|---|")
    depths, varis = list(s["by_depth"].items()), list(s["by_variables"].items())
    for i in range(max(len(depths), len(varis))):
        left = (f"{depths[i][0]} | {pct(depths[i][1]['k']/depths[i][1]['n'])} | "
                f"{depths[i][1]['n']:,}" if i < len(depths) else " |  | ")
        right = (f"{varis[i][0]} | {pct(varis[i][1]['k']/varis[i][1]['n'])} | "
                 f"{varis[i][1]['n']:,}" if i < len(varis) else " |  | ")
        L.append(f"| {left} | | {right} |")

    L.append("\n## T13 Open- vs closed-weight models (exploratory)\n")
    L.append("| weights | models | correct | n | accuracy |")
    L.append("|---|---|---|---|---|")
    for kind, v in sorted(s["by_weights"].items()):
        count = sum(1 for m in s["models"] if (m in OPEN_WEIGHTS) == (kind == "open"))
        L.append(f"| {kind} | {count} | {v['k']:,} | {v['n']:,} | {pct(v['k']/v['n'])} |")

    reg = s.get("regression", {})
    if reg.get("fitted"):
        L.append("\n## T14 Logistic regression, clustered by equation\n")
        L.append(f"`correct ~ representation + order + tier`, n={reg['n']:,} over "
                 f"{reg['clusters']} equation clusters. Log-odds against the "
                 f"`{CONTROL}` control and the small tier.\n")
        L.append("| term | beta | se | p |")
        L.append("|---|---|---|---|")
        for name, v in sorted(reg["coefficients"].items(),
                              key=lambda kv: -kv[1]["beta"]):
            L.append(f"| `{name}` | {v['beta']:+.3f} | {v['se']:.3f} | "
                     f"{'<1e-12' if v['p'] < 1e-12 else format(v['p'], '.3g')} |")

    (RES / "tables.md").write_text("\n".join(L) + "\n", encoding="utf-8")


def main() -> None:
    FIG.mkdir(exist_ok=True); RES.mkdir(exist_ok=True)
    rows, sample = load()
    s = build(rows, sample)
    (RES / "summary.json").write_text(json.dumps(s, indent=2, default=float) + "\n")
    for fn in (fig_heatmap, fig_ranking, fig_delta, fig_outcomes, fig_difficulty,
               fig_significance, fig_loss, fig_cot, fig_repeat, fig_strict):
        try:
            fn(s)
        except Exception as exc:                      # a bad figure must not lose the tables
            print(f"figure {fn.__name__} failed: {exc}", file=sys.stderr)
    write_tables(s)
    print(f"{s['counts']['rows']:,} rows -> results/tables.md, results/summary.json, "
          f"{len(list(FIG.glob('*.png')))} figures", file=sys.stderr)


if __name__ == "__main__":
    main()
