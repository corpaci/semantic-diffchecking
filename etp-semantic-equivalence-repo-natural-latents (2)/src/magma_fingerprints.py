"""
magma_fingerprints.py -- a SEMANTIC representation of every equation.

Every text representation in equations_representations_v2.json describes the
same object: a law  lhs = rhs  over one binary operation. The py_lambda /
py_cayley_table views are literally executable, which means the meaning of an
equation can be measured directly instead of approximated by an embedding:

    fingerprint(E)[m] = 1  iff  magma m satisfies E for every variable assignment

over a fixed bank of finite magmas m. Two facts make this the strongest
signal available for the stronger/weaker/equivalent/incomparable task:

  * SOUND REFUTATION: if some magma satisfies A but not B, then A does NOT
    imply B -- this is a proof, not a guess (a finite counter-model).
  * SUBSET STRUCTURE: A => B forces Models(A) to be a subset of Models(B),
    so the direction of the relation is written directly into the
    fingerprints' subset relation -- exactly the asymmetric signal that
    symmetric similarity measures cannot express.

Unlike rich_model_counting.py (which exec()s py_cayley_table per table and
is slow), this evaluates the parsed 'formal' view vectorised over all tables
of the same size at once, and the bank mixes exhaustive tiny magmas with
STRUCTURED families (linear / affine magmas mod n, translation-invariant
magmas, projections) that are known from the Equational Theories Project to
refute most false implications -- random tables almost never satisfy a
non-trivial law and therefore carry almost no information.

Requires: numpy only.
"""
import itertools
import re

import numpy as np


# ---------------------------------------------------------------------------
# Parsing the 'formal' view:  "x = (y ◇ z) ◇ x"
# ---------------------------------------------------------------------------
_OP = '◇'


def _tokenize(s):
    return re.findall(r'[A-Za-z]+|[◇=()]', s)


def _parse_term(toks, pos):
    if toks[pos] == '(':
        node, pos = _parse_expr(toks, pos + 1)
        assert toks[pos] == ')'
        return node, pos + 1
    return ('var', toks[pos]), pos + 1


def _parse_expr(toks, pos):
    left, pos = _parse_term(toks, pos)
    while pos < len(toks) and toks[pos] == _OP:      # left-assoc if unparenthesised
        right, pos = _parse_term(toks, pos + 1)
        left = ('op', left, right)
    return left, pos


def parse_equation(s):
    toks = _tokenize(s)
    eq = toks.index('=')
    lhs, _ = _parse_expr(toks[:eq], 0)
    rhs, _ = _parse_expr(toks[eq + 1:], 0)
    return lhs, rhs


def _vars_in_order(node, out):
    if node[0] == 'var':
        if node[1] not in out:
            out.append(node[1])
    else:
        _vars_in_order(node[1], out)
        _vars_in_order(node[2], out)
    return out


# ---------------------------------------------------------------------------
# The magma bank -- three families, each with an EXACT evaluator
# ---------------------------------------------------------------------------
def _eval_tables(node, tables, assign, var_index, t_idx):
    if node[0] == 'var':
        return np.broadcast_to(assign[None, :, var_index[node[1]]], (tables.shape[0], assign.shape[0]))
    L = _eval_tables(node[1], tables, assign, var_index, t_idx)
    R = _eval_tables(node[2], tables, assign, var_index, t_idx)
    return tables[t_idx, L, R]


def _assignments(n, k):
    return np.array(list(itertools.product(range(n), repeat=k)), dtype=np.int16).reshape(n ** k, k)


def _satisfies_tables(lhs, rhs, varlist, tables, fix_first_var=False, chunk=256):
    """Brute force: every assignment of the variables, every table at once.
    fix_first_var=True is exact for translation-invariant magmas (shifting
    every variable by t shifts both sides by t), cutting cost by a factor n."""
    n = tables.shape[1]
    k = len(varlist)
    if fix_first_var and k > 0:
        rest = _assignments(n, k - 1)
        assign = np.concatenate([np.zeros((len(rest), 1), dtype=np.int16), rest], axis=1)
    else:
        assign = _assignments(n, k)
    var_index = {v: i for i, v in enumerate(varlist)}
    out = np.empty(tables.shape[0], dtype=bool)
    for s in range(0, tables.shape[0], chunk):
        tb = tables[s:s + chunk]
        t_idx = np.arange(tb.shape[0])[:, None]
        L = _eval_tables(lhs, tb, assign, var_index, t_idx)
        R = _eval_tables(rhs, tb, assign, var_index, t_idx)
        out[s:s + chunk] = (L == R).all(axis=1)
    return out


def _eval_affine(node, abc, var_index, k):
    """Symbolic evaluation in x◇y = a*x + b*y + c: every term is an affine
    form  sum_i coef_i * v_i + const.  Returns (coef (T,k), const (T,))."""
    a, b, c = abc[:, 0:1], abc[:, 1:2], abc[:, 2]
    if node[0] == 'var':
        coef = np.zeros((abc.shape[0], k), dtype=np.int64)
        coef[:, var_index[node[1]]] = 1
        return coef, np.zeros(abc.shape[0], dtype=np.int64)
    Lc, L0 = _eval_affine(node[1], abc, var_index, k)
    Rc, R0 = _eval_affine(node[2], abc, var_index, k)
    return a * Lc + b * Rc, a[:, 0] * L0 + b[:, 0] * R0 + c


class TableFamily:
    """Explicit Cayley tables of one size, evaluated by brute force."""
    def __init__(self, name, tables, translation_invariant=False):
        self.name, self.tables, self.ti = name, tables, translation_invariant

    def __len__(self):
        return len(self.tables)

    def evaluate(self, lhs, rhs, varlist):
        return _satisfies_tables(lhs, rhs, varlist, self.tables, fix_first_var=self.ti)


class AffineFamily:
    """All affine magmas x◇y = a*x + b*y + c on Z_n. Checked symbolically: a
    law holds iff both sides have identical coefficients mod n -- exact, and
    independent of the number of variables, so large n costs nothing."""
    def __init__(self, n):
        self.name, self.n = f'affine_n{n}', n
        self.abc = np.array(list(itertools.product(range(n), repeat=3)), dtype=np.int64)

    def __len__(self):
        return len(self.abc)

    def evaluate(self, lhs, rhs, varlist):
        var_index = {v: i for i, v in enumerate(varlist)}
        Lc, L0 = _eval_affine(lhs, self.abc, var_index, len(varlist))
        Rc, R0 = _eval_affine(rhs, self.abc, var_index, len(varlist))
        n = self.n
        return (((Lc - Rc) % n == 0).all(axis=1)) & ((L0 - R0) % n == 0)


def _all_tables(n):
    return np.array(list(itertools.product(range(n), repeat=n * n)), dtype=np.int16).reshape(-1, n, n)


def _translation_invariant_tables(n, max_count, rng):
    """x◇y = x + f(y - x) (mod n) for functions f: Z_n -> Z_n -- a family the
    Equational Theories Project leaned on heavily for counterexamples."""
    x = np.arange(n)[:, None]
    y = np.arange(n)[None, :]
    if n ** n <= max_count:
        fs = [np.array(f) for f in itertools.product(range(n), repeat=n)]
    else:
        fs = [rng.randint(0, n, size=n) for _ in range(max_count)]
    return np.array([(x + f[(y - x) % n]) % n for f in fs], dtype=np.int16)


def build_magma_bank(seed=0, exhaustive_3=False, affine_sizes=tuple(range(2, 12)),
                     ti_sizes=(3, 4, 5, 6), ti_max=400, random_sizes=((3, 300), (4, 200))):
    """A list of magma families. Defaults (~7k magmas, fast):
      * all 16 magmas of size 2 (brute force)
      * all affine magmas a*x+b*y+c mod n for n = 2..11 (symbolic, exact)
      * translation-invariant magmas x + f(y-x) mod n, n = 3..6
      * a few hundred random tables of size 3 and 4
    exhaustive_3=True adds all 19,683 magmas of size 3 (several times slower)."""
    rng = np.random.RandomState(seed)
    fams = [TableFamily('all_n2', _all_tables(2))]
    if exhaustive_3:
        fams.append(TableFamily('all_n3', _all_tables(3)))
    fams += [AffineFamily(n) for n in affine_sizes]
    fams += [TableFamily(f'transinv_n{n}', _translation_invariant_tables(n, ti_max, rng),
                         translation_invariant=True) for n in ti_sizes]
    fams += [TableFamily(f'random_n{n}', rng.randint(0, n, size=(cnt, n, n)).astype(np.int16))
             for n, cnt in random_sizes]
    return fams


def bank_labels(bank):
    """Family name of every fingerprint column."""
    return [f.name for f in bank for _ in range(len(f))]


def fingerprints(formals, bank):
    """(N_equations, N_magmas) bool matrix: bit m is set iff magma m satisfies
    the equation for every assignment of its variables."""
    F = np.zeros((len(formals), sum(len(f) for f in bank)), dtype=bool)
    for i, formal in enumerate(formals):
        lhs, rhs = parse_equation(formal)
        varlist = _vars_in_order(rhs, _vars_in_order(lhs, []))
        F[i] = np.concatenate([f.evaluate(lhs, rhs, varlist) for f in bank])
    return F


# ---------------------------------------------------------------------------
# Pairwise semantic features
# ---------------------------------------------------------------------------
def counterexample_counts(F):
    """C[i, j] = number of bank magmas satisfying equation i but NOT j.
    C[i, j] > 0 is a sound proof that  i does NOT imply j."""
    Fi = F.astype(np.float32)
    return (Fi @ (1.0 - Fi).T).astype(np.int32)


def pair_semantic_features(F, ii, jj, C=None):
    """Directional, per-pair features from the fingerprints.

    For pair (A, B):
      cex_ab   = #magmas with A true, B false  (>0 => A does not imply B)
      cex_ba   = #magmas with B true, A false  (>0 => B does not imply A)
      both     = #magmas satisfying both
      n_a, n_b = #models of each (log-scaled)
      jaccard  = |A∩B| / |A∪B|
      refuted_ab, refuted_ba = hard 0/1 refutation flags
    """
    if C is None:
        C = counterexample_counts(F)
    nm = F.sum(axis=1).astype(np.float64)
    both = (F[ii] & F[jj]).sum(axis=1).astype(np.float64)
    cex_ab = C[ii, jj].astype(np.float64)
    cex_ba = C[jj, ii].astype(np.float64)
    union = nm[ii] + nm[jj] - both
    jac = np.where(union > 0, both / np.maximum(union, 1), 1.0)
    return np.stack([
        np.log1p(cex_ab), np.log1p(cex_ba), np.log1p(both),
        np.log1p(nm[ii]), np.log1p(nm[jj]), jac,
        (cex_ab > 0).astype(float), (cex_ba > 0).astype(float),
    ], axis=1)


PAIR_SEMANTIC_FEATURE_NAMES = ['log_cex_ab', 'log_cex_ba', 'log_both', 'log_models_a',
                               'log_models_b', 'jaccard', 'refuted_ab', 'refuted_ba']


def rule_based_relation(C, ii, jj):
    """Zero-training decision rule: an implication holds unless a
    counter-model refutes it. Returns label ids using the dataset's
    convention (see data/decode_matrix.py):
        0 equivalent   (A=>B and B=>A)
        1 stronger     (B=>A only)
        2 weaker       (A=>B only)
        3 incomparable (neither)
    """
    fwd = C[ii, jj] == 0      # A => B not refuted
    bwd = C[jj, ii] == 0      # B => A not refuted
    return np.where(fwd & bwd, 0, np.where(bwd, 1, np.where(fwd, 2, 3)))


# ---------------------------------------------------------------------------
# Cheap syntactic invariants of a single equation (from the 'formal' view)
# ---------------------------------------------------------------------------
def _depth(node):
    return 0 if node[0] == 'var' else 1 + max(_depth(node[1]), _depth(node[2]))


def _nops(node):
    return 0 if node[0] == 'var' else 1 + _nops(node[1]) + _nops(node[2])


def _var_counts(node, out):
    if node[0] == 'var':
        out[node[1]] = out.get(node[1], 0) + 1
    else:
        _var_counts(node[1], out)
        _var_counts(node[2], out)
    return out


def _leftmost(node):
    return node[1] if node[0] == 'var' else _leftmost(node[1])


def _rightmost(node):
    return node[1] if node[0] == 'var' else _rightmost(node[2])


def structural_invariants(formal):
    """Per-equation features known to matter for implication in magma laws:
    size, depth, #variables, whether a side is a bare variable, whether a
    variable occurs on only one side (such laws force strong collapse), and
    the leftmost/rightmost variable agreement (invariants preserved by the
    left/right-projection magmas)."""
    lhs, rhs = parse_equation(formal)
    vl, vr = _var_counts(lhs, {}), _var_counts(rhs, {})
    allv = set(vl) | set(vr)
    only_one_side = len(set(vl) ^ set(vr))
    return np.array([
        _nops(lhs), _nops(rhs), _nops(lhs) + _nops(rhs),
        _depth(lhs), _depth(rhs),
        len(allv), only_one_side,
        float(lhs[0] == 'var'), float(rhs[0] == 'var'),
        float(_leftmost(lhs) == _leftmost(rhs)),
        float(_rightmost(lhs) == _rightmost(rhs)),
        max(list(vl.values()) + list(vr.values())),
        sum(vl.values()) + sum(vr.values()),
    ], dtype=np.float64)


STRUCTURAL_FEATURE_NAMES = ['ops_lhs', 'ops_rhs', 'ops_total', 'depth_lhs', 'depth_rhs',
                            'n_vars', 'n_vars_one_side', 'lhs_is_var', 'rhs_is_var',
                            'leftmost_agree', 'rightmost_agree', 'max_var_mult',
                            'n_var_occurrences']


if __name__ == '__main__':
    bank = build_magma_bank()
    print({f.name: len(f) for f in bank}, 'total', len(bank_labels(bank)))
    F = fingerprints(['x ◇ y = y ◇ x', 'x ◇ (y ◇ z) = (x ◇ y) ◇ z', 'x = y', 'x = x'], bank)
    print(F.sum(axis=1))
    C = counterexample_counts(F)
    print(C)
