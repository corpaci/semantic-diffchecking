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

notebooks/
  notebook.ipynb             Full comparison notebook -- run this to reproduce all results
  notebook_executed.ipynb    Same notebook, already executed -- open to see results directly

data/
  equations_representations.json   4,694 real ETP equations, 5 representations each
  oracle_labeled_pairs.csv          50,000 pairs, real Lean-proof-backed ground truth
  matrix.bin + decode_matrix.py     The COMPLETE relationship matrix -- all ~22M pairs, compact
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
empirically across every symmetric measure tested, with zero exceptions.

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
