"""
Script 6: Rich Model-Counting via Executable Representations
================================================================

THOUGHT PROCESS
----------------
This project's `py_cayley_table` representation isn't just text to embed --
it's literally executable Python code that checks an equation against a
real multiplication table:

    def law(table):
        n = len(table)
        return all(table[x][y] == table[y][x] for x in range(n) for y in range(n))

That means instead of approximating meaning through embeddings, we can
EXECUTE the real semantic check -- extending the exact condensation engine
(script 1) past its size-2/3 exhaustive-enumeration limit, using random
sampling for larger magma sizes.

RESULT FROM THIS PROJECT: when this method commits to a confident
stronger/weaker call, it's right 90.4% of the time -- dramatically better
than any embedding-based method tested. But it only speaks confidently for
about 9% of all pairs; its "equivalent" calls specifically are unreliable
(same "no counterexample found in this random sample" problem as the exact
engine in script 1).

TWO REAL BUGS FOUND BUILDING THIS -- READ BEFORE USING
----------------------------------------------------------

BUG A (float32 precision -- also documented in script 4): clipping a
probability to [1e-9, 1-1e-9] using float32 silently fails at p=1.0, because
`1 - 1e-9` rounds to exactly 1.0 in float32. Always compute entropy/KL in
float64. This bug alone turned a real result into a fake 79% "accuracy"
(pure majority-class collapse) before it was caught.

BUG B (a genuine dataset-level confound, not a code bug -- the more
important one to understand): whenever EITHER equation in a pair has zero
satisfying models in the check universe, BOTH directional loss values
collapse to exactly ~0 -- which looks EXACTLY like a confident "equivalent"
call to any downstream classifier, but has nothing to do with the equations'
real relationship. Worse: in the real ETP dataset, "unresolvable" equations
are heavily correlated with the TRUE label for reasons unrelated to
semantics (complex equations are more likely to be both unresolvable AND
part of a `stronger`/`weaker` family). Feeding "number of satisfying
models" directly into a classifier alongside loss values let it learn this
shortcut and produced a fake 97.68% accuracy. THE FIX: always pass
resolvability as its OWN explicit feature (see `is_resolvable` below), never
let a zero-loss value silently mean two different things.

Requires: numpy only (uses Python's own exec() to run the provided code)
"""
import itertools
import numpy as np


def make_law_fn(code_str):
    """Safely extract the law() function from the repo's provided source."""
    namespace = {}
    exec(code_str, namespace)
    return namespace['law']


def build_candidate_universe(seed=0):
    """
    Exhaustive for tiny sizes (matches script 1's own universe), then random
    sampling for larger sizes -- exhaustive enumeration is only feasible up
    to about size 3 (3^9 = 19,683 tables); size 4 alone is already 4.3
    billion tables.
    """
    universe = []

    def all_tables_exhaustive(n):
        entries = list(itertools.product(range(n), repeat=n * n))
        return [np.array(e).reshape(n, n).tolist() for e in entries]

    def random_tables(n, count, s):
        rng = np.random.RandomState(s)
        return [rng.randint(0, n, size=(n, n)).tolist() for _ in range(count)]

    universe.extend(all_tables_exhaustive(2))       # 16 tables
    universe.extend(all_tables_exhaustive(3))       # 19,683 tables
    for n, count in [(4, 5000), (5, 5000), (6, 3000), (7, 2000), (8, 1000)]:
        universe.extend(random_tables(n, count, seed + n))
    return universe   # 35,699 total


def evaluate_equation_against_universe(law_code, universe):
    """Returns a boolean numpy array: which tables in the universe satisfy
    this equation."""
    law_fn = make_law_fn(law_code)
    return np.array([law_fn(t) for t in universe], dtype=bool)


def compare_via_model_counting(model_set_a, model_set_b, eps=1e-6):
    """
    Same Loss(A|B)/Loss(B|A) logic as script 1, now over the richer universe.
    Returns is_resolvable as an EXPLICIT separate field -- see BUG B above
    for why this matters: never let a caller assume zero-loss means
    "equivalent" without also checking resolvability.
    """
    n_a, n_b = model_set_a.sum(), model_set_b.sum()
    if n_a == 0 or n_b == 0:
        return {'relation': None, 'is_resolvable': False,
                'loss_A_given_B': None, 'loss_B_given_A': None}

    intersection = (model_set_a & model_set_b).sum()
    # BUG A fix: compute in float64
    p_a_given_b = np.float64(intersection) / np.float64(n_b)
    p_b_given_a = np.float64(intersection) / np.float64(n_a)

    def H(p):
        p = np.clip(p, 1e-9, 1 - 1e-9)   # safe now: float64, not float32
        return float(-p * np.log2(p) - (1 - p) * np.log2(1 - p))

    loss_ab, loss_ba = H(p_a_given_b), H(p_b_given_a)

    if loss_ab <= eps and loss_ba <= eps:
        relation = 'equivalent'
    elif loss_ba <= eps:
        relation = 'A_stronger'
    elif loss_ab <= eps:
        relation = 'B_stronger'
    else:
        relation = 'incomparable'

    return {'relation': relation, 'is_resolvable': True,
            'loss_A_given_B': loss_ab, 'loss_B_given_A': loss_ba,
            'n_models_A': int(n_a), 'n_models_B': int(n_b)}


if __name__ == '__main__':
    print("Building candidate universe (this takes a few seconds)...")
    universe = build_candidate_universe()
    print(f"  {len(universe):,} candidate magmas\n")

    law_commutative = "def law(table):\n    n = len(table)\n    return all(table[x][y] == table[y][x] for x in range(n) for y in range(n))"
    law_reflexive = "def law(table):\n    n = len(table)\n    return all(x == x for x in range(n))"   # trivially true everywhere

    models_a = evaluate_equation_against_universe(law_commutative, universe)
    models_b = evaluate_equation_against_universe(law_reflexive, universe)
    print(f"commutativity satisfied by {models_a.sum():,} / {len(universe):,} candidate magmas")
    print(f"reflexivity satisfied by {models_b.sum():,} / {len(universe):,} candidate magmas")

    result = compare_via_model_counting(models_a, models_b)
    print(f"\ncomparison result: {result}")
    print("(reflexivity should show as strictly weaker than nothing in particular here --")
    print(" it's satisfied by EVERY magma, so it should end up 'weaker' relative to almost anything)")
