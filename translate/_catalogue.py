"""Shared machinery for the deterministic ETP representation catalogues.

The directories beside this file — `ssa/`, `slots/`, `rpn/`, `polish/`,
`tptp/`, `smtlib/`, `ascii_tree/`, `graphviz/`, `json_ast/`,
`confusable_vars/` — all do the same thing to the same 4694 laws: walk the
parse tree, emit one rendering per law, verify each rendering by reading it
back, and write `{meta, equations}`. Only the walk differs.

So the walk is all each directory holds. This module owns everything else: the
oracle bootstrap, the per-row checks, the JSON and listing writers, and both
CLIs. The earlier catalogues (`latex/`, `lean/`, `py_lambda/`,
`py_cayley_table/`, `text/`, `text2/`) predate it and each carry their own
copy — they are left alone rather than retrofitted, since rewriting a verified
catalogue to save duplication is a bad trade.

A directory supplies a `Representation` and gets the rest:

    REPRESENTATION = Representation(
        name="ssa", key="ssa", render=render, read_back=read_back, ...)

`render` turns an `Equation` into text; `read_back` turns that text into an
`Equation` again. The second is the load-bearing one — a rendering nobody can
read back is not evidence about anything, and structural equality of the two
trees is what catches a dropped bracket or a re-nested subterm.

## Reading back, and why it goes through the oracle

Every `read_back` here ends by handing a *canonical infix string* to
`normalizer.parse_equation`, rather than assembling `Op`/`Var` nodes directly.
The tree therefore comes from the same parser the semantic oracle uses, so a
successful round trip is evidence about that parser's reading and not about a
private one written to agree with itself. The per-directory reader only has to
recover the structure; if it recovers the wrong structure, the check fails.

## Matching up to renaming

`match="up-to-renaming"` compares `normalize()`d trees instead of raw ones. Only
`confusable_vars/` needs it, because renaming the variables is the whole point
of that rendering. This is not a weaker check than it looks: the oracle grades
reconstructions up to renaming anyway (`nl_test/` relies on exactly that), so
it is the same equivalence the experiment itself uses.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

# The oracle package is imported by path rather than installed: its modules
# import each other by top-level name and locate their own data with absolute
# paths, so putting the directory on sys.path is both necessary and sufficient.
ORACLE_DIR = Path(
    os.environ.get("TRANSLATE_ORACLE_DIR", Path(__file__).resolve().parent.parent / "oracle")
)
if str(ORACLE_DIR) not in sys.path:
    sys.path.insert(0, str(ORACLE_DIR))

from normalizer import (  # noqa: E402  (path bootstrap must run first)
    CANONICAL_OP,
    CANONICAL_VARS,
    Equation,
    Op,
    OutsideFragment,
    ParseFailure,
    Var,
    normalize,
    parse_equation,
)

MATCH_MODES = ("exact", "up-to-renaming")


@dataclass(frozen=True)
class Representation:
    """One rendering of the ETP catalogue.

    Fields:
      name       directory name, and the suffix of the output files.
      key        the per-row JSON key holding the rendering.
      render     `Equation -> str`.
      read_back  `str -> Equation`, raising `ParseFailure`/`OutsideFragment`
                 on anything unreadable.
      style      recorded verbatim in `meta.style`, so a catalogue always says
                 which options produced it.
      match      "exact" (default) or "up-to-renaming"; see the module
                 docstring.
      multiline  whether a rendering spans several lines, which changes only
                 how the plain-text listing is laid out.
      blurb      one line for `--help`.
    """

    name: str
    key: str
    render: Callable[[Equation], str]
    read_back: Callable[[str], Equation]
    blurb: str
    style: dict = field(default_factory=dict)
    match: str = "exact"
    multiline: bool = False

    def __post_init__(self):
        if self.match not in MATCH_MODES:
            raise ValueError(f"match must be one of {MATCH_MODES}, got {self.match!r}")


# -- helpers shared by the renderers -----------------------------------------


def infix(term: Var | Op, *, top: bool = True) -> str:
    """Canonical infix text for a term — the form `parse_equation` reads.

    Every reader in these directories builds its result with this, so they all
    hand the oracle's parser the same shape of input.
    """
    if isinstance(term, Var):
        return term.name
    inner = f"{infix(term.left, top=False)} {CANONICAL_OP} {infix(term.right, top=False)}"
    return inner if top else f"({inner})"


def variables(equation: Equation) -> list[str]:
    """The equation's variables in first-appearance order."""
    names: list[str] = []
    equation.lhs.variables(names)
    equation.rhs.variables(names)
    return names


def slot_name(index: int) -> str:
    """The canonical variable letter for a 1-based slot number."""
    if not 1 <= index <= len(CANONICAL_VARS):
        raise ParseFailure(f"variable slot out of range 1..{len(CANONICAL_VARS)}: {index}")
    return CANONICAL_VARS[index - 1]


# -- verification -------------------------------------------------------------


def same(rep: Representation, a: Equation, b: Equation) -> bool:
    """Whether two trees count as equal under this representation's match mode."""
    return normalize(a) == normalize(b) if rep.match == "up-to-renaming" else a == b


def check_row(rep: Representation, node: int, law: str, rendered: str) -> None:
    """Round-trip and canonical-form checks for one row.

    Raises `AssertionError` naming the equation, because a partially-wrong
    catalogue is worse than no catalogue and the build refuses to write one.
    """
    equation = parse_equation(law)

    canonical = normalize(equation).render()
    assert canonical == law, (
        f"Equation {node}: catalogue text {law!r} is not in canonical form "
        f"({canonical!r}); the no-normalized-field assumption no longer holds"
    )

    try:
        reread = rep.read_back(rendered)
    except (ParseFailure, OutsideFragment) as exc:
        raise AssertionError(
            f"Equation {node}: rendered {rep.name} could not be read back.\n"
            f"  formal: {law}\n  rendered:\n{_indent(rendered)}\n  error:  {exc}"
        ) from None
    assert same(rep, reread, equation), (
        f"Equation {node}: {rep.name} did not round-trip "
        f"({rep.match}).\n  formal: {law}\n  rendered:\n{_indent(rendered)}\n"
        f"  reread: {reread.render()}"
    )


def check_distinct(rows: list[dict], key: str) -> None:
    """Assert no two equations produced the same rendering.

    A collision means the rendering has lost something that distinguishes two
    laws, which no amount of per-row checking would reveal; the message names
    the colliding nodes so the counterexample is immediately in hand.
    """
    seen: dict[str, int] = {}
    for row in rows:
        first = seen.setdefault(row[key], row["node"])
        assert first == row["node"], (
            f"Equations {first} and {row['node']} produced the same rendering — it "
            f"is not injective.\n{_indent(row[key])}"
        )


def _indent(text: str) -> str:
    """Indent a possibly multi-line rendering for an error message."""
    return "\n".join("    " + line for line in text.splitlines())


# -- building -----------------------------------------------------------------


def build_rows(rep: Representation, mapper, *, verify: bool = True) -> list[dict]:
    """Render every catalogue law, verifying each row as it is built."""
    rows: list[dict] = []
    for index, law in enumerate(mapper.laws):
        node = index + 1
        equation = parse_equation(law)
        rendered = rep.render(equation)
        if verify:
            check_row(rep, node, law, rendered)
        rows.append({
            "node": node,
            "formal": law,
            rep.key: rendered,
            "order": equation.size(),
            "variables": variables(equation),
        })
    if verify:
        check_distinct(rows, rep.key)
    return rows


def write_json(path: Path, rows: list[dict], meta: dict) -> Path:
    """Write the catalogue as `{meta, equations}`; returns the path written."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"meta": meta, "equations": rows},
                               ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def write_listing(path: Path, rows: list[dict], rep: Representation) -> Path:
    """Write a plain listing of every rendering, for skimming.

    Single-line renderings get `N. text`; multi-line ones get a commented
    header and a blank line between entries, so the file stays readable.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    if rep.multiline:
        body = "".join(f"# Equation {r['node']}\n{r[rep.key]}\n\n" for r in rows)
    else:
        body = "".join(f"{r['node']}. {r[rep.key]}\n" for r in rows)
    path.write_text(body, encoding="utf-8")
    return path


# -- the two CLIs -------------------------------------------------------------


def resolve(spec: str) -> str:
    """Expand an ETP equation number to its catalogue text; pass text through."""
    if not spec.strip().isdigit():
        return spec
    from mapper import NodeMapper

    mapper = resolve.mapper = getattr(resolve, "mapper", None) or NodeMapper()
    node = int(spec)
    if not 1 <= node <= len(mapper.laws):
        raise SystemExit(f"ETP equation number out of range 1..{len(mapper.laws)}: {node}")
    return mapper.law_text(node)


def analyze(rep: Representation, text: str) -> dict:
    """Parse + render, returning errors as data rather than exceptions."""
    try:
        equation = parse_equation(text)
    except ParseFailure as exc:
        return {"input": text, "ok": False, "error": "parse-failure", "reason": str(exc)}
    except OutsideFragment as exc:
        return {"input": text, "ok": False, "error": "outside-fragment", "reason": str(exc)}
    return {
        "input": text,
        "ok": True,
        "formal": equation.render(),
        rep.key: rep.render(equation),
        "order": equation.size(),
        "variables": variables(equation),
    }


def verify_round_trip(rep: Representation, text: str) -> bool:
    """Whether the rendering of `text` reads back to the same equation."""
    equation = parse_equation(text)
    try:
        reread = rep.read_back(rep.render(equation))
    except (ParseFailure, OutsideFragment):
        return False
    return same(rep, reread, equation)


def selftest(rep: Representation, cases: tuple, bad: tuple = ()) -> None:
    """Pinned renderings, round trips, and refusals; exit non-zero on failure.

    `cases` are `(formal, expected_rendering)`; `bad` are `(rendering, why)`
    pairs the reader must refuse rather than silently misread — the practical
    form of whatever unambiguity claim the representation makes.
    """
    failures = 0
    for text, expected in cases:
        got = rep.render(parse_equation(text))
        ok = got == expected
        failures += not ok
        sep = "\n" if rep.multiline else " "
        print(f"[{'ok ' if ok else 'FAIL'}] {text!r} ->{sep}{got}"
              + ("" if ok else f"\n       expected:\n{expected}"))
        if not ok:
            continue

    for text, _ in cases:
        ok = verify_round_trip(rep, text)
        failures += not ok
        if not ok:
            print(f"[FAIL] round trip {text!r}")
    print(f"[ok ] round trip: {len(cases)} equations ({rep.match})")

    for rendering, why in bad:
        try:
            rep.read_back(rendering)
        except (ParseFailure, OutsideFragment, AssertionError) as exc:
            print(f"[ok ] refused: {why:<34} ({str(exc)[:44]})")
        else:
            failures += 1
            print(f"[FAIL] accepted malformed input: {why} ({rendering!r})")

    for text, expected_error in (("a * b * c = c", "parse-failure"),
                                 ("a * b = b + a", "outside-fragment")):
        result = analyze(rep, text)
        ok = not result["ok"] and result["error"] == expected_error
        failures += not ok
        print(f"[{'ok ' if ok else 'FAIL'}] {text!r} -> {result.get('error')}")

    print("selftest:", "all passed" if not failures else f"{failures} failures")
    raise SystemExit(1 if failures else 0)


def single_main(factory: Callable, cases: tuple, bad: tuple = (),
                add_args: Callable | None = None) -> None:
    """CLI for a single-equation translator: render arguments, or self-test."""
    probe = factory(argparse.Namespace(**_defaults(add_args)))
    parser = argparse.ArgumentParser(
        description=f"Convert ETP magma equations to {probe.blurb} (no model involved)."
    )
    parser.add_argument("equations", nargs="*",
                        help="equation strings and/or ETP equation numbers")
    parser.add_argument("--json", action="store_true",
                        help="emit a JSON array of records instead of text")
    parser.add_argument("--selftest", action="store_true")
    if add_args:
        add_args(parser)
    args = parser.parse_args()
    rep = factory(args)

    if args.selftest:
        selftest(rep, cases, bad)
    if not args.equations:
        parser.error("give at least one equation or ETP number (or use --selftest)")

    records = [analyze(rep, resolve(spec)) for spec in args.equations]
    if args.json:
        print(json.dumps(records, ensure_ascii=False, indent=2))
        return
    for record in records:
        if not record["ok"]:
            print(f"input:  {record['input']}\nerror:  {record['error']}\n"
                  f"reason: {record['reason']}\n")
            continue
        print(f"formal: {record['formal']}")
        print(f"{rep.name}:\n{record[rep.key]}" if rep.multiline
              else f"{rep.name}: {record[rep.key]}")
        print(f"order:  {record['order']}   variables: {', '.join(record['variables'])}\n")
    if any(not r["ok"] for r in records):
        raise SystemExit(1)


def catalogue_main(factory: Callable, script: str, add_args: Callable | None = None) -> None:
    """CLI for a catalogue build: render all 4694 laws, verify, write."""
    here = Path(script).resolve().parent
    probe = factory(argparse.Namespace(**_defaults(add_args)))
    parser = argparse.ArgumentParser(
        description=f"Export every ETP equation as a formal/{probe.name} pair "
                    "(no model involved)."
    )
    default_out = here / f"etp_equations_{probe.name}.json"
    parser.add_argument("--out", type=Path, default=default_out,
                        help=f"JSON output path (default {default_out.name})")
    parser.add_argument("--equations", type=Path, default=None,
                        help="path to equations.txt (default: the oracle's resolution)")
    parser.add_argument("--listing", type=Path, default=None,
                        help="also write a plain listing of every rendering")
    parser.add_argument("--limit", type=int, default=None,
                        help="only the first N equations (for a quick look)")
    parser.add_argument("--no-verify", action="store_true",
                        help="skip the round-trip and distinctness checks (not advised)")
    if add_args:
        add_args(parser)
    args = parser.parse_args()
    rep = factory(args)

    from mapper import NodeMapper
    mapper = NodeMapper(str(args.equations)) if args.equations else NodeMapper()
    if args.limit:
        mapper.laws = mapper.laws[: args.limit]

    started = time.monotonic()
    try:
        rows = build_rows(rep, mapper, verify=not args.no_verify)
    except AssertionError as exc:
        raise SystemExit(f"verification failed, nothing written:\n{exc}") from None
    elapsed = round(time.monotonic() - started, 2)

    meta = {
        "generator": f"translate/{rep.name}/build_catalogue.py",
        "source": mapper.equations_path,
        "count": len(rows),
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "representation": rep.blurb,
        "style": rep.style,
        "verified": not args.no_verify,
        "verification": (
            f"every row: rendering read back to an identical syntax tree "
            f"({rep.match}), and the catalogue text confirmed already canonical; "
            f"across the catalogue: all renderings confirmed pairwise distinct"
            if not args.no_verify else "skipped (--no-verify)"
        ),
    }

    written = [write_json(args.out, rows, meta)]
    if args.listing:
        written.append(write_listing(args.listing, rows, rep))

    orders = Counter(row["order"] for row in rows)
    sizes = [len(row[rep.key]) for row in rows]
    print(f"{len(rows)} equations from {mapper.equations_path}", file=sys.stderr)
    print("by order: " + ", ".join(f"{o}:{n}" for o, n in sorted(orders.items())),
          file=sys.stderr)
    print(f"characters per rendering: min {min(sizes)}, mean {sum(sizes)/len(sizes):.1f}, "
          f"max {max(sizes)}", file=sys.stderr)
    print(f"verified: {meta['verified']}  ({elapsed}s)", file=sys.stderr)
    for path in written:
        print(f"wrote {path} ({path.stat().st_size / 1024:.0f} KB)", file=sys.stderr)


def _defaults(add_args: Callable | None) -> dict:
    """The default value of every flag `add_args` registers.

    Lets `factory` be called before the real parse, to get at `blurb`/`name`
    for the help text without duplicating the defaults in each directory.
    """
    if add_args is None:
        return {}
    probe = argparse.ArgumentParser()
    add_args(probe)
    return vars(probe.parse_args([]))


__all__ = [
    "CANONICAL_OP", "CANONICAL_VARS", "Equation", "Op", "OutsideFragment",
    "ParseFailure", "Representation", "Var", "analyze", "build_rows",
    "catalogue_main", "check_distinct", "check_row", "infix", "normalize",
    "parse_equation", "resolve", "same", "selftest", "single_main", "slot_name",
    "variables", "verify_round_trip", "write_json", "write_listing",
]
