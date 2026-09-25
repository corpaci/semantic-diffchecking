# Automated Semantic Equivalence Checking for Formal Equations

Code, data, and paper for a study of whether pairwise semantic equivalence
between formal statements (equivalent / stronger / weaker / incomparable)
can be checked automatically, using the Equational Theories Project (ETP)
as a real, proof-backed testbed.

**Verified working end-to-end before this repository was assembled:** every
module imports cleanly standalone, and the main notebook executes with zero
errors from a fresh clone (not just in the original working directory).

## Repository structure

```
src/                    Core library -- import these directly, or run the notebook
  condensation_engine.py    Exact finite-model checking (no embeddings, self-contained)
  baseline_metrics.py       Cosine similarity + tree edit distance, on raw equation text
  embeddings.py             Two embedding schemes: generic char n-grams, domain-specific tokenizers
  resampling.py             Natural Latents purification (cross-view Ridge regression)
  losses.py                 KL divergence, cross-entropy, rank-based info gain, signed LLR, PMI
  rich_model_counting.py    Executes real equation-checking code against 35,699 candidate magmas
  rule_based_clean.py       Clean (bug-fixed) rule-based classifier over algebraic properties
  embeddings_enhanced.py    Family-specific tokenizers for all 19 representations
  magma_fingerprints.py     Semantic view: satisfaction bits over ~25k finite magmas (exact,
                            vectorised) + sound counter-model rule for implication

notebooks/
  notebook.ipynb                  Full comparison notebook -- run this to reproduce all results.
                                   Includes Section 6B: symmetric baselines (cosine similarity,
                                   Euclidean distance, tree edit distance), proven directly on real
                                   data to give identical confusion-matrix rows for "stronger" vs
                                   "weaker" -- the precise, classifier-independent signature of why
                                   symmetric measures cannot recover direction.
  notebook_with_pairs200k.ipynb   Modified notebook with integrated pairs_200k.csv support.
                                   Toggle between pre-generated pairs (faster) and on-the-fly
                                   generation (original method). See DATA_INTEGRATION_GUIDE.md
  notebook_all_representations.ipynb
                                  All 19 representations of equations_representations_v2.json:
                                   5-vs-19 views, per-family/per-view ablations, symmetric
                                   controls, advanced metrics, direct-latent models, and the
                                   semantic (magma counter-model) setup that reaches ~99%.
  notebook_executed.ipynb         Same notebook, already executed at full scale (1,200 equations,
                                   15,000 pairs, 5 independent splits) -- open to see results directly

data/
  equations_representations.json   4,694 real ETP equations, 5 representations each
  oracle_labeled_pairs.csv         50,000 pairs, real Lean-proof-backed ground truth
  pairs_200k.csv                   45,000 pre-generated pairs for faster experimentation
  matrix.bin + decode_matrix.py    The COMPLETE relationship matrix -- all ~22M pairs, compact
  (see data/README.md for full details)

paper/
  paper.tex                  Workshop paper draft (VeriCodeGen @ NeurIPS 2026)
  references.bib
  neurips_stub.sty            STAND-IN style file for compilation testing only -- see paper/README below
  paper_preview.pdf           Compiled preview

outputs/                   Generated figures land here when the notebook runs
```

## Quick start

```bash
pip install numpy scipy scikit-learn pandas matplotlib seaborn jupyter nbformat nbconvert
cd notebooks
jupyter nbconvert --to notebook --execute --output my_run.ipynb notebook.ipynb
```

Or use `src/` directly in your own scripts:

```python
import sys
sys.path.insert(0, 'src')
sys.path.insert(0, 'data')
from condensation_engine import compare_equations
from decode_matrix import load_matrix, relation_for

result = compare_equations("x = y \u25c7 y", "x \u25c7 y = y \u25c7 x")
print(result)
```

## Data Integration: Using Pre-Generated Pairs

The repository now includes **two ways** to run the notebook:

### Option 1: Pre-generated pairs (NEW - Recommended for faster runs)
```bash
cd notebooks
jupyter notebook notebook_with_pairs200k.ipynb
# Set USE_PREGENERATED_PAIRS = True in Cell 5
```
- \u2705 **Faster**: No matrix generation overhead
- \u2705 **Reproducible**: Exact same pairs every run
- \u2705 Uses `data/pairs_200k.csv` (45K pairs) filtered to your equation sample

### Option 2: On-the-fly generation (Original method)
```bash
cd notebooks
jupyter notebook notebook_with_pairs200k.ipynb
# Set USE_PREGENERATED_PAIRS = False in Cell 5
```
- \u2705 **Flexible**: Generate exactly the pairs you need
- \u2705 **Controlled**: Guarantee symmetric pair inclusion

**See [DATA_INTEGRATION_GUIDE.md](DATA_INTEGRATION_GUIDE.md) for detailed information** on how all data components (equations, pairs, matrix) interconnect and flow through the pipeline.

## Headline results

| Approach | Best result |
|---|---|
| Symmetric similarity (cosine, Euclidean, PMI) | 0% weaker recall -- proven mathematically incapable of direction |
| Embedding + directional loss, per-view, trained classifier | 40.2% accuracy |
| ...validated at full scale (21M held-out pairs) | 45.9--46.6% accuracy |
| Exact finite-model verification (executes real equation-checking code) | 90.4% precision / 98.6% recall on confident calls, 9--32% coverage |
| Clean rule-based classifier (property differences, no training) | 20.8% accuracy -- below chance, a deliberate negative result |

Full trial log with confusion matrices for every method: see the paper draft
in `paper/`, or the earlier project documentation referenced there.

## Key findings, in one paragraph each

**Any symmetric comparison function is provably incapable of distinguishing
"stronger" from "weaker."** Proven directly: cosine similarity returns
bit-identical floating point values for `f(A,B)` and `f(B,A)`. Confirmed
empirically across every symmetric measure tested (cosine similarity,
Euclidean distance, tree edit distance -- see Section 6B of the notebook),
with the precise, classifier-independent signature: for every symmetric
measure, the "stronger" and "weaker" rows of the confusion matrix are
exactly, digit-for-digit identical, at full scale (verified on real counts
in the hundreds per cell, not just a small test sample).

**Keeping multiple representations separate through scoring ("late fusion")
consistently outperforms pooling them into one summary first.** This one
architectural choice roughly doubled accuracy in every comparison run.

**Exact verification (executing real equation-checking code against actual
candidate structures) is far more precise than any embedding-based
approximation, but covers only a minority of pairs** -- a genuine
precision/coverage tradeoff, not solved by any method tested here.

**Two real implementation bugs were found and fixed during this project,**
both of which produced misleadingly high accuracy before diagnosis: a
float32 precision failure that silently produced NaN and a fake 79%
accuracy, and a feature-leakage mechanism (resolvability information
correlating with the true label for reasons unrelated to logical content)
that produced a fake 97.68% accuracy. Both are documented in detail in the
paper's Limitations section, in case they generalize to similar pipelines.

## Citing / reusing

If you build on this, please cite the Equational Theories Project
(teorth/equational_theories) as the source dataset, and the Natural Latents
papers (Wentworth & Lorell, 2025) for the theoretical framework the
resampling/purification step is based on. Full references in
`paper/references.bib`.
