"""What a method is, and how every method is run on the shared splits."""
import time
from dataclasses import dataclass
from typing import Callable, Optional

import numpy as np

from ..utils.classifier import describe_classifier, make_classifier
from ..utils.metrics import evaluate_splits


@dataclass
class Method:
    """One labelled experiment.

    Exactly one of `features` / `rule` is set:
      features(ctx, split) -> X, shape (n_pairs, d): pair features for EVERY pair.
          The shared base classifier is fitted on split.train_pairs and scores
          split.test_pairs. `split` is None unless per_split=True (features that
          must be fitted on the split's training equations only, e.g. a WL vocabulary).
      rule(ctx, split) -> predicted label for every pair. No classifier. A rule may
          tune thresholds on split.train_pairs; it is scored on split.test_pairs.
    """
    name: str
    family: str
    description: str
    representations: str
    features: Optional[Callable] = None
    rule: Optional[Callable] = None
    per_split: bool = False
    symmetric: bool = False

    @property
    def kind(self):
        return 'learned' if self.features is not None else 'rule'


def _fit_predict(cfg, X_train, y_train, X_test):
    clf = make_classifier(cfg, n_jobs=1)
    clf.fit(X_train, y_train)
    return clf.predict(X_test)


def run_method(ctx, m):
    """Features are built in this process; the per-split fits run in parallel
    worker processes (one single-threaded model each -- measured faster here
    than one multi-threaded model at a time)."""
    from joblib import Parallel, delayed
    t0 = time.time()
    n_features = 0
    if m.rule is not None:
        preds = [m.rule(ctx, s)[s.test_pairs] for s in ctx.splits]
    else:
        X_all = None if m.per_split else m.features(ctx, None)
        jobs = []
        for s in ctx.splits:
            X = X_all if X_all is not None else m.features(ctx, s)
            n_features = X.shape[1]
            jobs.append((X[s.train_pairs], ctx.y[s.train_pairs], X[s.test_pairs]))
        preds = Parallel(n_jobs=min(ctx.cfg.n_jobs, len(jobs)), backend='loky')(
            delayed(_fit_predict)(ctx.cfg, *j) for j in jobs)
    truths = [ctx.y[s.test_pairs] for s in ctx.splits]
    preds = [np.asarray(p) for p in preds]
    ev = evaluate_splits(truths, preds)
    return {
        'name': m.name, 'family': m.family, 'description': m.description,
        'representations': m.representations, 'kind': m.kind, 'symmetric': m.symmetric,
        'classifier': describe_classifier(ctx.cfg) if m.kind == 'learned' else 'none (rule; thresholds tuned on train pairs where applicable)',
        'n_features': n_features, 'runtime_s': time.time() - t0, **ev,
    }
