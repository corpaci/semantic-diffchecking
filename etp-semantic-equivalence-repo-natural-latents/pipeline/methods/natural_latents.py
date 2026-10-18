"""
Natural Latents methods: per-view latents (raw, or resampled from the other
18 views by cross-validated Ridge -- src/resampling.py) and the directional
entropy-type losses between them (src/losses.py).

For each embedding scheme (generic / family / repr) x latent state (raw / resampled):
  * each single loss (KL, CrossEntropy, RankInfoGain, SignedLLR, PMI_control), 19 views
  * Mix = KL + CE + RankInfoGain + SignedLLR, 19 views and the original 5 views
  * Mix + cosine on latents
  * direct latents [z(A), z(B), z(A) - z(B)]
  * cosine / Euclidean on latents (symmetric controls)
"""
import numpy as np

from ..utils.data import ALL_VIEWS, ORIGINAL_5_VIEWS
from ..utils.embeddings import SCHEMES, tfidf_views
from ..utils.features import directional_pair, matrix_both_directions, matrix_one_direction
from .base import Method

STATES = {'raw': 'RAW', 'res': 'RESAMPLED'}
LOSS_NAMES = ['KL', 'CrossEntropy', 'RankInfoGain', 'SignedLLR', 'PMI_control']
MIX = ['KL', 'CrossEntropy', 'RankInfoGain', 'SignedLLR']


def latents(ctx, scheme, state):
    """{view: (n_equations, n_components)} per-view latents (cached)."""
    def build():
        from resampling import NaturalLatentResampler
        cfg = ctx.cfg
        rs = NaturalLatentResampler(embed_fn=None, ridge_alpha=cfg.ridge_alpha, n_components=cfg.n_components)
        rs.view_names = list(ALL_VIEWS)
        rs.equation_ids = list(range(len(ctx.node_order)))
        rs.view_matrices = tfidf_views(ctx, scheme)
        lat = (rs.raw_per_view_latents(cfg.n_components) if state == 'raw'
               else rs.per_view_resampled_latents(cfg.n_components))
        return {v: np.stack([lat[v][i] for i in rs.equation_ids]) for v in ALL_VIEWS}
    return ctx.cached(f'latents[{scheme},{state}]', build)


def loss_matrices(ctx, scheme, state):
    """{view: {loss: NxN}} with M[i, j] = loss(i -> j) (cached)."""
    def build():
        from losses import LOSS_FUNCTIONS
        return {v: {ln: fn(Z) for ln, fn in LOSS_FUNCTIONS.items()}
                for v, Z in latents(ctx, scheme, state).items()}
    return ctx.cached(f'losses[{scheme},{state}]', build)


def symmetric_matrices(ctx, scheme, state):
    def build():
        from symmetric_methods import SYMMETRIC_METHODS
        return {v: {m: SYMMETRIC_METHODS[m](Z) for m in ('CosineSimilarity', 'Euclidean')}
                for v, Z in latents(ctx, scheme, state).items()}
    return ctx.cached(f'symmetric_on_latents[{scheme},{state}]', build)


def loss_features(ctx, scheme, state, loss_names, views, I=None, J=None):
    L = loss_matrices(ctx, scheme, state)
    I = ctx.ii if I is None else I
    J = ctx.jj if J is None else J
    return matrix_both_directions([L[v][ln] for ln in loss_names for v in views], I, J)


def direct_latent_features(ctx, scheme, state, views=ALL_VIEWS):
    lat = latents(ctx, scheme, state)
    return directional_pair(np.concatenate([lat[v] for v in views], axis=1), ctx.ii, ctx.jj)


def get_methods(cfg):
    out = []
    for scheme, sname in SCHEMES.items():
        for state, stname in STATES.items():
            tag = f'NL {sname}, {stname}'
            for ln in LOSS_NAMES:
                out.append(Method(
                    f'{tag} | {ln} (19 views)', 'natural-latents',
                    f'{ln} between per-view latents, both directions, all 19 views'
                    + (' -- symmetric NEGATIVE CONTROL' if ln == 'PMI_control' else ''),
                    'all 19', symmetric=(ln == 'PMI_control'),
                    features=lambda ctx, s, a=scheme, b=state, l=ln: loss_features(ctx, a, b, [l], ALL_VIEWS)))
            out.append(Method(
                f'{tag} | Mix KL+CE+Rank+LLR (19 views)', 'natural-latents',
                '4 directional losses x 19 views x 2 directions (152 features)', 'all 19',
                features=lambda ctx, s, a=scheme, b=state: loss_features(ctx, a, b, MIX, ALL_VIEWS)))
            out.append(Method(
                f'{tag} | Mix KL+CE+Rank+LLR (original 5 views)', 'natural-latents',
                'Mix restricted to lean, latex, py_lambda, py_cayley_table, natural_language', 'original 5',
                features=lambda ctx, s, a=scheme, b=state: loss_features(ctx, a, b, MIX, ORIGINAL_5_VIEWS)))
            out.append(Method(
                f'{tag} | Mix + cosine on latents (19 views)', 'natural-latents',
                'Mix (152) plus one cosine column per view (19)', 'all 19',
                features=lambda ctx, s, a=scheme, b=state: np.concatenate([
                    loss_features(ctx, a, b, MIX, ALL_VIEWS),
                    matrix_one_direction([symmetric_matrices(ctx, a, b)[v]['CosineSimilarity'] for v in ALL_VIEWS],
                                         ctx.ii, ctx.jj)], axis=1)))
            out.append(Method(
                f'{tag} | Direct latents [z(A),z(B),z(A)-z(B)] (19 views)', 'natural-latents',
                'the latents themselves instead of losses between them', 'all 19',
                features=lambda ctx, s, a=scheme, b=state: direct_latent_features(ctx, a, b)))
            out.append(Method(
                f'{tag} | Direct latents + Mix losses (19 views)', 'natural-latents',
                'direct latents [z(A),z(B),z(A)-z(B)] (456) plus KL+CE+Rank+LLR in both directions (152), '
                'one model', 'all 19',
                features=lambda ctx, s, a=scheme, b=state: np.concatenate([
                    direct_latent_features(ctx, a, b), loss_features(ctx, a, b, MIX, ALL_VIEWS)], axis=1)))
            for sym in ('CosineSimilarity', 'Euclidean'):
                out.append(Method(
                    f'{tag} | SYMMETRIC {sym} on latents (19 views)', 'symmetric',
                    f'{sym} between per-view latents, one column per view', 'all 19', symmetric=True,
                    features=lambda ctx, s, a=scheme, b=state, m=sym: matrix_one_direction(
                        [symmetric_matrices(ctx, a, b)[v][m] for v in ALL_VIEWS], ctx.ii, ctx.jj)))
    return out
