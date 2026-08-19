# `translate/latex` — ETP formal equations → LaTeX, deterministically

An ETP law is a small, fully specified object: one binary operation, some
variables, an equality. Turning it into LaTeX is a structural rewrite of its
parse tree, so **no model is involved anywhere in this directory** — there is
nothing here to guess at, and a guess would introduce exactly the kind of
silent drift this project exists to measure.

```
formal (ETP)                       LaTeX                                        typeset
x ◇ y = y ◇ x                      x \diamond y = y \diamond x                  x ⋄ y = y ⋄ x
x ◇ (y ◇ z) = (x ◇ y) ◇ z          x \diamond (y \diamond z) = ...              x ⋄ (y ⋄ z) = (x ⋄ y) ⋄ z
(x ◇ y) ◇ z = (w ◇ u) ◇ v          (x \diamond y) \diamond z = ...              (x ⋄ y) ⋄ z = (w ⋄ u) ⋄ v
```

The parse tree comes from [`../../oracle/normalizer.py`](../../oracle/README.md):
`parse_equation` returns `Equation(lhs, rhs)` over `Op(left, right)` and
`Var(name)` nodes, and `latexify` walks it. Reusing the oracle's parser rather
than writing a second one is deliberate — a private parser here could disagree
with the one the semantic oracle uses, and a LaTeX rendering would then no
longer be evidence about the same equation.

## Files

| file | role |
|---|---|
| `latexify.py` | the renderer: `LatexStyle`, `to_latex`, `analyze`, `verify_round_trip`, a CLI, and `--selftest` |
| `build_catalogue.py` | export all 4694 ETP laws to JSON (and, with `--tex`, to a compilable document) |
| `etp_equations_latex.json` | the generated catalogue — 4694 formal/LaTeX pairs, 1.1 MB |

Nothing needs installing: system `python3` plus a copy of the ETP
`equations.txt` (located exactly as [`../../oracle`](../../oracle/README.md)
locates it — `$ETP_EQUATIONS`, else `$ETP_ROOT/data/equations.txt`, else
`~/equational_theories/...`; or pass `--equations`).

## The generated catalogue

```bash
python3 build_catalogue.py                      # -> etp_equations_latex.json
```

```json
{
  "meta": {
    "generator": "translate/latex/build_catalogue.py",
    "source": "/home/malpat/equational_theories/data/equations.txt",
    "count": 4694,
    "generated_at": "2026-08-09T06:50:08Z",
    "style": { "operator": "\\diamond", "delimiters": "none", "...": null },
    "verified": true,
    "verification": "every row: rendered LaTeX re-parsed to an identical syntax tree ..."
  },
  "equations": [
    { "node": 43, "formal": "x ◇ y = y ◇ x", "latex": "x \\diamond y = y \\diamond x",
      "order": 2, "variables": ["x", "y"] }
  ]
}
```

`node` is the ETP equation number — line N of `equations.txt` *is* Equation N,
the invariant `NodeMapper` enforces when it loads the file — so these rows join
directly against the implication graph and the semantic oracle.

There is deliberately **no `normalized` field**: the catalogue text is already
canonical (variables renamed by first appearance, `◇` as the operation), and the
build asserts that for every row rather than asking you to take it on trust.

By order: 2 laws of order 0, 5 of order 1, 39 of order 2, 364 of order 3, and
4284 of order 4.

| flag | meaning |
|---|---|
| `--out PATH` | JSON output path (default `etp_equations_latex.json` beside the script) |
| `--equations PATH` | a specific `equations.txt` |
| `--tex PATH` | also write a LaTeX document listing every equation — compiles with `pdflatex`, no packages beyond `geometry` |
| `--limit N` | only the first N equations |
| `--no-verify` | skip the per-row checks (not advised) |
| *style flags* | as below; the chosen style is recorded in `meta` |

## Rendering one equation

```bash
python3 latexify.py "x ◇ (y ◇ z) = (x ◇ y) ◇ z"
# formal: x ◇ (y ◇ z) = (x ◇ y) ◇ z
# latex:  x \diamond (y \diamond z) = (x \diamond y) \diamond z
# order:  4   variables: x, y, z

python3 latexify.py 43 4512 --delimiters inline    # bare integers are ETP numbers
python3 latexify.py --operator "\circ" --quantify 43
python3 latexify.py --json 43                      # records, for piping
python3 latexify.py --selftest                     # rendering + round trip + error cases
```

### Style

| flag | default | effect |
|---|---|---|
| `--operator` | `\diamond` | the operation's LaTeX command. Tested: `\diamond \circ \cdot \ast \star \bullet \otimes` |
| `--delimiters` | `none` | `none` (bare formula), `inline` (`$…$`), `display` (`\[…\]`), `equation` (environment, takes a label) |
| `--label` | `eq:etp` | label for the `equation` environment; `build_catalogue.py` appends the node number (`eq:etp43`) |
| `--auto-size` | off | `\left( … \right)` instead of plain parentheses |
| `--quantify` | off | prefix `\forall x y z: ` over the law's variables |
| `--mathbin` | off | wrap the operator in `\mathbin{…}` — needed only for a custom macro that is not already a binary-operator symbol |

From Python:

```python
from latexify import LatexStyle, to_latex, analyze

to_latex("x ◇ y = y ◇ x")                                   # 'x \\diamond y = y \\diamond x'
to_latex("a*(b*c) = (a*b)*c", LatexStyle(operator=r"\circ", delimiters="inline"))
analyze("a * b * c = c")   # {'ok': False, 'error': 'parse-failure', 'reason': '...'}
```

`to_latex` raises the oracle's `ParseFailure` / `OutsideFragment` for anything
that is not a single-operation magma identity; `analyze` returns those as data.

## Decisions worth knowing

**Every nested operator is parenthesized, on both sides.** `Op(Op(x,y),z)`
renders as `(x \diamond y) \diamond z`, not `x \diamond y \diamond z`. No
parentheses are dropped by an associativity convention, because the magma
operation is not associative — a reader who resolved a bare chain left-to-right
would be reading a genuinely different law. This matches the catalogue's own
notation.

**Multi-character variable names get `\mathit{…}`.** ETP only ever uses single
letters, where math italic is already right; a name like `foo` would otherwise
be set as the product f·o·o. The parser accepts such names from other sources.

**The `\forall` prefix uses spaces and a plain colon** — `\forall x y z: `, not
`\forall x, y, z\colon`. Both spellings would typeset slightly better, and both
would break the round-trip check below: the oracle's `strip_noise` recognises a
quantifier prefix ending in `,` `.` or `:`, and its variable-list pattern is
non-greedy, so a comma-separated list leaves `y, z: …` behind. Staying readable
by this project's own parser is worth more than the spacing. (That is a
limitation of the stripper's regex, not of the equation — worth knowing if you
ever feed hand-written LaTeX back into the oracle.)

## Verification

Three independent checks, all runnable here:

| check | what it proves | how |
|---|---|---|
| round trip | the *structure* is right — parenthesization, variable placement, orientation. Renders each law, parses the LaTeX back with the oracle's parser, and requires the syntax trees to be **equal** (frozen dataclasses, so `==` compares shape and names exactly) | every row of `build_catalogue.py`; 9 styles × 8 equations in `latexify.py --selftest` |
| canonical form | the catalogue text really is already normalized, so omitting a `normalized` field stays honest | every row of `build_catalogue.py` |
| compilation | the output is valid LaTeX, not merely well-formed to us | `build_catalogue.py --tex out.tex && pdflatex out.tex` |

A round-trip failure aborts the build with the offending node, before anything
is written — a partially-wrong catalogue is worse than none. It is also the
check that matters most: a dropped parenthesis still *looks* like a plausible
equation, and nothing else would catch it.

Two style options cannot be read back by the oracle's stripper — an `equation`
environment (document structure, not math wrapping) and a `\mathbin`-wrapped or
otherwise unknown operator macro. `readable_style` neutralizes those before the
round trip, so the check still covers the structure; the operator's *spelling*
is a literal substitution into that structure, and `pdflatex` is what validates
it.

**Checked on this machine:** all 4694 equations round-trip and compile
(`pdflatex` → 98 pages, no errors), and the typeset first page was inspected
against the catalogue. `--delimiters equation`, `--quantify`, `--auto-size`,
`--operator \circ`, `--operator \star --delimiters inline`, and
`--mathbin --operator \mathsf{op}` each build and compile.
