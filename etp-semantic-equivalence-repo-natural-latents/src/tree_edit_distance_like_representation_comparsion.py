"""
Same-notation edit-distance similarity for every representation, reusing the repo's own parsers
(pipeline/utils/trees.py). For each notation, A's text and B's text in THAT notation are parsed
with the notation's own parser and compared:
    tree notations      -> Zhang-Shasha tree edit distance (edist)
    sequence notations  -> token Levenshtein (rapidfuzz)
similarity = 1 - distance / (size(A) + size(B))       (same normalisation as the repo)

  python edit_distance_same_notation.py PAIRS.csv OUT_DIR --repo REPO_PATH
         [--reps all|tree|logic|code|sequence|formal,lean,...] [--chunksize 20000] [--nrows N]

  tree     = formal latex lean confusable_vars tptp smtlib py_lambda py_cayley_table json_ast slots ascii_tree graphviz
  logic    = formal latex lean confusable_vars tptp smtlib
  code     = py_lambda py_cayley_table
  sequence = rpn polish ssa text text2 natural_language word_problem   (Levenshtein, not a tree)
  all      = tree + sequence

PAIRS.csv needs columns node_a, node_b, relation. No other columns are read.
Writes OUT_DIR/<rep>/edit_<rep>.csv with node_a, node_b, relation, similarity (empty if a text is
missing or fails to parse), and OUT_DIR/summary.csv (mean similarity per relation for each notation).
"""
import argparse, json, os, sys
import numpy as np, pandas as pd

p = argparse.ArgumentParser()
p.add_argument('pairs'); p.add_argument('out_dir')
p.add_argument('--repo', required=True, help='path to etp-semantic-equivalence-repo-natural-latents')
p.add_argument('--json', default=None, help='equations_representations_v2.json (default: <repo>/data/...)')
p.add_argument('--reps', default='all')
p.add_argument('--chunksize', type=int, default=20000)
p.add_argument('--nrows', type=int, default=None)
a = p.parse_args()

sys.path.insert(0, a.repo)
from pipeline.utils.trees import TREE_PARSERS, SEQUENCE_PARSERS, parse_representation, edit_similarity

GROUPS = {'tree': list(TREE_PARSERS), 'sequence': list(SEQUENCE_PARSERS),
          'logic': ['formal', 'latex', 'lean', 'confusable_vars', 'tptp', 'smtlib'],
          'code': ['py_lambda', 'py_cayley_table']}
GROUPS['all'] = GROUPS['tree'] + GROUPS['sequence']
reps = []                                       # --reps accepts group names and notation names, mixed
for tok in a.reps.split(','):
    for r in (GROUPS[tok] if tok in GROUPS else [tok]):
        if r not in reps:
            reps.append(r)
bad = [r for r in reps if r not in GROUPS['all']]
if bad:
    raise SystemExit(f'unknown representation(s): {bad}; choose from {GROUPS["all"]}')

eqs = json.load(open(a.json or os.path.join(a.repo, 'data', 'equations_representations_v2.json')))
row_of = {e['node']: i for i, e in enumerate(eqs)}

parsed, n_fail = {}, {}
for r in reps:                                  # parse every equation once per notation
    out, fails = [], 0
    for e in eqs:
        t = e.get(r)
        try:
            out.append(parse_representation(r, t) if isinstance(t, str) and t.strip() else None)
        except Exception:
            out.append(None); fails += 1
    parsed[r], n_fail[r] = out, fails
    print(f'parsed {r}: {sum(x is not None for x in out)} ok, {fails} failed to parse', flush=True)

def path(r): return os.path.join(a.out_dir, r, f'edit_{r}.csv')
for r in reps:
    os.makedirs(os.path.dirname(path(r)), exist_ok=True)
    if os.path.exists(path(r)):
        os.remove(path(r))

cache = {r: {} for r in reps}
total, first = 0, True
for chunk in pd.read_csv(a.pairs, usecols=['node_a', 'node_b', 'relation'], chunksize=a.chunksize, nrows=a.nrows):
    ia = chunk.node_a.map(row_of).to_numpy(); ib = chunk.node_b.map(row_of).to_numpy()
    for r in reps:
        P, c, sims = parsed[r], cache[r], np.full(len(chunk), np.nan)
        for k, (i, j) in enumerate(zip(ia, ib)):
            x, y = P[i], P[j]
            if x is None or y is None:
                continue
            key = (i, j) if i < j else (j, i)          # symmetric measure: score each unordered pair once
            if key not in c:
                c[key] = edit_similarity(P[key[0]], P[key[1]])
            sims[k] = c[key]
        if len(c) > 2_000_000:
            c.clear()
        out = chunk.copy(); out['similarity'] = sims
        out.to_csv(path(r), mode='a', header=first, index=False)
    first = False
    total += len(chunk)
    print(f'scored {total} rows x {len(reps)} notations', flush=True)

rows = []
for r in reps:
    s = pd.read_csv(path(r)); g = s.groupby('relation').similarity.mean()
    rows.append({'notation': r, 'method': 'tree edit distance' if r in TREE_PARSERS else 'token Levenshtein',
                 'n_scored': int(s.similarity.notna().sum()), 'n_missing': int(s.similarity.isna().sum()),
                 **{f'mean_{k}': round(v, 3) for k, v in g.items()}})
pd.DataFrame(rows).to_csv(os.path.join(a.out_dir, 'summary.csv'), index=False)
print(pd.DataFrame(rows).to_string(index=False))