"""Export the whole ETP catalogue as formal + Lean 4 declaration pairs.

Walks every law in `equations.txt` (4694 in the current data drop), renders each
to a complete Lean 4 declaration with `leanify`, and writes one JSON file:

    {
      "meta":      { source, count, style, generated_at, verified, ... },
      "equations": [ { node, formal, name, lean, statement, order, variables }, ... ]
    }

`formal` is the catalogue line verbatim — line N *is* Equation N, which is the
invariant `NodeMapper` enforces when it loads the file — and `name` is the
ETP's own `EquationN`, so these rows join directly against the implication
graph, the semantic oracle, and the ETP repository's declarations. No separate
"normalized" field is emitted: the catalogue text is already in canonical form
(variables renamed by first appearance, `◇` as the operation), and the build
asserts that rather than asking you to take it on trust.

Three checks run over every row before anything is written, because a silently
mangled equation still looks like a plausible declaration:

  * **round trip** — the emitted declaration string is read back (declaration
    head and `∀ … : G,` binder stripped, body re-parsed) and the resulting
    syntax tree must equal the original, binder list included. This catches a
    dropped or misplaced parenthesis, which is the failure mode that would
    otherwise survive review.
  * **canonical form** — the catalogue text must equal its own normalization,
    so the claim above stays true if the ETP data drop ever changes.
  * **source cross-check** — when the ETP repository's Lean source is present
    next to `equations.txt`, every `equation N := <law>` command in
    `equational_theories/Equations/` is extracted and its law must be
    byte-identical to catalogue line N. This pins the naming claim itself:
    the `EquationN` emitted here states exactly what the ETP's `EquationN`
    states. (The ETP also declares 20 extra laws beyond the catalogue —
    `Equation5093` and friends, of order > 4; they have no catalogue node and
    are ignored.)

`--lean` additionally writes a single self-contained Lean file declaring all
4694 laws — the `Magma` class and `◇` notation are included, copied from the
ETP's `Magma.lean`, so it elaborates with plain `lean`, no Lake project and no
Mathlib — and `--compile` runs `lean` on it: the end-to-end check that the
output is not just parseable by us but valid Lean 4.

CLI:
    python3 build_catalogue.py                          # -> etp_equations_lean.json
    python3 build_catalogue.py --lean etp_equations.lean --compile
    python3 build_catalogue.py --out /tmp/etp.json --decl def --limit 40
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path

from leanify import (  # noqa: F401  (also performs the oracle sys.path bootstrap)
    CARRIER,
    ORACLE_DIR,
    LeanStyle,
    add_style_args,
    equation_variables,
    lean_decl,
    lean_name,
    lean_statement,
    read_back,
    style_from_args,
)
from mapper import NodeMapper  # noqa: E402  (available via leanify's bootstrap)
from normalizer import (  # noqa: E402
    OutsideFragment,
    ParseFailure,
    normalize,
    parse_equation,
)

DEFAULT_OUT = Path(__file__).parent / "etp_equations_lean.json"


def build_rows(mapper: NodeMapper, style: LeanStyle, *, verify: bool = True) -> list[dict]:
    """Render every catalogue law, verifying each row as it is built.

    Returns one record per equation in node order. Raises `AssertionError` on
    the first row that fails a check — a partially-wrong catalogue is worse than
    no catalogue, so this refuses to write one.
    """
    rows: list[dict] = []
    for index, law in enumerate(mapper.laws):
        node = index + 1
        equation = parse_equation(law)
        decl = lean_decl(equation, style, node)

        if verify:
            canonical = normalize(equation).render()
            assert canonical == law, (
                f"Equation {node}: catalogue text {law!r} is not in canonical form "
                f"({canonical!r}); the no-normalized-field assumption no longer holds"
            )
            try:
                binders, reparsed = read_back(decl)
            except (ParseFailure, OutsideFragment) as exc:
                raise AssertionError(
                    f"Equation {node}: emitted Lean could not be read back.\n"
                    f"  formal: {law}\n  lean:   {decl}\n  error:  {exc}"
                ) from None
            assert reparsed == equation, (
                f"Equation {node}: Lean did not round-trip.\n"
                f"  formal: {law}\n  lean:   {decl}\n  reread: {reparsed.render()}"
            )
            assert binders == equation_variables(equation), (
                f"Equation {node}: binder list {binders} does not match the law's "
                f"variables in first-appearance order"
            )

        rows.append({
            "node": node,
            "formal": law,
            "name": lean_name(style, node),
            "lean": decl,
            "statement": lean_statement(equation),
            "order": equation.size(),
            "variables": equation_variables(equation),
        })
    return rows


# -- Cross-check against the ETP's own Lean source ----------------------------

# One `equation N := <law>` command, possibly commented out: the laws moved to
# Equations/Basic.lean stay behind as comments in the Eqns*.lean shards, and
# both copies are checked.
_ETP_EQUATION = re.compile(r"^(?:--\s*)?equation\s+(\d+)\s*:=\s*(.+?)\s*$")


def crosscheck_etp_source(mapper: NodeMapper, rows: list[dict]) -> dict:
    """Compare every row against the ETP repository's own declarations.

    Locates `equational_theories/Equations/` relative to the `equations.txt`
    that produced the rows (repo layout: `data/equations.txt` and
    `equational_theories/Equations/*.lean` share a root), extracts every
    `equation N := <law>` command, and requires the law for node N to be
    byte-identical to the catalogue line — which is what makes "our
    `EquationN` is the ETP's `EquationN`" a checked statement rather than a
    naming convention. Missing source degrades to `performed: False` (the
    JSON catalogue can be built from `equations.txt` alone); any mismatch or
    missing node raises `AssertionError` and aborts the build.
    """
    source_dir = (
        Path(mapper.equations_path).resolve().parent.parent
        / "equational_theories" / "Equations"
    )
    if not source_dir.is_dir():
        return {"performed": False,
                "reason": f"ETP Lean source not found at {source_dir}"}

    found: dict[int, str] = {}
    for path in sorted(source_dir.glob("*.lean")):
        for line in path.read_text(encoding="utf-8").splitlines():
            match = _ETP_EQUATION.match(line)
            if not match:
                continue
            node, law = int(match.group(1)), match.group(2)
            assert found.setdefault(node, law) == law, (
                f"ETP source declares equation {node} twice with different laws: "
                f"{found[node]!r} vs {law!r}"
            )

    for row in rows:
        law = found.get(row["node"])
        assert law is not None, (
            f"Equation {row['node']} is in the catalogue but has no "
            f"`equation` command under {source_dir}"
        )
        assert law == row["formal"], (
            f"Equation {row['node']}: catalogue and ETP Lean source disagree.\n"
            f"  catalogue: {row['formal']}\n  ETP source: {law}"
        )

    beyond = sum(1 for node in found if node > len(mapper.laws))
    return {
        "performed": True,
        "source": str(source_dir),
        "matched": len(rows),
        "etp_extra_laws_ignored": beyond,
    }


# -- Output files -------------------------------------------------------------


def write_json(path: Path, rows: list[dict], meta: dict) -> Path:
    """Write the catalogue as `{meta, equations}`; returns the path written."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"meta": meta, "equations": rows}
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


# The self-contained header: `universe u` for the ETP's universe-polymorphic
# form, and the `Magma` class + `◇` notation copied from the ETP's
# `Magma.lean` so the file needs no imports at all — everything after this is
# core Lean 4, which is what lets plain `lean` (no Lake, no Mathlib) elaborate
# it and prove the output is valid Lean, not merely well-formed to us.
_LEAN_HEADER = """/-!
The {count} equational laws of the Equational Theories Project, rendered as
explicit Lean 4 declarations.

Generated by semantic-diffchecking/translate/lean/build_catalogue.py from
{source} — do not edit by hand.

Each `{prefix}N` below states exactly what the ETP declaration `EquationN`
states (the build cross-checks every law against the `equation N := ...`
commands in the ETP source when that source is present). The `Magma` class and
`◇` notation are copied from the ETP's `Magma.lean` so this file is
self-contained: it elaborates with plain `lean`, no Lake project and no
Mathlib.
-/
{universe_line}
/-- One binary operation on a carrier type, nothing assumed about it.
Copied from the ETP's `Magma.lean`. -/
class Magma (α : Type _) where
  /-- `a ◇ b` denotes a binary operation of `a` and `b`. -/
  op : α → α → α

@[inherit_doc] infix:65 " ◇ " => Magma.op

"""


def write_lean(path: Path, rows: list[dict], style: LeanStyle, source: str) -> Path:
    """Write one self-contained Lean file declaring every law.

    One declaration per line (two with `--docstring`), in node order, under
    the header above. Refuses `--universe star`: `Type*` is Mathlib notation,
    and this file's whole point is to elaborate without Mathlib.
    """
    if style.universe == "star":
        raise SystemExit(
            "--lean with --universe star: `Type*` is Mathlib notation and the "
            "self-contained file has no imports; use --universe u or zero"
        )
    header = _LEAN_HEADER.format(
        count=len(rows),
        source=source,
        prefix=style.prefix,
        universe_line="\nuniverse u\n" if style.universe == "u" else "",
    )
    body = "\n".join(row["lean"] for row in rows)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(header + body + "\n", encoding="utf-8")
    return path


def compile_lean(path: Path) -> dict:
    """Elaborate the written file with `lean`; the end-to-end validity check.

    Uses whichever `lean` is on PATH (under elan, the default toolchain — the
    file is core-only, so any recent Lean 4 will do). Failure aborts with
    Lean's own diagnostics; success returns the toolchain and timing for
    `meta`. Expect roughly a minute for the full catalogue.
    """
    lean = shutil.which("lean")
    if lean is None:
        raise SystemExit("--compile: no `lean` on PATH (install via elan) — "
                         "the .lean file was still written")
    version = subprocess.run([lean, "--version"], capture_output=True, text=True,
                             check=True).stdout.strip()
    started = time.monotonic()
    result = subprocess.run([lean, str(path)], capture_output=True, text=True)
    elapsed = round(time.monotonic() - started, 1)
    if result.returncode != 0:
        raise SystemExit(
            f"`lean {path}` failed after {elapsed}s:\n{result.stdout}{result.stderr}"
        )
    return {"lean": version, "seconds": elapsed}


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Export every ETP equation as a formal/Lean-4 pair (no model involved)."
    )
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT,
                        help=f"JSON output path (default {DEFAULT_OUT.name} beside this script)")
    parser.add_argument("--equations", type=Path, default=None,
                        help="path to equations.txt (default: the oracle's resolution — "
                             "$ETP_EQUATIONS, else $ETP_ROOT/data/equations.txt)")
    parser.add_argument("--lean", type=Path, default=None,
                        help="also write a self-contained Lean file declaring every equation")
    parser.add_argument("--compile", action="store_true",
                        help="run `lean` on the --lean file after writing it (requires --lean)")
    parser.add_argument("--limit", type=int, default=None,
                        help="only the first N equations (for a quick look)")
    parser.add_argument("--no-verify", action="store_true",
                        help="skip the round-trip, canonical-form, and ETP-source "
                             "checks (not advised)")
    add_style_args(parser)
    args = parser.parse_args()

    if args.compile and not args.lean:
        parser.error("--compile requires --lean")

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
        crosscheck = (
            crosscheck_etp_source(mapper, rows)
            if not args.no_verify
            else {"performed": False, "reason": "skipped (--no-verify)"}
        )
    except AssertionError as exc:
        raise SystemExit(f"verification failed, nothing written:\n{exc}") from None
    elapsed = round(time.monotonic() - started, 2)

    written = []
    if args.lean:
        written.append(write_lean(args.lean, rows, style, mapper.equations_path))
    compiled = compile_lean(args.lean) if args.compile else None

    meta = {
        "generator": "translate/lean/build_catalogue.py",
        "source": mapper.equations_path,
        "count": len(rows),
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "style": {
            "decl": style.decl,
            "universe": style.universe,
            "prefix": style.prefix,
            "docstring": style.docstring,
            "carrier": CARRIER,
        },
        "verified": not args.no_verify,
        "verification": (
            "every row: emitted declaration read back to an identical syntax tree "
            "with an identical binder list, and the catalogue text confirmed "
            "already canonical"
            if not args.no_verify else "skipped (--no-verify)"
        ),
        "etp_source_crosscheck": crosscheck,
        "compiled": compiled,
    }
    written.insert(0, write_json(args.out, rows, meta))

    orders = Counter(row["order"] for row in rows)
    print(f"{len(rows)} equations from {mapper.equations_path}", file=sys.stderr)
    print("by order: " + ", ".join(f"{o}:{n}" for o, n in sorted(orders.items())), file=sys.stderr)
    print(f"verified: {meta['verified']}  ({elapsed}s)", file=sys.stderr)
    if crosscheck.get("performed"):
        print(f"ETP source cross-check: {crosscheck['matched']} matched "
              f"({crosscheck['etp_extra_laws_ignored']} ETP laws beyond the "
              f"catalogue ignored)", file=sys.stderr)
    else:
        print(f"ETP source cross-check: not performed — {crosscheck['reason']}",
              file=sys.stderr)
    if compiled:
        print(f"compiled: {compiled['lean']} ({compiled['seconds']}s)", file=sys.stderr)
    for path in written:
        print(f"wrote {path} ({path.stat().st_size / 1024:.0f} KB)", file=sys.stderr)


if __name__ == "__main__":
    main()
