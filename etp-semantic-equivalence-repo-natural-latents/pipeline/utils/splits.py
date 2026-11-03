"""Node-held-out splits, identical for every method."""
from dataclasses import dataclass

import numpy as np


@dataclass
class Split:
    seed: int
    train_nodes: np.ndarray    # bool per equation (index into Context.node_order)
    train_pairs: np.ndarray    # bool per pair: both equations are training equations
    test_pairs: np.ndarray     # bool per pair: both equations are held-out equations


def node_holdout_splits(n_nodes, ii, jj, seeds, test_frac, groups=None, giant=None, giant_mode='drop'):
    """Hold out `test_frac` of the EQUATIONS: test pairs contain only held-out
    equations, train pairs only training equations, and pairs that mix the two
    are dropped -- no equation is ever seen in training, in any pairing.

    With `groups` (twin-group id per equation, see twins.py) whole groups are held out
    instead, so an equation's oracle-equivalent or dual twins are never on the other side.
    The giant group (a third of all equations) cannot be split sensibly:
      giant_mode='drop'  -> its equations are left out of both train and test (default)
      giant_mode='train' -> its equations are always training equations, never test"""
    out = []
    for s in seeds:
        rng = np.random.RandomState(s)
        if groups is None:
            perm = rng.permutation(n_nodes)
            is_test = np.zeros(n_nodes, dtype=bool)
            is_test[perm[:int(test_frac * n_nodes)]] = True
            usable = np.ones(n_nodes, dtype=bool)
        else:
            groups = np.asarray(groups)
            ids = np.array([g for g in np.unique(groups) if g != giant])
            rng.shuffle(ids)
            is_test = np.zeros(n_nodes, dtype=bool)
            budget = int(test_frac * n_nodes)
            for g in ids:                                  # whole groups until ~test_frac of equations
                if is_test.sum() >= budget:
                    break
                is_test |= groups == g
            usable = np.ones(n_nodes, dtype=bool) if giant_mode == 'train' else groups != giant
        train_nodes = ~is_test & usable
        out.append(Split(s, train_nodes, train_nodes[ii] & train_nodes[jj], is_test[ii] & is_test[jj]))
    return out
