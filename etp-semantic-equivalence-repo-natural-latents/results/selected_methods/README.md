# Selected methods: confusion matrices

Produced by:

```bash
python run_all.py --match 'Representation-specific, (RAW|RESAMPLED) \| Direct latents|STRUCT (Weisfeiler|Structural invariants|WL \(h=3\) \+ structural invariants$)|Condensation|Magma counter-model' --out results/selected_methods
```

Setup: 1,200 equations, 15,000 ordered pairs, 5 node-held-out splits. Learned
methods use HistGradientBoostingClassifier. Confusion matrices are summed over
the 5 test sets (6,786 test predictions).

| Method | Accuracy | Balanced acc. | Macro F1 |
|---|---|---|---|
| Magma counter-model rule (no training) | 0.996 | 0.997 | 0.996 |
| WL (h=3) + structural invariants | 0.949 | 0.950 | 0.952 |
| Structural invariants | 0.875 | 0.873 | 0.867 |
| Representation-specific RAW direct latents | 0.809 | 0.788 | 0.787 |
| WL subtree features (h=3) | 0.805 | 0.788 | 0.784 |
| Representation-specific RESAMPLED direct latents | 0.788 | 0.766 | 0.763 |
| Condensation engine, corrected | 0.481 | 0.368 | 0.357 |
| Condensation engine, as published | 0.260 | 0.226 | 0.241 |

## Condensation engine: how to read its numbers

`src/condensation_engine.py` compares the model sets of two equations over all
19,699 magmas of size 2 and 3, using conditional entropy.

- **Coverage.** Only 68.7% of equations have any model in that universe, so the
  engine can answer only **47.1% of pairs**. On the rest it returns
  `unresolvable`, scored here as `incomparable`. That is why its overall
  numbers are low.
- **Bug in the published version.** Its entropy function returns H(0) = 0, so
  two equations with *disjoint* model sets count as implying each other. That
  sends 1,504 truly incomparable pairs to `equivalent`. The corrected version
  treats Loss = 0 only when P(B|A) = 1.
- **On the pairs it can answer** (3,322 test pairs):

| Version | Accuracy | Balanced acc. |
|---|---|---|
| as published | 0.522 | 0.842 |
| corrected | 0.974 | 0.986 |

The magma counter-model rule is the same idea as the corrected engine, but with
a larger bank: affine and translation-invariant magmas up to size 11. Every
equation then has models, so every pair gets an answer.
