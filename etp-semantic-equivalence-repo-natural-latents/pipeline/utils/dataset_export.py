"""
Export the exact evaluation dataset every method is scored on:

  equations.csv        the sampled equations with all 19 representations
  pairs.csv            the labelled ordered pairs, with both equations' formal text and,
                       for every split seed, whether the pair is train / test / excluded
  equation_splits.csv  for every split seed, whether each equation is train or test
  evaluation_dataset.xlsx   the same three tables in one workbook (+ a README sheet)
"""
import os

import pandas as pd

from .data import ALL_VIEWS, LABEL_NAMES

README = [
    ('What', 'The exact data every method in run_all.py is evaluated on.'),
    ('Source', 'data/equations_representations_v2.json (equations) and data/matrix.bin '
               '(ETP implication matrix: Lean proofs / verified counterexamples).'),
    ('Equations', 'A random sample of equations that have all 19 representations.'),
    ('Pairs', 'Unordered pairs drawn at random among those resolved in BOTH directions; '
              'each contributes both orderings (A,B) and (B,A).'),
    ('relation', 'equivalent = A=>B and B=>A; stronger = only B=>A; weaker = only A=>B; '
                 'incomparable = neither (convention of data/decode_matrix.py).'),
    ('forward / backward', 'forward = does node_a imply node_b; backward = does node_b imply node_a.'),
    ('split_<seed>', 'Node-held-out split: a fraction of EQUATIONS is held out. train = both '
                     'equations are training equations; test = both are held-out equations; '
                     'excluded = mixed pair, used by no method in that split.'),
]


def export_dataset(ctx, out_dir):
    os.makedirs(out_dir, exist_ok=True)
    cfg = ctx.cfg

    eq = pd.DataFrame([{'node': e['node'], **{v: e[v] for v in ['formal'] + [x for x in ALL_VIEWS if x != 'formal']}}
                       for e in ctx.equations])

    pairs = ctx.pairs[['node_a', 'node_b', 'relation']].copy()
    pairs.insert(0, 'pair_id', range(len(pairs)))
    pairs['forward_a_implies_b'] = pairs.relation.isin(['equivalent', 'weaker'])
    pairs['backward_b_implies_a'] = pairs.relation.isin(['equivalent', 'stronger'])
    pairs['formal_a'] = [ctx.formal[i] for i in ctx.ii]
    pairs['formal_b'] = [ctx.formal[j] for j in ctx.jj]
    eq_split = pd.DataFrame({'node': ctx.node_order})
    for s in ctx.splits:
        pairs[f'split_{s.seed}'] = ['train' if tr else 'test' if te else 'excluded'
                                    for tr, te in zip(s.train_pairs, s.test_pairs)]
        eq_split[f'split_{s.seed}'] = ['train' if t else 'test' for t in s.train_nodes]

    summary = [('equations', len(eq)), ('ordered pairs', len(pairs))]
    summary += [(f'label count: {n}', int((pairs.relation == n).sum())) for n in LABEL_NAMES]
    for s in ctx.splits:
        summary.append((f'split {s.seed}: train / test / excluded pairs',
                        f'{int(s.train_pairs.sum())} / {int(s.test_pairs.sum())} / '
                        f'{int(len(pairs) - s.train_pairs.sum() - s.test_pairs.sum())}'))
    summary += [('sample_size', cfg.sample_size), ('pair_sample_size', cfg.pair_sample_size),
                ('data_seed', cfg.data_seed), ('split_seeds', list(cfg.split_seeds)),
                ('test_frac (of equations)', cfg.test_frac)]

    eq.to_csv(os.path.join(out_dir, 'equations.csv'), index=False)
    pairs.to_csv(os.path.join(out_dir, 'pairs.csv'), index=False)
    eq_split.to_csv(os.path.join(out_dir, 'equation_splits.csv'), index=False)
    xlsx = os.path.join(out_dir, 'evaluation_dataset.xlsx')
    with pd.ExcelWriter(xlsx, engine='openpyxl') as xw:
        pd.DataFrame(README + summary, columns=['Item', 'Value']).to_excel(xw, sheet_name='README', index=False)
        pairs.to_excel(xw, sheet_name='pairs', index=False)
        eq.to_excel(xw, sheet_name='equations', index=False)
        eq_split.to_excel(xw, sheet_name='equation_splits', index=False)
        for ws in xw.sheets.values():
            ws.freeze_panes = 'B2'
        xw.sheets['README'].column_dimensions['A'].width = 40
        xw.sheets['README'].column_dimensions['B'].width = 120
    return out_dir, summary
