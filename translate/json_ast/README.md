# `translate/json_ast` — ETP equations as JSON syntax tree

Every one of the 4694 ETP laws rendered as JSON syntax tree. No model is involved:
the rendering is a structural walk of the equation's parse tree, so the same law
always produces the same output, byte for byte.

The same tree [`../py_lambda/`](../py_lambda/) writes as executable code, written as
inert data: a one-key object per node, a string per variable.

```
Equation 4512   x ◇ (y ◇ z) = (x ◇ y) ◇ z

{"=": [{"◇": ["x", {"◇": ["y", "z"]}]}, {"◇": [{"◇": ["x", "y"]}, "z"]}]}
```

## What it isolates

There is no evaluation story and nothing to run, which is the point: it
separates "reads a nested structure" from "simulates a program", two abilities
the Python rendering necessarily conflates.

## Files

| file | what it is |
| --- | --- |
| `jsonify.py` | translates one equation; importable and a CLI |
| `build_catalogue.py` | runs it over all 4694 laws and writes the JSON |
| `etp_equations_json_ast.json` | the catalogue: `{meta, equations}`, 4694 rows |
| `etp_equations_json_ast.txt` | the same renderings as a plain listing, for skimming |

The shared build, verification and CLI machinery lives in
[`../_catalogue.py`](../_catalogue.py); this directory supplies only the walk.

## Usage

```bash
python3 jsonify.py "x ◇ (y ◇ z) = (x ◇ y) ◇ z"   # an equation, or
python3 jsonify.py 4512                           # an ETP equation number
python3 jsonify.py --json 4512                    # machine-readable record
python3 jsonify.py --selftest                     # pinned cases + round trips

python3 build_catalogue.py                      # -> etp_equations_json_ast.json
python3 build_catalogue.py --listing preview.txt --limit 40
```

As a library:

```python
from jsonify import representation
rep = representation()
rep.render(equation)       # Equation -> JSON syntax tree
rep.read_back(text)        # back to the oracle's Equation tree
```

## Output format

Matches every sibling catalogue, so the representations join row for row:

```json
{ "node": 4512, "formal": "x ◇ (y ◇ z) = (x ◇ y) ◇ z",
  "json_ast": "{\"=\": [{\"◇\": [\"x\", {\"◇\": [\"y\", \"z\"]}]}, {\"◇\": [{\"◇\": [\"x\", \"y\"]}, \"z\"]}]}",
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
characters per rendering: min 17, mean 71.6, max 73
verified: True
```

The checks are not vacuous: rendering a *different* law, truncating the
rendering, and passing an empty string are each rejected, and `--selftest`
pins the refusals specific to this notation. The build is deterministic —
rebuilding reproduces every row identically, with `generated_at` the only field
that changes.
