# `translate/smtlib` — ETP equations as SMT-LIB 2 script

Every one of the 4694 ETP laws rendered as SMT-LIB 2 script. No model is involved:
the rendering is a structural walk of the equation's parse tree, so the same law
always produces the same output, byte for byte.

The same term as [`../tptp/`](../tptp/), wrapped in the ceremony a real SMT script
carries: a sort declaration, a typed function symbol, and a quantifier block with a
sort on every binder.

```
Equation 4512   x ◇ (y ◇ z) = (x ◇ y) ◇ z

(declare-sort M 0)
(declare-fun op (M M) M)
(assert (forall ((x M) (y M) (z M))
  (= (op x (op y z)) (op (op x y) z))))
```

## What it isolates

Nothing about the law changes between this and [`../tptp/`](../tptp/), so the
pair isolates whether surrounding boilerplate dilutes the signal — the law is a
handful of tokens inside a four-line file.

The reader checks the declarations as well as the assertion. They are
boilerplate, but a script asserting a law about an undeclared function would
not be an SMT script, and a reader that ignored them could not tell the
difference.

## Files

| file | what it is |
| --- | --- |
| `smtify.py` | translates one equation; importable and a CLI |
| `build_catalogue.py` | runs it over all 4694 laws and writes the JSON |
| `etp_equations_smtlib.json` | the catalogue: `{meta, equations}`, 4694 rows |
| `etp_equations_smtlib.txt` | the same renderings as a plain listing, for skimming |

The shared build, verification and CLI machinery lives in
[`../_catalogue.py`](../_catalogue.py); this directory supplies only the walk.

## Usage

```bash
python3 smtify.py "x ◇ (y ◇ z) = (x ◇ y) ◇ z"   # an equation, or
python3 smtify.py 4512                           # an ETP equation number
python3 smtify.py --json 4512                    # machine-readable record
python3 smtify.py --selftest                     # pinned cases + round trips

python3 build_catalogue.py                      # -> etp_equations_smtlib.json
python3 build_catalogue.py --listing preview.txt --limit 40
```

As a library:

```python
from smtify import representation
rep = representation()
rep.render(equation)       # Equation -> SMT-LIB 2 script
rep.read_back(text)        # back to the oracle's Equation tree
```

## Output format

Matches every sibling catalogue, so the representations join row for row:

```json
{ "node": 4512, "formal": "x ◇ (y ◇ z) = (x ◇ y) ◇ z",
  "smtlib": "(declare-sort M 0) …",
  "order": 4, "variables": ["x", "y", "z"] }
```

`node` is the ETP equation number — line N of `equations.txt` *is* Equation N,
the identifier the implication graph and the semantic oracle use — so a row here
joins directly against the oracle and against every other representation.

## Verification

The parse tree comes from [`../../oracle/normalizer.py`](../../oracle/normalizer.py),
not a second parser written here — a private parser could disagree with the one
the semantic oracle uses, and then a rendering would no longer be evidence about
the same equation. Reading back goes the same way: the reader recovers the
structure, rebuilds canonical infix text, and hands *that* to the oracle's
`parse_equation`.

`build_catalogue.py` refuses to write anything unless every row passes and the
catalogue as a whole passes:

- **round trip** — the rendering reads back to a syntax tree equal to the
  original (exact). Structural
  equality, not string equality, so a dropped or misplaced subterm is caught.
- **canonical form** — the catalogue line equals its own normalization.
- **distinctness** — all 4694 renderings differ; a collision would mean the
  rendering had lost something that separates two laws.

Current state:

```
4694 equations, by order: 0:2, 1:5, 2:39, 3:364, 4:4284
characters per rendering: min 79, mean 120.0, max 137
verified: True
```

The checks are not vacuous: rendering a *different* law, truncating the
rendering, and passing an empty string are each rejected, and `--selftest`
pins the refusals specific to this notation. The build is deterministic —
rebuilding reproduces every row identically, with `generated_at` the only field
that changes.
