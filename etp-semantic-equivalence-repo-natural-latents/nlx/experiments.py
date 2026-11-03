"""The six experiments.  Every one writes <out>/<name>_rows.csv (one row per fit x stratum) and a summary + figure."""
import os, time
import numpy as np, pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from pipeline.utils.data import ALL_VIEWS
from . import assign, subsets, info as I
from pipeline.utils import gcca_plus as gp, semantic_latents as sl
from sklearn.decomposition import PCA
from sklearn.ensemble import HistGradientBoostingClassifier
from .evaluate import _block, STRATA
from .encoders import get_channel
from .encoders import ENCODERS, applies, channel, split_channel
from .evaluate import evaluate, LABELS

REP8 = ['formal', 'lean', 'latex', 'py_lambda', 'ssa', 'json_ast', 'natural_language', 'word_problem']
KEYS = lambda df: [k for k in KEY if k in df.columns]
KEY = ['AUC_equiv_vs_rest', 'recall_at_10pct_FPR', 'equiv_F1', 'equiv_precision', 'equiv_recall', 'balanced_acc']


class Runner:
    def __init__(self, ctx, setup, args):
        self.ctx, self.setup, self.a = ctx, setup, args
        self.t0 = time.time()
        self.cm = []

    def splits(self):
        for mode in self.a.mode:
            for seed in self.a.seeds:
                yield self.setup.split(mode, seed)

    def fit(self, split, channels, tag, **kw):
        a = self.a
        rows, cms = evaluate(self.ctx, self.setup, split, channels, kind=kw.get('kind', a.kind), feat=kw.get('feat', a.feat),
                             k=a.k, eval=kw.get('eval', a.eval), clf_iter=a.clf_iter, want_cm=a.confusions)
        for r in rows:
            r.update(tag, mode=split['mode'], seed=split['seed'], channels='+'.join(channels), n_channels=len(channels),
                     kind=kw.get('kind', a.kind), feat=kw.get('feat', a.feat))
        for st, cm in cms:
            for i in range(4):
                for j in range(4):
                    self.cm.append(dict(tag, mode=split['mode'], seed=split['seed'], stratum=st, true=LABELS[i], pred=LABELS[j], count=int(cm[i, j])))
        return rows

    def save(self, name, rows):
        os.makedirs(self.a.out, exist_ok=True)
        df = pd.DataFrame(rows)
        df.to_csv(os.path.join(self.a.out, f'{name}_rows.csv'), index=False)
        if self.cm:
            pd.DataFrame(self.cm).to_csv(os.path.join(self.a.out, f'{name}_confusions.csv'), index=False)
            self.cm = []
        print(f'  [{time.time() - self.t0:.0f}s] saved {name}_rows.csv ({len(df)} rows)', flush=True)
        return df

    def main_stratum(self, df):
        """small-small (the hard, twin-free pairs) for mode 'small'; 'all' for mode 'giant'."""
        return df[((df['mode'] == 'small') & (df.stratum == 'small-small')) | ((df['mode'] == 'giant') & (df.stratum == 'all'))]

    # ------------------------------------------------------------------ 1. which encoder for which notation
    def encoders(self):
        print('[1] encoders: every notation x every encoder, one channel at a time', flush=True)
        rows = []
        cand = self.a.encoders or [e for e in ENCODERS if not e.startswith('st:')]
        for sp in self.splits():
            for v in ALL_VIEWS:
                for e in cand:
                    if applies(e, v):
                        rows += self.fit(sp, [channel(v, e)], dict(exp='encoders', view=v, encoder=e))
        df = self.save('encoders', rows)
        d = self.main_stratum(df)
        T = d.groupby(['view', 'encoder'])[self.a.metric].mean().unstack().reindex(ALL_VIEWS)
        T.to_csv(os.path.join(self.a.out, 'encoders_by_view.csv'))
        print(T.round(3).to_string())
        fig, ax = plt.subplots(figsize=(1.1 * T.shape[1] + 3, 0.35 * len(T) + 1.5))
        im = ax.imshow(T.values.astype(float), cmap='viridis', aspect='auto')
        ax.set_xticks(range(T.shape[1])); ax.set_xticklabels(T.columns, rotation=30, ha='right')
        ax.set_yticks(range(len(T))); ax.set_yticklabels(T.index)
        for i in range(T.shape[0]):
            for j in range(T.shape[1]):
                if T.values[i, j] == T.values[i, j]:
                    ax.text(j, i, f'{T.values[i, j]:.2f}', ha='center', va='center', fontsize=7, color='w')
        ax.set_title(f'{self.a.metric}: one notation, one encoder'); fig.colorbar(im); fig.tight_layout()
        fig.savefig(os.path.join(self.a.out, 'encoders_by_view.png'), dpi=150); plt.close(fig)

    # ------------------------------------------------------------------ 2. encoder assignment presets over all notations
    def assign(self):
        print('[2] assign: rules for choosing an encoder per notation (all notations together)', flush=True)
        rows = []
        for sp in self.splits():
            presets = {'all_repr': assign.uniform('tfidf_repr'), 'all_generic': assign.uniform('tfidf_generic'),
                       'all_word': assign.uniform('tfidf_word'), 'all_lsa': assign.uniform('lsa64'),
                       'by_group': assign.by_group(), 'by_group_plus_formal': assign.by_group(extras=True)}
            ch, table = assign.best_per_view(self.ctx, self.setup, sp, seed=sp['seed'])
            presets['learned_best_per_view'] = ch
            pd.DataFrame([dict(view=v, encoder=e, auc=a) for (v, e), a in table.items()]).to_csv(
                os.path.join(self.a.out, f'assign_learned_choice_{sp["mode"]}_{sp["seed"]}.csv'), index=False) if os.makedirs(self.a.out, exist_ok=True) is None else None
            for name, chs in presets.items():
                rows += self.fit(sp, chs, dict(exp='assign', preset=name))
        df = self.save('assign', rows)
        S = self.main_stratum(df).groupby('preset')[KEYS(df)].mean().sort_values(self.a.metric, ascending=False)
        S.to_csv(os.path.join(self.a.out, 'assign_summary.csv')); print(S.round(3).to_string())

    # ------------------------------------------------------------------ 3. how many notations: n = 1, 2, 3 ... all
    def nviews(self):
        print('[3] nviews: random subsets of n notations', flush=True)
        pool = assign.uniform(self.a.pool_encoder) if not self.a.pool else [channel(v, self.a.pool_encoder) for v in self.a.pool]
        rows = []
        for sp in self.splits():
            rng = np.random.RandomState(sp['seed'])
            for n in self.a.ns:
                for d, sub in enumerate(subsets.random_subsets(pool, n, 1 if n >= len(pool) else self.a.draws, rng)):
                    for kind in self.a.kinds:
                        rows += self.fit(sp, sub, dict(exp='nviews', n=len(sub), draw=d), kind=kind)
        df = self.save('nviews', rows)
        d = self.main_stratum(df)
        S = d.groupby(['kind', 'n'])[KEYS(d)].agg(['mean', 'std'])
        S.to_csv(os.path.join(self.a.out, 'nviews_summary.csv')); print(d.groupby(['kind', 'n'])[KEYS(d)].mean().round(3).to_string())
        fig, axs = plt.subplots(1, 2, figsize=(10, 3.6))
        for ax, m in zip(axs, ['AUC_equiv_vs_rest', 'equiv_F1' if 'equiv_F1' in d.columns else 'recall_at_10pct_FPR']):
            for kind, g in d.groupby('kind'):
                s = g.groupby('n')[m].agg(['mean', 'min', 'max'])
                ax.plot(s.index, s['mean'], marker='o', label=kind); ax.fill_between(s.index, s['min'], s['max'], alpha=.15)
            ax.set_xlabel('number of notations'); ax.set_ylabel(m); ax.legend(); ax.grid(alpha=.3)
        fig.suptitle('Equivalents vs number of notations (band = min..max over random subsets and seeds)'); fig.tight_layout()
        fig.savefig(os.path.join(self.a.out, 'nviews_curve.png'), dpi=150); plt.close(fig)

    # ------------------------------------------------------------------ 4. all pairs / sampled triples of a small pool
    def pairs(self):
        print('[4] pairs: every pair and sampled triples among', self.a.pool or REP8, flush=True)
        pool = [channel(v, self.a.pool_encoder) for v in (self.a.pool or REP8)]
        rows = []
        for sp in self.splits():
            rng = np.random.RandomState(sp['seed'])
            for s in [(c,) for c in pool] + subsets.all_pairs(pool) + subsets.sample_triples(pool, self.a.triples, rng):
                rows += self.fit(sp, list(s), dict(exp='pairs', n=len(s)))
        df = self.save('pairs', rows)
        d = self.main_stratum(df)
        m = self.a.metric
        sc = d.groupby('channels')[m].mean()
        single = {c: sc.get(c, np.nan) for c in pool}
        M = pd.DataFrame(np.nan, index=pool, columns=pool)
        G = pd.DataFrame(np.nan, index=pool, columns=pool)
        for (x, y) in subsets.all_pairs(pool):
            v = sc.get(f'{x}+{y}', np.nan)
            M.loc[x, y] = M.loc[y, x] = v
            G.loc[x, y] = G.loc[y, x] = v - max(single[x], single[y])
        for c in pool:
            M.loc[c, c] = single[c]
        short = lambda i: [x.split(':')[0] for x in i]
        M.index, M.columns, G.index, G.columns = short(M.index), short(M.columns), short(G.index), short(G.columns)
        M.to_csv(os.path.join(self.a.out, 'pairs_matrix.csv')); G.to_csv(os.path.join(self.a.out, 'pairs_gain_over_best_single.csv'))
        print(M.round(3).to_string()); print('gain over the better single notation:'); print(G.round(3).to_string())
        fig, axs = plt.subplots(1, 2, figsize=(11, 4.4))
        for ax, T, t, cm in ((axs[0], M, m + ' (diagonal = single notation)', 'viridis'), (axs[1], G, 'gain of the pair over its better member', 'RdBu')):
            v = T.values.astype(float)
            im = ax.imshow(v, cmap=cm, vmin=(-np.nanmax(abs(v)) if cm == 'RdBu' else None), vmax=(np.nanmax(abs(v)) if cm == 'RdBu' else None))
            ax.set_xticks(range(len(T))); ax.set_xticklabels(T.columns, rotation=45, ha='right', fontsize=8)
            ax.set_yticks(range(len(T))); ax.set_yticklabels(T.index, fontsize=8); ax.set_title(t, fontsize=9); fig.colorbar(im, ax=ax)
        fig.tight_layout(); fig.savefig(os.path.join(self.a.out, 'pairs_matrix.png'), dpi=150); plt.close(fig)

    # ------------------------------------------------------------------ 5. groups of notations
    def groups(self):
        print('[5] groups: notation groups alone and together', flush=True)
        enc = self.a.pool_encoder
        G = {g: [channel(v, enc) for v in vs] for g, vs in assign.GROUPS.items() if vs}
        rows = []
        for sp in self.splits():
            for name, chs in subsets.group_combos(G, self.a.max_groups):
                rows += self.fit(sp, list(chs), dict(exp='groups', combo=name))
        df = self.save('groups', rows)
        S = self.main_stratum(df).groupby('combo')[KEYS(df)].mean().sort_values(self.a.metric, ascending=False)
        S.to_csv(os.path.join(self.a.out, 'groups_summary.csv')); print(S.round(3).to_string())

    # ------------------------------------------------------------------ 6. greedy forward selection
    def greedy(self):
        print('[6] greedy: add the notation that helps most on a validation split, up to n =', self.a.n_max, flush=True)
        pool = [channel(v, self.a.pool_encoder) for v in (self.a.pool or ALL_VIEWS)]
        rows = []
        for sp in self.splits():
            inner = self.setup.inner(sp)

            def score(sub):
                r, _ = evaluate(self.ctx, self.setup, inner, list(sub), kind=self.a.kind, feat='z', k=self.a.k, eval='cheap')
                r = [x for x in r if x['stratum'] == 'small-small'] or r
                return r[0].get('AUC_equiv_vs_rest', 0.0)
            trace = subsets.greedy_forward(pool, score, self.a.n_max)
            for n, sub, vs in trace:
                for r in self.fit(sp, list(sub), dict(exp='greedy', n=n, val_score=vs, last_added=sub[-1])):
                    rows.append(r)
        df = self.save('greedy', rows)
        S = self.main_stratum(df).groupby('n')[KEYS(df)].mean()
        S.to_csv(os.path.join(self.a.out, 'greedy_summary.csv')); print(S.round(3).to_string())
        order = self.main_stratum(df).groupby(['n', 'last_added']).size().reset_index().sort_values(['n', 0], ascending=[True, False]).groupby('n').head(3)
        print('most often added at each step:'); print(order.to_string(index=False))

    # ------------------------------------------------------------------ 7. entropy / information-gain losses between latents
    def info(self):
        print('[7] info: KL / cross-entropy / rank information gain / signed LLR between latents (within and across notation groups)', flush=True)
        a, ctx, S = self.a, self.ctx, self.setup
        pool = [channel(v, a.pool_encoder) for v in (a.pool or ALL_VIEWS)]
        rows = []
        for sp in self.splits():
            train_idx = np.nonzero(sp['train_nodes'])[0]
            X = {c: get_channel(ctx, c) for c in pool}
            fold = sl.fold_ids(ctx.twin_group, S.giant, 5, sp['seed'])
            m = gp.fit_gcca_plus(X, train_idx, fold, k=min(a.k, 64 * len(X)), d_white=64, crossfit=True)
            lat = I.group_latents(m, pool, assign.GROUPS)
            stats = {n: I.LatentStats(Z, train_idx, a.knn) for n, Z in lat.items()}
            te = sp['te']; ia, ib, y = S.ii[te], S.jj[te], S.y[te]
            feats_te = {}
            for name, xn, yn in I.variants(list(lat)):
                ab, ba = I.both_directions(stats[xn], stats[yn], ia, ib)
                feats_te[name] = (ab, ba)
                for loss in I.LOSSES:
                    sc = I.equiv_score(loss, ab[loss], ba[loss])
                    dirauc = I.direction_auc(y, ab[loss] - ba[loss])
                    for st in STRATA:
                        sel = np.ones(len(te), bool) if st == 'all' else S.strat[te] == st
                        if not sel.any():
                            continue
                        r = _block(y[sel], None, sc[sel]); r['direction_AUC'] = I.direction_auc(y[sel], (ab[loss] - ba[loss])[sel])
                        r.update(exp='info', variant=name, loss=loss, stratum=st, mode=sp['mode'], seed=sp['seed'])
                        rows.append(r)
            if a.eval == 'full':
                rows += self._info_classifier(sp, stats, lat, feats_te)
            print(f'  [{time.time() - self.t0:.0f}s] seed {sp["seed"]} {sp["mode"]} done', flush=True)
        df = self.save('info', rows)
        d = df[df.exp == 'info'] if 'exp' in df else df
        d = d[d.get('loss').notna()] if 'loss' in d else d
        d = self.main_stratum(d)
        S1 = d.groupby(['variant', 'loss'])[['AUC_equiv_vs_rest', 'recall_at_10pct_FPR', 'direction_AUC']].mean().round(3)
        S1.to_csv(os.path.join(a.out, 'info_summary.csv'))
        P = d.groupby(['variant', 'loss'])['AUC_equiv_vs_rest'].mean().unstack().loc[lambda t: t.index.isin(['shared->shared'] + [v for v in t.index if '->' in v])]
        P.to_csv(os.path.join(a.out, 'info_auc_by_variant.csv'))
        print(P.round(3).sort_values('KL', ascending=False).to_string())
        within = [v for v in P.index if v.split('->')[0] == v.split('->')[1]]
        print('within-latent best:', P.loc[within].max().round(3).to_dict())
        cross = [v for v in P.index if v.split('->')[0] != v.split('->')[1]]
        print('cross-latent best :', P.loc[cross].max().round(3).to_dict())

    def _info_classifier(self, sp, stats, lat, feats_te):
        a, S = self.a, self.setup
        tr = sp['tr'] if len(sp['tr']) <= a.info_train else np.random.RandomState(sp['seed']).choice(sp['tr'], a.info_train, replace=False)
        ia_t, ib_t = S.ii[tr], S.jj[tr]
        sets = {'shared only (8 features)': ['shared->shared'],
                'within each group': [v for v in feats_te if v.split('->')[0] == v.split('->')[1] and v != 'shared->shared'],
                'across groups': [v for v in feats_te if v.split('->')[0] != v.split('->')[1]],
                'all variants': list(feats_te)}
        cache = {}
        def feat(names, ia, ib, train):
            cols = []
            for nm in names:
                xn, yn = nm.split('->')
                key = (nm, train)
                if key not in cache:
                    cache[key] = I.both_directions(stats[xn], stats[yn], ia, ib) if train else feats_te[nm]
                ab, ba = cache[key]
                cols += [ab[l] for l in I.LOSSES] + [ba[l] for l in I.LOSSES]
            return np.column_stack(cols)
        te = sp['te']; y = S.y[te]; rows = []
        for label, names in sets.items():
            if not names:
                continue
            clf = HistGradientBoostingClassifier(max_iter=a.clf_iter, learning_rate=0.05, class_weight='balanced', random_state=sp['seed'])
            clf.fit(feat(names, ia_t, ib_t, True), S.y[tr])
            proba = clf.predict_proba(feat(names, None, None, False))
            pred, p_eq = clf.classes_[proba.argmax(1)], proba[:, list(clf.classes_).index(0)]
            for st in STRATA:
                sel = np.ones(len(te), bool) if st == 'all' else S.strat[te] == st
                if sel.any():
                    r = _block(y[sel], pred[sel], p_eq[sel])
                    r.update(exp='info_classifier', variant=label, loss='classifier on %d latent pairs' % len(names), stratum=st, mode=sp['mode'], seed=sp['seed'])
                    rows.append(r)
        return rows

    # ------------------------------------------------------------------ 8. mutual information between notations' latents
    def mi(self):
        print('[8] mi: Gaussian mutual information between the latents of two notations (held-out laws)', flush=True)
        a, ctx = self.a, self.ctx
        views = a.pool or ALL_VIEWS
        mats = []
        for sp in self.splits():
            tr = np.nonzero(sp['train_nodes'])[0]
            te = np.nonzero(~sp['train_nodes'])[0]
            Z = {}
            for v in views:
                X = get_channel(ctx, channel(v, a.pool_encoder))
                Z[v] = PCA(n_components=int(min(a.k, X.shape[1], len(tr) - 1)), random_state=0).fit(X[tr]).transform(X)
            M = pd.DataFrame(np.nan, index=views, columns=views)
            for i, x in enumerate(views):
                for y_ in views[i + 1:]:
                    M.loc[x, y_] = M.loc[y_, x] = I.gaussian_mi(Z[x], Z[y_], tr, te)
            M['seed'] = sp['seed']; M['mode'] = sp['mode']
            mats.append(M)
        os.makedirs(a.out, exist_ok=True)
        full = pd.concat(mats)
        full.to_csv(os.path.join(a.out, 'mi_rows.csv'))
        avg = full.drop(columns=['seed', 'mode']).groupby(level=0).mean().loc[views, views]
        avg.to_csv(os.path.join(a.out, 'mi_matrix.csv'))
        gm = {}
        for g, vs in assign.GROUPS.items():
            for h, ws in assign.GROUPS.items():
                vals = [avg.loc[x, y_] for x in vs for y_ in ws if x in avg.index and y_ in avg.columns and x != y_]
                gm[(g, h)] = np.nanmean(vals) if vals else np.nan
        G = pd.Series(gm).unstack().round(3)
        G.to_csv(os.path.join(a.out, 'mi_by_group.csv'))
        print('mean MI (nats) between groups of notations:'); print(G.to_string())
        print('most / least informative notation pairs:')
        pr = avg.where(np.triu(np.ones(avg.shape), 1).astype(bool)).stack().dropna().sort_values()
        print(pr.head(3).round(3).to_string()); print(pr.tail(3).round(3).to_string())
        fig, ax = plt.subplots(figsize=(8, 7))
        im = ax.imshow(avg.values.astype(float), cmap='viridis')
        ax.set_xticks(range(len(views))); ax.set_xticklabels(views, rotation=60, ha='right', fontsize=7)
        ax.set_yticks(range(len(views))); ax.set_yticklabels(views, fontsize=7)
        ax.set_title('Gaussian mutual information (nats) between notation latents, held-out laws'); fig.colorbar(im); fig.tight_layout()
        fig.savefig(os.path.join(a.out, 'mi_matrix.png'), dpi=150); plt.close(fig)
