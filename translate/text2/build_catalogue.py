"""Export the whole ETP catalogue as formal + bracket-free text pairs.

Walks every law in `equations.txt` (4694 in the current data drop), verbalizes
each with `prefixify`, and writes one JSON file:

    {
      "meta":      { source, count, style, generated_at, verified, ... },
      "equations": [ { node, formal, text, order, variables }, ... ]
    }

Same shape, same node numbering and the same `text` key as
[`../text/`](../text/), so the two renderings join row for row and can be
swapped for one another in an experiment without touching anything downstream.

`formal` is the catalogue line verbatim — line N *is* Equation N, which is the
invariant `NodeMapper` enforces when it loads the file, so `node` here is the
same identifier the implication graph and the semantic oracle use. No separate
"normalized" field is emitted: the catalogue text is already in canonical form
(variables renamed by first appearance, `◇` as the operation), and the build
asserts that rather than asking you to take it on trust.

Three checks run over every row, plus one over the catalogue as a whole,
because a silently mangled equation still looks like a plausible equation:

  * **round trip** — the sentence is read back and the resulting syntax tree
    must equal the original. Since this representation carries its structure in
    the phrasing rather than in delimiters, this is the check that a nesting
    was not silently flattened or re-associated.
  * **canonical form** — the catalogue text must equal its own normalization, so
    the claim above stays true if the ETP data drop ever changes.
  * **text purity** — the rendering must contain nothing but lowercase words,
    spaces, and the quantifier's comma. A stray `◇`, digit, or bracket
    character would mean some part of the equation had not actually been put
    into words, which is the one thing this representation is for.
  * **distinctness** (whole catalogue) — all 4694 sentences must differ. The
    case for a bracket-free rendering rests on the grammar being unambiguous;
    two laws sharing a sentence would be a direct counterexample, so it is
    worth checking rather than arguing.

`--txt` additionally writes a plain-text listing of every equation, which is
the readable artefact to skim when deciding whether the wording is any good.

CLI:
    python3 build_catalogue.py                          # -> etp_equations_text2.json
    python3 build_catalogue.py --out /tmp/etp.json --operator-word product
    python3 build_catalogue.py --txt preview.txt --limit 40
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from collections import Counter
from pathlib import Path

from prefixify import (  # noqa: F401  (also performs the oracle sys.path bootstrap)
    ORACLE_DIR,
    PrefixStyle,
    PrefixStyleError,
    add_style_args,
    style_from_args,
    text_equation,
    to_equation,
)
from mapper import NodeMapper  # noqa: E402  (available via prefixify's bootstrap)
from normalizer import (  # noqa: E402
    OutsideFragment,
    ParseFailure,
    normalize,
    parse_equation,
)

DEFAULT_OUT = Path(__file__).parent / "etp_equations_text2.json"

# Lowercase words, single spaces, and the comma that ends a `for all …,`
# prefix. Deliberately strict: anything outside this set means a symbol
# survived into a representation whose whole point is that none do.
PURE_TEXT = re.compile(r"[a-z]+(?:[, ][a-z]+)*")


def check_row(node: int, law: str, sentence: str, style: PrefixStyle) -> None:
    """Run the three per-row checks; raise `AssertionError` on the first failure.

    Split out from `build_rows` so the failure messages stay close to the
    reasons in the module docstring, and so a caller can re-check a single row
    without rebuilding the catalogue.
    """
    equation = parse_equation(law)

    canonical = normalize(equation).render()
    assert canonical == law, (
        f"Equation {node}: catalogue text {law!r} is not in canonical form "
        f"({canonical!r}); the no-normalized-field assumption no longer holds"
    )

    try:
        reread = to_equation(sentence, style)
    except (ParseFailure, OutsideFragment) as exc:
        raise AssertionError(
            f"Equation {node}: rendered text could not be read back.\n"
            f"  formal: {law}\n  text:   {sentence}\n  error:  {exc}"
        ) from None
    assert reread == equation, (
        f"Equation {node}: text did not round-trip.\n"
        f"  formal: {law}\n  text:   {sentence}\n  reread: {reread.render()}"
    )

    assert PURE_TEXT.fullmatch(sentence), (
        f"Equation {node}: rendering is not pure text — a symbol survived "
        f"verbalization.\n  formal: {law}\n  text:   {sentence}"
    )


def check_distinct(rows: list[dict]) -> None:
    """Assert no two equations produced the same sentence.

    A collision would mean the bracket-free grammar is ambiguous in practice,
    which is the one claim this representation depends on; the message names
    the colliding nodes so the counterexample is immediately in hand.
    """
    seen: dict[str, int] = {}
    for row in rows:
        first = seen.setdefault(row["text"], row["node"])
        assert first == row["node"], (
            f"Equations {first} and {row['node']} produced the same sentence — the "
            f"rendering is not injective.\n  text: {row['text']}"
        )


def build_rows(mapper: NodeMapper, style: PrefixStyle, *, verify: bool = True) -> list[dict]:
    """Verbalize every catalogue law, verifying each row as it is built.

    Returns one record per equation in node order. Raises `AssertionError` on
    the first row that fails a check — a partially-wrong catalogue is worse than
    no catalogue, so this refuses to write one.
    """
    rows: list[dict] = []
    for index, law in enumerate(mapper.laws):
        node = index + 1
        equation = parse_equation(law)
        sentence = text_equation(equation, style)

        if verify:
            check_row(node, law, sentence, style)

        names: list[str] = []
        equation.lhs.variables(names)
        equation.rhs.variables(names)
        rows.append({
            "node": node,
            "formal": law,
            "text": sentence,
            "order": equation.size(),
            "variables": names,
        })
    if verify:
        check_distinct(rows)
    return rows


def write_json(path: Path, rows: list[dict], meta: dict) -> Path:
    """Write the catalogue as `{meta, equations}`; returns the path written."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"meta": meta, "equations": rows}
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def write_txt(path: Path, rows: list[dict]) -> Path:
    """Write a plain-text listing, one `N. sentence` per line.

    The point of this representation is that it can simply be read, so the
    build can produce something a person actually reads.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(f"{row['node']}. {row['text']}\n" for row in rows), encoding="utf-8"
    )
    return path


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Export every ETP equation as a formal/text pair, bracket-free "
                    "(no model involved)."
    )
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT,
                        help=f"JSON output path (default {DEFAULT_OUT.name} beside this script)")
    parser.add_argument("--equations", type=Path, default=None,
                        help="path to equations.txt (default: the oracle's resolution — "
                             "$ETP_EQUATIONS, else $ETP_ROOT/data/equations.txt)")
    parser.add_argument("--txt", type=Path, default=None,
                        help="also write a plain-text listing of every equation")
    parser.add_argument("--limit", type=int, default=None,
                        help="only the first N equations (for a quick look)")
    parser.add_argument("--no-verify", action="store_true",
                        help="skip the round-trip, canonical-form, purity and "
                             "distinctness checks (not advised)")
    add_style_args(parser)
    args = parser.parse_args()

    style = style_from_args(args)
    try:
        mapper = NodeMapper(str(args.equations)) if args.equations else NodeMapper()
    except SystemExit as exc:  # missing catalogue: re-raise with its own message
        raise SystemExit(str(exc)) from None

    if args.limit:
        mapper.laws = mapper.laws[: args.limit]

    started = time.monotonic()
    try:
        rows = build_rows(mapper, style, verify=not args.no_verify)
    except AssertionError as exc:
        raise SystemExit(f"verification failed, nothing written:\n{exc}") from None
    elapsed = round(time.monotonic() - started, 2)

    meta = {
        "generator": "translate/text2/build_catalogue.py",
        "source": mapper.equations_path,
        "count": len(rows),
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "style": {
            "form": "prefix",
            "operator_word": style.operator_word,
            "open_phrase": style.open_phrase,
            "connector": style.connector,
            "equals_word": style.equals_word,
            "quantify": style.quantify,
        },
        "verified": not args.no_verify,
        "verification": (
            "every row: rendered text read back to an identical syntax tree, the "
            "catalogue text confirmed already canonical, and the rendering "
            "confirmed free of every symbol (lowercase words and spaces only); "
            "across the catalogue: all sentences confirmed pairwise distinct"
            if not args.no_verify else "skipped (--no-verify)"
        ),
    }

    written = [write_json(args.out, rows, meta)]
    if args.txt:
        written.append(write_txt(args.txt, rows))

    orders = Counter(row["order"] for row in rows)
    words = [len(row["text"].split()) for row in rows]
    print(f"{len(rows)} equations from {mapper.equations_path}", file=sys.stderr)
    print("by order: " + ", ".join(f"{o}:{n}" for o, n in sorted(orders.items())), file=sys.stderr)
    print(f"words per equation: min {min(words)}, mean {sum(words) / len(words):.1f}, "
          f"max {max(words)}", file=sys.stderr)
    print(f"verified: {meta['verified']}  ({elapsed}s)", file=sys.stderr)
    for path in written:
        print(f"wrote {path} ({path.stat().st_size / 1024:.0f} KB)", file=sys.stderr)


if __name__ == "__main__":
    main()
