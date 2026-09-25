#!/usr/bin/env python
"""
Run every method on the same data, splits and base classifier, and write
results/method_comparison.xlsx (+ CSVs and confusion-matrix images).

Examples
  python run_all.py                                   # everything (~1-1.5 h on 4 CPUs)
  python run_all.py --quick                           # smoke test: 300 equations, 2 splits
  python run_all.py --modules symmetric structural    # only some method modules
  python run_all.py --match "WL|Magma"                # only methods whose name matches a regex
  python run_all.py --classifier rf                   # same run with the Random Forest as base classifier
  python run_all.py --list                            # list every method and exit
  python run_all.py --export-dataset                  # write the evaluation data (equations, pairs, splits)
  python run_all.py --resume                          # continue a stopped run (results are
                                                      # checkpointed after every method; Ctrl-C
                                                      # or kill still writes the sheet)

Method modules: symmetric, natural_latents, advanced, structural, thresholds, semantic
"""
import argparse
import os
import pickle
import re
import signal
import sys
import time
import warnings

os.environ.setdefault('OMP_NUM_THREADS', '1')      # 1 thread per model; splits run in parallel processes
warnings.filterwarnings('ignore', message="The parameter 'token_pattern' will not be used")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from pipeline.config import Config                             # noqa: E402
from pipeline.methods import MODULES, all_methods              # noqa: E402
from pipeline.methods.base import run_method                   # noqa: E402
from pipeline.utils.classifier import describe_classifier      # noqa: E402
from pipeline.utils.context import Context                     # noqa: E402
from pipeline.utils.reporting import write_all                 # noqa: E402


def _raise_keyboard_interrupt(signum, frame):
    raise KeyboardInterrupt


def parse_args():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--modules', nargs='+', choices=list(MODULES), help='only these method modules')
    p.add_argument('--match', help='only methods whose name matches this regex')
    p.add_argument('--classifier', choices=['hgb', 'rf'], help='base classifier for every learned method')
    p.add_argument('--sample-size', type=int)
    p.add_argument('--pairs', type=int)
    p.add_argument('--seeds', type=int, nargs='+', help='split seeds')
    p.add_argument('--out', help='results directory')
    p.add_argument('--no-png', action='store_true', help='skip confusion-matrix images')
    p.add_argument('--quick', action='store_true', help='smoke test: 300 equations, 3,000 pairs, 2 splits')
    p.add_argument('--list', action='store_true', help='list methods and exit')
    p.add_argument('--export-dataset', action='store_true',
                   help='write the evaluation dataset (equations, labelled pairs, splits) to <results>/evaluation_dataset and exit')
    p.add_argument('--resume', action='store_true',
                   help='skip methods already saved in <results>/checkpoint.pkl (same settings only)')
    return p.parse_args()


def main():
    a = parse_args()
    cfg = Config()
    if a.quick:
        cfg.sample_size, cfg.pair_sample_size, cfg.split_seeds = 300, 3000, (42, 7)
        cfg.exhaustive_size3_magmas = False
    if a.classifier:
        cfg.classifier = a.classifier
    if a.sample_size:
        cfg.sample_size = a.sample_size
    if a.pairs:
        cfg.pair_sample_size = a.pairs
    if a.seeds:
        cfg.split_seeds = tuple(a.seeds)
    if a.out:
        cfg.results_dir = a.out
    if a.no_png:
        cfg.save_confusion_pngs = False

    methods = all_methods(cfg, a.modules)
    if a.match:
        methods = [m for m in methods if re.search(a.match, m.name)]
    if a.list:
        for m in methods:
            print(f'{m.family:20s} {m.kind:8s} {m.name}')
        print(f'{len(methods)} methods')
        return

    ckpt_path = os.path.join(cfg.results_dir, 'checkpoint.pkl')
    fingerprint = {k: v for k, v in cfg.as_dict().items() if k not in ('results_dir', 'save_confusion_pngs', 'n_jobs')}
    done = {}
    if a.resume and os.path.exists(ckpt_path):
        with open(ckpt_path, 'rb') as f:
            saved = pickle.load(f)
        if saved['config'] != fingerprint:
            sys.exit('[resume] checkpoint was made with different settings; run without --resume '
                     f'or use another --out directory.\n  checkpoint: {saved["config"]}\n  now: {fingerprint}')
        done = saved['results']
        print(f'[resume] {len(done)} methods already finished in {ckpt_path}')

    if a.export_dataset:
        from pipeline.utils.dataset_export import export_dataset
        out, summary = export_dataset(Context(cfg), os.path.join(cfg.results_dir, 'evaluation_dataset'))
        print(f'[dataset] written to {out}')
        for k, v in summary:
            print(f'  {k}: {v}')
        return

    print(f'[run] {len(methods)} methods | base classifier: {describe_classifier(cfg)}')
    t0 = time.time()
    ctx = Context(cfg)

    # a kill (SIGTERM) behaves like Ctrl-C: stop, keep what finished, write the report
    signal.signal(signal.SIGTERM, _raise_keyboard_interrupt)
    os.makedirs(cfg.results_dir, exist_ok=True)
    stopped = False
    try:
        for k, m in enumerate(methods, 1):
            if m.name in done:
                continue
            r = run_method(ctx, m)
            done[m.name] = r
            with open(ckpt_path + '.tmp', 'wb') as f:          # checkpoint after EVERY method
                pickle.dump({'config': fingerprint, 'results': done}, f)
            os.replace(ckpt_path + '.tmp', ckpt_path)
            o = r['overall']
            print(f"[{k:3d}/{len(methods)}] {m.name[:78]:78s} bal={o['balanced_accuracy']:.3f}"
                  f"±{o['balanced_accuracy_std']:.3f} acc={o['accuracy']:.3f} F1={o['macro_f1']:.3f} "
                  f"({r['runtime_s']:.0f}s)", flush=True)
    except KeyboardInterrupt:
        stopped = True
        print(f'\n[stopped] writing the report for the {len(done)} finished methods '
              f'(continue later with --resume)', flush=True)

    results = [done[m.name] for m in methods if m.name in done]
    if not results:
        print('[stopped] nothing finished yet')
        return
    config_rows = [(k, str(v)) for k, v in cfg.as_dict().items()] + [
        ('base classifier', describe_classifier(cfg)),
        ('equations', len(ctx.node_order)), ('ordered pairs', len(ctx.y)),
        ('label counts (equivalent, stronger, weaker, incomparable)', ctx.pairs.relation.value_counts()
         .reindex(['equivalent', 'stronger', 'weaker', 'incomparable']).tolist()),
        ('test pairs per split', [int(s.test_pairs.sum()) for s in ctx.splits]),
        ('train pairs per split', [int(s.train_pairs.sum()) for s in ctx.splits]),
        ('methods finished / selected', f'{len(results)} / {len(methods)}' + (' (run stopped early)' if stopped else '')),
        ('total runtime this session (s)', round(time.time() - t0, 1)),
    ]
    xlsx, tables = write_all(results, ctx, config_rows)
    print(f'\n[done] {len(results)}/{len(methods)} methods -> {xlsx}')
    print(tables['Summary'][['Rank', 'Family', 'Method', 'Balanced accuracy', 'Accuracy', 'Macro F1']]
          .head(15).to_string(index=False, float_format='%.3f'))


if __name__ == '__main__':
    main()
