# `translate/py_cayley_table` — ETP formal equations → finite-magma checkers, deterministically

An ETP law is a small, fully specified object: one binary operation, some
variables, an equality. Turning it into a Python checker is a structural
rewrite of its parse tree, so **no model is involved anywhere in this
directory** — there is nothing here to guess at, and a guess would introduce
exactly the kind of silent drift this project exists to measure.

The target form is a function that decides the law on one finite magma, given
as a Cayley table — `table[a][b]` is `a ◇ b` over the carrier
`range(len(table))`:

```python
# x ◇ y = y ◇ x
def law(table):
    n = len(table)
    return all(table[x][y] == table[y][x] for x in range(n) for y in range(n))

# x = (y ◇ x) ◇ (x ◇ z)
def law(table):
    n = len(table)
    return all(x == table[table[y][x]][table[x][z]] for x in range(n) for y in range(n) for z in range(n))
```

Every `◇` becomes a table lookup — nested lookups for nested operations — and
the formal text's implicit universal quantification becomes one `for` clause
per variable, in first-appearance order. This is the representation under
which a law is *decidable*: the ETP itself refutes implications by exhibiting
finite magmas, and this checker run on such a table reproduces exactly that
judgment.

**Deliberately absent: anything that names the law.** This catalogue is test
data for representation-translation experiments (can a model translate one
representation into another without changing the meaning?), and a model may
well have seen the ETP data. So every checker is named `law`, with no
docstring, no comment, no equation number — nothing that would let a
translator shortcut through the answer key instead of reading the structure.

The parse tree comes from [`../../oracle/normalizer.py`](../../oracle/README.md):
`parse_equation` returns `Equation(lhs, rhs)` over `Op(left, right)` and
`Var(name)` nodes, and `cayleyify` walks it. Reusing the oracle's parser rather
than writing a second one is deliberate — a private parser here could disagree
with the one the semantic oracle uses, and a Python rendering would then no
longer be evidence about the same equation.

## Files

| file | role |
|---|---|
| `cayleyify.py` | the renderer: `checker_source`, `analyze`, `read_back`, `verify_round_trip`, `holds`, `semantically_agrees`, a CLI, and `--selftest` |
| `build_catalogue.py` | export all 4694 ETP laws to JSON |
| `etp_equations_py_cayley_table.json` | the generated catalogue — 4694 formal/checker pairs, 1.7 MB |

Nothing needs installing beyond system `python3` plus a copy of the ETP
`equations.txt` (located exactly as [`../../oracle`](../../oracle/README.md)
locates it — `$ETP_EQUATIONS`, else `$ETP_ROOT/data/equations.txt`, else
`~/equational_theories/...`; or pass `--equations`).

## The generated catalogue

```bash
python3 build_catalogue.py            # -> etp_equations_py_cayley_table.json
```

```json
{
  "meta": {
    "generator": "translate/py_cayley_table/build_catalogue.py",
    "source": "equational_theories/data/equations.txt",
    "count": 4694,
    "style": { "form": "def", "function_name": "law", "table_name": "table",
               "size_name": "n", "docstring": false,
               "node_in_representation": false },
    "verified": true
  },
  "equations": [
    { "node": 43, "formal": "x ◇ y = y ◇ x",
      "py_cayley_table": "def law(table):\n    n = len(table)\n    return all(table[x][y] == table[y][x] for x in range(n) for y in range(n))\n",
      "order": 2, "variables": ["x", "y"] }
  ]
}
```

`node` and `formal` live only in the row metadata, for joining against the
implication graph and the other catalogues — the `py_cayley_table` string
itself is clean. There is deliberately **no `normalized` field**: the
catalogue text is already canonical (variables renamed by first appearance,
`◇` as the operation), and the build asserts that for every row rather than
asking you to take it on trust.

| flag | meaning |
|---|---|
| `--out PATH` | JSON output path (default `etp_equations_py_cayley_table.json` beside the script) |
| `--equations PATH` | a specific `equations.txt` |
| `--limit N` | only the first N equations |
| `--no-verify` | skip the round-trip, semantic, and canonical-form checks (not advised) |

## Rendering one equation

```bash
python3 cayleyify.py "x ◇ (y ◇ z) = (x ◇ y) ◇ z"
# formal: x ◇ (y ◇ z) = (x ◇ y) ◇ z
# python:
#   def law(table):
#       n = len(table)
#       return all(table[x][table[y][z]] == table[table[x][y]][z] for x in range(n) for y in range(n) for z in range(n))
# node:   Equation 4512
# order:  4   variables: x, y, z

python3 cayleyify.py 43 4512         # bare integers are ETP numbers
python3 cayleyify.py --json 43       # records, for piping
python3 cayleyify.py --selftest      # rendering + round trip + semantics + error cases
```

From Python:

```python
from cayleyify import checker_source, compile_checker, holds, analyze
from normalizer import parse_equation   # via cayleyify's sys.path bootstrap

eq = parse_equation("x ◇ y = y ◇ x")
src = checker_source(eq)                 # the string above
fn = compile_checker(src)
fn(((0, 1), (1, 0)))                     # True  — xor is commutative
fn(((0, 0), (1, 1)))                     # False — left projection is not
holds(eq, ((0, 1), (1, 0)))              # True  — same judgment, straight off the tree
```

`checker_source` raises the oracle's `ParseFailure` / `OutsideFragment` for
anything that is not a single-operation magma identity, plus this module's
`Unrepresentable` for a law whose variable names Python cannot bind or that
would shadow the scaffold's own names (`law`, `table`, `n` — never triggered
by the catalogue, whose variables are `x y z w u v`); `analyze` returns all of
these as data.

## Decisions worth knowing

**A fixed three-line scaffold.** `def law(table):` / `n = len(table)` /
`return all(<comparison> <for-clauses>)` — byte-deterministic, with the
comparison and the `for` clauses as the only degrees of freedom. A fixed shape
is what lets `read_back` demand exactness instead of guessing, and what makes
two checkers comparable term-for-term.

**Lookups, not calls.** `table[a][b]` instead of an `op(a, b)` closure keeps
the checker self-contained — the emitted string uses only `len`, `range`, and
`all`, and is compiled with exactly those three builtins in scope, pinning
that claim. The sibling [`../py_lambda`](../py_lambda) catalogue is the
abstract-operation counterpart: the same laws over an `op` callable, one
assignment at a time, rather than one whole magma at a time.

**Brute force is the right amount of force.** Complexity is `n^k` for `k`
distinct variables; the catalogue's maximum is `k = 6` (a handful of order-4
laws), which is 4096 iterations at `n = 4`. Nothing here needs to be cleverer
than the specification, and the naive nest is what stays provably isomorphic
to the term tree.

**Decidability is the point.** A law's satisfaction fingerprint across a
library of small tables separates inequivalent laws with a concrete
counterexample table as the certificate — the same move the ETP uses to refute
implications. That makes this the representation whose semantic content can be
probed empirically, downstream of translation experiments.

## Verification

Three independent checks run over every row of the build; a failure aborts
with the offending node before anything is written.

| check | what it proves | how |
|---|---|---|
| round trip | the *structure* is right — lookup order, nesting, loop-variable order. `read_back` parses the emitted string with Python's own `ast` module (not a parser of ours), checks the scaffold exactly, walks the comparison back to the oracle's AST, and requires the trees to be **equal** (frozen dataclasses, so `==` compares shape and names exactly) and the loop variables to match first-appearance order | every row of `build_catalogue.py`; also in `cayleyify.py --selftest` |
| semantics | the string *decides* the law, not merely resembles it — the compiled checker's verdict and a brute-force reference judgment (which never sees the string) must agree, table by table, on six small Cayley tables chosen to be mutually distinguishing: left/right projection (tell a swapped lookup apart), xor, addition mod 3, min, and one arbitrary asymmetric table | every row of `build_catalogue.py`; the selftest additionally confirms a deliberately swapped-lookup checker is rejected |
| canonical form | the catalogue text really is already normalized, so omitting a `normalized` field stays honest | every row of `build_catalogue.py` |

The semantic check is the distinctive one: for LaTeX or Lean the best a build
can do locally is re-parse its own output, but a checker can be *run*, so
structure and meaning are checked by two independent routes.
