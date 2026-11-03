"""Entropy / information-gain measures BETWEEN TWO LATENTS (and within one).

A 'latent' is an (n_laws, k) matrix: the shared GCCA latent, or the average of the per-notation predictions of a GROUP of
notations (tree / sequence / spelled_out / interpreted / perturbed), all living in the same k-dim shared space, so a law seen
through group X can be compared with a law seen through group Y.

For a pair of laws (a, b) and latents X (source) and Y (target), with local Gaussians built from the k nearest TRAINING laws:
  KL            KL( N(x_a, var_a) || N(y_b, var_b) )                    how costly it is to describe a by b's neighbourhood
  CrossEntropy  H( N(x_a, var_a), N(y_b, var_b) )                      KL plus a's own uncertainty
  RankInfoGain  log2( chance_rank / (rank + .5) ), rank = #training laws closer to x_a than y_b    (rank-based, density-aware)
  SignedLLR     log N(x_a; y_b, var_b) - log N(x_a; global)            does a fit b's neighbourhood better than the population?
Direction a->b uses (X from a, Y from b); b->a uses (X from b, Y from a).  X == Y gives the within-latent version.
Neighbourhoods, global statistics and ranks use TRAINING laws only (test laws are only queried), so nothing leaks."""
import numpy as np
from scipy.spatial.distance import cdist
from sklearn.neighbors import NearestNeighbors
from sklearn.metrics import roc_auc_score

LOSSES = ['KL', 'CrossEntropy', 'RankInfoGain', 'SignedLLR']
HIGHER_IS_CLOSER = {'KL': False, 'CrossEntropy': False, 'RankInfoGain': True, 'SignedLLR': True}


class LatentStats:
    def __init__(self, Z, train_idx, k=10):
        self.Z = np.asarray(Z, np.float64)
        self.tr = np.asarray(train_idx)
        k = int(min(k, len(self.tr) - 2))
        nn = NearestNeighbors(n_neighbors=k + 1).fit(self.Z[self.tr])
        idx = nn.kneighbors(self.Z, return_distance=False)
        pos = -np.ones(len(self.Z), int)
        pos[self.tr] = np.arange(len(self.tr))
        keep = np.empty((len(self.Z), k), int)
        for i in range(len(self.Z)):
            row = idx[i]
            if pos[i] >= 0:
                row = row[row != pos[i]]
            keep[i] = row[:k]
        self.var = self.Z[self.tr][keep].var(axis=1) + 1e-3
        self.mu_g = self.Z[self.tr].mean(0)
        self.var_g = self.Z[self.tr].var(0) + 1e-3
        self.Ztr = self.Z[self.tr]


def pair_losses(SX, SY, ia, ib, chunk=2000):
    """dict loss -> (len(ia),) for the direction a -> b  (source in latent X, target in latent Y)."""
    mi, vi, mj, vj = SX.Z[ia], SX.var[ia], SY.Z[ib], SY.var[ib]
    diff2 = (mi - mj) ** 2
    out = {'KL': 0.5 * (np.log(vj / vi) - 1 + vi / vj + diff2 / vj).sum(1),
           'CrossEntropy': 0.5 * (np.log(2 * np.pi * vj) + (vi + diff2) / vj).sum(1),
           'SignedLLR': (-0.5 * (np.log(2 * np.pi * vj) + diff2 / vj).sum(1))
                        - (-0.5 * (np.log(2 * np.pi * SY.var_g) + (mi - SY.mu_g) ** 2 / SY.var_g).sum(1))}
    d_ab = np.sqrt(diff2.sum(1))
    gain = np.empty(len(ia))
    chance = len(SY.tr) / 2.0
    for s in range(0, len(ia), chunk):
        D = cdist(mi[s:s + chunk], SY.Ztr)
        rank = (D < d_ab[s:s + chunk, None]).sum(1)
        gain[s:s + chunk] = np.log2(chance / (rank + 0.5))
    out['RankInfoGain'] = gain
    return out


def both_directions(SX, SY, ia, ib):
    ab, ba = pair_losses(SX, SY, ia, ib), pair_losses(SX, SY, ib, ia)
    return ab, ba


def group_latents(m, pool, groups):
    """m: result of fit_gcca_plus over `pool` channels.  -> {'shared': E, 'tree': mean of the tree notations' latents, ...}"""
    out = {'shared': m['E_plain']}
    for g, views in groups.items():
        chs = [c for c in pool if c.split(':')[0] in views]
        if chs:
            out[g] = np.mean([m['P'][c] for c in chs], axis=0)
    return out


def variants(names):
    """(label, X, Y): shared->shared, every group within itself, every ordered pair of different groups."""
    v = [('shared->shared', 'shared', 'shared')]
    gs = [n for n in names if n != 'shared']
    v += [(f'{g}->{g}', g, g) for g in gs]
    v += [(f'{g}->{h}', g, h) for g in gs for h in gs if g != h]
    return v


def direction_auc(y, d):
    """stronger vs weaker separated by the asymmetry d = loss(a->b) - loss(b->a); sign-free (0.5 = blind)."""
    m = (y == 1) | (y == 2)
    if not ((y == 1).any() and (y == 2).any()):
        return np.nan
    a = roc_auc_score(y[m] == 1, d[m])
    return float(max(a, 1 - a))


def equiv_score(loss, ab, ba):
    s = ab + ba
    return s if HIGHER_IS_CLOSER[loss] else -s


# ------------------------------------------------------------------------------------ mutual information between latents
def gaussian_mi(Zx, Zy, tr, te):
    """Gaussian mutual information (nats) between two latents: canonical correlations are FITTED on training laws and
    EVALUATED on held-out laws (so the estimate is not inflated by over-fitting).  MI = -1/2 sum log(1 - rho^2)."""
    def whiten(Z):
        mu = Z[tr].mean(0)
        U, S, Vt = np.linalg.svd(Z[tr] - mu, full_matrices=False)
        keep = S > 1e-8 * S[0]
        return mu, Vt.T[:, keep] / S[keep] * np.sqrt(len(tr) - 1)
    mx, Wx = whiten(Zx)
    my, Wy = whiten(Zy)
    C = ((Zx[tr] - mx) @ Wx).T @ ((Zy[tr] - my) @ Wy) / (len(tr) - 1)
    P, s, Qt = np.linalg.svd(C, full_matrices=False)
    u = (Zx[te] - mx) @ Wx @ P
    v = (Zy[te] - my) @ Wy @ Qt.T
    u, v = u - u.mean(0), v - v.mean(0)
    rho = (u * v).sum(0) / (np.linalg.norm(u, axis=0) * np.linalg.norm(v, axis=0) + 1e-12)
    rho = np.clip(rho, 0, 0.999)
    return float(-0.5 * np.log(1 - rho ** 2).sum())
