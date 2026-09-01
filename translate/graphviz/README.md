# `translate/graphviz` — ETP equations as Graphviz DOT source

Every one of the 4694 ETP laws rendered as Graphviz DOT source. No model is involved:
the rendering is a structural walk of the equation's parse tree, so the same law
always produces the same output, byte for byte.

The tree as an explicit node and edge list in Graphviz DOT.

```
Equation 4512   x ◇ (y ◇ z) = (x ◇ y) ◇ z

digraph law {
  ordering=out;
  n1 [label="="];
  n2 [label="◇"];
  n3 [label="x"];
  n4 [label="◇"];
  n5 [label="y"];
  n6 [label="z"];
  n7 [label="◇"];
  n8 [label="◇"];
  n9 [label="x"];
  n10 [label="y"];
  n11 [label="z"];
  n1 -> n2;
  n1 -> n7;
  n2 -> n3;
  n2 -> n4;
  n4 -> n5;
  n4 -> n6;
  n7 -> n8;
  n7 -> n11;
  n8 -> n9;
  n8 -> n10;
}
```

## What it isolates

Nodes are numbered in pre-order, which is deliberately *not* a path encoding —
an id like `n0110` would spell out the structure the reader is supposed to
recover — so the ids identify without describing, and the shape lives entirely
in the edges.

Left versus right survives only as edge order, which is why the graph declares
`ordering=out`: that is real DOT semantics for "out-edge order is significant",
so the convention is stated inside the artifact rather than assumed. It also
makes argument order a separately observable failure, which matters here — the
magma operation is not commutative, so swapping two arguments yields a
different law rather than a cosmetic difference.

The reader validates the envelope (`digraph … { … }` and the `ordering=out`
declaration) before reading the contents. Reading only the node and edge lines
would be easier, but then a rendering that had lost its `ordering=out` would
still round-trip, and the check would be blind to the loss of the very
convention the representation depends on.

## Files

| file | what it is |
| --- | --- |
| `dotify.py` | translates one equation; importable and a CLI |
| `build_catalogue.py` | runs it over all 4694 laws and writes the JSON |
| `etp_equations_graphviz.json` | the catalogue: `{meta, equations}`, 4694 rows |
| `etp_equations_graphviz.txt` | the same renderings as a plain listing, for skimming |

The shared build, verification and CLI machinery lives in
[`../_catalogue.py`](../_catalogue.py); this directory supplies only the walk.

## Usage

```bash
python3 dotify.py "x ◇ (y ◇ z) = (x ◇ y) ◇ z"   # an equation, or
python3 dotify.py 4512                           # an ETP equation number
python3 dotify.py --json 4512                    # machine-readable record
python3 dotify.py --selftest                     # pinned cases + round trips

python3 build_catalogue.py                      # -> etp_equations_graphviz.json
python3 build_catalogue.py --listing preview.txt --limit 40
```

As a library:

```python
from dotify import representation
rep = representation()
rep.render(equation)       # Equation -> Graphviz DOT source
rep.read_back(text)        # back to the oracle's Equation tree
```

## Output format

Matches every sibling catalogue, so the representations join row for row:

```json
{ "node": 4512, "formal": "x ◇ (y ◇ z) = (x ◇ y) ◇ z",
  "graphviz": "digraph law { …",
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
characters per rendering: min 109, mean 346.7, max 353
verified: True
```

The checks are not vacuous: rendering a *different* law, truncating the
rendering, and passing an empty string are each rejected, and `--selftest`
pins the refusals specific to this notation. The build is deterministic —
rebuilding reproduces every row identically, with `generated_at` the only field
that changes.
