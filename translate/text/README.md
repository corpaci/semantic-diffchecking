# `translate/text` — ETP equations as deterministic English text

Every one of the 4694 ETP laws, verbalized word for word. No model is involved:
the rendering is a structural walk of the equation's parse tree, so the same
law always produces the same sentence, byte for byte.

```
Equation 43    x ◇ y = y ◇ x
               x diamond y equals y diamond x

Equation 1491  x = (y ◇ x) ◇ (y ◇ (y ◇ x))
               x equals open bracket y diamond x close bracket diamond open bracket
               y diamond open bracket y diamond x close bracket close bracket
```

This is **not** the same thing as [`../nl/`](../nl/), which asks a model to
describe a law in prose. That representation is fluent and lossy; this one is
mechanical and exactly invertible. Having both lets the project separate *the
model misread the notation* from *the model misread the mathematics*.

## The rendering

Read the canonical form aloud. Every symbol becomes one word or phrase:

| symbol | words           |
| ------ | --------------- |
| `◇`    | `diamond`       |
| `=`    | `equals`        |
| `(`    | `open bracket`  |
| `)`    | `close bracket` |

Variables keep their letters. Brackets appear exactly where the canonical form
has them — around every nested operation, never around a whole side — so the
word sequence pins down one tree and no other. That is the entire
specification, which is why it is easy to believe and cheap to check.

## Why bracket words

Three schemes were considered for the nesting, which is the only genuinely open
question in a rendering this small.

**1. Bracket words** — `x diamond open bracket y diamond z close bracket equals
x`. **Chosen.** Verbose, but it is how a person reads a formula out loud, the
reader never has to hold anything in their head, and it inverts by
substitution.

**2. Prefix noun phrases** — `the diamond of x and the diamond of y and z
equals x`. Formally this is fine: the grammar `T := var | "the diamond of" T
"and" T` is unambiguous, so no two trees collide. But recovering the tree means
counting arities to work out which `and` closes which `of`, and at ETP's order
4 that gets ugly fast — `(x ◇ y) ◇ (z ◇ w)` becomes `the diamond of the diamond
of x and y and the diamond of z and w`, in which three of the words are `and`.
This project measures whether models preserve meaning across representations; a
notation whose correct reading requires arity bookkeeping would measure the
notation instead.

**3. Spoken "quantity"** — `x diamond the quantity y diamond z`. The usual
dictation shorthand, and genuinely ambiguous: there is no closing marker, so at
depth two the reader cannot tell where the group ends. Rejected outright.

The cost of (1) is length. At order 4 the longest law is 23 words, still one
line; the mean is 21.1.

## Why `diamond` and not `times`

The ETP operation is an arbitrary binary operation on an arbitrary set. It is
not associative, not commutative, and has no identity — so calling it "times"
would quietly import three properties it does not have, and a reader who
believed the word would answer implication questions wrongly for reasons that
belong to this directory rather than to their algebra. `diamond` names the
symbol the catalogue itself uses (`◇`), carries no algebraic baggage, and keeps
this representation aligned with `\diamond` in [`../latex/`](../latex/).

`--operator-word times` is there for when a plainer reading is wanted, and the
choice is recorded in the catalogue's `meta.style` either way.

## Files

| file                      | what it is                                              |
| ------------------------- | ------------------------------------------------------- |
| `textify.py`              | translates one equation; importable and a CLI            |
| `build_catalogue.py`      | runs `textify` over all 4694 laws and writes the JSON    |
| `etp_equations_text.json` | the catalogue: `{meta, equations}`, 4694 rows            |
| `etp_equations_text.txt`  | the same sentences as a plain listing, for skimming      |

## Usage

```bash
python3 textify.py "x ◇ (y ◇ z) = (x ◇ y) ◇ z"   # an equation, or
python3 textify.py 43 1491                        # ETP equation numbers
python3 textify.py --json 43                      # machine-readable record
python3 textify.py --selftest                     # pinned cases + round trips

python3 build_catalogue.py                        # -> etp_equations_text.json
python3 build_catalogue.py --txt preview.txt --limit 40
```

As a library:

```python
from textify import to_text, to_equation, TextStyle
to_text("x ◇ (y ◇ z) = x")        # 'x diamond open bracket y diamond z close bracket equals x'
to_equation(...)                   # back to the oracle's Equation tree
```

Style is carried by the frozen `TextStyle` dataclass and exposed as CLI flags:
`--operator-word` (default `diamond`), `--brackets` (`bracket` or
`parenthesis`), `--equals-word` (default `equals`), and `--quantify`, which
prefixes `for all x y z, `. A style whose vocabulary could not be read back
unambiguously — a one-letter operator word, a phrase containing another phrase,
anything not lowercase — is refused at construction rather than producing a
catalogue that cannot be inverted.

## Output format

Matches the sibling catalogues exactly, so the representations line up row for
row:

```json
{
  "meta": { "generator": "...", "source": "...", "count": 4694,
            "generated_at": "...", "style": { ... },
            "verified": true, "verification": "..." },
  "equations": [
    { "node": 43, "formal": "x ◇ y = y ◇ x",
      "text": "x diamond y equals y diamond x",
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
evidence about the same equation. Reading back works the same way: the words
are substituted to symbols and handed to the oracle's own `parse_equation`.

`build_catalogue.py` refuses to write anything unless all three checks pass on
all 4694 rows:

- **round trip** — the sentence is read back and the resulting syntax tree must
  equal the original. Structural equality, not string equality, so a dropped
  bracket or a mis-nested subterm is caught; that is exactly the failure that
  would otherwise still *look* like a plausible equation.
- **canonical form** — the catalogue line must equal its own normalization, so
  the "no normalized field needed" claim above stays true if the ETP data drop
  changes.
- **text purity** — the rendering must be lowercase words, spaces, and the
  quantifier's comma, and nothing else. A surviving `◇`, digit, or bracket
  character would mean some part of the equation had not actually been put into
  words, which is the one thing this representation is for.

Current state of the generated catalogue:

```
4694 equations, by order: 0:2, 1:5, 2:39, 3:364, 4:4284
words per equation: min 3, mean 21.1, max 23
verified: True (0.55s)
```

The checks are not vacuous — each of *dropped close bracket*, *re-nested
brackets*, *swapped operand order*, *surviving symbol*, *stray digit* and
*uppercased word* was injected into a correct sentence and every one was
caught. The 4694 sentences are also pairwise distinct, and the build is
deterministic: rebuilding reproduces every row identically, with `generated_at`
the only field that changes.
