# `translate/text2` — ETP equations as bracket-free English text

Every one of the 4694 ETP laws, verbalized word for word with no brackets at
all. Each operation becomes a noun phrase naming its two arguments — `the
diamond of A and B` — so the structure is carried by the phrasing rather than
by delimiters. No model is involved: the rendering is a structural walk of the
equation's parse tree, so the same law always produces the same sentence, byte
for byte.

```
Equation 43    x ◇ y = y ◇ x
               the diamond of x and y equals the diamond of y and x

Equation 1491  x = (y ◇ x) ◇ (y ◇ (y ◇ x))
               x equals the diamond of the diamond of y and x and the diamond of
               y and the diamond of y and x
```

## Relationship to `../text/`

This is the companion to [`../text/`](../text/), and the two differ in exactly
one decision — how the grouping is encoded:

```
x ◇ (y ◇ z) = x

../text/   x diamond open bracket y diamond z close bracket equals x
here       the diamond of x and the diamond of y and z equals x
```

Everything else is shared: same catalogue, same node numbering, same `text`
key, same output shape, same verification. That is deliberate. The pair is a
controlled contrast — two English renderings of identical content whose only
difference is whether a reader recovers the structure from delimiters or from
arity — which is exactly the kind of minimal pair this project exists to
measure. They join row for row, so one can be swapped for the other in an
experiment without touching anything downstream.

Neither supersedes the other, and `../text/` is unchanged by this directory.

## Why this is unambiguous

The grammar is

```
term  :=  VAR  |  "the" OPERATOR "of" term "and" term
```

and it is LL(1): the first token decides the production (`the` opens a phrase,
anything else is a variable), and each sub-term is self-delimiting because the
operation's arity is fixed at two. So no two distinct trees produce the same
sentence, and the reader needs no backtracking.

That is the argument; the build checks it rather than asking you to accept it.
All 4694 sentences are confirmed pairwise distinct (a collision would be a
direct counterexample), every one reads back to the tree it came from, and the
selftest confirms that the near-miss sentences a genuinely ambiguous grammar
would have to accept — `the diamond of x and y and z equals x`, with one `and`
too many, and `the diamond of x equals x`, with one too few — are refused
instead.

## What it costs

A *reader* must count arities to see which `and` closes which `of`. At ETP's
order 4 that is real work:

```
(x ◇ y) ◇ (z ◇ w)   ->   the diamond of the diamond of x and y and the diamond of z and w
```

in which three of the words are `and`. That difficulty is the reason both
representations exist, not an argument against this one.

It costs nothing in brevity, which is worth stating because the intuition runs
the other way: dropping the bracket words does *not* shorten the sentences.
Measured over the full catalogue, this rendering is slightly **longer** —

| rendering            | min | mean     | max |
| -------------------- | --- | -------- | --- |
| `../text/` brackets  | 3   | 21.1     | 23  |
| `text2` prefix       | 3   | **22.5** | 23  |

— because a prefix phrase spends four words per operation (`the diamond of` …
`and`), whereas the bracketed form spends one for a top-level operation and
three for a nested one. The two agree at the maximum because order-4 laws are
nearly all nested throughout.

## Why `diamond` and not `times`

The ETP operation is an arbitrary binary operation on an arbitrary set. It is
not associative, not commutative, and has no identity — so calling it "times"
would quietly import three properties it does not have, and a reader who
believed the word would answer implication questions wrongly for reasons that
belong to this directory rather than to their algebra. `diamond` names the
symbol the catalogue itself uses (`◇`) and keeps this aligned with `../text/`
and with `\diamond` in [`../latex/`](../latex/).

`--operator-word product` reads more naturally as English (`the product of x
and y`) and is there when that is wanted; the choice is recorded in the
catalogue's `meta.style` either way.

## Files

| file                       | what it is                                            |
| -------------------------- | ----------------------------------------------------- |
| `prefixify.py`             | translates one equation; importable and a CLI          |
| `build_catalogue.py`       | runs `prefixify` over all 4694 laws and writes the JSON |
| `etp_equations_text2.json` | the catalogue: `{meta, equations}`, 4694 rows          |
| `etp_equations_text2.txt`  | the same sentences as a plain listing, for skimming    |

The translator is named `prefixify.py` rather than `textify.py` so that both it
and `../text/textify.py` can be imported into one process — Python caches
modules by name, and two files called `textify` on the path would silently
shadow each other.

## Usage

```bash
python3 prefixify.py "x ◇ (y ◇ z) = (x ◇ y) ◇ z"   # an equation, or
python3 prefixify.py 43 1491                        # ETP equation numbers
python3 prefixify.py --json 43                      # machine-readable record
python3 prefixify.py --selftest                     # pinned cases + round trips

python3 build_catalogue.py                          # -> etp_equations_text2.json
python3 build_catalogue.py --txt preview.txt --limit 40
```

As a library:

```python
from prefixify import to_text, to_equation, PrefixStyle
to_text("x ◇ (y ◇ z) = x")     # 'the diamond of x and the diamond of y and z equals x'
to_equation(...)                # back to the oracle's Equation tree
```

Style is carried by the frozen `PrefixStyle` dataclass and exposed as CLI
flags: `--operator-word` (default `diamond`), `--connector` (default `and`),
`--equals-word` (default `equals`), and `--quantify`, which prefixes `for all x
y z, `. A style that could not be read back unambiguously is refused at
construction rather than producing a catalogue that cannot be inverted — a
one-letter word (indistinguishable from a variable), a connector or equality
phrase colliding with the `the … of` opener (which would break the LL(1)
property the whole representation rests on), or anything not lowercase.

## Output format

Matches the sibling catalogues exactly, so the representations line up row for
row:

```json
{
  "meta": { "generator": "...", "source": "...", "count": 4694,
            "generated_at": "...", "style": { "form": "prefix", ... },
            "verified": true, "verification": "..." },
  "equations": [
    { "node": 43, "formal": "x ◇ y = y ◇ x",
      "text": "the diamond of x and y equals the diamond of y and x",
      "order": 2, "variables": ["x", "y"] }
  ]
}
```

`node` is the ETP equation number — line N of `equations.txt` *is* Equation N,
the identifier the implication graph and the semantic oracle use, so a row here
can be joined directly against the oracle and against every other
representation.

## Verification

The parse tree comes from [`../../oracle/normalizer.py`](../../oracle/normalizer.py),
not from a second parser written here — a private parser could disagree with
the one the semantic oracle uses, and then a text rendering would no longer be
evidence about the same equation. Reading back works the same way: a small
recursive-descent pass rebuilds the canonical *infix* string, brackets and all,
and hands that to the oracle's own `parse_equation`. This module only recovers
the structure; if it recovered the wrong structure the round trip would fail.

`build_catalogue.py` refuses to write anything unless three checks pass on all
4694 rows and a fourth passes on the catalogue as a whole:

- **round trip** — the sentence is read back and the resulting syntax tree must
  equal the original. Structural equality, not string equality. Because this
  representation carries its structure in the phrasing, this is the check that
  a nesting was not silently flattened or re-associated.
- **canonical form** — the catalogue line must equal its own normalization, so
  the "no normalized field needed" claim above stays true if the ETP data drop
  changes.
- **text purity** — the rendering must be lowercase words, spaces, and the
  quantifier's comma, and nothing else.
- **distinctness** — all 4694 sentences must differ. The case for a
  bracket-free rendering rests on the grammar being unambiguous, so this is
  checked rather than argued.

Current state of the generated catalogue:

```
4694 equations, by order: 0:2, 1:5, 2:39, 3:364, 4:4284
words per equation: min 3, mean 22.5, max 23
verified: True (0.52s)
```

The checks are not vacuous — each of *re-associated nesting*, *swapped operand
order*, *dropped connector*, *dropped phrase opener*, *surviving symbol*,
*stray digit* and *uppercased word* was injected into a correct sentence, and
an artificial sentence collision was fed to the distinctness check; all eight
were caught. The build is deterministic: rebuilding reproduces every row
identically, with `generated_at` the only field that changes.

Independently of the build, all 4694 rows were re-read from the written JSON
and compared against `../text/`: **both renderings read back to the same
syntax tree for every law**, which is the strongest available statement that
the two directories describe the same 4694 equations. The two sentences
coincide verbatim on exactly the two operation-free laws (`x equals x` and `x
equals y`), where there is no grouping to encode.
