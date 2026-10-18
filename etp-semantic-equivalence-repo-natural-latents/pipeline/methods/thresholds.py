"""
Threshold rules -- no classifier. Thresholds are tuned on the split's TRAIN
pairs (maximising balanced accuracy) and applied to its test pairs.

On the entropy-type Natural Latents losses (Generic RAW latents; each view's
NxN loss matrix is z-scored, then averaged over the 19 views into one score
S[i, j] = loss(i -> j)):
  * two thresholds:  A => B iff s*S[A,B] <= t,  B => A iff s*S[B,A] <= t  (sign s tuned)
  * sum/difference:  equivalent if S[A,B]+S[B,A] <= t1; else the direction of
                     S[A,B]-S[B,A] if |difference| >= t2; else incomparable

On the magma conditional entropy H(B | A) = h(P(B holds | A holds)) over the
fingerprint bank:  A => B iff H <= eps  (eps = 0 is exactly the counter-model rule).
"""
import itertools

import numpy as np
from sklearn.metrics import balanced_accuracy_score

from ..utils.data import implications_to_label
from .base import Method
from .natural_latents import loss_matrices
from .semantic import fingerprints

SCHEME, STATE = 'generic', 'raw'


def mean_zscored_loss(ctx, loss):
    def build():
        acc = 0.0
        for v, mats in loss_matrices(ctx, SCHEME, STATE).items():
            m = mats[loss]
            off = m[~np.eye(len(m), dtype=bool)]
            acc = acc + (m - off.mean()) / (off.std() + 1e-12)
        return acc / len(loss_matrices(ctx, SCHEME, STATE))
    return ctx.cached(f'mean_zscored[{loss}]', build)


def _best(candidates, predict, y, mask):
    return max(candidates, key=lambda c: balanced_accuracy_score(y[mask], predict(*c)[mask]))


def two_threshold_rule(loss):
    def rule(ctx, split):
        S = mean_zscored_loss(ctx, loss)
        f_all, b_all = S[ctx.ii, ctx.jj], S[ctx.jj, ctx.ii]
        tr = split.train_pairs

        def predict(sign, t):
            return implications_to_label(sign * f_all <= t, sign * b_all <= t)

        cands = [(sg, t) for sg in (1, -1)
                 for t in np.quantile(sg * f_all[tr], np.linspace(0.02, 0.98, 49))]
        return predict(*_best(cands, predict, ctx.y, tr))
    return rule


def sum_difference_rule(loss):
    def rule(ctx, split):
        S = mean_zscored_loss(ctx, loss)
        f, b = S[ctx.ii, ctx.jj], S[ctx.jj, ctx.ii]
        tr = split.train_pairs

        def predict(sign, t1, t2):
            tot, diff = sign * (f + b), sign * (f - b)
            return np.where(tot <= t1, 0, np.where(diff <= -t2, 2, np.where(diff >= t2, 1, 3)))

        cands = [(sg, t1, t2) for sg in (1, -1)
                 for t1, t2 in itertools.product(np.quantile(sg * (f + b)[tr], np.linspace(0.02, 0.5, 13)),
                                                 np.quantile(np.abs(f - b)[tr], np.linspace(0.05, 0.95, 13)))]
        return predict(*_best(cands, predict, ctx.y, tr))
    return rule


def magma_conditional_entropy(ctx):
    def build():
        F, _ = fingerprints(ctx)
        F = F.astype(np.float64)                 # float64: 1 - 1e-12 must not round to 1
        n_models = F.sum(axis=1)
        p = np.where(n_models[:, None] > 0, (F @ F.T) / np.maximum(n_models[:, None], 1), 1.0)
        pc = np.clip(p, 1e-12, 1 - 1e-12)
        H = -(pc * np.log2(pc) + (1 - pc) * np.log2(1 - pc))
        H = np.where(p >= 1, 0.0, H)             # all of A's models satisfy B
        return np.where(p < 0.5, 1.0, H)         # keep the score monotone in p
    return ctx.cached('magma_conditional_entropy', build)


def magma_entropy_rule(ctx, split):
    H = magma_conditional_entropy(ctx)
    f, b = H[ctx.ii, ctx.jj], H[ctx.jj, ctx.ii]

    def predict(eps):
        return implications_to_label(f <= eps, b <= eps)

    eps = _best([(e,) for e in (0.0, 1e-3, 1e-2, 0.05, 0.1, 0.2, 0.5)], predict, ctx.y, split.train_pairs)
    return predict(*eps)


def get_methods(cfg):
    out = []
    for loss in ('KL', 'CrossEntropy', 'SignedLLR', 'RankInfoGain'):
        out.append(Method(f'THRESH {loss}: two implication thresholds', 'threshold',
                          f'mean z-scored {loss} over 19 views, one tuned threshold per direction',
                          'all 19', rule=two_threshold_rule(loss)))
        out.append(Method(f'THRESH {loss}: sum/difference thresholds', 'threshold',
                          f'mean z-scored {loss}: sum decides equivalent, signed difference decides direction',
                          'all 19', rule=sum_difference_rule(loss)))
    out.append(Method('THRESH Magma conditional entropy H(B|A) <= eps', 'threshold',
                      'entropy of P(B holds | A holds) over the magma bank, eps tuned on train pairs',
                      'formal (executed)', rule=magma_entropy_rule))
    return out
