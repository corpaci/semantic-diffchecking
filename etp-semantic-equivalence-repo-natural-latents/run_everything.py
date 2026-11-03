#!/usr/bin/env python
"""ONE script, ONE split: cosine, tree edit distance (ASSESS / GTED) and every natural-latent variant, for n = 1 ... 19 notations.

  python3 run_everything.py --profile paper --out all_methods            (the paper run; see PROFILES below)
  python3 run_everything.py --profile quick --out all_quick               (smoke test, a few minutes)
  python3 run_everything.py --out all_methods --resume                    (continue an interrupted run)
  python3 run_everything.py --out all_methods --summarize-only            (rebuild the tables from the CSV)

WHAT IS SHARED  For every (mode, seed) the twin-free split is built ONCE with the nlx Setup (whole twin groups held out; mode small =
giant class train-only, test = small--small pairs).  The same train pairs and the same test pairs go to EVERY method, and the same random
subsets of notations go to cosine and to every natural-latent variant, so all rows are directly comparable.
METHODS
  cosine        mean over the chosen notations of the cosine between the two laws' TF-IDF vectors         (score; no classifier)
  tree_edit     ASSESS, GTED (alpha-conversion) and a variable-blind ablation on the formal law's operator tree   (score; n-independent)
                + 'tree sim + sizes' : gradient-boosted 4-class classifier on the tree similarities, sizes and variable counts
  natural_latent  kind concat | gcca  x  feature set z | zpa | plus | sym | loss | mix | z+loss | z+mix   (gradient-boosted 4-class classifier)
                z = [z(A), z(B), z(A)-z(B)];  sym = per-notation cosine / Euclid;  loss = per-notation KL / cross-entropy / rank info gain /
                signed LLR (both directions);  mix = sym + loss;  z+loss, z+mix = direct latents plus those.
                n = 1 uses ALL 19 single notations; n = 19 is the full set; other n use random subsets (--draws per n).
CROSS-REPRESENTATION (--xr, on by default): pair (A, B) with notation u for law A and a DIFFERENT notation v for law B, for every ordered pair (u, v)
  of the --xr-views notations (default 8; --xr-all = all 19).  The diagonal u == v (same notation) is run too, as the reference.
  Possible only where both notations live in ONE space, so it is run for:
    xr_cosine       one char n-gram TF-IDF vocabulary shared by all notations; cosine(A in u, B in v)                          (score)
    xr_gcca_cosine  cosine of the two laws in the shared GCCA latent (each notation's projection lands in the same space)       (score)
    xr_gcca_<loss>  KL / CrossEntropy / RankInfoGain / SignedLLR between A seen through u and B seen through v (both directions) (score)
    xr_gcca_clf     (--xr-clf) gradient-boosted 4-class classifier on [z_u(A), z_v(B), z_u(A)-z_v(B), cos, dist]             (classifier)
  NOT possible (documented, not silently skipped):  natural-latent kind 'concat' (each notation has its own, unrelated latent axes) and
  tree edit (needs a tree for each notation; the notations that parse to the same tree give the formal-tree result by construction).
NOT included  NLSEM-1..13 (run_nlsem_strata.py) use their own split, so they cannot share these test pairs.
METRICS (all on the same test pairs, equivalent vs rest)  AUC, recall at 10% false positives (threshold from the TEST negatives: a ranking
metric), derived precision at that point (from the test equivalent rate), plus precision / recall / F1 at each method's DECISION RULE:
score methods = threshold maximising F1 on TRAIN pairs (also a 10%-FPR threshold from train pairs); classifiers = 4-class argmax.

OUTPUT MAP  (<out> is the --out folder, default ./all_methods, created next to where you run the command)
  <out>/all_methods_rows.csv            every cosine / tree-edit / natural-latent run, one row per run x test stratum   (checkpoint file for --resume)
  <out>/all_methods_rows.csv.bak        the previous rows file, kept when you re-run WITHOUT --resume
  <out>/summary_by_method_and_n.csv     mean / std over seeds and subsets for each method x number of notations
  <out>/table_auc_by_n.csv, table_recall_by_n.csv, table_precision_by_n.csv    method x n tables (AUC, recall@10%FPR, derived precision)
  <out>/table_tree_edit.csv             the n-independent tree-edit baselines
  <out>/tables.tex                      LaTeX versions of the three method x n tables
  <out>/xr_rows.csv                     every cross-representation run: one row per method x (notation of A, notation of B) x stratum
  <out>/xr_matrix_<method>_AUC.csv|.png and xr_matrix_<method>_recall10.csv|.png     notation(A) x notation(B) matrices and heat maps
  <out>/xr_summary.csv                  same-notation (diagonal) vs cross-notation (off-diagonal) means per method
  <out>/xr_tables.tex                   LaTeX table of that summary
SAVED WHILE THE RUN GOES (no need to wait for the end; every item can be switched off, see the --no-save-* flags)
  <out>/pair_scores/split_<mode>_<seed>.npz    the split: train / test pair indices, the test pairs' laws (ii, jj), labels y and strata
  <out>/pair_scores/<family>__<method...>__<hash>.npz   one file per run: the score (and, for classifiers, the 4 class probabilities and the
                                                predicted class) of every TEST pair, in the order of the split file's `te`; thresholds too
  <out>/pair_scores/index.csv                  job name -> file, so you can find any run's scores
  <out>/confusion_long.csv                     4 x 4 confusion counts (true x predicted) for every classifier run and stratum; the score methods'
                                                2 x 2 counts (TP, FN, FP, TN) are columns of all_methods_rows.csv / xr_rows.csv
  <out>/tree_distances.npz                     every tree-edit distance / similarity computed so far (re-used after a restart)
  <out>/models/<...>.joblib                    every trained gradient-boosting classifier
  <out>/latents/<mode>_<seed>_<kind>_<hash>.npy  the latent matrix (laws x dims) of every natural-latent run, once per kind and subset
  <out>/latents/xr_gcca_<mode>_<seed>.npz      the shared GCCA latents of every notation used in the cross-representation step
  <out>/summary_* , table_* , xr_*             rebuilt every --summary-every finished runs (default 20) and again at the end
Main stratum: small--small (mode small)."""
import argparse, os, sys, time, warnings
warnings.filterwarnings('ignore')
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import numpy as np, pandas as pd

PROFILES = {   # (ns, draws, seeds, concat feats, gcca feats)
    'quick': dict(ns=[1, 3, 19], draws=1, seeds=[42], concat=['z', 'loss'], gcca=['z'], sample_size=500, pairs=20000, max_train=8000, clf_iter=60),
    'paper': dict(ns=[1, 2, 3, 4, 6, 8, 12, 19], draws=3, seeds=[42, 7], concat=['z', 'sym', 'loss', 'mix', 'z+loss', 'z+mix'], gcca=['z', 'zpa', 'plus'],
                  sample_size=None, pairs=None, max_train=40000, clf_iter=150),
    'full': dict(ns=[1, 2, 3, 4, 5, 6, 8, 10, 12, 15, 19], draws=5, seeds=[42, 7, 11], concat=['z', 'sym', 'loss', 'mix', 'z+loss', 'z+mix'],
                 gcca=['z', 'zpa', 'plus', 'z+loss', 'z+mix'], sample_size=None, pairs=None, max_train=40000, clf_iter=150),
}
COLS = ['job', 'family', 'method', 'kind', 'feat', 'n_notations', 'draw', 'channels', 'mode', 'seed', 'stratum', 'decision_rule', 'n', 'test_equiv_rate',
        'AUC_equiv_vs_rest', 'recall_at_10pct_FPR', 'derived_precision_at_10pct_FPR', 'AUC_equiv_vs_incomp', 'equiv_precision', 'equiv_recall', 'equiv_F1',
        'equiv_specificity', 'precision_fpr10rule', 'recall_fpr10rule', 'F1_fpr10rule', 'balanced_acc', 'acc', 'recall_equivalent', 'recall_stronger',
        'recall_weaker', 'recall_incomparable', 'TP', 'FN', 'FP', 'TN', 'theta_maxF1', 'theta_fpr10']


# ------------------------------------------------------------------------------------------------ helpers
def prf(pos, pred):
    tp = int((pos & pred).sum()); fp = int((~pos & pred).sum()); fn = int((pos & ~pred).sum())
    P = tp / (tp + fp) if tp + fp else np.nan; R = tp / (tp + fn) if tp + fn else np.nan
    return P, R, (2 * P * R / (P + R) if P == P and R == R and P + R > 0 else np.nan)


def best_f1_threshold(s, pos):
    best, th = -1, float(np.median(s))
    for t in np.unique(np.quantile(s, np.linspace(0.01, 0.99, 197))):
        f = prf(pos, s > t)[2]
        if f == f and f > best: best, th = f, t
    return float(th)


def derived_precision(r10, pi, fpr=0.10):
    return r10 * pi / (r10 * pi + fpr * (1 - pi)) if r10 == r10 and pi > 0 else np.nan


def cos_pairs(X, ia, ib):
    a, b = X[ia], X[ib]
    return (a * b).sum(1) / (np.linalg.norm(a, axis=1) * np.linalg.norm(b, axis=1) + 1e-9)



import hashlib, re as _re


class Saver:
    """Everything that is written besides the metric rows.  All paths are under --out (see the OUTPUT MAP in the header)."""
    def __init__(self, out, scores=True, models=True, latents=True):
        self.out, self.scores_on, self.models_on, self.latents_on = out, scores, models, latents
        for d in ('pair_scores', 'models', 'latents'): os.makedirs(os.path.join(out, d), exist_ok=True)
        self.index_path = os.path.join(out, 'pair_scores', 'index.csv'); self.conf_path = os.path.join(out, 'confusion_long.csv')
        self.conf_first = not os.path.exists(self.conf_path); self.idx_first = not os.path.exists(self.index_path)

    @staticmethod
    def name(job):
        return _re.sub(r'[^A-Za-z0-9_.+-]+', '_', job)[:80] + '__' + hashlib.md5(job.encode()).hexdigest()[:8]

    def split(self, setup, split, mode, seed):                                         # OUTPUT -> <out>/pair_scores/split_<mode>_<seed>.npz
        if not self.scores_on: return
        p = os.path.join(self.out, 'pair_scores', f'split_{mode}_{seed}.npz')
        if not os.path.exists(p):
            te = split['te']
            np.savez_compressed(p, tr=split['tr'], te=te, ii_te=setup.ii[te], jj_te=setup.jj[te], y_te=setup.y[te], strat_te=setup.strat[te].astype(str),
                                train_nodes=split['train_nodes'])

    def scores(self, job, **arrays):                                                   # OUTPUT -> <out>/pair_scores/<name>.npz  (+ index.csv)
        if not self.scores_on: return
        fn = self.name(job) + '.npz'
        np.savez_compressed(os.path.join(self.out, 'pair_scores', fn), **{k: np.asarray(v, np.float32) if np.asarray(v).dtype.kind == 'f' else np.asarray(v) for k, v in arrays.items()})
        pd.DataFrame([dict(job=job, file=fn)]).to_csv(self.index_path, mode='w' if self.idx_first else 'a', header=self.idx_first, index=False); self.idx_first = False

    def model(self, job, obj):                                                         # OUTPUT -> <out>/models/<name>.joblib
        if not self.models_on: return
        import joblib
        joblib.dump(obj, os.path.join(self.out, 'models', self.name(job) + '.joblib'), compress=3)

    def latent(self, key, arr):                                                        # OUTPUT -> <out>/latents/<key>.npy
        if not self.latents_on: return
        p = os.path.join(self.out, 'latents', _re.sub(r'[^A-Za-z0-9_.+-]+', '_', key)[:90] + '__' + hashlib.md5(key.encode()).hexdigest()[:8] + '.npy')
        if not os.path.exists(p): np.save(p, np.asarray(arr, np.float32))

    def confusion(self, base, y, pred, strata_te, strata):                             # OUTPUT -> <out>/confusion_long.csv
        rows = []
        for st in strata:
            sel = np.ones(len(y), bool) if st == 'all' else strata_te == st
            if not sel.any(): continue
            cm = np.zeros((4, 4), int); np.add.at(cm, (y[sel].astype(int), pred[sel].astype(int)), 1)
            rows += [dict(base, stratum=st, true=LAB4[i], pred=LAB4[j], count=int(cm[i, j])) for i in range(4) for j in range(4)]
        if rows:
            pd.DataFrame(rows).to_csv(self.conf_path, mode='w' if self.conf_first else 'a', header=self.conf_first, index=False); self.conf_first = False


LAB4 = ['equivalent', 'stronger', 'weaker', 'incomparable']

def score_rows(setup, split, s_tr, s_te, base, strata, block, saver=None, job=None):
    """Score-only method (higher = more equivalent): ranking metrics + threshold decision rules chosen on TRAIN pairs."""
    te, tr = split['te'], split['tr']
    y_te = setup.y[te]; pos_tr = setup.y[tr] == 0
    th_f1, th10 = best_f1_threshold(s_tr, pos_tr), float(np.quantile(s_tr[~pos_tr], 0.90))
    rows = []
    for st in strata:
        sel = np.ones(len(te), bool) if st == 'all' else setup.strat[te] == st
        if not sel.any(): continue
        r = block(y_te[sel], None, s_te[sel]); pos = y_te[sel] == 0
        P, R, F = prf(pos, s_te[sel] > th_f1); P2, R2, F2 = prf(pos, s_te[sel] > th10)
        pred_b = s_te[sel] > th_f1
        r.update(TP=int((pos & pred_b).sum()), FN=int((pos & ~pred_b).sum()), FP=int((~pos & pred_b).sum()), TN=int((~pos & ~pred_b).sum()),
                 theta_maxF1=th_f1, theta_fpr10=th10,
                 equiv_precision=P, equiv_recall=R, equiv_F1=F, precision_fpr10rule=P2, recall_fpr10rule=R2, F1_fpr10rule=F2,
                 decision_rule='max-F1 threshold on train pairs', test_equiv_rate=float(pos.mean()), stratum=st, **base)
        rows.append(r)
    if saver is not None and job is not None:
        saver.scores(job, score=s_te, y=y_te, theta_maxF1=th_f1, theta_fpr10=th10)
    return rows


def add_derived(rows):
    for r in rows:
        r['derived_precision_at_10pct_FPR'] = derived_precision(r.get('recall_at_10pct_FPR', np.nan), r.get('test_equiv_rate', np.nan))
    return rows


# ------------------------------------------------------------------------------------------------ tree edit

def clf_rows(ev, setup, te, strata, pred, p_eq, base):
    """4-class classifier -> one row per stratum, equivalent-vs-rest counts included."""
    y = setup.y[te]; rows = []
    for st in strata:
        sel = np.ones(len(te), bool) if st == 'all' else setup.strat[te] == st
        if not sel.any(): continue
        r = ev._block(y[sel], pred[sel], p_eq[sel]); pos, pb = y[sel] == 0, pred[sel] == 0
        r.update(TP=int((pos & pb).sum()), FN=int((pos & ~pb).sum()), FP=int((~pos & pb).sum()), TN=int((~pos & ~pb).sum()),
                 decision_rule='4-class argmax', test_equiv_rate=float(pos.mean()), stratum=st, **base)
        rows.append(r)
    return rows


def save_classifier(saver, job, base, setup, te, strata, clf, proba, pred, p_eq):
    saver.scores(job, p_equivalent=p_eq, proba=proba, pred=pred, classes=clf.classes_, y=setup.y[te])           # OUTPUT -> <out>/pair_scores/
    saver.confusion({k: base[k] for k in ('family', 'method', 'kind', 'feat', 'n_notations', 'draw', 'channels', 'mode', 'seed')} | dict(job=job),
                    setup.y[te], pred, setup.strat[te], strata)                                                      # OUTPUT -> <out>/confusion_long.csv
    saver.model(job, clf)                                                                                            # OUTPUT -> <out>/models/


def nl_run(a, P, R, saver, job, split, sub, kind, feat, strata, base):
    """One natural-latent run: fit the latent on the training laws, classify the test pairs, save everything."""
    from sklearn.ensemble import HistGradientBoostingClassifier
    import nlx.latent_loss as ll
    ctx, setup, ev = R['ctx'], R['setup'], R['ev']
    L = ll.Latent(ctx, setup, split, list(sub), kind, feat, a.k)
    te, tr = split['te'], split['tr']
    saver.latent(f"{base['mode']}_{base['seed']}_{kind}_{'+'.join(sub)}", L.E)                                      # OUTPUT -> <out>/latents/
    if a.eval == 'cheap':
        p_eq = L.cosine(setup.ii[te], setup.jj[te]); y = setup.y[te]; rows = []
        for st in strata:
            sel = np.ones(len(te), bool) if st == 'all' else setup.strat[te] == st
            if sel.any():
                r = ev._block(y[sel], None, p_eq[sel]); r.update(decision_rule='score only (cosine of latent)', test_equiv_rate=float(np.mean(y[sel] == 0)), stratum=st, **base); rows.append(r)
        saver.scores(job, score=p_eq, y=y)
        return rows
    clf = HistGradientBoostingClassifier(max_iter=P['clf_iter'], learning_rate=0.05, class_weight='balanced', random_state=split['seed'])
    clf.fit(L.features(setup.ii[tr], setup.jj[tr]), setup.y[tr])
    proba = clf.predict_proba(L.features(setup.ii[te], setup.jj[te])); pred = clf.classes_[proba.argmax(1)]
    p_eq = proba[:, list(clf.classes_).index(0)]
    save_classifier(saver, job, base, setup, te, strata, clf, proba, pred, p_eq)
    return clf_rows(ev, setup, te, strata, pred, p_eq, base)


class TreeEdit:
    def __init__(self, ctx, setup, polish_path, procs, cache_path=None):
        import json, tree_metrics as tm
        self.tm, self.procs, self.setup = tm, procs, setup
        eq = {int(e['node']): e for e in json.load(open(polish_path))['equations']}
        missing = [n for n in ctx.node_order if int(n) not in eq]
        if missing: raise SystemExit(f'{len(missing)} laws of the sample are not in {polish_path} (e.g. {missing[:3]})')
        self.trees = {}
        for i, n in enumerate(ctx.node_order):
            raw = tm.parse_polish(eq[int(n)]['polish'])
            self.trees[i] = dict(raw=raw, assess=tm.assess_tree(raw), alpha=tm.alpha_tree(raw), blind=tm.blind_tree(raw))
        self.cols = ['assess_tsed_sim', 'gted_alpha_sim', 'gted_blind_sim', 'assess_tsed_d', 'gted_alpha_d', 'gted_blind_d', 'size_a', 'size_b', 'nvar_a', 'nvar_b']
        self.F = np.full((len(setup.ii), len(self.cols)), np.nan)
        self.cache_path = cache_path; self.sig = np.array([len(setup.ii), int(setup.ii.sum()), int(setup.jj.sum())])
        if cache_path and os.path.exists(cache_path):                    # re-use distances from an earlier (interrupted) run
            d = np.load(cache_path)
            if d['sig'].tolist() == self.sig.tolist() and d['F'].shape == self.F.shape: self.F = d['F']; print(f'  tree distances re-used from {cache_path}', flush=True)

    def save(self):                                                       # OUTPUT -> <out>/tree_distances.npz
        if self.cache_path: np.savez_compressed(self.cache_path, F=self.F, sig=self.sig)

    def need(self, idx):
        idx = np.asarray(idx); todo = idx[np.isnan(self.F[idx, 0])]
        if len(todo) == 0: return
        from multiprocessing import Pool
        pairs = list(zip(self.setup.ii[todo].tolist(), self.setup.jj[todo].tolist()))
        with Pool(self.procs, initializer=self.tm._init, initargs=(self.trees,)) as p:
            R = p.map(self.tm.pair_row, pairs, chunksize=500)
        self.F[todo] = np.array([[r[c] for c in self.cols] for r in R])
        self.save()

    def get(self, idx, cols):
        return self.F[np.asarray(idx)][:, [self.cols.index(c) for c in cols]]


# ------------------------------------------------------------------------------------------------ the run
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--out', default='all_methods'); ap.add_argument('--profile', choices=list(PROFILES), default='paper')
    ap.add_argument('--methods', nargs='+', choices=['cosine', 'tree', 'nl'], default=['cosine', 'tree', 'nl'])
    ap.add_argument('--mode', nargs='+', choices=['small', 'giant'], default=['small'])
    ap.add_argument('--ns', type=int, nargs='+'); ap.add_argument('--draws', type=int); ap.add_argument('--seeds', type=int, nargs='+')
    ap.add_argument('--concat-feats', nargs='+'); ap.add_argument('--gcca-feats', nargs='+')
    ap.add_argument('--no-singles-all', action='store_true', help='n=1 uses random draws instead of all 19 single notations')
    ap.add_argument('--eval', choices=['full', 'cheap'], default='full'); ap.add_argument('--k', type=int, default=16)
    ap.add_argument('--knn', type=int, default=10); ap.add_argument('--polish', default=None, help='etp_equations_polish.json')
    ap.add_argument('--pool-encoder', default='tfidf_repr'); ap.add_argument('--procs', type=int, default=os.cpu_count() or 1)
    ap.add_argument('--no-save-scores', action='store_true', help='do not save per-pair scores / predictions')
    ap.add_argument('--no-save-models', action='store_true', help='do not save trained classifiers (each ~0.5 MB)')
    ap.add_argument('--no-save-latents', action='store_true', help='do not save latent matrices (a few MB each)')
    ap.add_argument('--summary-every', type=int, default=20, help='rebuild the summary tables every N finished runs (0 = only at the end)')
    ap.add_argument('--no-xr', action='store_true', help='skip the cross-representation step')
    ap.add_argument('--xr-views', nargs='+', default=['formal', 'lean', 'latex', 'py_lambda', 'ssa', 'json_ast', 'natural_language', 'word_problem'])
    ap.add_argument('--xr-all', action='store_true', help='cross-representation over all 19 notations (361 ordered pairs; slower)')
    ap.add_argument('--xr-clf', action='store_true', help='also train the 4-class classifier for every ordered notation pair (slow)')
    ap.add_argument('--xr-train-pairs', type=int, default=10000, help='train pairs used for thresholds / classifier in the cross-representation step')
    ap.add_argument('--resume', action='store_true'); ap.add_argument('--summarize-only', action='store_true')
    a = ap.parse_args(); P = PROFILES[a.profile]
    for k in ('ns', 'draws', 'seeds'): setattr(a, k, getattr(a, k) or P[k])
    a.concat_feats = [f for f in (a.concat_feats or P['concat']) if f != 'none']; a.gcca_feats = [f for f in (a.gcca_feats or P['gcca']) if f != 'none']
    os.makedirs(a.out, exist_ok=True)
    rows_path = os.path.join(a.out, 'all_methods_rows.csv')      # OUTPUT -> <out>/all_methods_rows.csv  (all non-cross-representation runs)
    if a.summarize_only:
        summarize(a.out); return summarize_xr(a.out)
    os.chdir(HERE)
    from pipeline.config import Config
    from pipeline.utils.context import Context
    import nlx.evaluate as ev, nlx.latent_loss as ll
    from nlx import assign, subsets
    from nlx.encoders import get_channel
    ev.Latent = ll.Latent                                   # loss / symmetric feature sets
    cfg = Config(); sample, pairs = P['sample_size'], P['pairs']
    if sample: cfg.sample_size = sample
    if pairs: cfg.pair_sample_size = pairs
    cfg.split_seeds = (42,)
    ctx = Context(cfg); ctx.nlx_knn = a.knn
    setup = ev.Setup(ctx, 0.3, P['max_train'])
    run_ctx = dict(ctx=ctx, setup=setup, ev=ev, assign=assign, subsets=subsets, get_channel=get_channel)
    execute(a, P, run_ctx, rows_path)
    summarize(a.out); summarize_xr(a.out)


def execute(a, P, R, rows_path):
    ctx, setup, ev, assign, subsets, get_channel = R['ctx'], R['setup'], R['ev'], R['assign'], R['subsets'], R['get_channel']
    from sklearn.ensemble import HistGradientBoostingClassifier
    from sklearn.metrics import roc_auc_score
    done = set(); first = True
    if os.path.exists(rows_path):
        if a.resume:
            prev = pd.read_csv(rows_path, usecols=['job']); done = set(prev['job']); first = False
        else:
            os.replace(rows_path, rows_path + '.bak')
            xp = os.path.join(os.path.dirname(rows_path), 'xr_rows.csv')
            if os.path.exists(xp): os.replace(xp, xp + '.bak')
    t0 = time.time()

    saver = Saver(a.out, scores=not a.no_save_scores, models=not a.no_save_models, latents=not a.no_save_latents)
    R['saver'] = saver
    wrote = {rows_path: not first}      # file -> already has a header
    counter = {'n': 0}

    def emit(job, rows, path=None, cols=None):
        path = path or rows_path
        for r in rows: r['job'] = job
        pd.DataFrame(add_derived(rows)).reindex(columns=cols or COLS).to_csv(path, mode='a' if wrote.get(path) else 'w', header=not wrote.get(path), index=False)
        wrote[path] = True; done.add(job)    # OUTPUT -> rows_path (all_methods_rows.csv) or xr_rows.csv
        counter['n'] += 1
        if a.summary_every and counter['n'] % a.summary_every == 0:        # OUTPUT -> the summary_* / table_* / xr_* files, refreshed while the run goes
            try: summarize(a.out, quiet=True); summarize_xr(a.out, quiet=True)
            except Exception as e: print(f'  (interim summary skipped: {e})', flush=True)

    pool = assign.uniform(a.pool_encoder)
    tree = None
    if 'tree' in a.methods:
        pp = a.polish or next((p for p in ['translate/polish/etp_equations_polish.json', '../translate/polish/etp_equations_polish.json',
                                           '../../translate/polish/etp_equations_polish.json', 'etp_equations_polish.json'] if os.path.exists(p)), None)
        if pp is None: raise SystemExit('tree edit needs etp_equations_polish.json: pass --polish translate/polish/etp_equations_polish.json')
        tree = TreeEdit(ctx, setup, pp, a.procs, cache_path=os.path.join(a.out, 'tree_distances.npz'))
    for mode in a.mode:
        for seed in a.seeds:
            split = setup.split(mode, seed); tr, te = split['tr'], split['te']
            strata = ('small-small',) if mode == 'small' else ev.STRATA
            print(f'[{time.time() - t0:.0f}s] split mode={mode} seed={seed}: {len(tr)} train pairs, {len(te)} test pairs, '
                  f'equivalent rate in test {np.mean(setup.y[te] == 0):.3f}', flush=True)
            sid = f'{mode}|{seed}'
            # twin-free check on the split actually used (the Context '[leakage]' line at start-up is about a different default split)
            tg = ctx.twin_group; test_nodes = np.zeros(len(tg), bool)
            test_nodes[np.unique(np.r_[setup.ii[te], setup.jj[te]])] = True
            train_nodes = split['train_nodes']
            shared = set(np.unique(tg[test_nodes])) & set(np.unique(tg[train_nodes]))
            shared.discard(setup.giant) if mode == 'giant' else None
            print(f'[twin-check] mode={mode} seed={seed}: twin groups on BOTH sides = {len(shared)} '
                  f'({"OK, twin-free" if not shared else "LEAK"}); test laws {int(test_nodes.sum())}, train laws {int(train_nodes.sum())}', flush=True)
            saver.split(setup, split, mode, seed)
            # ---- tree edit (n-independent) -------------------------------------------------------------
            if tree is not None:
                jobs = [f'{sid}|tree|{m}' for m in ('assess', 'gted', 'blind', 'clf')]
                if not all(j in done for j in jobs):
                    tree.need(np.union1d(tr, te))
                    for name, col in (('ASSESS', 'assess_tsed_sim'), ('GTED (alpha)', 'gted_alpha_sim'), ('variable-blind', 'gted_blind_sim')):
                        job = f'{sid}|tree|{ {"ASSESS": "assess", "GTED (alpha)": "gted", "variable-blind": "blind"}[name]}'
                        base = dict(family='tree_edit', method=name, kind='-', feat='-', n_notations=np.nan, draw=0, channels='formal operator tree', mode=mode, seed=seed)
                        emit(job, score_rows(setup, split, tree.get(tr, [col])[:, 0], tree.get(te, [col])[:, 0], base, strata, ev._block, saver, job))
                    cs = [c for c in tree.cols]
                    clf = HistGradientBoostingClassifier(max_iter=P['clf_iter'], learning_rate=0.05, class_weight='balanced', random_state=seed)
                    clf.fit(tree.get(tr, cs), setup.y[tr]); pr = clf.predict_proba(tree.get(te, cs)); pred = clf.classes_[pr.argmax(1)]
                    p_eq = pr[:, list(clf.classes_).index(0)]
                    base = dict(family='tree_edit', method='tree similarities + sizes (classifier)', kind='-', feat='-', n_notations=np.nan, draw=0, channels='formal operator tree', mode=mode, seed=seed)
                    save_classifier(saver, f'{sid}|tree|clf', base, setup, te, strata, clf, pr, pred, p_eq)
                    rows = clf_rows(ev, setup, te, strata, pred, p_eq, base)
                    emit(f'{sid}|tree|clf', rows)
            # ---- same random subsets for cosine and natural latents --------------------------------------
            rng = np.random.RandomState(seed)
            plan = []
            for n in a.ns:
                if n == 1 and not a.no_singles_all: subs = [(c,) for c in pool]
                else: subs = subsets.random_subsets(pool, n, 1 if n >= len(pool) else a.draws, rng)
                plan += [(len(s), d, s) for d, s in enumerate(subs)]
            if 'cosine' in a.methods:
                chan = {}
                for n, d, sub in plan:
                    job = f'{sid}|cosine|{n}|{d}|{"+".join(sub)}'
                    if job in done: continue
                    for c in sub:
                        if c not in chan:
                            X = get_channel(ctx, c); chan[c] = (cos_pairs(X, setup.ii[tr], setup.jj[tr]), cos_pairs(X, setup.ii[te], setup.jj[te]))
                    s_tr = np.mean([chan[c][0] for c in sub], 0); s_te = np.mean([chan[c][1] for c in sub], 0)
                    base = dict(family='cosine', method='cosine (mean over notations)', kind='-', feat='-', n_notations=n, draw=d, channels='+'.join(sub), mode=mode, seed=seed)
                    emit(job, score_rows(setup, split, s_tr, s_te, base, strata, ev._block, saver, job))
                print(f'  [{time.time() - t0:.0f}s] cosine done', flush=True)
            if 'nl' in a.methods:
                combos = [('concat', f) for f in a.concat_feats] + [('gcca', f) for f in a.gcca_feats]
                for kind, feat in combos:
                    for n, d, sub in plan:
                        job = f'{sid}|nl|{kind}|{feat}|{n}|{d}|{"+".join(sub)}'
                        if job in done: continue
                        base = dict(family='natural_latent', method=f'NL {kind} {feat}', kind=kind, feat=feat, n_notations=n, draw=d, channels='+'.join(sub), mode=mode, seed=seed)
                        rows = nl_run(a, P, R, saver, job, split, sub, kind, feat, strata, base)
                        emit(job, rows)
                    print(f'  [{time.time() - t0:.0f}s] NL {kind} {feat} done', flush=True)
            if not a.no_xr:
                run_xr(a, P, R, emit, done, mode, seed, split, strata, t0)
    print(f'all jobs done in {time.time() - t0:.0f}s -> {rows_path}', flush=True)


XCOLS = COLS + ['rep_a', 'rep_b', 'cross']


def run_xr(a, P, R, emit, done, mode, seed, split, strata, t0):
    """Cross-representation: law A read in notation u, law B read in notation v (u != v), plus the u == v diagonal."""
    ctx, setup, ev, assign = R['ctx'], R['setup'], R['ev'], R['assign']
    from nlx.encoders import channel, get_channel
    from nlx import info as I
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.ensemble import HistGradientBoostingClassifier
    xp = os.path.join(a.out, 'xr_rows.csv')                                   # OUTPUT -> <out>/xr_rows.csv
    views = [v for v in (list(ctx.texts) if a.xr_all else a.xr_views) if v in ctx.texts]
    sid = f'{mode}|{seed}'
    tr_all, te = split['tr'], split['te']
    tr = tr_all if len(tr_all) <= a.xr_train_pairs else np.random.RandomState(seed).choice(tr_all, a.xr_train_pairs, replace=False)
    ia_t, ib_t, ia_e, ib_e = setup.ii[tr], setup.jj[tr], setup.ii[te], setup.jj[te]
    def emit_scores(method, u, v, s_tr, s_te):
        job = f'{sid}|xr|{method}|{u}|{v}'
        if job in done: return
        base = dict(family='cross_representation', method=method, kind='-', feat='-', n_notations=2 if u != v else 1, draw=0, channels=f'A:{u} | B:{v}',
                    mode=mode, seed=seed, rep_a=u, rep_b=v, cross=(u != v))
        sub = dict(split, tr=tr)
        emit(job, score_rows(setup, sub, s_tr, s_te, base, strata, ev._block, R['saver'], job), xp, XCOLS)
    # ---- (1) cosine in one shared TF-IDF space ---------------------------------------------------------------
    pooled = [t for v in views for t in ctx.texts[v]]
    vec = TfidfVectorizer(analyzer='char', ngram_range=(2, 4), sublinear_tf=True, max_features=ctx.cfg.max_features).fit(pooled)    # label-free
    M = {v: vec.transform(ctx.texts[v]) for v in views}
    sp_cos = lambda U, V, ia, ib: np.asarray(U[ia].multiply(V[ib]).sum(1)).ravel()          # rows are L2-normalised by the vectoriser
    for u in views:
        for v in views:
            emit_scores('xr_cosine (shared TF-IDF)', u, v, sp_cos(M[u], M[v], ia_t, ib_t), sp_cos(M[u], M[v], ia_e, ib_e))
    print(f'  [{time.time() - t0:.0f}s] xr cosine (shared TF-IDF) done', flush=True)
    # ---- (2) shared GCCA latent: cosine, losses, optional classifier -------------------------------------------
    from pipeline.utils import gcca_plus as gp, semantic_latents as sl
    chans = [channel(v, a.pool_encoder) for v in views]
    Xc = {c: get_channel(ctx, c) for c in chans}
    train_idx = np.nonzero(split['train_nodes'])[0]
    fold = sl.fold_ids(ctx.twin_group, setup.giant, 5, seed)
    m = gp.fit_gcca_plus(Xc, train_idx, fold, k=min(a.k, 64 * len(Xc)), d_white=64, crossfit=True)
    Z = {v: np.asarray(m['P'][c], np.float64) for v, c in zip(views, chans)}                 # every notation's latent, in the SAME space
    stats = {v: I.LatentStats(Z[v], train_idx, a.knn) for v in views}
    if R['saver'].latents_on:                                                                  # OUTPUT -> <out>/latents/xr_gcca_<mode>_<seed>.npz
        np.savez_compressed(os.path.join(a.out, 'latents', f'xr_gcca_{mode}_{seed}.npz'), **{v: Z[v].astype(np.float32) for v in views})
    nrm = lambda X: X / (np.linalg.norm(X, axis=1, keepdims=True) + 1e-9)
    Zn = {v: nrm(Z[v]) for v in views}
    for u in views:
        for v in views:
            emit_scores('xr_gcca_cosine', u, v, (Zn[u][ia_t] * Zn[v][ib_t]).sum(1), (Zn[u][ia_e] * Zn[v][ib_e]).sum(1))
            if all(f'{sid}|xr|xr_gcca_{l}|{u}|{v}' in done for l in I.LOSSES): continue
            sc = {}
            for tag, ia, ib in (('tr', ia_t, ib_t), ('te', ia_e, ib_e)):
                ab = I.pair_losses(stats[u], stats[v], ia, ib); ba = I.pair_losses(stats[v], stats[u], ib, ia)    # A through u -> B through v, and back
                for l in I.LOSSES: sc[(l, tag)] = I.equiv_score(l, ab[l], ba[l])
            for l in I.LOSSES:
                emit_scores(f'xr_gcca_{l}', u, v, sc[(l, 'tr')], sc[(l, 'te')])
    print(f'  [{time.time() - t0:.0f}s] xr GCCA cosine + losses done', flush=True)
    if a.xr_clf:
        for u in views:
            for v in views:
                job = f'{sid}|xr|xr_gcca_clf|{u}|{v}'
                if job in done: continue
                feat = lambda ia, ib: np.hstack([Z[u][ia], Z[v][ib], Z[u][ia] - Z[v][ib], (Zn[u][ia] * Zn[v][ib]).sum(1, keepdims=True), np.linalg.norm(Z[u][ia] - Z[v][ib], axis=1, keepdims=True)])
                clf = HistGradientBoostingClassifier(max_iter=P['clf_iter'], learning_rate=0.05, class_weight='balanced', random_state=seed).fit(feat(ia_t, ib_t), setup.y[tr])
                pr = clf.predict_proba(feat(ia_e, ib_e)); pred = clf.classes_[pr.argmax(1)]; p_eq = pr[:, list(clf.classes_).index(0)]
                base = dict(family='cross_representation', method='xr_gcca_clf', kind='gcca', feat='z', n_notations=2 if u != v else 1, draw=0, channels=f'A:{u} | B:{v}',
                            mode=mode, seed=seed, rep_a=u, rep_b=v, cross=(u != v))
                save_classifier(R['saver'], job, {k: base[k] for k in base if k not in ('rep_a', 'rep_b', 'cross')}, setup, te, strata, clf, pr, pred, p_eq)
                rows = clf_rows(ev, setup, te, strata, pred, p_eq, base)
                emit(job, rows, xp, XCOLS)
        print(f'  [{time.time() - t0:.0f}s] xr GCCA classifier done', flush=True)


# ------------------------------------------------------------------------------------------------ tables
def summarize(out, quiet=False):
    d = pd.read_csv(os.path.join(out, 'all_methods_rows.csv'))
    d = d[((d['mode'] == 'small') & (d.stratum == 'small-small')) | ((d['mode'] == 'giant') & (d.stratum == 'all'))]
    m = ['AUC_equiv_vs_rest', 'recall_at_10pct_FPR', 'derived_precision_at_10pct_FPR', 'equiv_precision', 'equiv_recall', 'equiv_F1', 'test_equiv_rate']
    m = [c for c in m if c in d]
    d['n_key'] = d.n_notations.fillna(0).astype(int)
    G = d.groupby(['family', 'method', 'n_key'])
    S = G[m].agg(['mean', 'std']); S.columns = ['_'.join(c) for c in S.columns]; S['runs'] = G.size()
    S.reset_index().to_csv(os.path.join(out, 'summary_by_method_and_n.csv'), index=False)    # OUTPUT -> <out>/summary_by_method_and_n.csv
    S = S.reset_index()
    tex = []
    ns = sorted(n for n in S.n_key.unique() if n > 0)
    for metric, label in (('AUC_equiv_vs_rest', 'AUC'), ('recall_at_10pct_FPR', 'Recall at 10\\% false-positive rate'), ('derived_precision_at_10pct_FPR', 'Precision at that point (derived)')):
        if metric + '_mean' not in S: continue
        W = S[S.n_key > 0].pivot_table(index='method', columns='n_key', values=metric + '_mean')[ns]
        W.round(3).to_csv(os.path.join(out, f'table_{label.split()[0].lower()}_by_n.csv'))    # OUTPUT -> <out>/table_auc|recall|precision_by_n.csv
        W.columns.name = None; W.columns = [f'$n{{=}}{c}$' for c in W.columns]; W = W.reset_index().rename(columns={'method': 'Method'})
        body = W.to_latex(index=False, na_rep='--', escape=False, float_format='%.3f', column_format='l' + 'c' * len(ns))
        tex.append(f'\\begin{{table*}}[t]\n\\centering\\scriptsize\\setlength{{\\tabcolsep}}{{3pt}}\n{body}\\caption{{{label}, by number of notations $n$. Mean over seeds and random subsets of $n$ notations ($n=1$: every single notation; $n=19$: all). All methods share the same twin-free train and test pairs.}}\n\\end{{table*}}\n')
    base = S[S.n_key == 0]
    if len(base):
        base[['method'] + [c for c in base.columns if c.endswith('_mean')]].round(3).to_csv(os.path.join(out, 'table_tree_edit.csv'), index=False)
    with open(os.path.join(out, 'tables.tex'), 'w') as f: f.write('\n'.join(tex))    # OUTPUT -> <out>/tables.tex
    if quiet: return
    print(f'summary written to {out}/ (summary_by_method_and_n.csv, table_*_by_n.csv, tables.tex)')
    best = S[S.n_key > 0].sort_values('recall_at_10pct_FPR_mean', ascending=False).head(8)[['method', 'n_key', 'AUC_equiv_vs_rest_mean', 'recall_at_10pct_FPR_mean', 'runs']]
    print('top 8 settings by recall at 10% FPR:'); print(best.round(3).to_string(index=False))


def summarize_xr(out, quiet=False):
    p = os.path.join(out, 'xr_rows.csv')
    if not os.path.exists(p): return
    d = pd.read_csv(p)
    d = d[((d['mode'] == 'small') & (d.stratum == 'small-small')) | ((d['mode'] == 'giant') & (d.stratum == 'all'))]
    import matplotlib; matplotlib.use('Agg'); import matplotlib.pyplot as plt
    rows = []
    for meth, g in d.groupby('method'):
        for metric, tag in (('AUC_equiv_vs_rest', 'AUC'), ('recall_at_10pct_FPR', 'recall10')):
            W = g.pivot_table(index='rep_a', columns='rep_b', values=metric, aggfunc='mean')
            safe = ''.join(ch if ch.isalnum() else '_' for ch in meth)
            W.round(3).to_csv(os.path.join(out, f'xr_matrix_{safe}_{tag}.csv'))               # OUTPUT -> <out>/xr_matrix_<method>_<AUC|recall10>.csv
            fig, ax = plt.subplots(figsize=(1.0 + 0.55 * len(W.columns), 0.8 + 0.5 * len(W.index)))
            im = ax.imshow(W.values.astype(float), cmap='viridis'); ax.set_xticks(range(len(W.columns))); ax.set_xticklabels(W.columns, rotation=60, ha='right', fontsize=7)
            ax.set_yticks(range(len(W.index))); ax.set_yticklabels(W.index, fontsize=7); ax.set_xlabel('notation of law B'); ax.set_ylabel('notation of law A')
            ax.set_title(f'{meth}: {tag}', fontsize=8); fig.colorbar(im, ax=ax, shrink=0.8); fig.tight_layout()
            fig.savefig(os.path.join(out, f'xr_matrix_{safe}_{tag}.png'), dpi=150); plt.close(fig)       # OUTPUT -> <out>/xr_matrix_<method>_<tag>.png
        same, cross = g[~g.cross], g[g.cross]
        rows.append(dict(method=meth, same_AUC=same.AUC_equiv_vs_rest.mean(), cross_AUC=cross.AUC_equiv_vs_rest.mean(), same_recall10=same.recall_at_10pct_FPR.mean(),
                         cross_recall10=cross.recall_at_10pct_FPR.mean(), best_cross_pair=(f"{cross.loc[cross.AUC_equiv_vs_rest.idxmax(), 'rep_a']} -> {cross.loc[cross.AUC_equiv_vs_rest.idxmax(), 'rep_b']}" if len(cross) else ''),
                         best_cross_AUC=cross.AUC_equiv_vs_rest.max(), runs=len(g)))
    S = pd.DataFrame(rows); S.round(3).to_csv(os.path.join(out, 'xr_summary.csv'), index=False)           # OUTPUT -> <out>/xr_summary.csv
    T = S.rename(columns={'method': 'Method', 'same_AUC': 'AUC same', 'cross_AUC': 'AUC cross', 'same_recall10': 'R@10 same', 'cross_recall10': 'R@10 cross'})[['Method', 'AUC same', 'AUC cross', 'R@10 same', 'R@10 cross']]
    T['Method'] = T['Method'].str.replace('_', '\\_', regex=False)
    with open(os.path.join(out, 'xr_tables.tex'), 'w') as f:                                            # OUTPUT -> <out>/xr_tables.tex
        f.write('\\begin{table}[t]\\centering\\small\n' + T.to_latex(index=False, escape=False, float_format='%.3f', column_format='lcccc') +
                '\\caption{Cross-representation: law A in one notation, law B in another. "same" is the diagonal (both laws in the same notation), "cross" the off-diagonal mean; AUC and recall at 10\\% false positives, equivalent vs.\\ rest, twin-free small--small pairs.}\n\\end{table}\n')
    if quiet: return
    print(f'cross-representation summary written to {out}/ (xr_summary.csv, xr_matrix_*.csv|png, xr_tables.tex)')
    print(S.round(3).to_string(index=False))


if __name__ == '__main__':
    main()