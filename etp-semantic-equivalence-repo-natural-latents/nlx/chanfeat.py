"""Per-notation pair features that work for ANY subset of notations (1, 2, 3 ... n views), for either latent kind.

Each channel (notation:encoder) gets its OWN k-dim latent (PCA fitted on TRAINING laws only).  For a pair of laws (a, b):
  sym   per channel: cosine and Euclidean distance between z_c(a) and z_c(b)                      (2 numbers per channel)
  loss  per channel: KL, cross-entropy, rank information gain, signed LLR, in both directions       (8 numbers per channel)
  mix   sym + loss                                                                                  (10 per channel)
Feature sets used by Latent:  loss | sym | mix  (these only)   and   z+loss | z+mix  (direct latents [zA,zB,zA-zB] plus these).
With one notation this is exactly the single-notation version of the original 19-view loss table; with n notations the classifier
receives n times as many features.  Neighbourhoods and statistics use training laws only (see info.py), so nothing leaks.
Per-channel results are cached per (channel, split, pair set), so re-using a notation in many random subsets costs nothing extra."""
import numpy as np
from sklearn.decomposition import PCA
from . import info as I

_CACHE = {}


class ChannelFeatures:
    def __init__(self, X, train_idx, kind='mix', k=8, knn=10, split_key=None):
        self.kind, self.k, self.knn, self.key = kind, k, knn, split_key
        self.train_idx = np.asarray(train_idx)
        self.X = X
        self.channels = list(X)
        self._Z, self._S = {}, {}

    def _latent(self, c):
        key = ('Z', c, self.key, self.k)
        if key not in _CACHE:
            tr = self.train_idx
            Z = PCA(n_components=int(min(self.k, self.X[c].shape[1], len(tr) - 1)), random_state=0).fit(self.X[c][tr]).transform(self.X[c])
            _CACHE[key] = np.asarray(Z, np.float32)
        return _CACHE[key]

    def _stats(self, c):
        key = ('S', c, self.key, self.k, self.knn)
        if key not in _CACHE:
            _CACHE[key] = I.LatentStats(self._latent(c), self.train_idx, self.knn)
        return _CACHE[key]

    def _block(self, c, ia, ib):
        pk = (hash(ia[:64].tobytes()), hash(ib[:64].tobytes()), len(ia))
        key = ('F', c, self.key, self.k, self.knn, self.kind, pk)
        if key in _CACHE:
            return _CACHE[key]
        Z = self._latent(c); a, b = Z[ia], Z[ib]
        cols = []
        if self.kind in ('sym', 'mix'):
            cols += [(a * b).sum(1) / (np.linalg.norm(a, axis=1) * np.linalg.norm(b, axis=1) + 1e-9), np.linalg.norm(a - b, axis=1)]
        if self.kind in ('loss', 'mix'):
            S = self._stats(c)
            ab, ba = I.both_directions(S, S, ia, ib)
            cols += [ab[l] for l in I.LOSSES] + [ba[l] for l in I.LOSSES]
        out = np.stack(cols, 1).astype(np.float32)
        _CACHE[key] = out
        return out

    def features(self, ia, ib):
        ia, ib = np.asarray(ia), np.asarray(ib)
        return np.hstack([self._block(c, ia, ib) for c in self.channels])


def clear_cache():
    _CACHE.clear()
