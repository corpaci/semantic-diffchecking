"""
Natural Latents, RAW (no cross-view resampling), two ways of feeding the classifier.
Drop-in method module for the repo: pipeline/methods/natural_latents_full.py

  VARIANT 1  "all views -> latents -> classifier"
      19 representations -> per-view TF-IDF -> per-view SVD (cfg.n_components = 8)
      -> concatenate (19 x 8 = 152) -> pair features [z(A), z(B), z(A) - z(B)]  (456)
      -> the repo's base classifier.
      (this is the repo's existing "Direct latents ... RAW" method, re-registered here
       so both variants sit side by side in one results sheet)

  VARIANT 2  "compress the latents into ONE representation"
      the same 152-dim concatenation -> standardise -> SVD to k dims  => one z per equation
      -> pair features [z(A), z(B), z(A) - z(B)]  (3k)  -> the base classifier.
      The standardiser and the SVD are fitted on the TRAINING equations of each split only
      (per_split=True), so no held-out equation influences the compression.

Both use the same node-held-out splits and the same base classifier as every other method.

Run on (nearly) all equations / many pairs:
    NLFULL_FAST_PAIRS=1 python run_all.py --modules nl_full --sample-size 4694 --pairs 400000 \
        --out results_nl_full
(--sample-size 4694 = every equation in the oracle; --pairs = ordered pairs sampled from the
 ~22M oracle pairs. NLFULL_FAST_PAIRS=1 swaps the slow python pair enumeration for a
 vectorised one with the same semantics -- needed for 4,694 equations.)

Register in pipeline/methods/__init__.py:
    from . import advanced, natural_latents, natural_latents_full, semantic, structural, symmetric, thresholds
    MODULES = {..., 'nl_full': natural_latents_full}
"""
import os

import numpy as np

from ..utils.data import ALL_VIEWS, LABEL_NAMES, implications_to_label
from ..utils.features import directional_pair
from .base import Method
from .natural_latents import latents

SCHEMES_USED = {'repr': 'Representation-specific', 'generic': 'Generic char n-gram'}
COMPRESSED_DIMS = (8, 16, 32)


# --------------------------------------------------------------------------- helpers
def concat_latents(ctx, scheme):
    """(n_equations, 19 * n_components): per-view RAW latents side by side (cached)."""
    lat = latents(ctx, scheme, 'raw')
    return np.concatenate([lat[v] for v in ALL_VIEWS], axis=1)


def compress(Z, train_nodes, k):
    """Standardise + SVD fitted on training equations only -> (n_equations, k).
    One representation per equation, in a space no held-out equation shaped."""
    mu = Z[train_nodes].mean(axis=0)
    sd = Z[train_nodes].std(axis=0) + 1e-8
    X = (Z - mu) / sd
    _, _, Vt = np.linalg.svd(X[train_nodes], full_matrices=False)
    return X @ Vt[:k].T


# --------------------------------------------------------------------------- methods
def get_methods(cfg):
    out = []
    for scheme, sname in SCHEMES_USED.items():
        tag = f'NLFULL {sname}, RAW'
        out.append(Method(
            f'{tag} | V1 all-view latents -> classifier', 'nl-full',
            '19 per-view SVD latents concatenated; features [z(A), z(B), z(A)-z(B)] (456)', 'all 19',
            features=lambda ctx, s, sc=scheme: directional_pair(concat_latents(ctx, sc), ctx.ii, ctx.jj)))
        for k in COMPRESSED_DIMS:
            out.append(Method(
                f'{tag} | V2 compressed to one rep (k={k})', 'nl-full',
                f'152-dim latent concatenation -> standardise -> SVD(k={k}), fitted on training '
                f'equations; features [z(A), z(B), z(A)-z(B)] ({3 * k})', 'all 19', per_split=True,
                features=lambda ctx, s, sc=scheme, kk=k: directional_pair(
                    compress(concat_latents(ctx, sc), s.train_nodes, kk), ctx.ii, ctx.jj)))
    return out


# --------------------------------------------------------------------------- optional: fast pair generation
def _generate_pairs_fast(nodes, n_pairs, seed):
    """Same semantics as pipeline.utils.data.generate_pairs (pairs resolved in BOTH directions,
    each sampled unordered pair contributes both orderings), vectorised over the oracle matrix."""
    import pandas as pd
    from decode_matrix import load_matrix
    M, _ = load_matrix()
    idx = np.asarray(nodes) - 1
    S = M[np.ix_(idx, idx)]                              # S[i, j]: nodes[i] => nodes[j]
    resolved = np.isin(S, (0, 1))
    iu, ju = np.triu_indices(len(nodes), 1)
    keep = resolved[iu, ju] & resolved[ju, iu]
    iu, ju = iu[keep], ju[keep]
    n_available = len(iu)
    sel = np.random.RandomState(seed).choice(n_available, min(n_pairs // 2, n_available), replace=False)
    a, b = iu[sel], ju[sel]
    lab_ab = implications_to_label(S[a, b] == 1, S[b, a] == 1)     # fwd: a=>b, bwd: b=>a
    lab_ba = implications_to_label(S[b, a] == 1, S[a, b] == 1)
    nodes = np.asarray(nodes)
    df = pd.DataFrame({'node_a': np.concatenate([nodes[a], nodes[b]]),
                       'node_b': np.concatenate([nodes[b], nodes[a]]),
                       'relation': np.array(LABEL_NAMES)[np.concatenate([lab_ab, lab_ba])]})
    return df.sample(frac=1, random_state=seed).reset_index(drop=True), n_available


if os.environ.get('NLFULL_FAST_PAIRS') == '1':
    from ..utils import context as _context
    _context.generate_pairs = _generate_pairs_fast
