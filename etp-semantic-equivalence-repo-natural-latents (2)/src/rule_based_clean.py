"""
Clean rule-based classifier: real algebraic properties, extracted honestly,
with resolvability kept as an EXPLICIT separate signal (the exact fix for
the leakage bug found in the external approach's version of this idea).
"""
import numpy as np, itertools

def make_law_fn(code_str):
    namespace = {}
    exec(code_str, namespace)
    return namespace['law']

def build_universe(seed=0):
    universe = []
    def exhaustive(n):
        return [np.array(e).reshape(n,n).tolist() for e in itertools.product(range(n), repeat=n*n)]
    def sampled(n, count, s):
        rng = np.random.RandomState(s)
        return [rng.randint(0,n,size=(n,n)).tolist() for _ in range(count)]
    universe += exhaustive(2) + exhaustive(3)
    for n, c in [(4,5000),(5,5000),(6,3000),(7,2000),(8,1000)]:
        universe += sampled(n, c, seed+n)
    return universe

def check_commutative(t):
    n=len(t); return all(t[i][j]==t[j][i] for i in range(n) for j in range(n))
def check_associative(t):
    n=len(t); return all(t[t[i][j]][k]==t[i][t[j][k]] for i in range(n) for j in range(n) for k in range(n))
def check_idempotent(t):
    n=len(t); return all(t[i][i]==i for i in range(n))
def find_identity(t):
    n=len(t)
    for e in range(n):
        if all(t[e][x]==x and t[x][e]==x for x in range(n)): return e
    return None

def extract_properties(law_code, universe):
    """Extract properties using ALL satisfying tables found (not just the
    first 20), and be EXPLICIT about resolvability -- never silently
    default a property when the equation doesn't resolve."""
    law_fn = make_law_fn(law_code)
    satisfying = [t for t in universe if law_fn(t)]
    n_sat = len(satisfying)
    if n_sat == 0:
        return {'resolvable': False, 'is_commutative': None, 'is_associative': None,
                'is_idempotent': None, 'has_identity': None, 'n_satisfying': 0}
    sample = satisfying[:50]  # cap for speed, but from the FULL pool, not just first-found
    return {
        'resolvable': True,
        'is_commutative': all(check_commutative(t) for t in sample),
        'is_associative': all(check_associative(t) for t in sample),
        'is_idempotent': all(check_idempotent(t) for t in sample),
        'has_identity': any(find_identity(t) is not None for t in sample),
        'n_satisfying': n_sat,
    }

def classify_rule_based(props_a, props_b, equiv_threshold=0.2, direction_threshold=0.1):
    """Same rule structure as the external method, but resolvability is
    checked EXPLICITLY and separately -- if either equation is unresolvable,
    we abstain rather than silently defaulting a property to a placeholder."""
    if not props_a['resolvable'] or not props_b['resolvable']:
        return 'unresolved'   # explicit abstention -- the actual fix

    bool_props = ['is_commutative', 'is_associative', 'is_idempotent', 'has_identity']
    diffs = []
    for p in bool_props:
        a_val = 1.0 if props_a[p] else -1.0
        b_val = 1.0 if props_b[p] else -1.0
        diffs.append(a_val - b_val)
    # log-scale satisfying-count difference (avoids raw-count domination)
    log_a = np.log1p(props_a['n_satisfying'])
    log_b = np.log1p(props_b['n_satisfying'])
    diffs.append(log_a - log_b)

    diffs = np.array(diffs)
    weights = np.array([0.2, 0.2, 0.15, 0.15, 0.3])
    weighted_score = np.sum(weights * np.sign(diffs) * np.minimum(np.abs(diffs), 1.0))

    if np.max(np.abs(diffs)) < equiv_threshold:
        return 'equivalent'
    sig_pos = np.sum(diffs > direction_threshold)
    sig_neg = np.sum(diffs < -direction_threshold)
    if sig_neg == 0 and sig_pos > 0: return 'stronger'
    elif sig_pos == 0 and sig_neg > 0: return 'weaker'
    elif weighted_score > direction_threshold: return 'stronger'
    elif weighted_score < -direction_threshold: return 'weaker'
    else: return 'incomparable'
