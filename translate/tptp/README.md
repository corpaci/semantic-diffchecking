# `translate/tptp` — ETP equations as TPTP first-order form

Every one of the 4694 ETP laws rendered as TPTP first-order form. No model is involved:
the rendering is a structural walk of the equation's parse tree, so the same law
always produces the same output, byte for byte.

The dialect Vampire reads — which is the format this project's own ground truth came
out of, since the ETP's implication data is Vampire output.

```
Equation 4512   x ◇ (y ◇ z) = (x ◇ y) ◇ z

fof(law, axiom, ![X,Y,Z] : op(X,op(Y,Z)) = op(op(X,Y),Z)).
```

## What it isolates

The most operationally realistic rendering in `translate/`: it is what an ATP
pipeline actually contains. It is also the one most likely to be dense in
pretraining data — plenty of TPTP problem files are famous — so it doubles as a
contamination probe.

The formula is named `law`, never `law4512`. An ETP node number in the text
would hand over the answer, which is the same reason [`../lean/`](../lean/)
strips it.

Variables are upper-cased because TPTP requires it. Upper-casing is injective
on the catalogue's single-letter variables, so the reader inverts it and the
round trip stays an exact tree match rather than a weaker up-to-renaming one.

## Files

| file | what it is |
| --- | --- |
| `tptpify.py` | translates one equation; importable and a CLI |
| `build_catalogue.py` | runs it over all 4694 laws and writes the JSON |
| `etp_equations_tptp.json` | the catalogue: `{meta, equations}`, 4694 rows |
| `etp_equations_tptp.txt` | the same renderings as a plain listing, for skimming |

The shared build, verification and CLI machinery lives in
[`../_catalogue.py`](../_catalogue.py); this directory supplies only the walk.

## Usage

```bash
python3 tptpify.py "x ◇ (y ◇ z) = (x ◇ y) ◇ z"   # an equation, or
python3 tptpify.py 4512                           # an ETP equation number
python3 tptpify.py --json 4512                    # machine-readable record
python3 tptpify.py --selftest                     # pinned cases + round trips

python3 build_catalogue.py                      # -> etp_equations_tptp.json
python3 build_catalogue.py --listing preview.txt --limit 40
```

As a library:

```python
from tptpify import representation
rep = representation()
rep.render(equation)       # Equation -> TPTP first-order form
rep.read_back(text)        # back to the oracle's Equation tree
```

## Output format

Matches every sibling catalogue, so the representations join row for row:

```json
{ "node": 4512, "formal": "x ◇ (y ◇ z) = (x ◇ y) ◇ z",
  "tptp": "fof(law, axiom, ![X,Y,Z] : op(X,op(Y,Z)) = op(op(X,Y),Z)).",
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
characters per rendering: min 30, mean 58.0, max 64
verified: True
```

The checks are not vacuous: rendering a *different* law, truncating the
rendering, and passing an empty string are each rejected, and `--selftest`
pins the refusals specific to this notation. The build is deterministic —
rebuilding reproduces every row identically, with `generated_at` the only field
that changes.
