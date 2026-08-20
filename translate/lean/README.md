# `translate/lean` — ETP formal equations → Lean 4 declarations, deterministically

An ETP law is a small, fully specified object: one binary operation, some
variables, an equality. Turning it into a Lean 4 declaration is a structural
rewrite of its parse tree, so **no model is involved anywhere in this
directory** — there is nothing here to guess at, and a guess would introduce
exactly the kind of silent drift this project exists to measure.

The target form is the ETP's own. In the [Equational Theories Project
repository](https://github.com/teorth/equational_theories), the command
`equation 43 := x ◇ y = y ◇ x` elaborates (via `Equations/Command.lean`) to a
reducible definition whose surface Lean is what this directory emits — the
complete signature, types and all:

```
formal (ETP)                 Lean 4
x ◇ y = y ◇ x                abbrev Equation43 (G : Type u) [Magma G] : Prop := ∀ x y : G, x ◇ y = y ◇ x
x = x ◇ (x ◇ x)              abbrev Equation8 (G : Type u) [Magma G] : Prop := ∀ x : G, x = x ◇ (x ◇ x)
x ◇ (y ◇ z) = (x ◇ y) ◇ z    abbrev Equation4512 (G : Type u) [Magma G] : Prop := ∀ x y z : G, x ◇ (y ◇ z) = (x ◇ y) ◇ z
```

`G` is the carrier, `[Magma G]` supplies the one binary operation (`◇` is the
ETP's notation for `Magma.op`), the codomain is `Prop`, and the law is
universally quantified over its variables in first-appearance order — which is
binder-for-binder the ETP's own order, since its `equation` command numbers
leaves by first appearance too.

The parse tree comes from [`../../oracle/normalizer.py`](../../oracle/README.md):
`parse_equation` returns `Equation(lhs, rhs)` over `Op(left, right)` and
`Var(name)` nodes, and `leanify` walks it. Reusing the oracle's parser rather
than writing a second one is deliberate — a private parser here could disagree
with the one the semantic oracle uses, and a Lean rendering would then no
longer be evidence about the same equation.

## Files

| file | role |
|---|---|
| `leanify.py` | the renderer: `LeanStyle`, `to_lean`, `analyze`, `read_back`, `verify_round_trip`, a CLI, and `--selftest` |
| `build_catalogue.py` | export all 4694 ETP laws to JSON (and, with `--lean`, to a self-contained compilable Lean file) |
| `etp_equations_lean.json` | the generated catalogue — 4694 formal/Lean pairs, 1.8 MB |
| `etp_equations.lean` | the generated Lean file — all 4694 declarations, self-contained, elaborates with plain `lean`, 472 KB |

Nothing needs installing beyond system `python3` plus a copy of the ETP
`equations.txt` (located exactly as [`../../oracle`](../../oracle/README.md)
locates it — `$ETP_EQUATIONS`, else `$ETP_ROOT/data/equations.txt`, else
`~/equational_theories/...`; or pass `--equations`). `--compile` additionally
wants a `lean` on PATH (any recent Lean 4 via elan; no Lake project, no
Mathlib).

## The generated catalogue

```bash
python3 build_catalogue.py                                # -> etp_equations_lean.json
python3 build_catalogue.py --lean etp_equations.lean --compile   # + the Lean file, elaborated
```

```json
{
  "meta": {
    "generator": "translate/lean/build_catalogue.py",
    "source": "equational_theories/data/equations.txt",
    "count": 4694,
    "style": { "decl": "abbrev", "universe": "u", "prefix": "Equation",
               "docstring": false, "carrier": "G" },
    "verified": true,
    "etp_source_crosscheck": { "performed": true, "matched": 4694, "...": null },
    "compiled": { "lean": "Lean (version 4.33.0, ...)", "seconds": 20.7 }
  },
  "equations": [
    { "node": 43, "formal": "x ◇ y = y ◇ x",
      "name": "Equation43",
      "lean": "abbrev Equation43 (G : Type u) [Magma G] : Prop := ∀ x y : G, x ◇ y = y ◇ x",
      "statement": "∀ x y : G, x ◇ y = y ◇ x",
      "order": 2, "variables": ["x", "y"] }
  ]
}
```

`node` is the ETP equation number — line N of `equations.txt` *is* Equation N,
the invariant `NodeMapper` enforces when it loads the file — so these rows join
directly against the implication graph, the semantic oracle, and the ETP
repository's own `EquationN` declarations. `statement` is the bare proposition
for consumers who want the law without the declaration wrapper.

There is deliberately **no `normalized` field**: the catalogue text is already
canonical (variables renamed by first appearance, `◇` as the operation), and the
build asserts that for every row rather than asking you to take it on trust.

By order: 2 laws of order 0, 5 of order 1, 39 of order 2, 364 of order 3, and
4284 of order 4.

| flag | meaning |
|---|---|
| `--out PATH` | JSON output path (default `etp_equations_lean.json` beside the script) |
| `--equations PATH` | a specific `equations.txt` |
| `--lean PATH` | also write a self-contained Lean file declaring every equation |
| `--compile` | run `lean` on that file after writing it (requires `--lean`) |
| `--limit N` | only the first N equations |
| `--no-verify` | skip the per-row and cross-repo checks (not advised) |
| *style flags* | as below; the chosen style is recorded in `meta` |

## Rendering one equation

```bash
python3 leanify.py "x ◇ (y ◇ z) = (x ◇ y) ◇ z"
# formal: x ◇ (y ◇ z) = (x ◇ y) ◇ z
# lean:   abbrev Equation4512 (G : Type u) [Magma G] : Prop := ∀ x y z : G, x ◇ (y ◇ z) = (x ◇ y) ◇ z
# node:   Equation 4512
# order:  4   variables: x, y, z

python3 leanify.py 43 4512 --decl def              # bare integers are ETP numbers
python3 leanify.py --universe star --docstring 43
python3 leanify.py --json 43                       # records, for piping
python3 leanify.py --selftest                      # rendering + round trip + error cases
```

Free-text input is welcome (that is what the oracle's parser is for): the node
is looked up in the catalogue, and a law that is the catalogue's only up to
variable renaming or `=` orientation is still named — and flagged:

```bash
python3 leanify.py "b ◇ a = a ◇ b"
# lean:   abbrev Equation43 (G : Type u) [Magma G] : Prop := ∀ b a : G, b ◇ a = a ◇ b
# node:   Equation 43 (up to renaming/orientation)
```

In `--json` records this is the `canonical` field: whether the statement as
written is byte-identical to the catalogue line, as opposed to merely denoting
the same law. Input outside the catalogue (order > 4, or no catalogue on disk)
renders under the name `EquationUnknown` with `node: null`.

### Style

| flag | default | effect |
|---|---|---|
| `--decl` | `abbrev` | `abbrev` or `def`. The ETP marks its equations reducible (the `equation` command compiles to an abbrev-hinted definition) so that tactics like `decide` look through the name; `def` makes the name opaque |
| `--universe` | `u` | `u` (`Type u`, the ETP's universe-polymorphic form), `star` (`Type*` — Mathlib notation, needs Mathlib in scope), `zero` (plain `Type`) |
| `--prefix` | `Equation` | declaration name prefix; the name is `{prefix}{node}`, so the default reproduces the ETP's `Equation43` etc. |
| `--docstring` | off | prefix each declaration with `/-- Equation N of the ETP catalogue: `…`. -/` |

Unlike the LaTeX renderer there is no operator option: `◇` *is* the ETP's
notation for `Magma.op`, and any other spelling would be a different (or
unelaboratable) declaration.

From Python:

```python
from leanify import LeanStyle, to_lean, analyze

to_lean("x ◇ y = y ◇ x")             # 'abbrev Equation43 (G : Type u) [Magma G] : Prop := …'
to_lean("x = x", LeanStyle(decl="def", universe="zero"), node=1)
analyze("a * b * c = c")             # {'ok': False, 'error': 'parse-failure', ...}
```

`to_lean` raises the oracle's `ParseFailure` / `OutsideFragment` for anything
that is not a single-operation magma identity, plus this module's
`Unrepresentable` for a law whose variable names Lean cannot bind; `analyze`
returns all three as data (`error: "lean-unrepresentable"` for the last).

## Decisions worth knowing

**The declaration is the ETP's surface form, not a re-design.** Name
(`EquationN`), carrier (`G : Type u`), instance-implicit `[Magma G]`, `Prop`
codomain, one `∀` with all binders ascribed `: G`, binders in first-appearance
order: each choice is read off what `Equations/Command.lean` elaborates
`equation N := …` into. The point of this directory is that "the Lean 4 form
of Equation N" is a checkable claim about the ETP, not a house style.

**Every nested operator is parenthesized, on both sides.** `Op(Op(x,y),z)`
renders as `(x ◇ y) ◇ z`, never `x ◇ y ◇ z`. In LaTeX that was a readability
decision; in Lean it is not optional — the ETP declares `◇` as `infix:65`,
*non*-associative, so a bare chain does not even parse — and the magma
operation is not associative, so the grouping is the meaning.

**Variable names are validated, not trusted.** Catalogue laws only ever use
`x y z w u v`, which pass through untouched. Free-text input can carry a name
that Lean would reject as a binder (`fun`, `Prop`) or — worse — silently
capture (`G`, the carrier itself: `∀ G : G, …` would elaborate to a different
proposition than the law). Those raise `Unrepresentable` instead of emitting a
declaration that does not mean its equation.

**The ETP declares 20 laws beyond the catalogue.** `Equation5093`,
`Equation28770`, … up to `Equation1875916474` are higher-order laws (order
> 4) studied individually in the ETP source. They have no line in
`equations.txt`, no node in the implication graph the oracle reasons over, and
so no row here; the source cross-check counts and ignores them.

**`universe u` comes from the file, not the declaration.** The exported Lean
file opens with a `universe u` line, so each declaration can say `Type u`
without relying on Lean's auto-bound universe parameters (which Mathlib-style
code disables). A single declaration pasted elsewhere needs that line, or
auto-bounding on.

## Verification

Four independent checks, all runnable here:

| check | what it proves | how |
|---|---|---|
| round trip | the *structure* is right — parenthesization, variable placement, orientation, binder list. `read_back` strips the declaration head and `∀ … : G,` binder off the emitted string itself, re-parses the body with the oracle's parser, and requires the syntax trees to be **equal** (frozen dataclasses, so `==` compares shape and names exactly) and the binders to match first-appearance order | every row of `build_catalogue.py`; 7 styles × 8 equations in `leanify.py --selftest` |
| canonical form | the catalogue text really is already normalized, so omitting a `normalized` field stays honest | every row of `build_catalogue.py` |
| source cross-check | the *naming* is right — our `EquationN` states exactly what the ETP's `EquationN` states. Every `equation N := law` command in the ETP repo's `Equations/*.lean` (commented copies included) is extracted, and the law must be byte-identical to catalogue line N | `build_catalogue.py`, automatically when the ETP source sits next to `equations.txt`; result recorded in `meta` |
| elaboration | the output is valid Lean 4, not merely well-formed to us | `build_catalogue.py --lean out.lean --compile` |

A failure in any of the first three aborts the build with the offending node,
before anything is written — a partially-wrong catalogue is worse than none.
The round trip is the check that matters most: a dropped parenthesis still
*looks* like a plausible declaration, and nothing else would catch it. The
cross-check is what turns "we call it Equation43" from a convention into a
statement about the ETP repository.

Unlike the LaTeX renderer there is no `readable_style` indirection: every
style option here (keyword, universe, prefix, docstring) leaves the statement
untouched, so the round trip covers each style exactly as emitted.

The exported Lean file is **self-contained**: it embeds the `Magma` class and
`◇` notation (copied from the ETP's `Magma.lean`) and needs no imports, so
plain `lean` elaborates it — no Lake project, no Mathlib, no ETP build. That
is also why `--lean` refuses `--universe star`: `Type*` is Mathlib notation.
