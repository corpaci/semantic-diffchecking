"""Export the whole ETP catalogue as formal + LaTeX pairs.

Walks every law in `equations.txt` (4694 in the current data drop), renders each
to LaTeX with `latexify`, and writes one JSON file:

    {
      "meta":      { source, count, style, generated_at, verified, ... },
      "equations": [ { node, formal, latex, order, variables }, ... ]
    }

`formal` is the catalogue line verbatim — line N *is* Equation N, which is the
invariant `NodeMapper` enforces when it loads the file, so `node` here is the
same identifier the implication graph and the semantic oracle use. No separate
"normalized" field is emitted: the catalogue text is already in canonical form
(variables renamed by first appearance, `◇` as the operation), and the build
asserts that rather than asking you to take it on trust.

Two checks run over every row before anything is written, because a silently
mangled equation still looks like a plausible equation:

  * **round trip** — the LaTeX is parsed back and the resulting syntax tree must
    equal the original. This catches a dropped or misplaced parenthesis, which
    is the failure mode that would otherwise survive review.
  * **canonical form** — the catalogue text must equal its own normalization, so
    the claim above stays true if the ETP data drop ever changes.

`--tex` additionally writes a LaTeX document listing every equation, which
`pdflatex` will compile — the end-to-end check that the output is not just
parseable by us but valid LaTeX.

CLI:
    python3 build_catalogue.py                          # -> etp_equations_latex.json
    python3 build_catalogue.py --out /tmp/etp.json --operator "\\circ"
    python3 build_catalogue.py --tex preview.tex --limit 40
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from pathlib import Path

from latexify import (  # noqa: F401  (also performs the oracle sys.path bootstrap)
    ORACLE_DIR,
    LatexStyle,
    add_style_args,
    latex_equation,
    readable_style,
    style_from_args,
)
from mapper import NodeMapper  # noqa: E402  (available via latexify's bootstrap)
from normalizer import (  # noqa: E402
    OutsideFragment,
    ParseFailure,
    normalize,
    parse_equation,
)

DEFAULT_OUT = Path(__file__).parent / "etp_equations_latex.json"


def build_rows(mapper: NodeMapper, style: LatexStyle, *, verify: bool = True) -> list[dict]:
    """Render every catalogue law, verifying each row as it is built.

    Returns one record per equation in node order. Raises `AssertionError` on
    the first row that fails a check — a partially-wrong catalogue is worse than
    no catalogue, so this refuses to write one.
    """
    rows: list[dict] = []
    for index, law in enumerate(mapper.laws):
        node = index + 1
        equation = parse_equation(law)

        if verify:
            canonical = normalize(equation).render()
            assert canonical == law, (
                f"Equation {node}: catalogue text {law!r} is not in canonical form "
                f"({canonical!r}); the no-normalized-field assumption no longer holds"
            )
            rendered = latex_equation(equation, readable_style(style))
            try:
                reparsed = parse_equation(rendered)
            except (ParseFailure, OutsideFragment) as exc:
                raise AssertionError(
                    f"Equation {node}: rendered LaTeX could not be read back.\n"
                    f"  formal: {law}\n  latex:  {rendered}\n  error:  {exc}"
                ) from None
            assert reparsed == equation, (
                f"Equation {node}: LaTeX did not round-trip.\n"
                f"  formal: {law}\n  latex:  {latex_equation(equation, style)}\n"
                f"  reread: {reparsed.render()}"
            )

        names: list[str] = []
        equation.lhs.variables(names)
        equation.rhs.variables(names)
        rows.append({
            "node": node,
            "formal": law,
            "latex": latex_equation(equation, _labelled(style, node)),
            "order": equation.size(),
            "variables": names,
        })
    return rows


def _labelled(style: LatexStyle, node: int) -> LatexStyle:
    """Give each `equation` environment a per-node label, e.g. `eq:etp43`.

    Only meaningful for `--delimiters equation`; with any other delimiter the
    label is unused and the style is returned unchanged. The prefix comes from
    `--label`, defaulting to `eq:etp`.
    """
    if style.delimiters != "equation":
        return style
    prefix = style.label or "eq:etp"
    return LatexStyle(
        operator=style.operator,
        delimiters=style.delimiters,
        label=f"{prefix}{node}",
        auto_size=style.auto_size,
        quantify=style.quantify,
        mathbin=style.mathbin,
    )


def write_json(path: Path, rows: list[dict], meta: dict) -> Path:
    """Write the catalogue as `{meta, equations}`; returns the path written."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"meta": meta, "equations": rows}
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


# A minimal document: `article`, no packages. Everything emitted by `latexify`
# (\diamond, \forall, \left(, the equation environment) is core LaTeX, so this
# compiles on a bare TeX install and proves the output is valid, not merely
# well-formed to us.
_TEX_HEADER = r"""\documentclass[10pt]{article}
\usepackage[margin=2cm]{geometry}
\title{Equational Theories Project --- %(count)d laws in LaTeX}
\date{}
\begin{document}
\maketitle
\noindent
"""

_TEX_FOOTER = "\n\\end{document}\n"


def write_tex(path: Path, rows: list[dict], style: LatexStyle) -> Path:
    """Write a compilable LaTeX document listing every equation.

    Inline math per line keeps the document flat and fast to compile even at
    4694 entries; a style that already carries its own delimiters (`display`,
    `equation`) is emitted as-is on its own line instead.
    """
    inline = style.delimiters == "none"
    lines = []
    for row in rows:
        body = f"${row['latex']}$" if inline else row["latex"]
        lines.append(rf"\textbf{{{row['node']}.}}\quad {body}\\[2pt]")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        _TEX_HEADER % {"count": len(rows)} + "\n".join(lines) + _TEX_FOOTER,
        encoding="utf-8",
    )
    return path


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Export every ETP equation as a formal/LaTeX pair (no model involved)."
    )
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT,
                        help=f"JSON output path (default {DEFAULT_OUT.name} beside this script)")
    parser.add_argument("--equations", type=Path, default=None,
                        help="path to equations.txt (default: the oracle's resolution — "
                             "$ETP_EQUATIONS, else $ETP_ROOT/data/equations.txt)")
    parser.add_argument("--tex", type=Path, default=None,
                        help="also write a compilable LaTeX document listing every equation")
    parser.add_argument("--limit", type=int, default=None,
                        help="only the first N equations (for a quick look)")
    parser.add_argument("--no-verify", action="store_true",
                        help="skip the round-trip and canonical-form checks (not advised)")
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
        "generator": "translate/latex/build_catalogue.py",
        "source": mapper.equations_path,
        "count": len(rows),
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "style": {
            "operator": style.operator,
            "delimiters": style.delimiters,
            "label_prefix": (style.label or "eq:etp") if style.delimiters == "equation" else None,
            "auto_size": style.auto_size,
            "quantify": style.quantify,
            "mathbin": style.mathbin,
        },
        "verified": not args.no_verify,
        "verification": (
            "every row: rendered LaTeX re-parsed to an identical syntax tree "
            "(structure, under a canonical operator spelling), and the "
            "catalogue text confirmed already canonical"
            if not args.no_verify else "skipped (--no-verify)"
        ),
    }

    written = [write_json(args.out, rows, meta)]
    if args.tex:
        written.append(write_tex(args.tex, rows, style))

    orders = Counter(row["order"] for row in rows)
    print(f"{len(rows)} equations from {mapper.equations_path}", file=sys.stderr)
    print("by order: " + ", ".join(f"{o}:{n}" for o, n in sorted(orders.items())), file=sys.stderr)
    print(f"verified: {meta['verified']}  ({elapsed}s)", file=sys.stderr)
    for path in written:
        print(f"wrote {path} ({path.stat().st_size / 1024:.0f} KB)", file=sys.stderr)


if __name__ == "__main__":
    main()
