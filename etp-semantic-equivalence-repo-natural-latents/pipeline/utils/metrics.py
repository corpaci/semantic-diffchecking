"""
Confusion matrices and classification metrics.

Per class c (one-vs-rest, from the 4x4 confusion matrix):
    TP = cm[c, c]      FN = row c minus TP      FP = column c minus TP      TN = the rest
    precision   = TP / (TP + FP)
    recall      = TP / (TP + FN)          (= sensitivity)
    specificity = TN / (TN + FP)
    F1          = 2 * precision * recall / (precision + recall)
    accuracy    = (TP + TN) / N           (one-vs-rest accuracy for that class)

Overall: accuracy, balanced accuracy (= macro recall), macro precision /
recall / specificity / F1, weighted F1, Cohen's kappa, Matthews correlation.

Every method is scored on each split separately (mean and std reported), and
the confusion matrices of all splits are also summed into one pooled matrix.
"""
import numpy as np
from sklearn.metrics import cohen_kappa_score, confusion_matrix, matthews_corrcoef

from .data import LABELS, LABEL_NAMES


def _safe(num, den):
    return float(num) / float(den) if den else 0.0


def per_class(cm):
    """4x4 confusion matrix -> list of dicts (one per class)."""
    n = cm.sum()
    rows = []
    for c, name in enumerate(LABEL_NAMES):
        tp = cm[c, c]
        fn = cm[c, :].sum() - tp
        fp = cm[:, c].sum() - tp
        tn = n - tp - fn - fp
        p, r = _safe(tp, tp + fp), _safe(tp, tp + fn)
        rows.append({
            'class': name, 'support': int(tp + fn),
            'TP': int(tp), 'FP': int(fp), 'FN': int(fn), 'TN': int(tn),
            'precision': p, 'recall': r, 'specificity': _safe(tn, tn + fp),
            'f1': _safe(2 * p * r, p + r), 'accuracy': _safe(tp + tn, n),
        })
    return rows


def overall(y_true, y_pred):
    cm = confusion_matrix(y_true, y_pred, labels=LABELS)
    pc = per_class(cm)
    support = np.array([r['support'] for r in pc], dtype=float)
    macro = lambda k: float(np.mean([r[k] for r in pc]))
    return {
        'accuracy': _safe(np.trace(cm), cm.sum()),
        'balanced_accuracy': macro('recall'),
        'macro_precision': macro('precision'),
        'macro_recall': macro('recall'),
        'macro_specificity': macro('specificity'),
        'macro_f1': macro('f1'),
        'weighted_f1': float(np.dot([r['f1'] for r in pc], support) / max(support.sum(), 1)),
        'cohen_kappa': float(cohen_kappa_score(y_true, y_pred, labels=LABELS)),
        'mcc': float(matthews_corrcoef(y_true, y_pred)),
    }, cm


OVERALL_KEYS = ['accuracy', 'balanced_accuracy', 'macro_precision', 'macro_recall',
                'macro_specificity', 'macro_f1', 'weighted_f1', 'cohen_kappa', 'mcc']
PER_CLASS_KEYS = ['precision', 'recall', 'specificity', 'f1', 'accuracy']


def evaluate_splits(y_true_list, y_pred_list):
    """Score each split, then aggregate: mean/std of every metric, the pooled
    confusion matrix, and per-class metrics (pooled and mean over splits)."""
    per_split, cms, pcs = [], [], []
    for t, p in zip(y_true_list, y_pred_list):
        o, cm = overall(t, p)
        per_split.append(o)
        cms.append(cm)
        pcs.append(per_class(cm))
    pooled = sum(cms)
    agg = {}
    for k in OVERALL_KEYS:
        vals = [o[k] for o in per_split]
        agg[k], agg[k + '_std'] = float(np.mean(vals)), float(np.std(vals))
    per_class_rows = []
    for c, row in enumerate(per_class(pooled)):
        for k in PER_CLASS_KEYS:
            row[k + '_mean_over_splits'] = float(np.mean([pc[c][k] for pc in pcs]))
            row[k + '_std_over_splits'] = float(np.std([pc[c][k] for pc in pcs]))
        per_class_rows.append(row)
    return {
        'overall': agg,
        'per_split': per_split,
        'confusion_pooled': pooled,
        'per_class': per_class_rows,
        # classifier-independent signature of a direction-blind (symmetric) method:
        # (A,B) and (B,A) get identical features, hence identical predictions, and
        # every test pair appears in both orders -> the two rows are equal
        'stronger_row_equals_weaker_row': bool(np.array_equal(pooled[1], pooled[2])),
    }
