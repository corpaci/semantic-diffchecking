"""Grade every recorded response with the semantic oracle.

Reads the raw JSONL written by `run_experiment.py`, extracts an identity from
each response, and asks [`oracle/oracle.py`](../oracle/oracle.py) how it relates
to the law the model was shown. Grading is separate from the sweep so verdicts
can be recomputed — after an extractor fix, say — without spending money again.

## Extraction

Models do not always answer with the identity alone. The smoke run produced
code fences (`phi-4`), a stray `<br>` (`claude-opus-5`), visible chain-of-thought
before the answer, and LaTeX typesetting around it. So the response is cleaned
(fences, `<thinking>` blocks, stray tags, and typesetting-only LaTeX such as
`\\,` and `\\text{...}` are removed — none of which changes what the text means)
and then read by a ladder:

    exact      the whole cleaned response parses
    fenced     the contents of a code fence parse
    last_line  the last non-empty line parses
    scan       the last parseable line anywhere

The strategy that succeeded is recorded, and two accuracies are reported:
*strict* counts only `exact`, *lenient* counts any. Lenient is the primary
outcome — the question is meaning preservation, not format compliance — but the
gap between them is published, because lenient extraction quietly rewards
verbose models.

## Outcomes

`equivalent` / `weaker` / `stronger` / `incomparable` / `unknown` come from the
oracle. `off_catalogue` means the answer is a well-formed magma identity that is
not an ETP node (order > 4, say) — a different failure from `unparseable`, and
worth separating. `content_filter` and `error` are calls that never produced a
usable response; all three of the last are excluded from accuracy denominators
and reported as a loss table, because the loss is not random across
representations.

    python3 grade.py              # -> results/graded.json
    python3 grade.py --tag smoke- # grade a smoke run instead
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(REPO / "oracle"))

from oracle import SemanticOracle  # noqa: E402

FENCE = re.compile(r"```[a-zA-Z0-9_+-]*\n(.*?)```", re.S)
THINK = re.compile(r"<(thinking|thought|reasoning)>.*?</\1>", re.S | re.I)
STRAY_TAG = re.compile(r"</?(br|p|div|thinking|thought|reasoning)\s*/?>", re.I)
# Typesetting-only LaTeX: spacing commands, \text{...} wrappers, display math
# delimiters. Removing these changes presentation, never meaning.
TEX_SPACE = re.compile(r"\\[,;:!]|\\quad|\\qquad")
TEX_TEXT = re.compile(r"\\(?:text|mathrm|mathit|mathsf|operatorname)\s*\{([^{}]*)\}")
TEX_DELIM = re.compile(r"\\[\[\]()]|\$\$?")


def clean(content: str) -> str:
    """Strip presentation so the parser sees the mathematics."""
    text = THINK.sub(" ", content or "")
    text = STRAY_TAG.sub(" ", text)
    text = TEX_TEXT.sub(r"\1", text)
    text = TEX_SPACE.sub(" ", text)
    text = TEX_DELIM.sub(" ", text)
    return text.strip()


def extract(oracle: SemanticOracle, content: str) -> tuple[str | None, str | None, bool]:
    """Return `(identity, strategy, visible_cot)` for one response."""
    def parses(text: str) -> bool:
        text = text.strip()
        return bool(text) and oracle.mapper.map(text).status != "parse-failure"

    cleaned = clean(content)
    if not cleaned:
        return None, None, False

    if parses(cleaned):
        return cleaned, "exact", False

    for body in reversed(FENCE.findall(content or "")):
        if parses(body):
            return body.strip(), "fenced", True

    lines = [line for line in cleaned.splitlines() if line.strip()]
    if lines and parses(lines[-1]):
        return lines[-1].strip(), "last_line", len(lines) > 1

    for index in range(len(lines) - 1, -1, -1):
        if parses(lines[index]):
            return lines[index].strip(), "scan", True
    return None, None, bool(lines)


def outcome_for(oracle: SemanticOracle, node: int, identity: str | None) -> tuple[str, dict]:
    """Bucket one answer; returns `(outcome, oracle detail)`."""
    if identity is None:
        return "unparseable", {}
    verdict = oracle.compare(node, identity)
    status = verdict.generated.get("status")
    if status == "mapped":
        return verdict.label, {"generated_node": verdict.generated.get("node"),
                               "generated_normalized": verdict.generated.get("normalized"),
                               "evidence": verdict.evidence}
    if status == "outside-fragment":
        return "off_catalogue", {"reason": verdict.generated.get("reason")}
    return "unparseable", {"reason": verdict.generated.get("reason")}


def grade_rows(tag: str) -> list[dict]:
    """Grade every raw row on disk."""
    oracle = SemanticOracle()
    sample = {r["node"]: r for r in json.loads((HERE / "sample.json").read_text())["equations"]}
    notes = json.loads((HERE / "prompts.json").read_text())["representations"]

    # A retried call leaves its failed attempt behind in the log, so keep the
    # last row per key and let a recovered call supersede the error it replaced.
    latest: dict[tuple, dict] = {}
    for path in sorted(HERE.glob(f"*/{tag}*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if row.get("_header") or "rep" not in row:
                continue
            key = (row["model"], row["rep"], row["node"], row["k"])
            if key not in latest or "error" in latest[key]:
                latest[key] = row

    out: list[dict] = []
    for row in latest.values():
        if True:

            if "error" in row:
                outcome, identity, strategy, cot, detail = "error", None, None, False, {}
            elif row.get("filtered"):
                outcome, identity, strategy, cot, detail = "content_filter", None, None, False, {}
            else:
                identity, strategy, cot = extract(oracle, row.get("content", ""))
                outcome, detail = outcome_for(oracle, row["node"], identity)

            meta = sample[row["node"]]
            out.append({
                "model": row["model"], "tier": row["tier"], "rep": row["rep"],
                "node": row["node"], "k": row["k"],
                "outcome": outcome, "correct": outcome == "equivalent",
                "strategy": strategy, "strict": strategy == "exact",
                "visible_cot": cot, "answer": identity,
                "finish": row.get("finish"), "provider": row.get("provider"),
                "prompt_tokens": row.get("prompt_tokens"),
                "completion_tokens": row.get("completion_tokens"),
                "reasoning_tokens": row.get("reasoning_tokens"),
                "cost": row.get("cost"), "latency_s": row.get("latency_s"),
                "retries": row.get("retries"),
                "order": meta["order"], "depth": meta["depth"],
                "variables": meta["variables"], "stratum": meta["stratum"],
                "note_tokens": notes[row["rep"]]["note_tokens"],
                **detail,
            })
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--tag", default="raw-", help="raw- (default) or smoke-")
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()

    rows = grade_rows(args.tag)
    out = args.out or (HERE / "results" /
                       ("graded.json" if args.tag == "raw-" else "graded-smoke.json"))
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(rows, ensure_ascii=False) + "\n", encoding="utf-8")

    gradeable = [r for r in rows if r["outcome"] not in
                 ("unparseable", "off_catalogue", "content_filter", "error")]
    print(f"{len(rows):,} rows graded -> {out}", file=sys.stderr)
    print("outcomes: " + ", ".join(f"{k}={v}" for k, v in
          Counter(r["outcome"] for r in rows).most_common()), file=sys.stderr)
    print("strategies: " + ", ".join(f"{k}={v}" for k, v in
          Counter(r["strategy"] for r in rows).most_common()), file=sys.stderr)
    if gradeable:
        correct = sum(r["correct"] for r in rows)
        strict = sum(r["correct"] and r["strict"] for r in rows)
        print(f"lenient accuracy {correct/len(rows)*100:.1f}% of all rows; "
              f"strict {strict/len(rows)*100:.1f}%; "
              f"gradeable {len(gradeable)/len(rows)*100:.1f}%", file=sys.stderr)


if __name__ == "__main__":
    main()
