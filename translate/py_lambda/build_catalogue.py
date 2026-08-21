"""Export the whole ETP catalogue as formal + Python-lambda pairs.

Walks every law in `equations.txt` (4694 in the current data drop), renders
each to a lambda predicate with `lambdify`, and writes one JSON file:

    {
      "meta":      { source, count, style, generated_at, verified, ... },
      "equations": [ { node, formal, py_lambda, order, variables }, ... ]
    }

`formal` is the catalogue line verbatim — line N *is* Equation N, which is the
invariant `NodeMapper` enforces when it loads the file, so `node` here is the
same identifier the implication graph and the semantic oracle use. The
`py_lambda` string itself carries neither the node number nor the formal text
— it is a bare `lambda op, …: … == …` — because these rows are test data for
representation-translation experiments and must not leak the answer key into
the representation. No separate "normalized" field is emitted: the catalogue
text is already in canonical form (variables renamed by first appearance, `◇`
as the operation), and the build asserts that rather than asking you to take
it on trust.

Three checks run over every row before anything is written, because a silently
mangled equation still looks like a plausible lambda:

  * **round trip** — the lambda is parsed with Python's own `ast` module and
    the resulting syntax tree must equal the original, parameter list
    included. This catches a swapped operand or a mis-nested subterm, the
    failure modes that would otherwise survive review.
  * **semantics** — the lambda is compiled and evaluated against a tree
    interpreter on every assignment of six small Cayley tables; the truth
    values must agree everywhere. The interpreter never sees the generated
    string, so this is an independent check that the code *computes* the law,
    not merely that it is shaped like it.
  * **canonical form** — the catalogue text must equal its own normalization,
    so the claim above stays true if the ETP data drop ever changes.

CLI:
    python3 build_catalogue.py                          # -> etp_equations_py_lambda.json
    python3 build_catalogue.py --out /tmp/etp.json --limit 40
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from pathlib import Path

from lambdify import (  # noqa: F401  (also performs the oracle sys.path bootstrap)
    OPNAME,
    ORACLE_DIR,
    TABLES,
    ReadBackFailure,
    equation_variables,
    py_lambda,
    read_back,
    semantically_agrees,
)
from mapper import NodeMapper  # noqa: E402  (available via lambdify's bootstrap)
from normalizer import normalize, parse_equation  # noqa: E402

DEFAULT_OUT = Path(__file__).parent / "etp_equations_py_lambda.json"


def build_rows(mapper: NodeMapper, *, verify: bool = True) -> list[dict]:
    """Render every catalogue law, verifying each row as it is built.

    Returns one record per equation in node order. Raises `AssertionError` on
    the first row that fails a check — a partially-wrong catalogue is worse
    than no catalogue, so this refuses to write one.
    """
    rows: list[dict] = []
    for index, law in enumerate(mapper.laws):
        node = index + 1
        equation = parse_equation(law)
        code = py_lambda(equation)

        if verify:
            canonical = normalize(equation).render()
            assert canonical == law, (
                f"Equation {node}: catalogue text {law!r} is not in canonical form "
                f"({canonical!r}); the no-normalized-field assumption no longer holds"
            )
            try:
                params, reparsed = read_back(code)
            except ReadBackFailure as exc:
                raise AssertionError(
                    f"Equation {node}: emitted lambda could not be read back.\n"
                    f"  formal: {law}\n  python: {code}\n  error:  {exc}"
                ) from None
            assert reparsed == equation, (
                f"Equation {node}: lambda did not round-trip.\n"
                f"  formal: {law}\n  python: {code}\n  reread: {reparsed.render()}"
            )
            assert params == equation_variables(equation), (
                f"Equation {node}: parameter list {params} does not match the law's "
                f"variables in first-appearance order"
            )
            assert semantically_agrees(equation, code), (
                f"Equation {node}: lambda disagrees with the tree interpreter on "
                f"some finite magma.\n  formal: {law}\n  python: {code}"
            )

        rows.append({
            "node": node,
            "formal": law,
            "py_lambda": code,
            "order": equation.size(),
            "variables": equation_variables(equation),
        })
    return rows


def write_json(path: Path, rows: list[dict], meta: dict) -> Path:
    """Write the catalogue as `{meta, equations}`; returns the path written."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"meta": meta, "equations": rows}
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Export every ETP equation as a formal/Python-lambda pair (no model involved)."
    )
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT,
                        help=f"JSON output path (default {DEFAULT_OUT.name} beside this script)")
    parser.add_argument("--equations", type=Path, default=None,
                        help="path to equations.txt (default: the oracle's resolution — "
                             "$ETP_EQUATIONS, else $ETP_ROOT/data/equations.txt)")
    parser.add_argument("--limit", type=int, default=None,
                        help="only the first N equations (for a quick look)")
    parser.add_argument("--no-verify", action="store_true",
                        help="skip the round-trip, semantic, and canonical-form checks "
                             "(not advised)")
    args = parser.parse_args()

    try:
        mapper = NodeMapper(str(args.equations)) if args.equations else NodeMapper()
    except SystemExit as exc:  # missing catalogue: re-raise with its own message
        raise SystemExit(str(exc)) from None

    if args.limit:
        mapper.laws = mapper.laws[: args.limit]

    started = time.monotonic()
    try:
        rows = build_rows(mapper, verify=not args.no_verify)
    except AssertionError as exc:
        raise SystemExit(f"verification failed, nothing written:\n{exc}") from None
    elapsed = round(time.monotonic() - started, 2)

    meta = {
        "generator": "translate/py_lambda/build_catalogue.py",
        "source": mapper.equations_path,
        "count": len(rows),
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "style": {
            "form": "lambda",
            "operator_name": OPNAME,
            "docstring": False,
            "node_in_representation": False,
        },
        "verified": not args.no_verify,
        "verification": (
            "every row: emitted lambda re-parsed (with Python's ast module) to an "
            "identical syntax tree with an identical parameter list, evaluated "
            f"against a tree interpreter on every assignment of {len(TABLES)} small "
            "Cayley tables, and the catalogue text confirmed already canonical"
            if not args.no_verify else "skipped (--no-verify)"
        ),
    }

    written = write_json(args.out, rows, meta)

    orders = Counter(row["order"] for row in rows)
    print(f"{len(rows)} equations from {mapper.equations_path}", file=sys.stderr)
    print("by order: " + ", ".join(f"{o}:{n}" for o, n in sorted(orders.items())), file=sys.stderr)
    print(f"verified: {meta['verified']}  ({elapsed}s)", file=sys.stderr)
    print(f"wrote {written} ({written.stat().st_size / 1024:.0f} KB)", file=sys.stderr)


if __name__ == "__main__":
    main()
