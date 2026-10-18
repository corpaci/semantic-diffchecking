"""
Structural methods on the equation's term tree (formal view):

  * structural invariants: 13 global facts (sizes, depths, #variables,
    variables on one side only, bare-variable sides, ...) -- src/magma_fingerprints.py
  * Weisfeiler-Lehman subtree counts (src/wl_features.py); the pattern
    vocabulary is fitted on each split's TRAINING equations only
  * WL + structural invariants
  * WL + structural invariants + direct latents (19 views)

Pair features are always [g(A), g(B), g(A) - g(B)].
"""
import numpy as np

from ..utils.features import directional_pair
from .base import Method
from .natural_latents import latents
from ..utils.data import ALL_VIEWS


def invariants(ctx):
    def build():
        import magma_fingerprints as mf
        return np.stack([mf.structural_invariants(f) for f in ctx.formal])
    return ctx.cached('structural_invariants[formal]', build)


def wl_matrix(ctx, split):
    """WL counts for every equation, vocabulary fitted on the split's training equations."""
    from wl_features import WLFeaturizer
    cfg = ctx.cfg
    train = [f for f, keep in zip(ctx.formal, split.train_nodes) if keep]
    return WLFeaturizer(h=cfg.wl_rounds, min_count=cfg.wl_min_count).fit(train).transform(ctx.formal)


def _pair(ctx, *blocks):
    return directional_pair(np.concatenate(blocks, axis=1), ctx.ii, ctx.jj)


def get_methods(cfg):
    return [
        Method('STRUCT Structural invariants (formal)', 'structural',
               '13 global properties of each equation tree', 'formal',
               features=lambda ctx, s: _pair(ctx, invariants(ctx))),
        Method(f'STRUCT Weisfeiler-Lehman subtree features (h={cfg.wl_rounds})', 'structural',
               'counts of WL subtree patterns (vocabulary from training equations only)', 'formal',
               per_split=True, features=lambda ctx, s: _pair(ctx, wl_matrix(ctx, s))),
        Method(f'STRUCT WL (h={cfg.wl_rounds}) + structural invariants', 'structural',
               'local subtree patterns + global invariants', 'formal', per_split=True,
               features=lambda ctx, s: _pair(ctx, wl_matrix(ctx, s), invariants(ctx))),
        Method(f'STRUCT WL + structural invariants + direct latents (19 views)', 'structural',
               'tree features plus Generic RESAMPLED per-view latents of all 19 representations',
               'formal + all 19', per_split=True,
               features=lambda ctx, s: _pair(ctx, wl_matrix(ctx, s), invariants(ctx), np.concatenate(
                   [latents(ctx, 'generic', 'res')[v] for v in ALL_VIEWS], axis=1))),
    ]
