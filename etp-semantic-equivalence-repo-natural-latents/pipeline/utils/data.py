"""Loading equations, sampling, labelled pairs, label conventions."""
import json
import os
import random

import numpy as np
import pandas as pd

from ..config import DATA_DIR

# 19 representations, grouped by family
REPRESENTATION_FAMILIES = {
    'formal': ['lean', 'latex', 'tptp', 'smtlib', 'formal'],
    'code': ['py_lambda', 'py_cayley_table', 'ssa'],
    'structural': ['rpn', 'polish', 'slots', 'json_ast', 'ascii_tree', 'graphviz'],
    'natural': ['natural_language', 'word_problem', 'text', 'text2'],
    'confusable': ['confusable_vars'],
}
ALL_VIEWS = [v for vs in REPRESENTATION_FAMILIES.values() for v in vs]
ORIGINAL_5_VIEWS = ['lean', 'latex', 'py_lambda', 'py_cayley_table', 'natural_language']

# label convention of data/decode_matrix.py (row = node_a, column = node_b)
LABEL_NAMES = ['equivalent', 'stronger', 'weaker', 'incomparable']
LABEL_IDS = {n: i for i, n in enumerate(LABEL_NAMES)}
LABELS = list(range(4))
SWAP = np.array([0, 2, 1, 3])          # label of (B, A) given the label of (A, B)


def implications_to_label(fwd, bwd):
    """fwd: A => B holds, bwd: B => A holds (bool arrays) -> label ids."""
    return np.where(fwd & bwd, 0, np.where(bwd, 1, np.where(fwd, 2, 3)))


def load_equations():
    with open(os.path.join(DATA_DIR, 'equations_representations_v2.json')) as f:
        return json.load(f)


def sample_equations(equations, n, seed):
    """Random sample (not "first N") of equations that have all 19 representations."""
    complete = [e for e in equations if all(e.get(v) not in (None, '') for v in ALL_VIEWS)]
    rng = random.Random(seed)
    return rng.sample(complete, n) if n < len(complete) else complete


def generate_pairs(nodes, n_pairs, seed):
    """Pairs drawn from the exact ETP relationship matrix. Only pairs resolved in
    BOTH directions are used; each sampled unordered pair contributes both
    orderings, so stronger/weaker are exactly balanced."""
    from decode_matrix import load_matrix, relation_for
    matrix, _ = load_matrix()
    unordered = []
    for i, a in enumerate(nodes):
        for b in nodes[i + 1:]:
            ra, rb = relation_for(matrix, a, b), relation_for(matrix, b, a)
            if ra != 'unresolved' and rb != 'unresolved':
                unordered.append((a, b, ra, rb))
    rng = random.Random(seed)
    chosen = rng.sample(unordered, min(n_pairs // 2, len(unordered)))
    rows = []
    for a, b, ra, rb in chosen:
        rows.append({'node_a': a, 'node_b': b, 'relation': ra})
        rows.append({'node_a': b, 'node_b': a, 'relation': rb})
    return pd.DataFrame(rows).sample(frac=1, random_state=seed).reset_index(drop=True), len(unordered)
