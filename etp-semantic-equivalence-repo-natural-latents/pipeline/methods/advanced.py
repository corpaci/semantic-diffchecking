"""
Advanced metrics (from the notebook's Section 12), on the pairs actually used:

  * Wasserstein-1D between per-view latent profiles (exact W1 = L1 between CDFs), 19 views
  * compression: NCD (symmetric) + directional compression gain, formal view
  * algebraic property vectors [p(A), p(B), p(A) - p(B)] (src/advanced_metrics.py)
  * edit-script features (Levenshtein, tokens added/removed/shared, ...), formal view
  * embedding super-model: Mix(19 views) + all of the above

The latent-based ones use the Generic RAW latents (the best latent set for
loss features in the notebook run).
"""
import zlib

import numpy as np

from ..utils.data import ALL_VIEWS
from ..utils.features import directional_pair
from .base import Method
from .natural_latents import MIX, latents, loss_features

SCHEME, STATE = 'generic', 'raw'


def wasserstein(ctx):
    def build():
        cols = []
        for v, Z in latents(ctx, SCHEME, STATE).items():
            P = np.abs(Z) + 1e-8
            cdf = np.cumsum(P / P.sum(axis=1, keepdims=True), axis=1)
            cols.append(np.abs(cdf[ctx.ii] - cdf[ctx.jj]).sum(axis=1))
        return np.stack(cols, axis=1)
    return ctx.cached('wasserstein_1d[generic,raw]', build)


def compression(ctx):
    def build():
        t = [f.encode() for f in ctx.formal]
        c = np.array([len(zlib.compress(x, 9)) for x in t])
        c_ab = np.array([len(zlib.compress(t[i] + t[j], 9)) for i, j in zip(ctx.ii, ctx.jj)])
        c_ba = np.array([len(zlib.compress(t[j] + t[i], 9)) for i, j in zip(ctx.ii, ctx.jj)])
        ncd = (np.minimum(c_ab, c_ba) - np.minimum(c[ctx.ii], c[ctx.jj])) / np.maximum(c[ctx.ii], c[ctx.jj])
        gain_ab = (c[ctx.jj] - (c_ab - c[ctx.ii])) / c[ctx.jj]
        gain_ba = (c[ctx.ii] - (c_ba - c[ctx.jj])) / c[ctx.ii]
        return np.stack([ncd, gain_ab, gain_ba], axis=1)
    return ctx.cached('compression[formal]', build)


def algebraic(ctx):
    def build():
        from advanced_metrics import algebraic_property_vector, extract_algebraic_properties
        P = np.stack([algebraic_property_vector(extract_algebraic_properties(f)) for f in ctx.formal])
        return directional_pair(P, ctx.ii, ctx.jj)
    return ctx.cached('algebraic_properties[formal]', build)


def edit_script(ctx):
    def build():
        from advanced_metrics import edit_script_feature_matrix
        n = len(ctx.formal)
        return edit_script_feature_matrix({i: f for i, f in enumerate(ctx.formal)}, list(range(n)), ctx.ii, ctx.jj)
    return ctx.cached('edit_script[formal]', build)


def get_methods(cfg):
    return [
        Method('ADV Wasserstein-1D on latents (19 views)', 'advanced',
               'exact 1-D Wasserstein between |latent| profiles, Generic RAW, one column per view',
               'all 19', symmetric=True, features=lambda ctx, s: wasserstein(ctx)),
        Method('ADV Compression: NCD + directional gain (formal)', 'advanced',
               'normalised compression distance + how much A helps compress B and vice versa',
               'formal', features=lambda ctx, s: compression(ctx)),
        Method('ADV Algebraic property vectors (formal)', 'advanced',
               '[p(A), p(B), p(A)-p(B)] of 11 hand-crafted properties', 'formal',
               features=lambda ctx, s: algebraic(ctx)),
        Method('ADV Edit-script features (formal)', 'advanced',
               'Levenshtein, tokens added/removed/shared, variable permutation, depth change, length ratio',
               'formal', features=lambda ctx, s: edit_script(ctx)),
        Method('ADV Embedding super-model (Mix19 + Wasserstein + compression + algebraic + edit)', 'advanced',
               'all advanced features plus Generic RAW Mix over 19 views', 'all 19',
               features=lambda ctx, s: np.concatenate([
                   loss_features(ctx, SCHEME, STATE, MIX, ALL_VIEWS), wasserstein(ctx),
                   compression(ctx), algebraic(ctx), edit_script(ctx)], axis=1)),
    ]
