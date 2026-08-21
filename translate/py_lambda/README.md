# `translate/py_lambda` — ETP formal equations → Python lambda predicates, deterministically

An ETP law is a small, fully specified object: one binary operation, some
variables, an equality. Turning it into a Python predicate is a structural
rewrite of its parse tree, so **no model is involved anywhere in this
directory** — there is nothing here to guess at, and a guess would introduce
exactly the kind of silent drift this project exists to measure.

The target form is a bare lambda over an abstract binary operation:

```
formal (ETP)                 Python
x ◇ y = y ◇ x                lambda op, x, y: op(x, y) == op(y, x)
x = x ◇ (x ◇ x)              lambda op, x: x == op(x, op(x, x))
x ◇ (y ◇ z) = (x ◇ y) ◇ z    lambda op, x, y, z: op(x, op(y, z)) == op(op(x, y), z)
```

`op` is the magma operation as a two-argument callable; the remaining
parameters are the law's variables in first-appearance order, so the formal
text's implicit universal quantification becomes the parameter list. Every `◇`
is a prefix call `op(a, b)` — prefix application has no precedence or
associativity, so the Python expression tree is isomorphic to the law's term
tree by construction.

**Deliberately absent: anything that names the law.** This catalogue is test
data for representation-translation experiments (can a model translate one
representation into another without changing the meaning?), and a model may
well have seen the ETP data. So the lambda carries no function name, no
docstring, no comment, no equation number — nothing that would let a
translator shortcut through the answer key instead of reading the structure.

The parse tree comes from [`../../oracle/normalizer.py`](../../oracle/README.md):
`parse_equation` returns `Equation(lhs, rhs)` over `Op(left, right)` and
`Var(name)` nodes, and `lambdify` walks it. Reusing the oracle's parser rather
than writing a second one is deliberate — a private parser here could disagree
with the one the semantic oracle uses, and a Python rendering would then no
longer be evidence about the same equation.

## Files

| file | role |
|---|---|
| `lambdify.py` | the renderer: `py_lambda`, `analyze`, `read_back`, `verify_round_trip`, `semantically_agrees`, a CLI, and `--selftest` |
| `build_catalogue.py` | export all 4694 ETP laws to JSON |
| `etp_equations_py_lambda.json` | the generated catalogue — 4694 formal/lambda pairs, 1.2 MB |

Nothing needs installing beyond system `python3` plus a copy of the ETP
`equations.txt` (located exactly as [`../../oracle`](../../oracle/README.md)
locates it — `$ETP_EQUATIONS`, else `$ETP_ROOT/data/equations.txt`, else
`~/equational_theories/...`; or pass `--equations`).

## The generated catalogue

```bash
python3 build_catalogue.py            # -> etp_equations_py_lambda.json
```

```json
{
  "meta": {
    "generator": "translate/py_lambda/build_catalogue.py",
    "source": "equational_theories/data/equations.txt",
    "count": 4694,
    "style": { "form": "lambda", "operator_name": "op",
               "docstring": false, "node_in_representation": false },
    "verified": true
  },
  "equations": [
    { "node": 43, "formal": "x ◇ y = y ◇ x",
      "py_lambda": "lambda op, x, y: op(x, y) == op(y, x)",
      "order": 2, "variables": ["x", "y"] }
  ]
}
```

`node` and `formal` live only in the row metadata, for joining against the
implication graph and the other catalogues — the `py_lambda` string itself is
clean. There is deliberately **no `normalized` field**: the catalogue text is
already canonical (variables renamed by first appearance, `◇` as the
operation), and the build asserts that for every row rather than asking you to
take it on trust.

| flag | meaning |
|---|---|
| `--out PATH` | JSON output path (default `etp_equations_py_lambda.json` beside the script) |
| `--equations PATH` | a specific `equations.txt` |
| `--limit N` | only the first N equations |
| `--no-verify` | skip the round-trip, semantic, and canonical-form checks (not advised) |

## Rendering one equation

```bash
python3 lambdify.py "x ◇ (y ◇ z) = (x ◇ y) ◇ z"
# formal: x ◇ (y ◇ z) = (x ◇ y) ◇ z
# python: lambda op, x, y, z: op(x, op(y, z)) == op(op(x, y), z)
# node:   Equation 4512
# order:  4   variables: x, y, z

python3 lambdify.py 43 4512          # bare integers are ETP numbers
python3 lambdify.py --json 43        # records, for piping
python3 lambdify.py --selftest       # rendering + round trip + semantics + error cases
```

From Python:

```python
from lambdify import py_lambda, analyze
from normalizer import parse_equation   # via lambdify's sys.path bootstrap

py_lambda(parse_equation("x ◇ y = y ◇ x"))   # 'lambda op, x, y: op(x, y) == op(y, x)'
analyze("a * b * c = c")                     # {'ok': False, 'error': 'parse-failure', ...}
```

`py_lambda` raises the oracle's `ParseFailure` / `OutsideFragment` for anything
that is not a single-operation magma identity, plus this module's
`Unrepresentable` for a law whose variable names Python cannot bind (a keyword,
or `op` itself — never triggered by the catalogue, whose variables are
`x y z w u v`); `analyze` returns all three as data.

## Decisions worth knowing

**Prefix calls, not an overloaded operator.** `op(a, b)` instead of `a * b` on
a term class: infix Python would reintroduce precedence and left-associativity
(`x * y * z` silently means `(x * y) * z`), exactly the class of ambiguity the
oracle's canonical text exists to rule out. With prefix calls the call tree
*is* the term tree, and the round trip below can demand exact equality.

**The lambda is executable, and that is checked.** The string is not just
shaped like the law — compiled, it decides the law on any concrete operation:
`fn(lambda a, b: table[a][b], *assignment)` evaluates the identity at one
point of a finite magma. The build exploits this (see Verification), and it is
what makes this representation semantically grounded rather than a re-skinning
of the LaTeX one.

**`==` is honest equality here.** The intended domains are finite carriers
(ints); no floats, no exotic `__eq__`. The lambda compiles and runs with an
empty `__builtins__`, pinning the claim that it needs nothing but its
parameters.

## Verification

Three independent checks run over every row of the build; a failure aborts
with the offending node before anything is written.

| check | what it proves | how |
|---|---|---|
| round trip | the *structure* is right — operand order, nesting, parameter order. `read_back` parses the emitted string with Python's own `ast` module (not a parser of ours), walks the `Lambda` node back to the oracle's AST, and requires the trees to be **equal** (frozen dataclasses, so `==` compares shape and names exactly) and the parameters to match first-appearance order | every row of `build_catalogue.py`; also in `lambdify.py --selftest` |
| semantics | the string *computes* the law, not merely resembles it — the compiled lambda and a tree interpreter (which never sees the string) must agree, truth value by truth value, on every assignment of six small Cayley tables chosen to be mutually distinguishing: left/right projection (tell a swapped operand apart), xor, addition mod 3, min, and one arbitrary asymmetric table | every row of `build_catalogue.py`; the selftest additionally confirms a deliberately swapped-operand lambda is rejected |
| canonical form | the catalogue text really is already normalized, so omitting a `normalized` field stays honest | every row of `build_catalogue.py` |

The semantic check is the distinctive one: for LaTeX or Lean the best a build
can do locally is re-parse its own output, but a Python predicate can be *run*,
so structure and meaning are checked by two independent routes.
