# `oracle` — normalization, ETP node mapping, and the formal semantic oracle

**Jump to [Setup](#setup-one-time) if you already have the [equational_theories](https://github.com/teorth/equational_theories) repo cloned.**

**You do not need to clone the whole
[equational_theories](https://github.com/teorth/equational_theories) repo.**
Only two files from it are used, and each can be pointed at directly:

| file (in the ETP repo) | used by | when |
|---|---|---|
| [`data/equations.txt`](https://github.com/teorth/equational_theories/blob/main/data/equations.txt) (~200 KB) | `mapper.py` (and everything built on it) | at **runtime** |
| `data/<date>-outcomes.json.zip` (~2 MB) | `build_matrix.py` | at **build time only** |

Download those two files anywhere and tell the tools where they are, via
environment variables (or, for the catalogue, the `NodeMapper(equations_path=)`
argument / for the outcomes, a positional CLI argument):

| variable | points at | consumed by | default if unset |
|---|---|---|---|
| `ETP_EQUATIONS` | your copy of `equations.txt` | `mapper.py`, `oracle.py` | `$ETP_ROOT/data/equations.txt` |
| `ETP_OUTCOMES` | your copy of the outcomes `.json`/`.json.zip` | `build_matrix.py` | `$ETP_ROOT/data/2024-11-10-outcomes.json.zip` |
| `ETP_ROOT` | a full checkout (fallback only) | both, to derive the above | `~/equational_theories` |

If a needed file is missing, the tools exit with a message telling you exactly
which file to download and how to point at it.

## Setup (one-time)

```bash
# Build the implication matrix from the outcomes file. Give the path directly:
python3 build_matrix.py /path/to/2024-11-10-outcomes.json.zip
# ...or via env var:
ETP_OUTCOMES=/path/to/outcomes.json.zip python3 build_matrix.py
# -> writes data/matrix.bin (22 MB) + data/matrix_meta.json (both gitignored)
```

After this, only `equations.txt` is needed at runtime — point at it with
`ETP_EQUATIONS=/path/to/equations.txt` (the outcomes file is no longer read).

### Already have the repo cloned?

If you have a full `equational_theories` checkout, you can **skip the two
downloads and skip setting any environment variables** — the defaults already
find both files inside the checkout:

- **Skip** downloading `equations.txt` and `outcomes.json.zip` (they are in the
  repo's `data/`).
- **Skip** `ETP_EQUATIONS` / `ETP_OUTCOMES` if your checkout is at
  `~/equational_theories`; otherwise set **only** `ETP_ROOT=/path/to/checkout`
  once and both files are located automatically.
- You **cannot skip** the build step — `data/matrix.bin` is generated locally
  and is not part of the repo. With the checkout in place it is just:

  ```bash
  python3 build_matrix.py            # reads $ETP_ROOT/data/2024-11-10-outcomes.json.zip
  ```

Everything after the build (the oracle and mapper) then runs with no arguments
and no env vars.

`matrix.bin` holds one byte per ordered pair: byte `[i*4694 + j]` is the
status of `Equation(i+1) => Equation(j+1)` (row = hypothesis), statuses
`proof_false / proof_true / conjecture_false / conjecture_true / unknown`.
Only verified proofs and counterexamples count as evidence; the 190
unsettled entries in this snapshot surface as `unknown`.

## Files

| file | role |
|---|---|
| `normalizer.py` | parser + normalizer for messy LLM output (many op symbols, `op(a,b)` style, LaTeX/markdown noise, quantifier prefixes). Rejects ambiguous chains, constants, multiple ops, chained `=` — argument order and grouping are **never** normalized away. Runnable directly to inspect the parsed/normalized form of an equation |
| `mapper.py` | normalized equation → ETP node, via canonical keys (variables renamed by first appearance, `=` orientation-independent). Distinguishes `mapped` / `parse-failure` / `outside-fragment` |
| `build_matrix.py` | one-time: outcomes JSON → compact binary matrix |
| `oracle.py` | the formal semantic oracle: labels a pair `equivalent / weaker / stronger / incomparable / unknown` (or `parse-failure` / `outside-fragment`), with the evidence |

## Usage

### `oracle.py` — compare two equations

The main tool. Maps both equations to ETP nodes and reads the proven relation
off the implication matrix.

| flag | argument | meaning |
|---|---|---|
| `--intended` | equation string **or** ETP number | the reference equation (e.g. the law you started from). A bare integer like `43` is read as "Equation 43"; anything else is parsed as a formula |
| `--generated` | equation string **or** ETP number | the equation to judge against the intended one (e.g. an LLM back-translation) |
| `--json` | — | emit the full `Verdict` as JSON (mapping details for both sides, both implication directions, evidence) instead of the human-readable summary. Use this to build dataset rows |
| `--selftest` | — | run the built-in battery of known pairs and exit non-zero on any mismatch; ignores `--intended`/`--generated` |

`--intended` and `--generated` are both required unless you pass `--selftest`.
The verdict is one of `equivalent / weaker / stronger / incomparable /
unknown`, or an off-graph status (`parse-failure` / `outside-fragment`) when a
side does not map to a node. `weaker`/`stronger` describe the **generated**
equation relative to the intended one: weaker = under-specified, stronger =
over-specified.

**Default (human-readable) output** — each side's mapping, both implication
directions, then the verdict with its evidence:

```bash
python3 oracle.py --intended "x ◇ y = y ◇ x" --generated "a*(b*c)=(a*b)*c"
#  intended: 'x ◇ y = y ◇ x' -> Equation 43  [x ◇ y = y ◇ x]
# generated: 'a*(b*c)=(a*b)*c' -> Equation 4512  [x ◇ (y ◇ z) = (x ◇ y) ◇ z]
#   forward: intended => generated : proof_false
#  backward: generated => intended : proof_false
#   verdict: INCOMPARABLE  (counterexample magmas refute the implication in both directions)
```

**Mixing a number and a formula** — here the model just renamed variables and
changed the operator symbol, so both sides land on Equation 43:

```bash
python3 oracle.py --intended 43 --generated "p * q = q * p"
#  intended: '43' -> Equation 43  [x ◇ y = y ◇ x]
# generated: 'p * q = q * p' -> Equation 43  [x ◇ y = y ◇ x]
#   forward: intended => generated : proof_true
#  backward: generated => intended : proof_true
#   verdict: EQUIVALENT  (both map to Equation 43)
```

**`--json`** — the same comparison as a record ready to serialize into a
dataset (`node`/`normalized` per side, `forward`/`backward`, `evidence`):

```bash
python3 oracle.py --intended 43 --generated "p * q = q * p" --json
# {
#   "label": "equivalent",
#   "intended":  { "status": "mapped", "input_text": "43",            "normalized": "x ◇ y = y ◇ x", "node": 43, "order": 2, "reason": null },
#   "generated": { "status": "mapped", "input_text": "p * q = q * p", "normalized": "x ◇ y = y ◇ x", "node": 43, "order": 2, "reason": null },
#   "forward": "proof_true",
#   "backward": "proof_true",
#   "evidence": "both map to Equation 43",
#   "notes": null
# }
```

**`--selftest`** — sanity-check the whole pipeline (prints one line per case,
exits 0 only if all pass):

```bash
python3 oracle.py --selftest
# [ok ] intended='x ◇ y = y ◇ x' generated='a * b = b * a' -> equivalent | both map to Equation 43
# ... (12 cases) ...
# selftest: all passed
```

### `normalizer.py` — parse and normalize an equation

The syntactic layer, runnable on its own to see exactly how a generated
equation is read and canonicalized — no matrix or catalogue needed. Takes one
or more equation strings.

| flag | argument | meaning |
|---|---|---|
| *(positional)* | one or more equation strings | the equation(s) to parse and normalize |
| `--json` | — | emit a JSON array of records (one per input) instead of text |

Two renderings are shown. **`parsed`** rebuilds the equation from the AST:
structure recovered and the operator canonicalized to `◇`, but the *original*
variable names kept — so you can see how the input was grouped. **`normalized`**
additionally renames variables to canonical letters by first appearance. (An
equation is symmetric, so `canonical_key` — shown only in `--json` — also folds
the two `=` orientations together; `normalized` does not.)

**Text mode** (default) — a block per input:

```bash
python3 normalizer.py "a * (b * c) = (a * b) * c"
# input:      a * (b * c) = (a * b) * c
# parsed:     a ◇ (b ◇ c) = (a ◇ b) ◇ c
# normalized: x ◇ (y ◇ z) = (x ◇ y) ◇ z
# order:      4
# variables:  a, b, c
```

Inputs that fall outside the fragment or fail to parse are reported, not
raised:

```bash
python3 normalizer.py "x ◇ y = y ◇ x" "a * b = b + a" "a * b * c = c"
# input:      x ◇ y = y ◇ x
# parsed:     x ◇ y = y ◇ x
# normalized: x ◇ y = y ◇ x
# order:      2
# variables:  x, y
#
# input:      a * b = b + a
# error:      outside-fragment
# reason:     multiple distinct operation symbols ['*', '+']: the fragment has exactly one binary operation
#
# input:      a * b * c = c
# error:      parse-failure
# reason:     unparenthesized chain 'a * b * c': the operation is not associative, so grouping must be explicit
```

**`--json` mode** — one `analyze()` record per input; `ok` distinguishes the
two shapes, so the output stays valid JSON for piping:

```bash
python3 normalizer.py --json "p * q = q * p" "a * b = b + a"
# [
#   {
#     "input": "p * q = q * p",
#     "ok": true,
#     "parsed": "p ◇ q = q ◇ p",
#     "normalized": "x ◇ y = y ◇ x",
#     "canonical_key": "x ◇ y = y ◇ x",
#     "order": 2,
#     "variables": ["p", "q"]
#   },
#   {
#     "input": "a * b = b + a",
#     "ok": false,
#     "error": "outside-fragment",
#     "reason": "multiple distinct operation symbols ['*', '+']: the fragment has exactly one binary operation"
#   }
# ]
```

### `mapper.py` — map equations to ETP nodes

Takes one or more equation strings as positional arguments and reports, for
each, whether it maps to a catalogue node — useful for checking normalization
and spotting off-fragment inputs without invoking the oracle.

| flag | argument | meaning |
|---|---|---|
| *(positional)* | one or more equation strings | the equation(s) to map |
| `--json` | — | emit a JSON array of records (one per input) instead of text, so the mapped result can be piped to other computations |

**Text mode** (default) — a load line, then one line per argument:

```bash
python3 mapper.py "op(a, op(b,c)) = op(op(a,b), c)"
# loaded 4694 laws, 4694 unique canonical keys
# 'op(a, op(b,c)) = op(op(a,b), c)' -> mapped Equation 4512 [x ◇ (y ◇ z) = (x ◇ y) ◇ z]

python3 mapper.py "x = x" "a * b = b + a" "x*(y*(z*w)) = ((x*y)*z)*w"
# loaded 4694 laws, 4694 unique canonical keys
# 'x = x' -> mapped Equation 1 [x = x]
# 'a * b = b + a' -> outside-fragment (multiple distinct operation symbols ['*', '+']: the fragment has exactly one binary operation)
# 'x*(y*(z*w)) = ((x*y)*z)*w' -> outside-fragment (valid magma identity, but order 6 > 4: not in the ETP catalogue)
```

**`--json` mode** — one record per input (no load line, so the output is valid
JSON). Each record carries `status`, `input_text`, `normalized`, `node`,
`order`, `reason` (the same keys as an `oracle.py --json` side) plus `law`, the
catalogue text when mapped. Non-mapped inputs still appear, with `node: null`
and a `reason`:

```bash
python3 mapper.py --json "p * q = q * p" "a * b = b + a"
# [
#   {
#     "status": "mapped",
#     "input_text": "p * q = q * p",
#     "normalized": "x ◇ y = y ◇ x",
#     "node": 43,
#     "order": 2,
#     "reason": null,
#     "law": "x ◇ y = y ◇ x"
#   },
#   {
#     "status": "outside-fragment",
#     "input_text": "a * b = b + a",
#     "normalized": null,
#     "node": null,
#     "order": null,
#     "reason": "multiple distinct operation symbols ['*', '+']: the fragment has exactly one binary operation",
#     "law": null
#   }
# ]
```

### `build_matrix.py`

`build_matrix.py` takes an optional positional path to the outcomes file (see
[Setup](#setup-one-time)).

### From Python

**`normalizer.py`** — the primitives are `parse_equation` (text → an
`Equation` AST, raising `ParseFailure` / `OutsideFragment`), `normalize`
(canonical variable renaming), and `canonical_key` (the orientation-independent
key). For the common "parse + normalize + metadata" case, `analyze` wraps all
three and never raises — it returns the same dict the CLI's `--json` emits:

```python
from normalizer import parse_equation, normalize, canonical_key, analyze

eq = parse_equation("a * (b * c) = (a * b) * c")   # -> Equation AST
eq.render()                                          # 'a ◇ (b ◇ c) = (a ◇ b) ◇ c'
normalize(eq).render()                               # 'x ◇ (y ◇ z) = (x ◇ y) ◇ z'
canonical_key(eq)                                    # '(x ◇ y) ◇ z = x ◇ (y ◇ z)'
eq.size()                                            # 4  (operation-symbol count / order)

analyze("p * q = q * p")
# {'input': 'p * q = q * p', 'ok': True, 'parsed': 'p ◇ q = q ◇ p',
#  'normalized': 'x ◇ y = y ◇ x', 'canonical_key': 'x ◇ y = y ◇ x',
#  'order': 2, 'variables': ['p', 'q']}

analyze("a * b * c = c")                             # errors come back as data
# {'input': 'a * b * c = c', 'ok': False, 'error': 'parse-failure',
#  'reason': "unparenthesized chain 'a * b * c': the operation is not associative, ..."}
```

**`mapper.py`** — construct one `NodeMapper` (it reads the catalogue once) and
call `.map()` per equation. It returns a `MapResult`; branch on `.mapped` (or
`.status`) and read `.node` / `.normalized` / `.order`, or `.reason` when it did
not map. `.to_dict()` gives the JSON-ready view, and `.law_text(node)` goes the
other way (node number → catalogue string):

```python
from mapper import NodeMapper
m = NodeMapper()

r = m.map("a * (b * c) = (a * b) * c")
r.status, r.node, r.normalized, r.order
# ('mapped', 4512, 'x ◇ (y ◇ z) = (x ◇ y) ◇ z', 4)

r.to_dict()
# {'status': 'mapped', 'input_text': 'a * (b * c) = (a * b) * c',
#  'normalized': 'x ◇ (y ◇ z) = (x ◇ y) ◇ z', 'node': 4512, 'order': 4, 'reason': None}

m.law_text(43)                       # node number -> catalogue text
# 'x ◇ y = y ◇ x'

bad = m.map("a * b = b + a")         # off-fragment inputs don't raise
bad.status, bad.mapped, bad.reason
# ('outside-fragment', False,
#  "multiple distinct operation symbols ['*', '+']: the fragment has exactly one binary operation")
```

**`oracle.py`** — `SemanticOracle.compare` returns a `Verdict` dataclass with
the same fields as its `--json` output (the oracle builds its own `NodeMapper`
internally, so you do not need to make one):

```python
from oracle import SemanticOracle
o = SemanticOracle()
v = o.compare("x = y ◇ (y ◇ x)", "a = (a ◇ b) ◇ b")
v.label, v.forward, v.backward, v.evidence
# ('incomparable', 'proof_false', 'proof_false',
#  'counterexample magmas refute the implication in both directions')
```
