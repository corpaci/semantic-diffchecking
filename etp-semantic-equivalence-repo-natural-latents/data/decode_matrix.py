"""
decode_matrix.py
==================
matrix.bin contains the COMPLETE, exact relationship for every single one of
the 4,694 x 4,694 = 22,033,636 possible ordered pairs of equations in the
Equational Theories Project catalogue -- derived from real Lean proofs, not
sampled or approximated. It's stored as one byte per pair (status codes: see
below), which is why 22 million relationships fit in just 21MB.

Use this script to:
  1. Look up the relationship between any two specific equation numbers.
  2. Export a CSV of ALL pairs (warning: this produces a ~400-600MB file --
     only do this if you actually need every pair; use export_sample() for
     anything smaller).
  3. Export a large but manageable random sample as CSV.

STATUS CODES IN THE RAW BYTES (from matrix_meta.json):
  0 = proof_false        1 = proof_true
  2 = conjecture_false    3 = conjecture_true      4 = unknown

DERIVED RELATION (combining forward and backward implication status):
  fwd=proof_true,  bwd=proof_true   -> equivalent
  fwd=proof_false, bwd=proof_true   -> stronger   (node_b implies node_a)
  fwd=proof_true,  bwd=proof_false  -> weaker      (node_a implies node_b)
  fwd=proof_false, bwd=proof_false  -> incomparable
  anything else (conjecture/unknown involved) -> unresolved

Requires: numpy only
"""
import json
import csv
import numpy as np
import os
import random

DATA_DIR = os.path.dirname(__file__)


def load_matrix():
    with open(os.path.join(DATA_DIR, 'matrix_meta.json')) as f:
        meta = json.load(f)
    n = meta['n']
    with open(os.path.join(DATA_DIR, 'matrix.bin'), 'rb') as f:
        raw = f.read()
    matrix = np.frombuffer(raw, dtype=np.uint8).reshape(n, n)
    return matrix, meta


def load_node_index():
    """matrix row/col index i corresponds to equation number (i+1) --
    verify against etp_equations_index.txt if you want the exact mapping,
    but in this dataset node numbers are simply 1..4694 in order."""
    with open(os.path.join(DATA_DIR, 'etp_equations_index.txt')) as f:
        lines = [l.strip() for l in f if l.strip()]
    return lines  # lines[i] is the formal statement for node i+1


def relation_for(matrix, node_a, node_b):
    """node_a, node_b are 1-indexed equation numbers (1 to 4694)."""
    i, j = node_a - 1, node_b - 1
    fwd = matrix[i, j]   # status of node_a => node_b
    bwd = matrix[j, i]   # status of node_b => node_a
    PROOF_FALSE, PROOF_TRUE = 0, 1
    if fwd == PROOF_TRUE and bwd == PROOF_TRUE:
        return 'equivalent'
    elif fwd == PROOF_FALSE and bwd == PROOF_TRUE:
        return 'stronger'
    elif fwd == PROOF_TRUE and bwd == PROOF_FALSE:
        return 'weaker'
    elif fwd == PROOF_FALSE and bwd == PROOF_FALSE:
        return 'incomparable'
    else:
        return 'unresolved'


def export_sample(out_path, n_pairs=50000, seed=42):
    """Export a random sample of pairs as CSV -- fast, small, good for
    exploring in pandas/Excel without decoding the whole 22M-pair matrix."""
    matrix, meta = load_matrix()
    n = meta['n']
    rng = random.Random(seed)
    pairs = set()
    while len(pairs) < n_pairs:
        a, b = rng.randint(1, n), rng.randint(1, n)
        if a != b:
            pairs.add((a, b))

    with open(out_path, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['node_a', 'node_b', 'relation'])
        for a, b in pairs:
            writer.writerow([a, b, relation_for(matrix, a, b)])
    print(f"wrote {len(pairs)} pairs to {out_path}")


def export_all(out_path):
    """Export EVERY pair -- 22,033,636 rows, expect ~400-600MB and several
    minutes. Only run this if you specifically need the full grid."""
    matrix, meta = load_matrix()
    n = meta['n']
    print(f"Exporting all {n*n:,} pairs -- this will take a while and produce a large file...")
    with open(out_path, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['node_a', 'node_b', 'relation'])
        for i in range(n):
            for j in range(n):
                if i == j:
                    continue
                writer.writerow([i + 1, j + 1, relation_for(matrix, i + 1, j + 1)])
            if i % 500 == 0:
                print(f"  {i}/{n}")
    print("done")


if __name__ == '__main__':
    matrix, meta = load_matrix()
    print(f"Loaded matrix: {meta['n']} x {meta['n']} equations")

    # example lookups
    print("\nExample lookups:")
    print("  node 43 vs node 1:", relation_for(matrix, 43, 1))
    print("  node 1 vs node 43:", relation_for(matrix, 1, 43))

    print("\nTo get a CSV sample, run:")
    print("  python3 -c \"from decode_matrix import export_sample; export_sample('my_sample.csv', 50000)\"")
    print("\nTo get ALL 22 million pairs (large, slow), run:")
    print("  python3 -c \"from decode_matrix import export_all; export_all('all_pairs.csv')\"")
