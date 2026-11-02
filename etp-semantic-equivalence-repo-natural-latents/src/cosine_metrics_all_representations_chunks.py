"""
Score cosine similarity for every representation (same-notation: rep_a vs rep_b), reading the
assembled CSV once in chunks. One folder per representation, each with its own scored file.

  python cosine_all_reps.py assembled_pairs.csv OUT_DIR --repo REPO_PATH
         [--reps formal,lean | all] [--cross lean:natural_language,formal:tptp]
         [--chunksize 5000] [--nrows 5000]

Writes OUT_DIR/<rep>/scored_<rep>.csv                (same notation)
       OUT_DIR/<repA>__<repB>/scored_<repA>__<repB>.csv   (cross notation, from --cross)
Each file has: node_a, node_b, relation, cosine.
"""
import argparse, os, sys
import pandas as pd

p = argparse.ArgumentParser()
p.add_argument('inp'); p.add_argument('out_dir')
p.add_argument('--repo', required=True, help='path to the etp-semantic-equivalence-repo-natural-latents folder')
p.add_argument('--reps', default='all')
p.add_argument('--cross', default='', help='comma-separated repA:repB pairs for cross-notation (optional)')
p.add_argument('--chunksize', type=int, default=5000)
p.add_argument('--nrows', type=int, default=None, help='only read this many rows (quick test)')
a = p.parse_args()

sys.path.insert(0, a.repo)
from src.baseline_metrics import cosine_similarity_equations as cos

header = pd.read_csv(a.inp, nrows=0).columns
all_reps = sorted({c[:-2] for c in header if c.endswith('_a') and c[:-2] + '_b' in header})
reps = all_reps if a.reps == 'all' else a.reps.split(',')
jobs = [(r, r) for r in reps]                                   # same-notation jobs
jobs += [tuple(x.split(':')) for x in a.cross.split(',') if x]  # cross-notation jobs
bad = sorted({r for j in jobs for r in j} - set(all_reps))
if bad:
    raise SystemExit(f'unknown representation(s): {bad}; choose from {all_reps}')

def name(j): return j[0] if j[0] == j[1] else f'{j[0]}__{j[1]}'
def path(j): return os.path.join(a.out_dir, name(j), f'scored_{name(j)}.csv')

def safe_cos(x, y):
    if not isinstance(x, str) or not isinstance(y, str) or not x.strip() or not y.strip():
        return None
    try:
        return cos(x, y)
    except ValueError:
        return None

for j in jobs:
    os.makedirs(os.path.dirname(path(j)), exist_ok=True)
    if os.path.exists(path(j)):
        os.remove(path(j))

need = ['node_a', 'node_b', 'relation'] + sorted({f'{j[0]}_a' for j in jobs} | {f'{j[1]}_b' for j in jobs})
total, first = 0, True
for chunk in pd.read_csv(a.inp, usecols=need, chunksize=a.chunksize, nrows=a.nrows):
    for j in jobs:
        out = chunk[['node_a', 'node_b', 'relation']].copy()
        out['cosine'] = [safe_cos(x, y) for x, y in zip(chunk[f'{j[0]}_a'], chunk[f'{j[1]}_b'])]
        out.to_csv(path(j), mode='a', header=first, index=False)
    first = False
    total += len(chunk)
    print(f'scored {total} rows x {len(jobs)} jobs', flush=True)

summary = []
for j in jobs:
    s = pd.read_csv(path(j))
    g = s.groupby('relation').cosine.mean()
    summary.append({'job': name(j), 'n_scored': int(s.cosine.notna().sum()), 'n_missing': int(s.cosine.isna().sum()),
                    **{f'mean_{k}': round(v, 3) for k, v in g.items()}})
pd.DataFrame(summary).to_csv(os.path.join(a.out_dir, 'summary.csv'), index=False)
print(pd.DataFrame(summary).to_string(index=False))