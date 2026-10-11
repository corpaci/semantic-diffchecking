"""Assemble the prompt for every (representation, equation) and check it.

One shared frame, one authored note per representation, one uniform output
contract, then the rendering:

    frame.txt   ->  task framing
                    {note}      <- <rep>/note.txt, the only per-rep authored text
                    requirements (identical for all 18)
                    {body}      <- the rendering from translate/<rep>/

Nothing is materialized for all 9000 prompts: the runner assembles from the
template and the catalogue, so there is no second copy to drift. What is written
per representation is `prompt_template.txt` (the frame with the note filled in,
`{body}` still open) and `example_prompt.txt` (two fully rendered examples, one
easy and one hard), which is what a reviewer actually needs to see.

## The checks

  * **note budget** - 25-40 tokens. The note is where experimenter bias would
    enter: a generous explanation of DOT against a terse one for RPN would
    confound the notation with my prose. Length is also recorded as a covariate.
  * **no digits in authored text** - the frame and every note must be free of
    digits, so no prompt can leak an ETP equation number. The renderings are
    node-number-free by construction and each `translate/*/build_catalogue.py`
    verifies that for its own catalogue (`tptp` names its formula `law`, not
    `law4512`; `lean` strips the number).
  * **every prompt renders** for all 500 sampled equations in all 18
    representations.

    python3 render_prompts.py            # write templates + examples, run checks
    python3 render_prompts.py --check    # checks only, write nothing
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(REPO / "oracle"))

NOTE_MIN, NOTE_MAX = 25, 40
FRAME = HERE / "frame.txt"
OUT = HERE / "prompts.json"

# `etp_canonical` is the control arm: the law in the catalogue's own notation,
# read out of any catalogue's `formal` field rather than a directory of its own.
CONTROL = "etp_canonical"


def _tokens(text: str) -> int:
    """Token count, cl100k_base. Approximate across model families, consistent
    across representations - which is what the budget comparison needs."""
    import tiktoken
    return len(tiktoken.get_encoding("cl100k_base").encode(text))


def load_catalogues() -> dict[str, dict[int, str]]:
    """`{representation: {node: rendering}}` for all 18."""
    out: dict[str, dict[int, str]] = {}
    for path in sorted((REPO / "translate").glob("*/etp_equations_*.json")):
        rows = json.loads(path.read_text())["equations"]
        key = next(k for k, v in rows[0].items()
                   if k not in ("node", "formal", "order", "variables") and isinstance(v, str))
        out[path.parent.name] = {r["node"]: r[key] for r in rows}
        out.setdefault(CONTROL, {r["node"]: r["formal"] for r in rows})
    return out


def build() -> dict:
    """Assemble every template and run the checks. Raises on any failure."""
    frame = FRAME.read_text(encoding="utf-8")
    assert "{note}" in frame and "{body}" in frame, "frame.txt lost a placeholder"
    catalogues = load_catalogues()
    sample = json.loads((HERE / "sample.json").read_text())
    nodes = [row["node"] for row in sample["equations"]]

    problems: list[str] = []
    if re.search(r"\d", frame):
        problems.append("frame.txt contains a digit; it could leak an equation number")

    reps = {}
    for name in sorted(catalogues):
        note_path = HERE / name / "note.txt"
        if not note_path.exists():
            problems.append(f"{name}: no note.txt")
            continue
        note = note_path.read_text(encoding="utf-8").strip()
        count = _tokens(note)
        if not NOTE_MIN <= count <= NOTE_MAX:
            problems.append(f"{name}: note is {count} tokens, budget is {NOTE_MIN}-{NOTE_MAX}")
        if re.search(r"\d", note):
            problems.append(f"{name}: note contains a digit; it could leak an equation number")
        missing = [n for n in nodes if n not in catalogues[name]]
        if missing:
            problems.append(f"{name}: {len(missing)} sampled equations have no rendering")

        template = frame.replace("{note}", note)
        reps[name] = {
            "note": note,
            "note_tokens": count,
            "template": template,
            "template_sha256": hashlib.sha256(template.encode()).hexdigest(),
            "prompt_tokens_mean": round(sum(
                _tokens(template.replace("{body}", catalogues[name][n])) for n in nodes
            ) / len(nodes), 1),
        }

    if problems:
        raise SystemExit("prompt checks failed:\n  " + "\n  ".join(problems))
    return {"meta": {"frame_sha256": hashlib.sha256(frame.encode()).hexdigest(),
                     "note_budget": [NOTE_MIN, NOTE_MAX],
                     "equations": len(nodes), "representations": len(reps),
                     "prompts": len(nodes) * len(reps)},
            "representations": reps}


def write_examples(built: dict, catalogues: dict, sample: dict) -> None:
    """Write per-representation templates and two rendered examples each."""
    rows = sample["equations"]
    easy = next(r for r in rows if r["order"] == 2)
    hard = max(rows, key=lambda r: (r["order"], r["depth"]))
    for name, info in built["representations"].items():
        (HERE / name / "prompt_template.txt").write_text(info["template"], encoding="utf-8")
        blocks = []
        for label, row in (("SIMPLE", easy), ("COMPLEX", hard)):
            blocks.append(
                f"{'=' * 78}\n{label}  -  Equation {row['node']}   {row['formal']}\n"
                f"  order {row['order']}, depth {row['depth']}, "
                f"{row['variables']} distinct variables\n{'=' * 78}\n\n"
                + info["template"].replace("{body}", catalogues[name][row["node"]])
            )
        (HERE / name / "example_prompt.txt").write_text("\n\n".join(blocks), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="run checks, write nothing")
    args = parser.parse_args()

    built = build()
    print(f"{built['meta']['representations']} representations x "
          f"{built['meta']['equations']} equations = {built['meta']['prompts']:,} prompts",
          file=sys.stderr)
    print(f"{'representation':18} {'note tok':>8} {'mean prompt tok':>16}", file=sys.stderr)
    for name, info in built["representations"].items():
        print(f"{name:18} {info['note_tokens']:8} {info['prompt_tokens_mean']:16.1f}",
              file=sys.stderr)
    print("all checks passed: note budget, no digits in authored text, "
          "every sampled equation renders", file=sys.stderr)

    if args.check:
        return
    write_examples(built, load_catalogues(), json.loads((HERE / "sample.json").read_text()))
    OUT.write_text(json.dumps(built, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {OUT} and per-representation prompt_template.txt / example_prompt.txt",
          file=sys.stderr)


if __name__ == "__main__":
    main()
