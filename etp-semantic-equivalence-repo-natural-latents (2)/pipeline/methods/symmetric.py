"""
Symmetric baselines that do NOT use Natural Latents.

  * cosine similarity on the raw TF-IDF vectors of every representation
    (one column per view), for each embedding scheme
  * tree edit distance on the equation alone (the 'formal' view)
  * edit distance on every representation's OWN structure (19 columns):
    Zhang-Shasha tree edit distance on the parsed tree of tree-like views,
    Levenshtein distance on the token sequence of sequential/text views
    (see pipeline/utils/trees.py) -- plus each representation on its own
  * tree convolution kernel on the formal view

All are symmetric: f(A, B) == f(B, A), so they cannot separate stronger from
weaker; the report checks that the two confusion-matrix rows are identical.
"""
import numpy as np

from ..utils.data import ALL_VIEWS
from ..utils.embeddings import SCHEMES, tfidf_views
from ..utils.trees import TREE_PARSERS, pairwise_edit_similarity, parse_representation
from .base import Method


def tfidf_cosine(ctx, scheme):
    def build():
        cols = []
        for v in ALL_VIEWS:
            X = tfidf_views(ctx, scheme)[v]
            Xn = X / (np.linalg.norm(X, axis=1, keepdims=True) + 1e-12)
            cols.append(np.einsum('ij,ij->i', Xn[ctx.ii], Xn[ctx.jj]))
        return np.stack(cols, axis=1)
    return ctx.cached(f'tfidf_cosine[{scheme}]', build)


def edit_similarity_columns(ctx):
    """{view: similarity per pair}, computed on each representation's own structure."""
    def build():
        out = {}
        for v in ALL_VIEWS:
            parsed = [parse_representation(v, t) for t in ctx.texts[v]]
            out[v] = pairwise_edit_similarity(parsed, ctx.ii, ctx.jj)
        return out
    return ctx.cached('edit_similarity[all views]', build)


def tree_kernel(ctx):
    def build():
        from advanced_metrics import tree_kernel_matrix
        n = len(ctx.formal)
        K = tree_kernel_matrix({i: f for i, f in enumerate(ctx.formal)}, list(range(n)))
        return K[ctx.ii, ctx.jj].reshape(-1, 1)
    return ctx.cached('tree_kernel[formal]', build)


def _kind(v):
    return 'tree edit distance' if v in TREE_PARSERS else 'token Levenshtein'


def get_methods(cfg):
    out = []
    for scheme, sname in SCHEMES.items():
        out.append(Method(
            f'SYMMETRIC Cosine on TF-IDF, {sname} (19 views, no Natural Latents)', 'symmetric',
            'cosine similarity of the raw TF-IDF vectors, one column per representation', 'all 19',
            symmetric=True, features=lambda ctx, s, sc=scheme: tfidf_cosine(ctx, sc)))
    out.append(Method(
        'SYMMETRIC Tree edit distance, equation only (formal)', 'symmetric',
        'Zhang-Shasha tree edit distance between the two equation trees (1 feature)', 'formal',
        symmetric=True, features=lambda ctx, s: edit_similarity_columns(ctx)['formal'].reshape(-1, 1)))
    out.append(Method(
        'SYMMETRIC Edit distance, all 19 representations', 'symmetric',
        'tree edit distance on the native tree of each tree-like representation and token '
        'Levenshtein on each sequential representation (19 features)', 'all 19', symmetric=True,
        features=lambda ctx, s: np.stack([edit_similarity_columns(ctx)[v] for v in ALL_VIEWS], axis=1)))
    for v in ALL_VIEWS:
        if v == 'formal':
            continue
        out.append(Method(
            f'SYMMETRIC Edit distance, {v} only ({_kind(v)})', 'symmetric-per-view',
            f'{_kind(v)} on the {v} representation alone (1 feature)', v, symmetric=True,
            features=lambda ctx, s, view=v: edit_similarity_columns(ctx)[view].reshape(-1, 1)))
    out.append(Method(
        'SYMMETRIC Tree convolution kernel (formal)', 'symmetric',
        'shared-subtree-pattern kernel on the formal view (src/advanced_metrics.py)', 'formal',
        symmetric=True, features=lambda ctx, s: tree_kernel(ctx)))
    return out
