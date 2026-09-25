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


def condensation_fingerprints(ctx):
    """The condensation engine's universe: all 16 size-2 and all 19,683 size-3
    magmas (src/condensation_engine.py), evaluated with the fast vectorised
    checker -- identical model sets, much faster."""
    def build():
        import magma_fingerprints as mf
        bank = [mf.TableFamily('all_n2', mf._all_tables(2)), mf.TableFamily('all_n3', mf._all_tables(3))]
        F = mf.fingerprints(ctx.formal, bank)
        return F, mf.counterexample_counts(F)
    return ctx.cached('condensation_fingerprints[size 2+3]', build)


def _condensation(ctx, as_published):
    """src/condensation_engine.compare_equations, vectorised (same model sets):
    Loss(B|A) = H(P(B|A)) with P(B|A) = |Models(A) & Models(B)| / |Models(A)|;
    Loss = 0 is read as A => B.
      as_published=True  -- the engine's H(p) returns 0 for p = 0 as well as p = 1,
                            so DISJOINT model sets also count as an implication
                            (this is how compare_equations behaves)
      as_published=False -- corrected: Loss = 0 only when P(B|A) = 1
    Engine output -> dataset label: 'A_stronger' (A => B only) = weaker,
    'B_stronger' = stronger. When either equation has NO model in the universe the
    engine answers 'unresolvable'; such pairs are scored as 'incomparable' here."""
    from ..utils.data import implications_to_label
    F, _ = condensation_fingerprints(ctx)
    Fi = F.astype(np.int32)
    n = Fi.sum(axis=1)
    inter = np.einsum('ij,ij->i', Fi[ctx.ii], Fi[ctx.jj])
    na, nb = n[ctx.ii], n[ctx.jj]
    fwd = inter == na                         # P(B|A) = 1
    bwd = inter == nb                         # P(A|B) = 1
    if as_published:
        fwd |= inter == 0
        bwd |= inter == 0
    pred = implications_to_label(fwd, bwd)
    return np.where((na > 0) & (nb > 0), pred, 3)


def get_condensation_coverage(ctx):
    F, _ = condensation_fingerprints(ctx)
    has = F.any(axis=1)
    return float(np.mean(has[ctx.ii] & has[ctx.jj])), float(np.mean(has))


def get_methods(cfg):
    return [
        Method('SEM Condensation engine, as published (size-2+3 magmas; unresolvable -> incomparable)',
               'semantic',
               'src/condensation_engine.py exactly: conditional entropy of model sets over 19,699 magmas, '
               'H(0)=0 so disjoint model sets count as implication; no-model pairs scored as incomparable',
               'formal (executed)', rule=lambda ctx, s: _condensation(ctx, as_published=True)),
        Method('SEM Condensation engine, corrected (size-2+3 magmas; unresolvable -> incomparable)',
               'semantic',
               'same, but Loss = 0 only when P(B|A) = 1 (disjoint model sets refute the implication)',
               'formal (executed)', rule=lambda ctx, s: _condensation(ctx, as_published=False)),
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
