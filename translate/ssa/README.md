# `translate/ssa` — ETP equations as single-assignment straight-line form

Every one of the 4694 ETP laws rendered as single-assignment straight-line form. No model is involved:
the rendering is a structural walk of the equation's parse tree, so the same law
always produces the same output, byte for byte.

Every operation gets its own line and its own name, so the rendering contains no
nesting at all. The tree survives only as the def-use edges between temporaries.

```
Equation 4512   x ◇ (y ◇ z) = (x ◇ y) ◇ z

t1 = y ◇ z
t2 = x ◇ t1
t3 = x ◇ y
t4 = t3 ◇ z
assert t2 = t4
```

## What it isolates

Every other representation lets a reader recover structure by matching
delimiters or counting arities. Here there is nothing to match: the tree has to
be rebuilt from data flow. That makes it the cleanest available probe of
whether a model tracks structure or merely balances brackets.

Temporaries are numbered in post-order, left side before right, so the
numbering is a function of the tree and nothing else. `t` is a legal ETP
variable letter but never collides — the catalogue's laws use at most six
distinct variables (`x y z w u v`), and a temporary is always `t` followed by
digits.

## Files

| file | what it is |
| --- | --- |
| `ssaify.py` | translates one equation; importable and a CLI |
| `build_catalogue.py` | runs it over all 4694 laws and writes the JSON |
| `etp_equations_ssa.json` | the catalogue: `{meta, equations}`, 4694 rows |
| `etp_equations_ssa.txt` | the same renderings as a plain listing, for skimming |

The shared build, verification and CLI machinery lives in
[`../_catalogue.py`](../_catalogue.py); this directory supplies only the walk.

## Usage

```bash
python3 ssaify.py "x ◇ (y ◇ z) = (x ◇ y) ◇ z"   # an equation, or
python3 ssaify.py 4512                           # an ETP equation number
python3 ssaify.py --json 4512                    # machine-readable record
python3 ssaify.py --selftest                     # pinned cases + round trips

python3 build_catalogue.py                      # -> etp_equations_ssa.json
python3 build_catalogue.py --listing preview.txt --limit 40
```

As a library:

```python
from ssaify import representation
rep = representation()
rep.render(equation)       # Equation -> single-assignment straight-line form
rep.read_back(text)        # back to the oracle's Equation tree
```

## Output format

Matches every sibling catalogue, so the representations join row for row:

```json
{ "node": 4512, "formal": "x ◇ (y ◇ z) = (x ◇ y) ◇ z",
  "ssa": "t1 = y ◇ z …",
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
characters per rendering: min 12, mean 58.8, max 60
verified: True
```

The checks are not vacuous: rendering a *different* law, truncating the
rendering, and passing an empty string are each rejected, and `--selftest`
pins the refusals specific to this notation. The build is deterministic —
rebuilding reproduces every row identically, with `generated_at` the only field
that changes.
