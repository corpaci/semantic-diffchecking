# Notes on the approaches

A reference for every approach tried in this project to predict the relation
between two ETP equations. For each one: what it does, what it reads, whether it
can tell direction, whether it trains, how well it did, and when to use it.

Code for every approach lives in `pipeline/methods/` (run with `python run_all.py`);
the algorithms themselves are in `src/`. The full comparison sheet is
`results/method_comparison.xlsx`.

---

## 0. The task and how everything is scored

**Task.** Given an ordered pair of equations (A, B), predict one of:

| Label | Meaning |
|---|---|
| `equivalent` | A ⇒ B and B ⇒ A |
| `stronger` | only B ⇒ A |
| `weaker` | only A ⇒ B |
| `incomparable` | neither |

Ground truth comes from the ETP implication matrix (Lean proofs and verified
counterexamples), the same source as `oracle/oracle.py`.

**Evaluation protocol (identical for every approach):**
- 1,200 randomly sampled equations that have all 19 representations;
  15,000 ordered pairs (7,500 unordered pairs in both directions).
- **Node-held-out splits:** 30% of the *equations* are held out, and test pairs
  contain only held-out equations. No test equation is ever seen in training, in
  any pairing. 5 random splits; mean ± std reported.
- **One base classifier** for every learned approach (gradient boosting by
  default, `--classifier rf` for the Random Forest).
- **Metrics:** accuracy, balanced accuracy, and per-class precision, recall,
  specificity, F1 and accuracy, plus macro and weighted averages, Cohen's
  kappa, MCC, and the pooled confusion matrix.

**Why balanced accuracy is the headline:** the classes are unbalanced
(incomparable 38%, stronger 25%, weaker 25%, equivalent 11%). Balanced accuracy is
the mean per-class recall, so chance is 0.25 regardless of class sizes.

**The direction test:** a *symmetric* method gives (A, B) and (B, A) the same
features, so it must give them the same prediction. Every test pair appears in both
orders, so for such a method the `stronger` and `weaker` rows of the confusion
matrix are **exactly identical**. The sheet checks this for every method.

---

## 1. Symmetric similarity baselines (control group)

**Idea.** Measure how similar the two equations are.

| Variant | Reads | Notes |
|---|---|---|
| Cosine on TF-IDF (generic / family / representation-specific) | all 19 representations | independent of Natural Latents; one column per view |
| Tree edit distance, equation only | `formal` | Zhang–Shasha distance between the two equation trees |
| Edit distance, all 19 representations | all 19, each in its own syntax | tree edit distance on native trees (Lean, TPTP, SMT-LIB s-expressions, Python AST, JSON, …); token Levenshtein on sequential/text views |
| Edit distance per representation | one view each | 18 single-view variants (formal is the row above) |
| Cosine / Euclidean on latents | Natural Latents | in `natural_latents.py` |
| Tree convolution kernel, Wasserstein | formal / latents | also symmetric |

**Direction-aware:** no, and provably so; the confusion rows are identical every time.
**Result:** about 0.30–0.41 balanced accuracy.
**Use:** only as a control. Similarity can separate *equivalent* from
*incomparable* somewhat, but can never tell *stronger* from *weaker*.

---

## 2. Natural Latents + entropy-type losses (the original pipeline)

**Idea.**
1. Embed each representation with TF-IDF (generic char n-grams,
   family-specific, or representation-specific tokenizers).
2. Compress each view to an 8-number latent (SVD), either **raw** or
   **resampled**: reconstructed from the other 18 views by cross-validated
   Ridge regression, which keeps only information the views share (Natural
   Latents).
3. Between two equations' latents compute directional scores: KL divergence,
   cross-entropy, rank info gain, signed LLR (and PMI as a symmetric control),
   using local Gaussians fitted from 10 nearest neighbours.
4. Feed the scores, in both directions, to the classifier.

**Direction-aware:** weakly. The KL-type scores differ between directions only
because the local spread around A and around B differ.
**Results:** single losses 0.43–0.46; **Mix (all 4 losses, 19 views) about 0.47**
(0.49 with gradient boosting); original 5 views 0.40–0.41; PMI 0.37–0.38.
- 19 views beat 5 views by about 6–7 points.
- Resampled vs raw, and generic vs family-specific vs representation-specific,
  all end up within about 1 point at 19 views.

**Weakness:** the loss scores measure closeness and density, not containment,
and squeeze 16 numbers per view into 8. Implication depends on what each equation
*is*, which a distance can't express.

### 2b. Direct latents
Feed the latents themselves, **[z(A), z(B), z(A) − z(B)]** over 19 views
(456 features), instead of losses between them.
**Result: about 0.78** (0.786 with representation-specific raw), from the same
embeddings. Removing the loss bottleneck is the single biggest gain within the
embedding approach. `z(A) − z(B)` flips sign when A and B are swapped, which gives
the classifier explicit direction.

### 2c. Embedding schemes compared
| Scheme | Single formal/tree view | 19 views combined |
|---|---|---|
| Generic char n-grams | ~0.32 | Mix 0.47, direct 0.78 |
| Family-specific (5 tokenizers) | ~0.32 | Mix 0.47, direct 0.73–0.77 |
| **Representation-specific (19 parsers)** | **~0.38–0.41** (+5–9 pts) | Mix 0.46, direct 0.77–0.79 |

Syntax-aware parsing makes each formal, code or tree view clearly more
informative on its own. With 19 redundant views combined, the advantage mostly
disappears. On natural-language views it is slightly worse.

---

## 3. Advanced metrics

| Metric | What it is | Direction | Result |
|---|---|---|---|
| Wasserstein-1D on latents | distance between latent profiles as distributions | symmetric | ~0.31 |
| Compression (NCD + gain) | how much A helps gzip compress B, and vice versa | weakly directional | ~0.35 |
| Algebraic property vectors | 11 hand-made counts (variables, ops, depth, …) of A and B, and their difference | directional | ~0.65 |
| Edit-script features | Levenshtein, tokens added/removed/shared, depth change, … | directional | ~0.59 |
| Super-model (Mix + all above) | everything in one model | directional | ~0.63 (RF) / 0.675 (gradient boosting) |

**Lesson:** the useful ones (algebraic, edit script) describe the equations' own
structure, not a distance between them.

---

## 4. Structural features of the equation tree

### 4a. Structural invariants (13 numbers per equation)
Operations per side, depth per side, number of variables, **variables on only one
side**, **whether a side is a bare variable**, leftmost/rightmost variable agreement,
maximum variable multiplicity, total occurrences. Pair features
[g(A), g(B), g(A) − g(B)].
**Result: about 0.87.** Global facts about each law predict a lot, because laws
like "x = (term without y)" force strong collapse.

### 4b. Weisfeiler–Lehman (WL) subtree features
Relabel each tree node with its label plus its children's labels, repeated for
h rounds, and count every pattern. The result is a bag of subtree shapes. Features
are invariant to renaming variables and to swapping the sides of `=`; the
pattern vocabulary is fitted on training equations only.
**Result:** h=1 0.72, **h=2–3 about 0.79**; deeper rounds add nothing.
The original Random Forest gets 0.70, so gradient boosting matters here.

### 4c. WL + structural invariants
**Result: about 0.95**, the best approach that doesn't execute the equations.
WL sees local shape, the invariants see global facts, and each covers the
other's blind spot. Adding the 19-view text latents on top slightly *hurts*
(0.94): the text views add nothing beyond the tree.

---

## 5. Threshold rules (no classifier)

**On the entropy-type embedding losses:** average a loss over views into one
score S(A→B), then either use one threshold per direction, or a sum threshold
for *equivalent* plus a signed-difference threshold for direction. Thresholds
are tuned on training pairs.
**Result: 0.26–0.28**, essentially chance. These losses aren't monotone in
the relation, so no single cut-off separates the classes.

**On the magma conditional entropy:** H(B | A), computed from P(B holds | A
holds) over the magma bank, is 0 exactly when every magma satisfying A also
satisfies B. Rule: A ⇒ B if H ≤ ε.
**Result: about 0.997** at ε = 0, and it only falls as ε grows. With ε = 0 this
is exactly the counter-model rule below.

**Lesson:** thresholds work when the entropy is over *models* of the equations,
not over text embeddings. Compute it in float64: in float32, `1 − 1e−12`
rounds to exactly 1, which silently produces NaN.

---

## 6. Semantic approach: executing the equations (magma counter-models)

**Idea.** The `py_cayley_table` representation is executable, so check each
equation against a bank of about 25,600 finite magmas:
- all 16 size-2 magmas;
- all 19,683 size-3 magmas;
- every affine magma a·x + b·y + c mod n for n = 2..11, checked *symbolically*;
- translation-invariant magmas x + f(y − x) mod n for n = 3..6;
- a few hundred random tables of size 3 and 4.

This gives each equation a **fingerprint**: which magmas satisfy it.

**Rule (no training):** A ⇒ B unless some magma satisfies A but not B.
- A counter-model is a **proof** that A ⇏ B. It never wrongly refutes a true
  implication; this was verified on all 22M ordered pairs.
- "No counter-model found" is a guess that A ⇒ B. That is the only source of error.

**Results:** **0.997** on the held-out splits; on **all 11M resolvable ETP pairs,
0.994 accuracy, 0.996 balanced**. Learned models on semantic features reach
0.996–0.997: they match the rule but don't beat it.
**Remaining errors:** false implications the bank can't refute. Every one is
"predicted too strong", never the other way.

**Relation to the ETP oracle (`oracle/oracle.py`):** the oracle *looks up* proven
answers and only covers the 4,694 catalogue equations. The magma rule
*computes* answers for any parseable equation, so it's the natural fallback the
oracle's own notes ask for when an equation is outside the catalogue.

---

## 7. Summary ranking (1,200 equations, node-held-out, balanced accuracy)

| Approach | Balanced acc. | Training | Direction |
|---|---|---|---|
| Threshold on embedding losses | 0.26–0.28 | thresholds only | weak |
| Symmetric similarity (cosine, edit distance, …) | 0.30–0.41 | yes | none, provably |
| Natural Latents entropy losses (Mix, 19 views) | 0.47–0.49 | yes | weak |
| Embedding super-model | 0.63–0.675 | yes | yes |
| Direct latents, 19 views | 0.78 | yes | yes |
| WL subtree features | 0.79 | yes | yes |
| Structural invariants | 0.87 | yes | yes |
| **WL + structural invariants** | **0.95** | yes | yes |
| **Magma counter-model rule / entropy threshold** | **0.997** | **none** | yes (exact on refutations) |

`results/method_comparison.xlsx` has the authoritative numbers for every one of
the 112 methods under the same base classifier.

## 8. Take-aways

1. **Direction needs asymmetric features.** No symmetric score can separate
   stronger from weaker, whatever the classifier.
2. **Don't compress pairs into distances.** Feeding each equation's own
   description plus the difference beats any distance or divergence between them.
3. **Structure beats text.** 19 text encodings of the same tree add robustness,
   not information. Reading the tree directly (WL + invariants) is much stronger.
4. **Meaning beats structure.** Implication is about models, so checking models
   is exact on refutations and about 99.5% overall with no training.
5. **Next steps:**
   - grow the magma bank where errors remain;
   - add a prover (Vampire, Prover9, egg) to *certify* the "implies" side;
   - apply transitive closure;
   - use learned models only for whatever remains unresolved.
