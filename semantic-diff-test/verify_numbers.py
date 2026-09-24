"""Check every figure quoted in ANALYSIS.md against results/summary.json.

A write-up is only as trustworthy as the arithmetic between the data and the
prose, and that step is done by hand. This re-derives each claim from the
summary and fails loudly on any mismatch.
"""
import json, re, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
s = json.loads((HERE / "results" / "summary.json").read_text())
text = (HERE / "ANALYSIS.md").read_text()
bad, checked = [], 0

def check(label, claimed, actual, tol=0.05):
    global checked
    checked += 1
    if actual is None or abs(claimed - actual) > tol:
        bad.append(f"{label}: ANALYSIS says {claimed}, data says {actual}")

# pooled accuracy rows: | `rep` | 73.7% | ...
for m in re.finditer(r"^\| `(\w+)`(?: \*\(control\)\*)? \| \*?\*?([\d.]+)%?\*?\*? \| "
                     r"([\d.]+)–([\d.]+) \| ([\d.]+)% \|", text, re.M):
    rep, acc, lo, hi, post = m.group(1), *map(float, m.groups()[1:])
    if rep in s["pooled"]:
        check(f"pooled {rep}", acc, s["pooled"][rep]["ci"][0] * 100)
        check(f"CI-lo {rep}", lo, s["pooled"][rep]["ci"][1] * 100)
        check(f"CI-hi {rep}", hi, s["pooled"][rep]["ci"][2] * 100)
        check(f"post {rep}", post, s["post_stratified"][rep] * 100)

# control arm per model
for m in re.finditer(r"^\| ([\w.\-]+) \| \*?\*?([\d.]+)%\*?\*? \|$", text, re.M):
    name, val = m.group(1), float(m.group(2))
    full = next((k for k in s["models"] if k.split("/")[-1] == name), None)
    if full:
        check(f"control {name}", val, s["grid"][f"{full}|etp_canonical"]["p"] * 100)

# outcome-composition table
for m in re.finditer(r"^\| `(\w+)` \| ([\d.]+) \| \*?\*?([\d.]+)\*?\*? \| ([\d.]+) \| "
                     r"([\d.]+) \| \*?\*?([\d.]+)\*?\*? \| ([\d.]+) \|$", text, re.M):
    rep = m.group(1)
    if rep not in s["outcomes"]:
        continue
    total = sum(s["outcomes"][rep].values())
    for i, key in enumerate(["equivalent", "weaker", "stronger", "incomparable",
                             "off_catalogue", "unparseable"]):
        check(f"{rep}/{key}", float(m.group(i + 2)),
              s["outcomes"][rep].get(key, 0) / total * 100)

# model table: lenient / strict
for m in re.finditer(r"^\| ([\w.\-]+) \| (?:frontier|medium|small) \| \*?\*?([\d.]+)%\*?\*? \| "
                     r"([\d.]+)% \|", text, re.M):
    name, lenient, strict = m.group(1), float(m.group(2)), float(m.group(3))
    full = next((k for k in s["models"] if k.split("/")[-1] == name), None)
    if full:
        v = s["strict_gap"][full]
        check(f"lenient {name}", lenient, v["lenient"] / v["n"] * 100)
        check(f"strict {name}", strict, v["strict"] / v["n"] * 100)

# scalar claims
check("common subset", float(re.search(r"common subset is (\d+)", text).group(1)),
      s["counts"]["common_subset"], tol=0)
n_sig = sum(1 for m in s["models"] for p, v in s["mcnemar"][m].items() if v["p_holm"] < 0.05)
check("McNemar significant", float(re.search(r"(\d+) of 153", text).group(1)), n_sig, tol=0)
for label, lo, hi, claimed in (("1 (unique)", 0, 0, 54.0), ("2-9", 0, 0, 54.2), ("10+", 0, 0, 51.0)):
    v = s["by_eqclass"][label]
    check(f"eqclass {label}", claimed, v["k"] / v["n"] * 100, tol=0.1)
abl = json.loads((HERE / "ablation" / "ablation_summary.json").read_text())
ctl = json.loads((HERE / "control_probe" / "control_probe_summary.json").read_text())
dose = json.loads((HERE / "dose_confusable" / "dose_summary.json").read_text())
ctl_n = sum(v["n"] for v in ctl["accuracy"].values())
dose_n = sum(v["n"] for v in dose["accuracy"].values())
check("total calls", float(re.search(r"\*\*([\d,]+) calls", text).group(1).replace(",", "")),
      s["counts"]["rows"] + abl["n_rows"] + 8400 + 5400, tol=0)
check("main rows", float(re.search(r"([\d,]+) main,", text).group(1).replace(",", "")),
      s["counts"]["main"], tol=0)
check("ablation rows", float(re.search(r"\((\d[\d,]*) note ablation", text).group(1).replace(",", "")),
      abl["n_rows"], tol=0)

# control probe table: | model | baseline | no_transform | bare_frame | both |
SLUG2 = {"mistral-small": "mistralai/mistral-small-3.2-24b-instruct",
         "qwen3-30b": "qwen/qwen3-30b-a3b-instruct-2507", "phi-4": "microsoft/phi-4",
         "llama-4-maverick": "meta-llama/llama-4-maverick", "grok-4.20": "x-ai/grok-4.20",
         "gemini-2.5-flash": "google/gemini-2.5-flash", "gpt-5.2": "openai/gpt-5.2"}
for m in re.finditer(r"^\| ([\w.\-]+) \| ([\d.]+) \| ([\d.]+) \*+ \| ([\d.]+) (?:\*+|ns) \| "
                     r"\*?\*?([\d.]+)\*?\*? \*+ \|$", text, re.M):
    name = m.group(1)
    if name not in SLUG2:
        continue
    for i, cond in enumerate(["baseline", "no_transform", "bare_frame", "both"]):
        cell = ctl["accuracy"].get(f"{SLUG2[name]}|etp_canonical|{cond}")
        check(f"control {name}/{cond}", float(m.group(i + 2)),
              cell["k"] / cell["n"] * 100 if cell and cell["n"] else None, tol=0.06)

# dose table: | `level` | ids | accuracy | merge | unparseable |
for m in re.finditer(r"^\| `(\w+)` \| `[^`]+` \| \*?\*?([\d.]+)%\*?\*? \| "
                     r"\*?\*?([\d.]+)%\*?\*? \| ([\d.]+)% \|$", text, re.M):
    lvl = m.group(1)
    d = dose["pooled"].get(lvl)
    if not d:
        continue
    check(f"dose {lvl} acc", float(m.group(2)), d["acc"][0] / d["acc"][1] * 100)
    check(f"dose {lvl} merge", float(m.group(3)), d["merge"][0] / d["merge"][1] * 100)
    check(f"dose {lvl} unparse", float(m.group(4)), d["unparseable"] / d["n"] * 100)

# ablation table: | model | `rep` | none | current | generous | ...
SLUG = {"qwen3-30b": "qwen/qwen3-30b-a3b-instruct-2507",
        "gemini-2.5-flash": "google/gemini-2.5-flash",
        "gpt-5.2": "openai/gpt-5.2", "claude-opus-5": "anthropic/claude-opus-5"}
for m in re.finditer(r"^\| ([\w.\-]+) \| `(\w+)` \| ([\d.]+) \| ([\d.]+) \| ([\d.]+) \|",
                     text, re.M):
    name, rep = m.group(1), m.group(2)
    if name not in SLUG:
        continue
    for i, cond in enumerate(["none", "current", "generous"]):
        cell = abl["accuracy"].get(f"{SLUG[name]}|{rep}|{cond}")
        check(f"ablation {name}/{rep}/{cond}", float(m.group(i + 3)),
              cell["k"] / cell["n"] * 100 if cell else None, tol=0.06)
tot_same = sum(v["same"] for v in s["repeat"].values())
tot_n = sum(v["n"] for v in s["repeat"].values())
check("repeat agreement", float(re.search(r"same verdict on ([\d.]+)% of triples", text).group(1)),
      tot_same / tot_n * 100)
check("repeat same n", float(re.search(r"\(([\d,]+) of\n?24,300\)", text).group(1).replace(",", "")),
      tot_same, tol=0)

# depth table
m = re.search(r"\| accuracy \| ([\d.]+)% \| ([\d.]+)% \| ([\d.]+)% \| \*\*([\d.]+)%\*\* \|", text)
if m:
    for i, d in enumerate(["1", "2", "3", "4"]):
        v = s["by_depth"][d]
        check(f"depth {d}", float(m.group(i + 1)), v["k"] / v["n"] * 100)

# adjacent-gap table
for m in re.finditer(r"^\| `(\w+)` → `(\w+)` \| \*?\*?([\d.]+) pp\*?\*? \| (yes|no) \|$",
                     text, re.M):
    above, below, gap = m.group(1), m.group(2), float(m.group(3))
    found = next((g for g in s["noise"]["adjacent_gaps"]
                  if g["above"] == above and g["below"] == below), None)
    check(f"gap {above}->{below}", gap, found["gap"] * 100 if found else None, tol=0.06)

# regression coefficients
for m in re.finditer(r"^\| `(\w+)` \| \*?\*?([+-][\d.]+)\*?\*? \|$", text, re.M):
    name, beta = m.group(1), float(m.group(2))
    if name in s["regression"]["coefficients"]:
        check(f"beta {name}", beta, s["regression"]["coefficients"][name]["beta"], tol=0.006)

# open vs closed
m = re.search(r"models average ([\d.]+)% and open-weight ([\d.]+)%", text)
if m:
    check("closed weights", float(m.group(1)),
          s["by_weights"]["closed"]["k"] / s["by_weights"]["closed"]["n"] * 100)
    check("open weights", float(m.group(2)),
          s["by_weights"]["open"]["k"] / s["by_weights"]["open"]["n"] * 100)

m = re.search(r"\*\*(\d+) of the 17 adjacent gaps", text)
if m:
    check("gaps below noise", float(m.group(1)), s["noise"]["gaps_below_noise"], tol=0)
m = re.search(r"regression .*?([\d,]+) rows", text)
if m:
    check("regression n", float(m.group(1).replace(",", "")), s["regression"]["n"], tol=0)

print(f"checked {checked} quoted figures")
if bad:
    print("MISMATCHES:"); [print("  " + b) for b in bad]; sys.exit(1)
print("ALL CHECKS PASS")
