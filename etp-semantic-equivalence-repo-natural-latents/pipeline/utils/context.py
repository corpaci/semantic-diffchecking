"""
Context: everything every method shares -- the sampled equations, the
labelled pairs, the splits -- plus a cache so that expensive artifacts
(TF-IDF matrices, Natural Latents, loss matrices, magma fingerprints, ...)
are computed once and reused by every method that needs them.
"""
import time

import numpy as np

from .data import (ALL_VIEWS, LABEL_IDS, generate_pairs, load_equations,
                   sample_equations)
from .splits import node_holdout_splits


class Context:
    def __init__(self, cfg, log=print):
        self.cfg, self.log = cfg, log
        t0 = time.time()
        self.all_equations = load_equations()
        sample = sample_equations(self.all_equations, cfg.sample_size, cfg.data_seed)
        pairs, n_available = generate_pairs([e['node'] for e in sample], cfg.pair_sample_size, cfg.data_seed)

        # equations are indexed 0..n-1 in node_order everywhere
        self.node_order = sorted(e['node'] for e in sample)
        by_node = {e['node']: e for e in sample}
        self.equations = [by_node[n] for n in self.node_order]
        self.texts = {v: [e[v] for e in self.equations] for v in ALL_VIEWS}
        self.formal = [e['formal'] for e in self.equations]

        idx = {n: i for i, n in enumerate(self.node_order)}
        self.pairs = pairs
        self.ii = np.array([idx[a] for a in pairs.node_a])
        self.jj = np.array([idx[b] for b in pairs.node_b])
        self.y = np.array([LABEL_IDS[r] for r in pairs.relation])
        self.splits = node_holdout_splits(len(self.node_order), self.ii, self.jj,
                                          cfg.split_seeds, cfg.test_frac)
        self._cache = {}
        log(f"[data] {len(self.node_order)} equations, {len(self.y):,} ordered pairs "
            f"(from {n_available:,} resolvable unordered pairs), label counts "
            f"{np.bincount(self.y, minlength=4).tolist()}, {len(self.splits)} splits "
            f"(~{int(np.mean([s.train_pairs.sum() for s in self.splits]))} train / "
            f"~{int(np.mean([s.test_pairs.sum() for s in self.splits]))} test pairs) "
            f"in {time.time() - t0:.1f}s")

    def cached(self, key, build):
        """Compute `build()` once per run and reuse it."""
        if key not in self._cache:
            t0 = time.time()
            self._cache[key] = build()
            self.log(f"    [artifact] {key} built in {time.time() - t0:.1f}s")
        return self._cache[key]
