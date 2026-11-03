"""Which notations (channels) to combine."""
import itertools
import numpy as np


def random_subsets(pool, n, draws, rng):
    pool = list(pool)
    n = min(n, len(pool))
    seen, out = set(), []
    for _ in range(draws * 20):
        s = tuple(sorted(rng.choice(len(pool), n, replace=False)))
        if s not in seen:
            seen.add(s)
            out.append(tuple(pool[i] for i in s))
        if len(out) >= draws:
            break
    return out


def all_pairs(pool):
    return list(itertools.combinations(pool, 2))


def sample_triples(pool, m, rng):
    allt = list(itertools.combinations(pool, 3))
    idx = rng.permutation(len(allt))[:m]
    return [allt[i] for i in idx]


def group_combos(groups, max_groups=3):
    """groups: dict name -> list of channels.  Every group alone, every pair of groups, ... up to max_groups, plus all."""
    names = list(groups)
    out = []
    for r in range(1, max_groups + 1):
        for combo in itertools.combinations(names, r):
            out.append(('+'.join(combo), tuple(c for g in combo for c in groups[g])))
    out.append(('all', tuple(c for g in names for c in groups[g])))
    return out


def greedy_forward(pool, score_fn, n_max, log=print):
    """Forward selection: start empty, add the channel that raises score_fn(subset) most.  score_fn must use VALIDATION
    data only.  Returns [(n, subset, score)]."""
    chosen, trace = [], []
    left = list(pool)
    for n in range(1, min(n_max, len(pool)) + 1):
        best, bc = -np.inf, None
        for c in left:
            s = score_fn(tuple(chosen + [c]))
            if s > best:
                best, bc = s, c
        chosen.append(bc)
        left.remove(bc)
        trace.append((n, tuple(chosen), best))
        log(f'  greedy n={n}  + {bc}   val score {best:.3f}')
    return trace
