"""
Script 1: Condensation Engine (exact finite-model checking)
=============================================================

THOUGHT PROCESS
----------------
Classical logic only answers "does A imply B?" with yes/no. We want a graded
alternative that distinguishes: equivalent / A-stronger / A-weaker / incomparable,
grounded in real information theory rather than a heuristic.

Loss(A|B) = H(A|B)   -- residual uncertainty about A, given B is true
Loss(B|A) = H(B|A)   -- the mirror direction

    Loss(A|B)=0, Loss(B|A)=0   -> equivalent
    Loss(B|A)=0 only           -> A is stronger (A implies B)
    Loss(A|B)=0 only           -> B is stronger
    both > 0                   -> incomparable

HOW IT'S COMPUTED HERE (the "exact" approach -- no embeddings at all)
----------------------------------------------------------------------
1. Enumerate every possible finite magma (a set with a binary operation ~)
   of size 2 and size 3 -- 2^4 + 3^9 = 19,699 candidate "worlds".
2. For each equation, check which of those 19,699 worlds satisfy it, for
   EVERY possible assignment of its variables -- this gives Models(equation),
   a boolean bitmask over the 19,699-world universe.
3. For a pair (A, B): P(A|B) = |Models(A) & Models(B)| / |Models(B)|,
   then Loss(A|B) = H(P(A|B)) using standard binary entropy.

LIMITATION, discovered and confirmed across this whole project:
- Only ~30-46% of real equations have ANY satisfying model within this small
  universe (resolvability drops sharply as variable count increases: ~100%
  at 1 variable, ~0% at 6 variables).
- When unresolvable, this engine has no "unknown" output and silently
  defaults toward "equivalent" -- this is a real, confirmed bug (see the
  README for the exact numbers), not a design choice. Fix: use a real
  constraint solver (Mace4/Prover9) instead of brute-force enumeration to
  push coverage further, and add an explicit "unresolved" state.

USAGE
-----
    from condensation_engine import compare_equations
    result = compare_equations("x = y \u25c7 y", "x \u25c7 y = y \u25c7 x")
    print(result)   # {'relation': 'incomparable', 'loss_A_given_B': ..., ...}
"""
import re
import itertools
import numpy as np


# ---------------------------------------------------------------------------
# Step 1: parser -- turns "x \u25c7 y = z" into a small nested-tuple AST
# ---------------------------------------------------------------------------
def tokenize(s):
    return re.findall(r'[A-Za-z]+|[\u25c7=()]', s)


def parse_term(toks, pos):
    if toks[pos] == '(':
        node, pos = parse_expr(toks, pos + 1)
        assert toks[pos] == ')'
        return node, pos + 1
    return ('var', toks[pos]), pos + 1


def parse_expr(toks, pos):
    left, pos = parse_term(toks, pos)
    if pos < len(toks) and toks[pos] == '\u25c7':
        right, pos = parse_term(toks, pos + 1)
        return ('op', left, right), pos
    return left, pos


def parse_equation(s):
    toks = tokenize(s)
    eq = toks.index('=')
    lhs, _ = parse_expr(toks[:eq], 0)
    rhs, _ = parse_expr(toks[eq + 1:], 0)
    return ('eq', lhs, rhs)


def collect_vars(node, out):
    if node[0] == 'var':
        out.add(node[1])
    else:
        collect_vars(node[1], out)
        collect_vars(node[2], out)


# ---------------------------------------------------------------------------
# Step 2: build the universe of candidate finite magmas
# ---------------------------------------------------------------------------
def all_tables(n):
    """Every possible n x n multiplication table -- n^(n^2) of them."""
    entries = list(itertools.product(range(n), repeat=n * n))
    return np.array(entries, dtype=np.int8).reshape(-1, n, n)


_UNIVERSE_CACHE = {}


def get_universe():
    """Build (once, cached) the combined size-2 + size-3 universe: 19,699 tables."""
    if 'T2' not in _UNIVERSE_CACHE:
        _UNIVERSE_CACHE['T2'] = all_tables(2)
        _UNIVERSE_CACHE['T3'] = all_tables(3)
    return _UNIVERSE_CACHE['T2'], _UNIVERSE_CACHE['T3']


# ---------------------------------------------------------------------------
# Step 3: vectorized evaluator -- check an equation against EVERY table in
# one universe at once, for every possible variable assignment
# ---------------------------------------------------------------------------
def eval_node(node, table, assign, var_index):
    T = table.shape[0]
    if node[0] == 'var':
        col = assign[:, var_index[node[1]]]
        return np.broadcast_to(col[None, :], (T, col.shape[0]))
    else:
        L = eval_node(node[1], table, assign, var_index)
        R = eval_node(node[2], table, assign, var_index)
        t_idx = np.arange(T)[:, None]
        return table[t_idx, L, R]


def models_of(equation_str, table, n):
    """Boolean array: for each table, does the equation hold for ALL
    variable assignments?"""
    ast = parse_equation(equation_str)
    varset = set()
    collect_vars(ast, varset)
    varlist = sorted(varset)
    var_index = {v: i for i, v in enumerate(varlist)}
    assign = np.array(list(itertools.product(range(n), repeat=len(varlist))), dtype=np.int8)
    L = eval_node(ast[1], table, assign, var_index)
    R = eval_node(ast[2], table, assign, var_index)
    return (L == R).all(axis=1)


def model_set(equation_str):
    """Full Models(equation) bitmask over the 19,699-table universe."""
    T2, T3 = get_universe()
    h2 = models_of(equation_str, T2, 2)
    h3 = models_of(equation_str, T3, 3)
    return np.concatenate([h2, h3])


# ---------------------------------------------------------------------------
# Step 4: entropy + classification
# ---------------------------------------------------------------------------
def H(p):
    """Standard binary entropy, in bits."""
    if p <= 0 or p >= 1:
        return 0.0
    return -p * np.log2(p) - (1 - p) * np.log2(1 - p)


def compare_equations(equation_a, equation_b, eps=1e-9):
    """
    The main entry point. Returns a dict with the relation and both
    directional losses, OR {'relation': 'unresolvable', ...} if either
    equation has zero satisfying models in the 19,699-table universe.
    """
    models_a = model_set(equation_a)
    models_b = model_set(equation_b)
    n_a, n_b = models_a.sum(), models_b.sum()

    if n_a == 0 or n_b == 0:
        return {'relation': 'unresolvable', 'loss_A_given_B': None, 'loss_B_given_A': None,
                'note': 'one or both equations have zero satisfying models in this finite universe '
                        '-- likely needs a magma size > 3 to resolve; see README for coverage stats'}

    intersection = (models_a & models_b).sum()
    p_a_given_b = intersection / n_b
    p_b_given_a = intersection / n_a
    loss_a_given_b = H(p_a_given_b)
    loss_b_given_a = H(p_b_given_a)

    if loss_a_given_b <= eps and loss_b_given_a <= eps:
        relation = 'equivalent'
    elif loss_b_given_a <= eps:
        relation = 'A_stronger'   # A implies B, B doesn't imply A
    elif loss_a_given_b <= eps:
        relation = 'B_stronger'
    else:
        relation = 'incomparable'

    return {'relation': relation, 'loss_A_given_B': loss_a_given_b, 'loss_B_given_A': loss_b_given_a,
            'n_models_A': int(n_a), 'n_models_B': int(n_b), 'n_shared_models': int(intersection)}


if __name__ == '__main__':
    # A few worked examples, illustrating each of the four outcomes
    examples = [
        ("x = x \u25c7 x", "x = x \u25c7 x"),                 # trivially equivalent
        ("x \u25c7 y = y \u25c7 x", "x = x"),                    # commutativity vs. reflexivity: incomparable
        ("x = y \u25c7 y", "x \u25c7 y = y \u25c7 y"),           # a genuine A-stronger / B-weaker pair
    ]
    for a, b in examples:
        result = compare_equations(a, b)
        print(f"A: {a}\nB: {b}\n  -> {result}\n")
