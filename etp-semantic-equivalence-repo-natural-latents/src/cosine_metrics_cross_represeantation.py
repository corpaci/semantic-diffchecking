"""
Cross-notation (and same-notation) cosine with ONE shared TF-IDF vectorizer, so every
notation pair is scored on the same scale. Needs only the pairs CSV (node_a,node_b,relation)
and equations_representations_v2.json; the big assembled CSV is NOT needed.

  python cosine_cross_pooled.py PAIRS.csv OUT_DIR --json equations_representations_v2.json
         [--reps all | formal,lean,natural_language] [--pairs-mode cross|same|all|lean:natural_language,...]  (default: cross)
         [--both-orders] [--ngram 2,4] [--chunksize 50000] [--nrows N]

Writes OUT_DIR/<repA>__<repB>/scored_<repA>__<repB>.csv  (same notation: OUT_DIR/<rep>/scored_<rep>.csv)
with columns node_a, node_b, relation, cosine; cosine = sim(repA text of A, repB text of B).
Also OUT_DIR/summary.csv.
"""
import argparse, itertools, json, os
import numpy as np, pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer

p = argparse.ArgumentParser()
p.add_argument('pairs'); p.add_argument('out_dir')
p.add_argument('--json', required=True)
p.add_argument('--reps', default='all')
p.add_argument('--pairs-mode', dest='mode', default='cross',
               help="cross (default) = different notations only, same = same notation only, all = same+cross, or repA:repB,repC:repD")
p.add_argument('--both-orders', action='store_true', help='for cross pairs also score repB(A) vs repA(B)')
p.add_argument('--ngram', default='2,4')
p.add_argument('--chunksize', type=int, default=50000)
p.add_argument('--nrows', type=int, default=None)
a = p.parse_args()

eqs = json.load(open(a.json))
all_reps = [k for k in eqs[0] if k != 'node']
reps = all_reps if a.reps == 'all' else a.reps.split(',')
bad = [r for r in reps if r not in all_reps]
if bad:
    raise SystemExit(f'unknown representation(s): {bad}; choose from {all_reps}')

df = pd.DataFrame(eqs).set_index('node')
row_of = {n: i for i, n in enumerate(df.index)}

# one vectorizer, fit once on the pooled text of all chosen notations (label-free)
lo, hi = map(int, a.ngram.split(','))
pool = pd.concat([df[r].dropna().astype(str) for r in reps]).loc[lambda s: s.str.strip() != '']
vec = TfidfVectorizer(analyzer='char', ngram_range=(lo, hi)).fit(pool.tolist())
print(f'fitted one vectorizer on {len(pool)} texts, {len(vec.vocabulary_)} features', flush=True)

M, valid = {}, {}
for r in reps:                                           # vectorise each notation once (L2-normalised rows)
    txt = df[r].fillna('').astype(str)
    valid[r] = (txt.str.strip() != '').to_numpy()
    M[r] = vec.transform(txt.tolist()).tocsr()

if a.mode in ('all', 'cross', 'same'):
    jobs = [(x, x) for x in reps] if a.mode in ('all', 'same') else []
    if a.mode in ('all', 'cross'):
        for x, y in itertools.combinations(reps, 2):
            jobs.append((x, y))
            if a.both_orders:
                jobs.append((y, x))
else:
    jobs = [tuple(s.split(':')) for s in a.mode.split(',') if s]
    bad = sorted({r for j in jobs for r in j} - set(reps))
    if bad:
        raise SystemExit(f'pair uses representation(s) not in --reps: {bad}')

def name(j): return j[0] if j[0] == j[1] else f'{j[0]}__{j[1]}'
def path(j): return os.path.join(a.out_dir, name(j), f'scored_{name(j)}.csv')
for j in jobs:
    os.makedirs(os.path.dirname(path(j)), exist_ok=True)
    if os.path.exists(path(j)):
        os.remove(path(j))
print(f'{len(jobs)} jobs', flush=True)

total, first = 0, True
for chunk in pd.read_csv(a.pairs, usecols=['node_a', 'node_b', 'relation'], chunksize=a.chunksize, nrows=a.nrows):
    ia = chunk.node_a.map(row_of).to_numpy()
    ib = chunk.node_b.map(row_of).to_numpy()
    for x, y in jobs:
        s = np.asarray(M[x][ia].multiply(M[y][ib]).sum(axis=1)).ravel()   # dot of unit vectors = cosine
        s[~(valid[x][ia] & valid[y][ib])] = np.nan
        out = chunk.copy(); out['cosine'] = s
        out.to_csv(path((x, y)), mode='a', header=first, index=False)
    first = False
    total += len(chunk)
    print(f'scored {total} rows x {len(jobs)} jobs', flush=True)

rows = []
for j in jobs:
    s = pd.read_csv(path(j))
    g = s.groupby('relation').cosine.mean()
    rows.append({'job': name(j), 'n_scored': int(s.cosine.notna().sum()), 'n_missing': int(s.cosine.isna().sum()),
                 **{f'mean_{k}': round(v, 3) for k, v in g.items()}})
pd.DataFrame(rows).to_csv(os.path.join(a.out_dir, 'summary.csv'), index=False)
print(pd.DataFrame(rows).head(30).to_string(index=False))