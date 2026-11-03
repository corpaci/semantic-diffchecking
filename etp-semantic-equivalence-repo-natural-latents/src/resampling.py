"""
resampling.py -- Natural Latents purification via cross-view Ridge regression.
Both real bugs found earlier in this project are fixed here:
  BUG 1: each view needs its own fit_key, or vocabulary silently corrupts.
  BUG 2: mediation must be tested via residuals against the purified latent,
         not by correlating two resampled views against each other directly.
"""
import numpy as np
from sklearn.linear_model import Ridge
from sklearn.model_selection import KFold


class NaturalLatentResampler:
    def __init__(self, embed_fn, ridge_alpha=1.0, n_components=8):
        self.embed_fn = embed_fn
        self.ridge_alpha = ridge_alpha
        self.n_components = n_components
        self.view_matrices = {}
        self.equation_ids = None
        self.view_names = None

    def fit_embeddings(self, representations):
        self.view_names = list(representations.keys())
        self.equation_ids = sorted(representations[self.view_names[0]].keys())
        for view in self.view_names:
            texts = [representations[view][eq_id] for eq_id in self.equation_ids]
            self.view_matrices[view] = self.embed_fn(texts, fit_key=view)
        return self

    def resample_view(self, target_view, held_out_folds=5, random_state=0):
        other_views = [v for v in self.view_names if v != target_view]
        X = np.concatenate([self.view_matrices[v] for v in other_views], axis=1)
        y = self.view_matrices[target_view]
        n = X.shape[0]
        recon = np.zeros_like(y, dtype=np.float64)
        kf = KFold(n_splits=min(held_out_folds, n), shuffle=True, random_state=random_state)
        for train_idx, test_idx in kf.split(X):
            model = Ridge(alpha=self.ridge_alpha)
            model.fit(X[train_idx], y[train_idx])
            recon[test_idx] = model.predict(X[test_idx])
        return recon

    def purify(self):
        resampled = {v: self.resample_view(v) for v in self.view_names}
        reduced = {}
        for v in self.view_names:
            X = resampled[v] - resampled[v].mean(axis=0)
            U, S, Vt = np.linalg.svd(X, full_matrices=False)
            k = min(self.n_components, U.shape[1])
            proj = U[:, :k] * S[:k]
            if k < self.n_components:
                proj = np.pad(proj, ((0, 0), (0, self.n_components - k)))
            reduced[v] = proj
        stacked = np.stack([reduced[v] for v in self.view_names], axis=0)
        stacked = (stacked - stacked.mean(axis=1, keepdims=True)) / (stacked.std(axis=1, keepdims=True) + 1e-8)
        pooled = stacked.mean(axis=0)
        self._resampled = resampled
        self._latent = {eq_id: pooled[i] for i, eq_id in enumerate(self.equation_ids)}
        return self._latent

    def per_view_resampled_latents(self, n_components=8):
        """Returns each view's OWN resampled (denoised) latent, kept SEPARATE
        (not pooled) -- for the late-fusion / per-view loss experiments."""
        if not hasattr(self, '_resampled'):
            self.purify()
        out = {}
        for v in self.view_names:
            X = self._resampled[v] - self._resampled[v].mean(axis=0)
            U, S, Vt = np.linalg.svd(X, full_matrices=False)
            k = min(n_components, U.shape[1])
            proj = U[:, :k] * S[:k]
            if k < n_components:
                proj = np.pad(proj, ((0, 0), (0, n_components - k)))
            out[v] = {eq_id: proj[i] for i, eq_id in enumerate(self.equation_ids)}
        return out

    def check_mediation(self):
        latent_mat = np.stack([self._latent[e] for e in self.equation_ids])
        residuals = {}
        for view in self.view_names:
            X = self.view_matrices[view]
            model = Ridge(alpha=self.ridge_alpha)
            model.fit(latent_mat, X)
            residuals[view] = X - model.predict(latent_mat)
        views = self.view_names
        mat = np.zeros((len(views), len(views)))
        for i, vi in enumerate(views):
            for j, vj in enumerate(views):
                a, b = residuals[vi], residuals[vj]
                k = min(a.shape[1], b.shape[1])
                corrs = [np.corrcoef(a[:, d], b[:, d])[0, 1] for d in range(k)]
                mat[i, j] = np.nanmean(np.abs(corrs))
        return views, mat

    def raw_per_view_latents(self, n_components=8):
        """The NO-resampling baseline: each view's own raw embedding,
        SVD-reduced, kept separate. For the with/without resampling comparison."""
        out = {}
        for v in self.view_names:
            X = self.view_matrices[v] - self.view_matrices[v].mean(axis=0)
            U, S, Vt = np.linalg.svd(X, full_matrices=False)
            k = min(n_components, U.shape[1])
            proj = U[:, :k] * S[:k]
            if k < n_components:
                proj = np.pad(proj, ((0, 0), (0, n_components - k)))
            out[v] = {eq_id: proj[i] for i, eq_id in enumerate(self.equation_ids)}
        return out
