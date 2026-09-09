# `translate/word_problem` — ETP equations as word problems

Every one of the 4694 ETP laws restated as a claim about a physical process. No
model is involved: the rendering is a fixed template over the equation's parse
tree, so the same law always produces the same paragraph, byte for byte.

```
Equation 4512   x ◇ (y ◇ z) = (x ◇ y) ◇ z

A workshop welder takes two parts, in a definite order, and fuses them into
one new part. Feeding the same two parts in the opposite order, or grouping
a sequence of welds differently, may give a different part.

Claim: for any parts x, y and z, welding x to the part made by welding y to
z gives the same part as welding the part made by welding x to y to z.
```

## What it isolates

The tree, the variables and their order are all preserved exactly, so this is a
control on *framing* rather than a new notation: any drop in accuracy is
attributable to the narrative dressing alone. It also probes something the
symbolic renderings cannot — whether a familiar law is recognised more or less
readily once it stops looking like algebra.

## Deterministic, not written by a model

[`../nl/`](../nl/) already occupies the model-written-prose slot, and its output
is fluent but lossy and unrepeatable. This is a fixed template instead: the
paragraph reads back to the law it came from, which is what lets it sit
alongside the other mechanical catalogues rather than needing its own grading
story.

## The scenario paragraph is constant

The first paragraph is byte-identical for all 4694 laws, and has to be. It
exists to stop a reader assuming the operation is commutative or associative —
neither holds for a magma — and if it varied with the law it would leak
information about the law. The reader compares it verbatim, so drift in the
boilerplate is an error rather than a silent change in what the catalogue means.

## Nesting, and what it costs

One operation, two phrasings, chosen so the sentence reads:

| position | phrasing |
| --- | --- |
| root of a side | `welding A to B` |
| nested inside another | `the part made by welding A to B` |

Both are unambiguous for the same reason [`../text2/`](../text2/) is: the
grammar `desc := VAR | "the part made by welding" desc "to" desc` is LL(1), so
the first word decides the production and each argument is self-delimiting.

The cost is the same too, and it is real. At order 4 a reader must count to see
which `to` closes which `welding`. Equation 1491 is the worst case in the
catalogue:

```
Claim: for any parts x and y, x gives the same part as welding the part
made by welding y to x to the part made by welding y to the part made by
welding y to x.
```

[`../ssa/`](../ssa/) is the flattened alternative if that matters more than the
prose reading — the same story told with named intermediate parts would not
nest at all.

## Files

| file | what it is |
| --- | --- |
| `storify.py` | translates one equation; importable and a CLI |
| `build_catalogue.py` | runs it over all 4694 laws and writes the JSON |
| `etp_equations_word_problem.json` | the catalogue: `{meta, equations}`, 4694 rows |
| `etp_equations_word_problem.txt` | the same renderings as a plain listing |

The shared build, verification and CLI machinery lives in
[`../_catalogue.py`](../_catalogue.py); this directory supplies only the walk.

## Usage

```bash
python3 storify.py "x ◇ (y ◇ z) = (x ◇ y) ◇ z"   # an equation, or
python3 storify.py 4512                           # an ETP equation number
python3 storify.py --json 4512                    # machine-readable record
python3 storify.py --selftest                     # pinned cases + round trips

python3 build_catalogue.py                        # -> etp_equations_word_problem.json
python3 build_catalogue.py --listing preview.txt --limit 40
```

As a library:

```python
from storify import representation
rep = representation()
rep.render(equation)       # Equation -> word problem
rep.read_back(text)        # back to the oracle's Equation tree
```

## Output format

Matches every sibling catalogue, so the representations join row for row:

```json
{ "node": 4512, "formal": "x ◇ (y ◇ z) = (x ◇ y) ◇ z",
  "word_problem": "A workshop welder takes two parts, …",
  "order": 4, "variables": ["x", "y", "z"] }
```

`node` is the ETP equation number — line N of `equations.txt` *is* Equation N,
the identifier the implication graph and the semantic oracle use — so a row here
joins directly against the oracle and against every other representation.

## Verification

The parse tree comes from [`../../oracle/normalizer.py`](../../oracle/normalizer.py),
not a second parser written here. Reading back goes the same way: the reader
strips the scenario and the claim frame, recovers the structure by recursive
descent, rebuilds canonical infix text, and hands *that* to the oracle's
`parse_equation`.

`build_catalogue.py` refuses to write anything unless every row passes and the
catalogue as a whole passes:

- **round trip** — the paragraph reads back to a syntax tree equal to the
  original (exact). The quantified parts are checked against the ones the claim
  actually uses, in order, so a quantifier that drifted from the body is an
  error rather than something discarded unread.
- **canonical form** — the catalogue line equals its own normalization.
- **distinctness** — all 4694 renderings differ.

Current state:

```
4694 equations, by order: 0:2, 1:5, 2:39, 3:364, 4:4284
characters per rendering: min 263, mean 368.2, max 385
verified: True
```

The checks are not vacuous: a correct rendering of a *different* law, a
truncated paragraph, an empty string, an altered scenario, a dropped scenario,
and two swapped arguments are all rejected — six for six. `--selftest` adds the
refusals specific to this template (a missing `Claim:`, a missing full stop, a
part used but not quantified, plural/singular disagreement, an operation missing
an argument, an unread word, a doubled link phrase). The build is deterministic:
rebuilding reproduces every row identically, with `generated_at` the only field
that changes.
