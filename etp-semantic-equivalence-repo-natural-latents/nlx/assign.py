"""Rules that choose an encoder for every notation.  Each preset returns a list of channels."""
import numpy as np
from sklearn.decomposition import TruncatedSVD
from sklearn.metrics import roc_auc_score
from pipeline.utils.data import ALL_VIEWS
from .encoders import channel, applies, get_channel, ENCODERS

PROSE = ['natural_language', 'word_problem', 'text', 'text2']
SEQUENCE = ['ssa', 'rpn', 'polish']
# the functional groups used in the study (tree notations include the two executable Python ones)
GROUPS = {'tree': ['formal', 'lean', 'latex', 'tptp', 'smtlib', 'json_ast', 'ascii_tree', 'graphviz', 'slots', 'py_lambda', 'py_cayley_table'],
          'sequence': ['rpn', 'polish', 'ssa'],
          'spelled_out': ['text', 'text2'],
          'interpreted': ['natural_language', 'word_problem'],
          'perturbed': ['confusable_vars']}


def uniform(enc, views=None):
    return [channel(v, enc) for v in (views or ALL_VIEWS) if applies(enc, v)]


def by_group(views=None, extras=False):
    """tree notations -> their own tokenizer; prose and token streams -> word n-grams; the rest -> own tokenizer.
    extras=True also adds two formal-only channels (WL subtrees, structural invariants)."""
    out = []
    for v in (views or ALL_VIEWS):
        out.append(channel(v, 'tfidf_word' if v in PROSE + SEQUENCE else 'tfidf_repr'))
    if extras and 'formal' in (views or ALL_VIEWS):
        out += [channel('formal', 'wl_formal'), channel('formal', 'inv_formal')]
    return out


def best_per_view(ctx, setup, split, candidates=('tfidf_repr', 'tfidf_generic', 'tfidf_family', 'tfidf_word', 'lsa64'),
                  views=None, n_pairs=6000, dim=16, seed=0):
    """LEARNED assignment: for every notation pick the encoder whose top-`dim` PCA cosine best separates equivalent from
    incomparable pairs.  Uses TRAINING pairs only (both laws in the training part of the split).
    Returns (channels, table of AUCs view x encoder)."""
    rng = np.random.RandomState(seed)
    tr = split['tr']
    y = setup.y[tr]
    keep = tr[(y == 0) | (y == 3)]
    if len(keep) > n_pairs:
        keep = rng.choice(keep, n_pairs, replace=False)
    ia, ib, yy = setup.ii[keep], setup.jj[keep], (setup.y[keep] == 0)
    train_idx = np.nonzero(split['train_nodes'])[0]
    table, chosen = {}, []
    for v in (views or ALL_VIEWS):
        best, be = -1, None
        for e in candidates:
            if not applies(e, v):
                continue
            X = get_channel(ctx, channel(v, e))
            Z = TruncatedSVD(min(dim, X.shape[1] - 1), random_state=0).fit(X[train_idx]).transform(X)
            Z = Z / (np.linalg.norm(Z, axis=1, keepdims=True) + 1e-9)
            auc = roc_auc_score(yy, (Z[ia] * Z[ib]).sum(1))
            table[(v, e)] = auc
            if auc > best:
                best, be = auc, e
        chosen.append(channel(v, be))
    return chosen, table
