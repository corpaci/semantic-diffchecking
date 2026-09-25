# Complete ETP Equation Dataset

Everything: all 4,694 equations with every representation, and the complete
exact relationship for every one of the 22,033,636 possible pairs.

# Complete ETP Equation Dataset

Everything: all 4,694 equations with every representation, and the complete
exact relationship for every one of the 22,033,636 possible pairs.

**File names match what `05_full_pipeline.py` (from the scripts package)
expects** — drop this `data/` folder in next to `scripts/` and the existing
workflow runs unmodified, just against the full dataset instead of the
500-equation sample. Verified directly: ran `05_full_pipeline.py` against
these exact files with zero code changes before this package was finalized.

## Files

| File | Contents | Size |
|---|---|---|
| `equations_representations.json` | **All 4,694 equations** (same name the pipeline script expects), each with 5 representations (Lean, LaTeX, Python lambda, Python Cayley-table code, and real LLM-generated natural-language description). 82 equations have `natural_language: null` — their generation attempt failed; everything else is complete. Identical content to `all_equations.json` below, just named for drop-in compatibility. | 5.6 MB |
| `oracle_labeled_pairs.csv` | 50,000 pairs, decoded and labeled (same name the pipeline script expects). Identical content to `sample_pairs_50000.csv` below. | 1 MB |
| `all_equations.json` | Same content as `equations_representations.json` — kept under its original name too, in case you're using `decode_matrix.py` or your own scripts that expect this name. | 5.6 MB |
| `sample_pairs_50000.csv` | Same content as `oracle_labeled_pairs.csv`. | 1 MB |
| `matrix.bin` | The **complete, exact** relationship for every one of the 4,694 × 4,694 possible ordered pairs — one byte per pair, derived from real Lean proofs (Terence Tao's Equational Theories Project). This is not a sample; it's every pair, exactly. | 21 MB |
| `matrix_meta.json` | Metadata for decoding `matrix.bin` (dimensions, status code meanings). | 1 KB |
| `etp_equations_index.txt` | The formal statement for each equation number, 1-indexed, matching `matrix.bin`'s row/column order. | 158 KB |
| `decode_matrix.py` | Script to read `matrix.bin` — look up any specific pair, export a random sample of any size, or export the complete 22M-row CSV if you actually need it. | — |

## Why `matrix.bin` instead of one giant CSV

22 million pairs as a CSV would be roughly 400–600MB and unwieldy to open in
most tools. The binary matrix contains the **exact same complete
information** in 21MB, because each pair only needs one byte. Use
`decode_matrix.py` to get any slice of it you actually need — a specific
lookup, a bigger sample, or (if you really want it) the full 22M-row export.

## Quick start

```python
from decode_matrix import load_matrix, relation_for

matrix, meta = load_matrix()
print(relation_for(matrix, 43, 1))   # look up any pair by equation number
```

```python
from decode_matrix import export_sample
export_sample('my_own_sample.csv', n_pairs=200000)   # any size you want
```

```python
from decode_matrix import export_all
export_all('every_single_pair.csv')   # the complete 22,033,636 rows -- slow, large
```

## The relation labels, precisely

Derived from two Lean-proof statuses per pair: `forward` (does node_a imply
node_b?) and `backward` (does node_b imply node_a?), both proven or refuted
in the actual ETP Lean formalization:

| forward | backward | relation |
|---|---|---|
| true | true | `equivalent` |
| false | true | `stronger` |
| true | false | `weaker` |
| false | false | `incomparable` |
| (proof incomplete either way) | | `unresolved` |

This convention was verified extensively against the repo's own
`oracle.compare()` function throughout this project — zero mismatches
across every independent spot check performed.

## Equation numbering

Equation numbers (the `node` field) run 1 to 4,694, matching the original
ETP catalogue exactly — the same numbering used throughout
[teorth/equational_theories](https://github.com/teorth/equational_theories)
and [corpaci/semantic-diffchecking](https://github.com/corpaci/semantic-diffchecking).
`all_equations.json`'s `node` field and `matrix.bin`'s row/column index
(1-indexed) refer to the same equations consistently across every file here.
