# `translate/slots` — ETP equations as positional slot encoding

Every one of the 4694 ETP laws rendered as positional slot encoding. No model is involved:
the rendering is a structural walk of the equation's parse tree, so the same law
always produces the same output, byte for byte.

A variable becomes the number of its first appearance, an operation becomes a
two-element list, and the equation is `[lhs, rhs]`. No letters, no operator symbol,
no delimiters that mean anything but nesting.

```
Equation 4512   x ◇ (y ◇ z) = (x ◇ y) ◇ z

[[1, [2, 3]], [[1, 2], 3]]
```

## What it isolates

What survives is exactly the tree shape and the co-reference pattern — which
occurrences are the same variable — and nothing else. Equation 8,
`x = x ◇ (x ◇ x)`, becomes `[1, [1, [1, 1]]]`: pure shape and sharing.

Numbering by first appearance in a left-to-right walk is the same order the
oracle's normalizer uses when it renames variables, so on this catalogue —
whose laws are already canonical — the encoding is a bijection with the law.

## Files

| file | what it is |
| --- | --- |
| `slotify.py` | translates one equation; importable and a CLI |
| `build_catalogue.py` | runs it over all 4694 laws and writes the JSON |
| `etp_equations_slots.json` | the catalogue: `{meta, equations}`, 4694 rows |
| `etp_equations_slots.txt` | the same renderings as a plain listing, for skimming |

The shared build, verification and CLI machinery lives in
[`../_catalogue.py`](../_catalogue.py); this directory supplies only the walk.

## Usage

```bash
python3 slotify.py "x ◇ (y ◇ z) = (x ◇ y) ◇ z"   # an equation, or
python3 slotify.py 4512                           # an ETP equation number
python3 slotify.py --json 4512                    # machine-readable record
python3 slotify.py --selftest                     # pinned cases + round trips

python3 build_catalogue.py                      # -> etp_equations_slots.json
python3 build_catalogue.py --listing preview.txt --limit 40
```

As a library:

```python
from slotify import representation
rep = representation()
rep.render(equation)       # Equation -> positional slot encoding
rep.read_back(text)        # back to the oracle's Equation tree
```

## Output format

Matches every sibling catalogue, so the representations join row for row:

```json
{ "node": 4512, "formal": "x ◇ (y ◇ z) = (x ◇ y) ◇ z",
  "slots": "[[1, [2, 3]], [[1, 2], 3]]",
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
characters per rendering: min 6, mean 25.5, max 26
verified: True
```

The checks are not vacuous: rendering a *different* law, truncating the
rendering, and passing an empty string are each rejected, and `--selftest`
pins the refusals specific to this notation. The build is deterministic —
rebuilding reproduces every row identically, with `generated_at` the only field
that changes.
