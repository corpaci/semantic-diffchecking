#!/usr/bin/env python
"""ASSESS (TSED) and GTED tree-edit similarities for ETP law pairs, with precision / recall / F1 logging.

  python3 tree_metrics.py --polish translate/polish/etp_equations_polish.json --pairs oracle_balanced_100k.csv --out tree_out

Labels: 'equal' and 'equivalent' are ONE class (equivalent); 'unknown' pairs are dropped.  Everything is reported as
equivalent-vs-rest (stronger, weaker, incomparable together) and as 4-class (equivalent / stronger / weaker / incomparable).

TREES   formal law -> operator tree from its Polish form.  '=' is the root, '◇' nodes are operators, variables are leaves.
METRICS (both: sim = 1 - d / max(|T1|, |T2|), unit costs for insert / delete / relabel, Zhang-Shasha exact tree edit distance)
  assess_tsed   ASSESS (2509.22246): operator labels get a <SLOT> suffix; variable NAMES are kept, so renaming costs 1 per leaf.
  gted_alpha    GTED  (2507.07399): same distance plus the alpha-conversion generalised operation: variables are renamed to
                x0, x1, ... in order of first appearance before comparing, so consistent renaming is free.
                (GTED's paper implements only alpha-conversion; commutativity / equivalence rules are NOT implemented there
                 and not here either, so x*y vs y*x are penalised.)
  gted_blind    ablation: variable leaves are interchangeable (relabel cost 0); only the shape counts.
CRITERIA (what turns a distance into a decision; every one logged with precision / recall / F1)
  threshold  predict 'equivalent' when sim > theta.  theta = the value that maximises equivalent-F1 on TRAIN pairs (ASSESS picks
             the F/Kappa-maximising theta the same way).  Test precision / recall / F1 at that theta.
  fpr10      theta = the 90th percentile of the sim of non-equivalent TRAIN pairs (10% false-positive budget); test P / R / F1.
  hgb        a 4-class gradient-boosted classifier on [sim, d, |T1|, |T2|, size gap, variable counts] (all three metrics together),
             giving 4-class P / R / F1 and a probability for equivalent.
Splits hold out whole laws (a test pair has both laws unseen in training).  Pass --twin-file node,group to hold out twin groups too.
"""
import argparse, json, os, sys, time
from functools import lru_cache
import numpy as np, pandas as pd
from multiprocessing import Pool

# ----------------------------------------------------------------------------------------------- trees
class N:
    __slots__ = ('label', 'kids')
    def __init__(self, label, kids=()):
        self.label, self.kids = label, list(kids)

def parse_polish(s):
    toks = s.split(); pos = 0
    def term():
        nonlocal pos
        t = toks[pos]; pos += 1
        if t in ('◇', '='):
            a = term(); b = term(); return N(t, [a, b])
        return N(t)
    t = term()
    assert pos == len(toks), s
    return t

def relabel(t, fn):
    return N(fn(t), [relabel(k, fn) for k in t.kids])

def leaves_in_order(t, out=None):
    out = [] if out is None else out
    if not t.kids: out.append(t.label)
    for k in t.kids: leaves_in_order(k, out)
    return out

def size(t): return 1 + sum(size(k) for k in t.kids)

def assess_tree(t):   # operator nodes get <SLOT>; variable names kept
    return relabel(t, lambda n: n.label + '<SLOT>' if n.kids else n.label)

def alpha_tree(t):    # GTED alpha-conversion: variables numbered by first appearance
    seen = {}
    for v in leaves_in_order(t): seen.setdefault(v, f'v{len(seen)}')
    return relabel(assess_tree(t), lambda n: n.label if n.kids else seen[n.label])

def blind_tree(t):    # variable leaves interchangeable
    return relabel(assess_tree(t), lambda n: 'VAR' if not n.kids else n.label)

# ----------------------------------------------------------------------------------------------- Zhang-Shasha (unit costs)
def _prep(t):
    labels, lml, keyroots = [], [], []
    def walk(n):                       # post-order; returns index of leftmost leaf of n's subtree
        first = None
        for k in n.kids:
            l = walk(k)
            if first is None: first = l
        labels.append(n.label)
        i = len(labels) - 1
        lml.append(i if first is None else first)
        return lml[i]
    walk(t)
    seen = set()
    for i in range(len(labels) - 1, -1, -1):
        if lml[i] not in seen: seen.add(lml[i]); keyroots.append(i)
    return labels, lml, sorted(keyroots)

def ted(t1, t2):
    a, la, ka = _prep(t1); b, lb, kb = _prep(t2)
    n, m = len(a), len(b)
    TD = np.zeros((n, m), dtype=np.int32)
    for i in ka:
        for j in kb:
            li, lj = la[i], lb[j]
            rows, cols = i - li + 2, j - lj + 2
            fd = np.zeros((rows, cols), dtype=np.int32)
            fd[1:, 0] = np.arange(1, rows); fd[0, 1:] = np.arange(1, cols)
            for x in range(1, rows):
                for y in range(1, cols):
                    ii, jj = li + x - 1, lj + y - 1
                    if la[ii] == li and lb[jj] == lj:
                        c = 0 if a[ii] == b[jj] else 1
                        fd[x, y] = min(fd[x - 1, y] + 1, fd[x, y - 1] + 1, fd[x - 1, y - 1] + c)
                        TD[ii, jj] = fd[x, y]
                    else:
                        p, q = la[ii] - li, lb[jj] - lj
                        fd[x, y] = min(fd[x - 1, y] + 1, fd[x, y - 1] + 1, fd[p, q] + TD[ii, jj])
    return int(TD[n - 1, m - 1])

# ----------------------------------------------------------------------------------------------- per-pair distances
TREES = {}
def _init(trees): TREES.update(trees)

def pair_row(ab):
    a, b = ab
    ta, tb = TREES[a], TREES[b]
    r = {}
    for name, f in (('assess_tsed', 'assess'), ('gted_alpha', 'alpha'), ('gted_blind', 'blind')):
        x, y = ta[f], tb[f]
        d = ted(x, y); mx = max(size(x), size(y))
        r[name + '_d'] = d; r[name + '_sim'] = 1 - d / mx
    r['size_a'], r['size_b'] = size(ta['assess']), size(tb['assess'])
    r['nvar_a'], r['nvar_b'] = len(set(leaves_in_order(ta['raw']))), len(set(leaves_in_order(tb['raw'])))
    return r

# ----------------------------------------------------------------------------------------------- evaluation
LAB = ['equivalent', 'stronger', 'weaker', 'incomparable']

def prf(y_true_pos, y_pred_pos):
    tp = int((y_true_pos & y_pred_pos).sum()); fp = int((~y_true_pos & y_pred_pos).sum()); fn = int((y_true_pos & ~y_pred_pos).sum())
    P = tp / (tp + fp) if tp + fp else float('nan'); R = tp / (tp + fn) if tp + fn else float('nan')
    F = 2 * P * R / (P + R) if P == P and R == R and P + R > 0 else float('nan')
    return P, R, F

def best_f1_threshold(sim, pos):
    best, th = -1, 0.5
    for t in np.unique(np.quantile(sim, np.linspace(0.01, 0.99, 197))):
        _, _, f = prf(pos, sim > t)
        if f == f and f > best: best, th = f, t
    return th

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--polish', required=True); ap.add_argument('--pairs', required=True)
    ap.add_argument('--out', default='tree_out'); ap.add_argument('--n-pairs', type=int, default=60000)
    ap.add_argument('--seeds', type=int, nargs='+', default=[0, 1, 2]); ap.add_argument('--test-frac', type=float, default=0.3)
    ap.add_argument('--twin-file', help='csv with columns node,group to hold out twin groups'); ap.add_argument('--procs', type=int, default=os.cpu_count())
    ap.add_argument('--no-hgb', action='store_true'); ap.add_argument('--mode', nargs='+', choices=['small', 'random'], default=['small', 'random'], help='small: giant-class laws are train-only, test pairs are small-small; random: plain held-out laws'); ap.add_argument('--reuse', action='store_true', help='reuse out/pair_distances.csv')
    a = ap.parse_args(); os.makedirs(a.out, exist_ok=True)
    eq = {e['node']: e for e in json.load(open(a.polish))['equations']}
    trees = {}
    for k, e in eq.items():
        raw = parse_polish(e['polish'])
        trees[k] = dict(raw=raw, assess=assess_tree(raw), alpha=alpha_tree(raw), blind=blind_tree(raw))
    df = pd.read_csv(a.pairs)
    df['relation'] = df['relation'].replace({'equal': 'equivalent'})
    df = df[df.relation.isin(LAB) & df.node_a.isin(eq) & df.node_b.isin(eq)].reset_index(drop=True)
    if len(df) > a.n_pairs: df = df.sample(a.n_pairs, random_state=0).reset_index(drop=True)
    print(f'{len(df)} pairs; equivalent share {(df.relation == "equivalent").mean():.3f}', flush=True)
    t0 = time.time(); pdp = os.path.join(a.out, 'pair_distances.csv')
    if a.reuse and os.path.exists(pdp):
        D = pd.read_csv(pdp)
    else:
        with Pool(a.procs, initializer=_init, initargs=(trees,)) as p:
            R = p.map(pair_row, list(zip(df.node_a, df.node_b)), chunksize=500)
        D = pd.concat([df, pd.DataFrame(R)], axis=1)
        D.to_csv(pdp, index=False)
    print(f'distances done in {time.time() - t0:.0f}s -> pair_distances.csv', flush=True)

    group = dict(zip(*pd.read_csv(a.twin_file)[['node', 'group']].values.T)) if a.twin_file else {}
    nodes = np.array(sorted(set(D.node_a) | set(D.node_b)))
    par = {n: n for n in nodes}
    def find(x):
        while par[x] != x: par[x] = par[par[x]]; x = par[x]
        return x
    for x, y in D[D.relation == 'equivalent'][['node_a', 'node_b']].values: par[find(x)] = find(y)
    roots = pd.Series({n: find(n) for n in nodes}); vc = roots.value_counts()
    giant_nodes = set(roots[roots == vc.index[0]].index) if vc.iloc[0] > 200 else set()
    print(f'giant class: {len(giant_nodes)} laws', flush=True)
    rows = []
    for mode, seed in [(m, sd) for m in a.mode for sd in a.seeds]:
        rng = np.random.RandomState(seed)
        keys = np.array([group.get(n, n) for n in nodes]); ug = np.unique(keys); rng.shuffle(ug)
        if mode == 'small':
            gk = {group.get(n, n) for n in giant_nodes}; ug = np.array([k for k in ug if k not in gk])
        frac = a.test_frac if mode == 'random' else a.test_frac * len(nodes) / len(ug)
        held = set(ug[:int(len(ug) * min(frac, 0.9))]); test_nodes = {n for n, k in zip(nodes, keys) if k in held}
        in_te = D.node_a.isin(test_nodes) & D.node_b.isin(test_nodes)
        in_tr = ~D.node_a.isin(test_nodes) & ~D.node_b.isin(test_nodes)
        tr, te = D[in_tr], D[in_te]
        ytr, yte = (tr.relation == 'equivalent').values, (te.relation == 'equivalent').values
        for m in ('assess_tsed', 'gted_alpha', 'gted_blind'):
            s_tr, s_te = tr[m + '_sim'].values, te[m + '_sim'].values
            from sklearn.metrics import roc_auc_score
            auc = roc_auc_score(yte, s_te)
            th = best_f1_threshold(s_tr, ytr)
            th10 = np.quantile(s_tr[~ytr], 0.90)
            for crit, t in (('threshold(max-F1 on train)', th), ('fpr10', th10)):
                P, Rc, F = prf(yte, s_te > t)
                rows.append(dict(mode=mode, seed=seed, test_equiv_rate=float(yte.mean()), metric=m, criterion=crit, theta=round(float(t), 4), task='equiv-vs-rest', precision=P, recall=Rc, F1=F, AUC=auc, n_test=len(te), n_equiv_test=int(yte.sum())))
        if not a.no_hgb:
            from sklearn.ensemble import HistGradientBoostingClassifier
            cols = [c for c in D.columns if c.endswith('_sim') or c.endswith('_d')] + ['size_a', 'size_b', 'nvar_a', 'nvar_b']
            for name, cs in (('assess_tsed', [c for c in cols if c.startswith('assess')] + cols[-4:]),
                             ('gted_alpha', [c for c in cols if c.startswith('gted_alpha')] + cols[-4:]),
                             ('all_three', cols)):
                clf = HistGradientBoostingClassifier(max_iter=150, learning_rate=0.05, class_weight='balanced', random_state=seed)
                clf.fit(tr[cs], tr.relation.map(LAB.index)); pr = clf.predict_proba(te[cs]); pred = clf.classes_[pr.argmax(1)]
                ytrue = te.relation.map(LAB.index).values
                P, Rc, F = prf(yte, pred == 0)
                rows.append(dict(mode=mode, seed=seed, test_equiv_rate=float(yte.mean()), metric=name, criterion='hgb', theta=np.nan, task='equiv-vs-rest', precision=P, recall=Rc, F1=F, AUC=roc_auc_score(yte, pr[:, list(clf.classes_).index(0)]), n_test=len(te), n_equiv_test=int(yte.sum())))
                for c in range(4):
                    P, Rc, F = prf(ytrue == c, pred == c)
                    rows.append(dict(mode=mode, seed=seed, test_equiv_rate=float(yte.mean()), metric=name, criterion='hgb', theta=np.nan, task=f'4class:{LAB[c]}', precision=P, recall=Rc, F1=F, AUC=np.nan, n_test=len(te), n_equiv_test=int(yte.sum())))
    R = pd.DataFrame(rows); R.to_csv(os.path.join(a.out, 'tree_metrics_rows.csv'), index=False)
    S = R.groupby(['task', 'mode', 'metric', 'criterion'])[['test_equiv_rate', 'theta', 'precision', 'recall', 'F1', 'AUC']].mean().round(3)
    S.to_csv(os.path.join(a.out, 'tree_metrics_summary.csv'))
    print(S.loc['equiv-vs-rest'].to_string())
    print(f'\nsaved to {a.out}/  (pair_distances.csv, tree_metrics_rows.csv, tree_metrics_summary.csv)')

if __name__ == '__main__':
    main()
