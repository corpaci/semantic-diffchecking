"""nlx -- natural-latent experiments: which encoder for which notation, and how many notations to combine.

  encoders.py    channels = (notation, encoder) pairs; registry of encoders (TF-IDF flavours, LSA, WL, invariants, optional neural)
  assign.py      rules that choose an encoder for every notation (uniform, by group, learned from training pairs)
  subsets.py     which notations to combine (1, 2, 3 ... n at a time; random, all pairs, groups, greedy)
  latent.py      shared latent over a set of channels + the pair features fed to the classifier
  evaluate.py    twin-free splits, the classifier, and every metric (4-class and equivalent-vs-rest)
  experiments.py the six experiments  (encoders, assign, nviews, pairs, groups, greedy)
Entry point: run_nlx.py (repo root).
"""
