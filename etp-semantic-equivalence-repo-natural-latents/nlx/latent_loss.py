"""Shared latent over a set of channels and the pair features built from it.
  kind 'gcca'    : GCCA / GCCA+ shared latent (what all notations agree on); the same code as NLSEM-4..13
  kind 'pca'     : automatic fallback of 'gcca' when only ONE channel is given (top-k PCA, no cross-view agreement exists)
  kind 'concat'  : the older way: every channel -> its own 8-d SVD latent, concatenated (grows with the number of channels)
  feat 'z'       : [z(A), z(B), z(A)-z(B)]                              (NLSEM-4)
  feat 'zpa'     : z + pair-aware terms (product, |diff|, cosine)
  feat 'plus'    : zpa + per-channel cosine / distance, weighted view average, cross-fitted   (NLSEM-10 style)
  feat 'sym' | 'loss' | 'mix'  : per-notation cosine+Euclid | KL, cross-entropy, rank info gain, signed LLR (both directions) | both
                                 (see chanfeat.py; any number of notations, either latent kind; the latent itself is then not used for features)
  feat 'z+loss' | 'z+mix'      : the direct latents [z(A), z(B), z(A)-z(B)] plus the per-notation features above"""
import numpy as np
from sklearn.decomposition import PCA, TruncatedSVD
from pipeline.utils import gcca_plus as gp
from pipeline.utils import semantic_latents as sl
from pipeline.utils.features import directional_pair
from .encoders import get_channel
from .chanfeat import ChannelFeatures

EXTRA = {'sym': ('sym', False), 'loss': ('loss', False), 'mix': ('mix', False), 'z+loss': ('loss', True), 'z+mix': ('mix', True)}
FEAT = {'z': dict(weighted=False), 'zpa': dict(weighted=False, pair_aware=True),
        'plus': dict(weighted=True, per_view=True, pair_aware=True, short=8)}


class Latent:
    def __init__(self, ctx, setup, split, channels, kind='gcca', feat='z', k=16):
        self.kind, self.feat, self.channels = kind, feat, list(channels)
        X = {c: get_channel(ctx, c) for c in self.channels}
        if kind == 'gcca' and len(X) == 1:
            # GCCA needs at least two views: with one view all whitened directions have equal weight, so its first k
            # columns are an ARBITRARY k-dim subspace.  Fall back to the top-k principal components (training laws only).
            c = self.channels[0]
            tr = np.nonzero(split['train_nodes'])[0]
            pca = PCA(n_components=int(min(k, X[c].shape[1], len(tr) - 1)), random_state=0).fit(X[c][tr])
            self.E, self.kind = pca.transform(X[c]).astype(np.float32), 'pca'
        elif kind == 'gcca':
            train_idx = np.nonzero(split['train_nodes'])[0]
            fold = sl.fold_ids(ctx.twin_group, setup.giant, 5, split['seed'])
            kk = min(k, 64 * len(X), len(train_idx) - 1)
            self.m = gp.fit_gcca_plus(X, train_idx, fold, k=kk, d_white=64, crossfit=(feat == 'plus'))
            self.E = self.m['E'] if feat == 'plus' else self.m['E_plain']
        elif kind == 'concat':
            Z = []
            for c in self.channels:
                key = f'nlx_svd8[{c}]'
                Z.append(ctx.cached(key, lambda c=c: TruncatedSVD(min(8, X[c].shape[1] - 1), random_state=0).fit_transform(X[c]).astype(np.float32)))
            self.E = np.hstack(Z)
        else:
            raise ValueError(kind)
        self.extra = None
        if feat in EXTRA:
            self.extra = ChannelFeatures(X, np.nonzero(split['train_nodes'])[0], kind=EXTRA[feat][0], k=8, knn=getattr(ctx, 'nlx_knn', 10),
                                         split_key=(split['mode'], split['seed']))

    def features(self, ia, ib):
        if self.extra is not None:
            parts = [self.extra.features(ia, ib)]
            if EXTRA[self.feat][1]:
                parts.insert(0, self._direct(ia, ib, 'z'))
            return np.hstack(parts)
        return self._direct(ia, ib, self.feat)

    def _direct(self, ia, ib, feat):
        if self.kind == 'gcca':
            return gp.pair_features(self.m, ia, ib, **FEAT[feat])
        return directional_pair(self.E, ia, ib)

    def cosine(self, ia, ib):
        a, b = self.E[ia], self.E[ib]
        return (a * b).sum(1) / (np.linalg.norm(a, axis=1) * np.linalg.norm(b, axis=1) + 1e-9)
