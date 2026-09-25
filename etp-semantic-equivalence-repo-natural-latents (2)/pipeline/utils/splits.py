"""Node-held-out splits, identical for every method."""
from dataclasses import dataclass

import numpy as np


@dataclass
class Split:
    seed: int
    train_nodes: np.ndarray    # bool per equation (index into Context.node_order)
    train_pairs: np.ndarray    # bool per pair: both equations are training equations
    test_pairs: np.ndarray     # bool per pair: both equations are held-out equations


def node_holdout_splits(n_nodes, ii, jj, seeds, test_frac):
    """Hold out `test_frac` of the EQUATIONS: test pairs contain only held-out
    equations, train pairs only training equations, and pairs that mix the two
    are dropped -- no equation is ever seen in training, in any pairing."""
    out = []
    for s in seeds:
        perm = np.random.RandomState(s).permutation(n_nodes)
        is_test = np.zeros(n_nodes, dtype=bool)
        is_test[perm[:int(test_frac * n_nodes)]] = True
        out.append(Split(s, ~is_test, ~is_test[ii] & ~is_test[jj], is_test[ii] & is_test[jj]))
    return out
