"""Twin-free splits, the classifier and every metric.

Splits hold out WHOLE twin groups (a law and its renamed / operand-swapped / equivalent twins never sit on both sides).
mode 'small' : the giant group (laws equivalent to E2) is training-only; test pairs are small-class pairs only (hard, honest)
mode 'giant' : 30% of giant laws are held out as well (a realistic mix; giant-giant pairs are easy)"""
import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import roc_auc_score
from .latent import Latent

LABELS = ['equivalent', 'stronger', 'weaker', 'incomparable']
STRATA = ('small-small', 'giant-giant', 'giant-other', 'all')


def _holdout(groups, giant, seed, frac, nodes_mask, giant_frac=0.0):
    rng = np.random.RandomState(seed)
    ids = np.array([g for g in np.unique(groups[nodes_mask]) if g != giant])
    rng.shuffle(ids)
    held = np.zeros(len(groups), bool)
    cap = int(frac * nodes_mask.sum())
    for g in ids:
        if held.sum() >= cap:
            break
        held |= (groups == g) & nodes_mask
    if giant_frac > 0:
        gi = np.nonzero((groups == giant) & nodes_mask)[0]
        held[rng.choice(gi, int(giant_frac * len(gi)), replace=False)] = True
    return held


class Setup:
    def __init__(self, ctx, test_frac=0.3, max_train=40000):
        self.ctx, self.test_frac, self.max_train = ctx, test_frac, max_train
        self.ii, self.jj, self.y = ctx.ii, ctx.jj, ctx.y
        self.giant = int(np.argmax(np.bincount(ctx.twin_group)))
        ig = ctx.twin_group == self.giant
        gi, gj = ig[self.ii], ig[self.jj]
        self.strat = np.where(gi & gj, 'giant-giant', np.where(gi | gj, 'giant-other', 'small-small'))

    def _pairs(self, nodes_mask, seed, cap=None):
        idx = np.nonzero(nodes_mask[self.ii] & nodes_mask[self.jj])[0]
        if cap and len(idx) > cap:
            idx = np.random.RandomState(seed).choice(idx, cap, replace=False)
        return idx

    def split(self, mode, seed):
        n = len(self.ctx.twin_group)
        everyone = np.ones(n, bool)
        test = _holdout(self.ctx.twin_group, self.giant, seed, self.test_frac, everyone,
                        self.test_frac if mode == 'giant' else 0.0)
        return dict(mode=mode, seed=seed, train_nodes=~test, tr=self._pairs(~test, seed, self.max_train), te=self._pairs(test, seed))

    def inner(self, split, frac=0.25):
        """validation split INSIDE the training part (always twin-free); used for greedy selection."""
        tn = split['train_nodes']
        val = _holdout(self.ctx.twin_group, self.giant, split['seed'] + 1, frac, tn)
        sub = tn & ~val
        return dict(mode='inner', seed=split['seed'], train_nodes=sub, tr=self._pairs(sub, split['seed'], self.max_train), te=self._pairs(val, split['seed']))


def _block(y, pred, p_eq):
    out = {'n': int(len(y))}
    if pred is not None:
        rec = {c: float(np.mean(pred[y == c] == c)) for c in range(4) if (y == c).any()}
        out['balanced_acc'] = float(np.mean(list(rec.values()))) if rec else np.nan
        out['acc'] = float(np.mean(pred == y))
        for c in range(4):
            out['recall_' + LABELS[c]] = rec.get(c, np.nan)
        tp = int(((pred == 0) & (y == 0)).sum()); fp = int(((pred == 0) & (y != 0)).sum())
        fn = int(((pred != 0) & (y == 0)).sum()); tn = int(((pred != 0) & (y != 0)).sum())
        P = tp / (tp + fp) if tp + fp else np.nan
        R = tp / (tp + fn) if tp + fn else np.nan
        out.update(equiv_precision=P, equiv_recall=R, equiv_specificity=tn / (tn + fp) if tn + fp else np.nan,
                   equiv_F1=2 * P * R / (P + R) if (P == P and R == R and P + R > 0) else np.nan)
    pos, neg = (y == 0), (y != 0)
    if p_eq is not None and pos.any() and neg.any():
        out['AUC_equiv_vs_rest'] = float(roc_auc_score(pos, p_eq))
        th = np.quantile(p_eq[neg], 0.90)
        out['recall_at_10pct_FPR'] = float((p_eq[pos] > th).mean())
        m = pos | (y == 3)
        if (y == 3).any():
            out['AUC_equiv_vs_incomp'] = float(roc_auc_score(y[m] == 0, p_eq[m]))
    return out


def evaluate(ctx, setup, split, channels, kind='gcca', feat='z', k=16, eval='full', clf_iter=150, want_cm=False):
    """Fit the latent on the training part, score the test pairs.  Returns (rows per stratum, confusion counts or None).
    eval 'full'  : HistGradientBoosting 4-class classifier on the pair features (all metrics)
    eval 'cheap' : no classifier; cosine of the shared latent is the score (AUC and recall@10%FPR only; ~20x faster)"""
    L = Latent(ctx, setup, split, channels, kind, feat, k)
    te, tr = split['te'], split['tr']
    y = setup.y[te]
    if eval == 'cheap':
        pred, p_eq = None, L.cosine(setup.ii[te], setup.jj[te])
    else:
        clf = HistGradientBoostingClassifier(max_iter=clf_iter, learning_rate=0.05, class_weight='balanced',
                                             random_state=split['seed'])
        clf.fit(L.features(setup.ii[tr], setup.jj[tr]), setup.y[tr])
        proba = clf.predict_proba(L.features(setup.ii[te], setup.jj[te]))
        pred = clf.classes_[proba.argmax(1)]
        p_eq = proba[:, list(clf.classes_).index(0)]
    rows, cms = [], []
    for st in STRATA:
        sel = np.ones(len(te), bool) if st == 'all' else setup.strat[te] == st
        if not sel.any():
            continue
        r = _block(y[sel], None if pred is None else pred[sel], p_eq[sel])
        r['stratum'] = st
        rows.append(r)
        if want_cm and pred is not None:
            cm = np.zeros((4, 4), int)
            np.add.at(cm, (y[sel].astype(int), pred[sel].astype(int)), 1)
            cms.append((st, cm))
    return rows, cms
