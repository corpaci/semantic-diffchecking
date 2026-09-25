"""
Semantic methods: check each equation against a bank of finite magmas
(src/magma_fingerprints.py) instead of embedding its text.

  * magma counter-model rule (NO training): A => B unless some magma satisfies
    A but not B; a counter-model is a proof that A does not imply B
  * learned: semantic pair features (counter-model counts both ways, #models,
    overlap, Jaccard, refutation flags)
  * learned: semantic + structural invariants
  * learned: semantic + structural invariants + WL
"""
import numpy as np

from ..utils.features import directional_pair
from .base import Method
from .structural import invariants, wl_matrix


def fingerprints(ctx):
    def build():
        import magma_fingerprints as mf
        bank = mf.build_magma_bank(exhaustive_3=ctx.cfg.exhaustive_size3_magmas)
        F = mf.fingerprints(ctx.formal, bank)
        return F, mf.counterexample_counts(F)
    return ctx.cached('magma_fingerprints', build)


def semantic_pair(ctx):
    def build():
        import magma_fingerprints as mf
        F, C = fingerprints(ctx)
        return mf.pair_semantic_features(F, ctx.ii, ctx.jj, C)
    return ctx.cached('semantic_pair_features', build)


def magma_rule(ctx, split):
    import magma_fingerprints as mf
    _, C = fingerprints(ctx)
    return mf.rule_based_relation(C, ctx.ii, ctx.jj)


def get_methods(cfg):
    return [
        Method('SEM Magma counter-model rule (no training)', 'semantic',
               'A => B iff no magma in the bank satisfies A but not B; no classifier, no training',
               'formal (executed, = py_cayley_table semantics)', rule=magma_rule),
        Method('SEM Semantic pair features', 'semantic',
               'counter-model counts both ways, #models, overlap, Jaccard, refutation flags',
               'formal (executed)', features=lambda ctx, s: semantic_pair(ctx)),
        Method('SEM Semantic + structural invariants', 'semantic',
               'semantic pair features + [g(A), g(B), g(A)-g(B)] of the invariants',
               'formal (executed)', features=lambda ctx, s: np.concatenate(
                   [semantic_pair(ctx), directional_pair(invariants(ctx), ctx.ii, ctx.jj)], axis=1)),
        Method(f'SEM Semantic + structural invariants + WL (h={cfg.wl_rounds})', 'semantic',
               'semantic pair features + tree features', 'formal (executed)', per_split=True,
               features=lambda ctx, s: np.concatenate(
                   [semantic_pair(ctx), directional_pair(np.concatenate(
                       [wl_matrix(ctx, s), invariants(ctx)], axis=1), ctx.ii, ctx.jj)], axis=1)),
    ]
