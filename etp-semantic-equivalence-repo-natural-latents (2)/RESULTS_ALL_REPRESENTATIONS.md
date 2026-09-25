# Results: all 19 representations, and the semantic (magma) setup

Source notebook: `notebooks/notebook_all_representations.ipynb`, executed end
to end (about 41 minutes on 4 CPUs, no errors).
Data: `data/equations_representations_v2.json` (19 representations per
equation) and the exact ETP relationship matrix (`data/matrix.bin`).

## Setup

| Setting | Value |
|---|---|
| Equations | 4,612 have all 19 representations (82 lack `natural_language`); a random sample of 1,200 is used for the learned models |
| Pairs | 15,000 ordered pairs (7,500 unordered × both directions), drawn from the exact matrix |
| Label counts | equivalent 1,608 · stronger 3,815 · weaker 3,815 · incomparable 5,762 |
| Evaluation | node-held-out splits (test equations never seen in training), 5 seeds, mean ± std |
| Embeddings | generic char 2–4-gram TF-IDF, and family-specific tokenizers (`src/embeddings_enhanced.py`); both raw and resampled (Natural Latents Ridge purification across the other 18 views); 8-d SVD latent per view |

Label convention (from `data/decode_matrix.py`): `equivalent` means A⇒B and
B⇒A; `stronger` means only B⇒A; `weaker` means only A⇒B; `incomparable`
means neither.

## Headline results (balanced accuracy, node-held-out, mean of 5 splits)

| Approach | Balanced acc. | Accuracy |
|---|---|---|
| Symmetric baselines (cosine, Euclidean, tree edit, tree kernel) | 0.408 (best) | 0.396 |
| Loss features (KL + CE + Rank + LLR), **original 5 views**, RF | 0.412 | 0.365 |
| Loss features, **all 19 views**, RF | 0.468 | 0.453 |
| Loss features, 19 views, gradient boosting + swap-consistency | 0.488 | 0.539 |
| Embedding "super-model" (Mix + Wasserstein + compression + algebraic + edit), gradient boosting | 0.675 | 0.712 |
| **Direct latents [z(A), z(B), z(A)−z(B)], 19 views, gradient boosting** | **0.778** | **0.802** |
| Structural invariants of the `formal` view only, gradient boosting | 0.873 | 0.874 |
| **Magma counter-model rule, NO training** | **0.997** | **0.996** |
| Semantic + structural + 19-view features, gradient boosting + swap-consistency | 0.997 | 0.995 |

### Full scale (no sampling, no training)

The magma rule was also scored on every resolvable pair of the complete ETP
matrix:

| Level | Result |
|---|---|
| Implication (22,033,446 ordered pairs) | accuracy **0.9971**; true implications wrongly refuted: **0** |
| 4-class (11,014,285 unordered pairs) | accuracy **0.9942**, balanced accuracy **0.9956** |

Every error is one-sided: a false implication that no magma in the bank
refutes, so the predicted relation is too strong.

## 5 views vs 19 views (Random Forest, Mix features)

| Latent set | 5 views | 19 views |
|---|---|---|
| Generic, RAW | 0.399 | 0.468 |
| Generic, RESAMPLED | 0.401 | 0.467 |
| Family-specific, RAW | 0.394 | 0.468 |
| Family-specific, RESAMPLED | 0.412 | 0.465 |
| Direct latents, family-specific resampled, gradient boosting | 0.689 | 0.730 |

## Which representation families matter (best latent set: Generic, RAW)

| Family | This family alone | All 19 views except this family |
|---|---|---|
| natural | 0.422 | 0.448 |
| structural | 0.415 | 0.454 |
| code | 0.393 | 0.462 |
| formal | 0.349 | 0.467 |
| confusable | 0.331 | 0.469 |

All 19 views together score 0.468. The top single views are `word_problem`
(0.384), `graphviz` (0.363), `text` (0.353), `py_cayley_table` (0.348) and
`text2` (0.347).

## Magma bank (25,637 magmas)

| Family | Count | Share of false implications (in sample) refuted alone |
|---|---|---|
| all size-2 | 16 | 0.910 |
| all size-3 | 19,683 | 0.964 |
| affine a·x+b·y+c mod n, n=2..11 (checked symbolically) | 4,355 | 0.88–0.91 per n |
| translation-invariant x+f(y−x) mod n, n=3..6 | 1,083 | 0.14–0.67 |
| random size 3 / 4 | 500 | 0.37 / 0.04 |

Adding all size-3 magmas raised full-scale implication accuracy from 0.9906
to 0.9971. Adding larger translation-invariant magmas (n=7, 8) added nothing.

## Findings

1. **All 19 views help the embedding pipeline** (+6–7 points), but no
   single family dominates.
2. **The loss scalars were the bottleneck.** Direct latents lift 0.47 to
   0.78, from the same embeddings.
3. **Symmetric measures are provably direction-blind.** The `stronger` and
   `weaker` confusion rows were identical for all 10 symmetric methods.
4. **Measuring meaning beats embedding text.** The magma counter-model rule
   is sound, needs no training, and reaches about 99.5% at full scale.
   Learned models on top match it but don't beat it.

## Recommended next steps

1. Grow the magma bank where errors remain: linear magmas over
   non-commutative rings, larger translation-invariant magmas evaluated
   symbolically, and size-4 magmas only for still-unresolved equations.
   Added magmas can only turn "not refuted" into "refuted", so accuracy
   cannot go down.
2. Prove the "holds" side: run Vampire, E or Prover9 on the `tptp`/`smtlib`
   views, with short timeouts, on unrefuted pairs.
3. Transitive closure: if A⇒B is proven and A⇒C is refuted, then B⇒C is
   refuted.
4. Train a learned model only on the residual pairs, using semantic +
   structural + 19-view features with swap-consistency.
5. If a neural model is wanted: order or box embeddings (A⇒B ⇔ box(A) ⊆
   box(B)), which are directional by construction.
