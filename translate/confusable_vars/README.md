# `translate/confusable_vars` — ETP equations as adversarial variable names

Every one of the 4694 ETP laws rendered as adversarial variable names. No model is involved:
the rendering is a structural walk of the equation's parse tree, so the same law
always produces the same output, byte for byte.

Structurally identical to the catalogue's own notation; only the variable names
change.

```
Equation 4512   x ◇ (y ◇ z) = (x ◇ y) ◇ z

l ◇ (I ◇ ll) = (l ◇ I) ◇ ll
```

## What it isolates

The oracle grades reconstructions up to renaming, so nothing about the *answer*
depends on the names, and any drop in accuracy is attributable to the naming
alone. That makes this a control rather than a new notation.

`confusable` (the default) uses names built from `l`, `I` and `1` — glyphs that
are hard to tell apart in most fonts, so keeping two occurrences straight
becomes visual work. `--names verbose` applies the opposite pressure: long words
that read like logical roles, each easy to see and expensive to hold.

Because renaming is the whole point, this is the one catalogue here matched
`up-to-renaming` — the round trip compares normalized trees. That is the same
equivalence [`../nl_test/`](../nl_test/) grades under, not a weakened check.

## Files

| file | what it is |
| --- | --- |
| `confusify.py` | translates one equation; importable and a CLI |
| `build_catalogue.py` | runs it over all 4694 laws and writes the JSON |
| `etp_equations_confusable_vars.json` | the catalogue: `{meta, equations}`, 4694 rows |
| `etp_equations_confusable_vars.txt` | the same renderings as a plain listing, for skimming |

The shared build, verification and CLI machinery lives in
[`../_catalogue.py`](../_catalogue.py); this directory supplies only the walk.

## Usage

```bash
python3 confusify.py "x ◇ (y ◇ z) = (x ◇ y) ◇ z"   # an equation, or
python3 confusify.py 4512                           # an ETP equation number
python3 confusify.py --json 4512                    # machine-readable record
python3 confusify.py --selftest                     # pinned cases + round trips

python3 build_catalogue.py                      # -> etp_equations_confusable_vars.json
python3 build_catalogue.py --listing preview.txt --limit 40
```

`--names confusable|verbose` selects the naming scheme (default `confusable`).

As a library:

```python
from confusify import representation
rep = representation()
rep.render(equation)       # Equation -> adversarial variable names
rep.read_back(text)        # back to the oracle's Equation tree
```

## Output format

Matches every sibling catalogue, so the representations join row for row:

```json
{ "node": 4512, "formal": "x ◇ (y ◇ z) = (x ◇ y) ◇ z",
  "confusable_vars": "l ◇ (I ◇ ll) = (l ◇ I) ◇ ll",
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
  original (up-to-renaming). Structural
  equality, not string equality, so a dropped or misplaced subterm is caught.
- **canonical form** — the catalogue line equals its own normalization.
- **distinctness** — all 4694 renderings differ; a collision would mean the
  rendering had lost something that separates two laws.

Current state:

```
4694 equations, by order: 0:2, 1:5, 2:39, 3:364, 4:4284
characters per rendering: min 5, mean 27.5, max 31
verified: True
```

The checks are not vacuous: rendering a *different* law, truncating the
rendering, and passing an empty string are each rejected, and `--selftest`
pins the refusals specific to this notation. The build is deterministic —
rebuilding reproduces every row identically, with `generated_at` the only field
that changes.
