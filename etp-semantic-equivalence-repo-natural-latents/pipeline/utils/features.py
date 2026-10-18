"""Helpers that turn per-equation or per-pair quantities into pair features."""
import numpy as np


def directional_pair(E, ii, jj):
    """Per-equation matrix E (n_eq, d) -> [E(A), E(B), E(A) - E(B)]."""
    return np.concatenate([E[ii], E[jj], E[ii] - E[jj]], axis=1)


def matrix_both_directions(mats, ii, jj):
    """List of NxN matrices M (M[i, j] = score(i -> j)) -> columns M[A,B], M[B,A] each."""
    cols = []
    for m in mats:
        cols += [m[ii, jj], m[jj, ii]]
    return np.stack(cols, axis=1)


def matrix_one_direction(mats, ii, jj):
    """For SYMMETRIC matrices: one column each (the reverse would be a duplicate)."""
    return np.stack([m[ii, jj] for m in mats], axis=1)


def stack(*blocks):
    return np.concatenate([b if b.ndim == 2 else b.reshape(-1, 1) for b in blocks], axis=1)
