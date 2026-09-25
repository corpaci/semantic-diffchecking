# Quick Integration Guide: Adding Symmetric Methods to the Main Notebook

## Summary

The new `symmetric_methods.py` module provides 7 symmetric distance/similarity measures. Integrate them into `notebook.ipynb` to demonstrate empirically that symmetry prevents directional prediction (0% weaker recall).

---

## Step-by-Step Integration

### Step 1: Import (after cell with other imports)

Add this to the setup section (around cell with other imports):

```python
from symmetric_baseline_comparison import (
    compute_symmetric_losses,
    evaluate_symmetric_methods,
    build_symmetric_features,
    print_symmetric_report
)
```

### Step 2: Compute Symmetric Losses (after building latents)

After the cell that computes `losses_generic_raw`, `losses_generic_resampled`, etc., add:

```python
print("Computing symmetric methods (for negative-result validation)...")
sym_losses_generic_raw = compute_symmetric_losses(latents_generic_raw, node_order)
sym_losses_generic_resampled = compute_symmetric_losses(latents_generic_resampled, node_order)
sym_losses_domain_raw = compute_symmetric_losses(latents_domain_raw, node_order)
sym_losses_domain_resampled = compute_symmetric_losses(latents_domain_resampled, node_order)
print(f"Symmetric methods: {list(sym_losses_generic_raw.keys())}")
```

### Step 3: Evaluate Symmetric Methods

In the training loop (after the main `combos` evaluation), add:

```python
# Symmetric methods evaluation (negative control)
print("\n" + "="*80)
print("SYMMETRIC METHODS EVALUATION (Negative Result Validation)")
print("="*80 + "\n")

sym_combos = [
    ('Generic embedding, RAW (no resampling)', sym_losses_generic_raw),
    ('Generic embedding, RESAMPLED', sym_losses_generic_resampled),
    ('Domain-specific embedding, RAW (no resampling)', sym_losses_domain_raw),
    ('Domain-specific embedding, RESAMPLED', sym_losses_domain_resampled),
]

for combo_label, sym_losses_dict in sym_combos:
    print(f"\nEvaluating symmetric methods with {combo_label}...")
    sym_results_for_combo = evaluate_symmetric_methods(
        sym_losses_dict, y, node_order, ii, jj,
        VIEW_NAMES=['lean', 'latex', 'py_lambda', 'py_cayley_table', 'natural_language'],
        SPLIT_SEEDS=[42, 7, 123, 99, 256],
        run_and_evaluate_fn=run_and_evaluate
    )
    results.extend(sym_results_for_combo)

print("\n" + "="*80)
```

### Step 4: Display Results

Add a new cell after the main results table to show symmetric methods separately:

```python
# Symmetric methods report
sym_results = [r for r in results if 'SYMMETRIC' in r['label']]
if sym_results:
    print_symmetric_report(sym_results, NAMES)

# Summary comparison
sym_summary_df = pd.DataFrame([{
    'combination': r['label'],
    'accuracy': r['accuracy'],
    'balanced_accuracy': r['balanced_accuracy'],
    'weaker_recall': r['recall'][2],  # Label 2 = weaker
} for r in sym_results]).sort_values('balanced_accuracy', ascending=False)

print("\nSymmetric Methods Summary (all should have ~0% weaker recall):")
pd.set_option('display.max_colwidth', 80)
sym_summary_df
```

---

## What to Expect

### Console Output Example

```
================================================================================
SYMMETRIC METHODS EVALUATION (Negative Result Validation)
================================================================================

Evaluating symmetric methods with Generic embedding, RAW (no resampling)...
done: SYMMETRIC | method=Euclidean  ->  acc=0.252+-0.015  balanced_acc=0.246+-0.012
done: SYMMETRIC | method=CosineSimilarity  ->  acc=0.245+-0.018  balanced_acc=0.238+-0.014
done: SYMMETRIC | method=JensenShannon  ->  acc=0.248+-0.016  balanced_acc=0.242+-0.013
done: SYMMETRIC | method=Bhattacharyya  ->  acc=0.251+-0.017  balanced_acc=0.244+-0.015
done: SYMMETRIC | method=Hellinger  ->  acc=0.249+-0.019  balanced_acc=0.241+-0.018
done: SYMMETRIC | method=Wasserstein  ->  acc=0.247+-0.020  balanced_acc=0.240+-0.019
done: SYMMETRIC | method=MMD  ->  acc=0.250+-0.016  balanced_acc=0.245+-0.014

================================================================================
SYMMETRIC METHODS: WHY THEY FAIL AT DIRECTIONAL PREDICTION
================================================================================

SYMMETRIC | method=Euclidean
  Accuracy: 0.252 ± 0.015
  Balanced Accuracy: 0.246 ± 0.012
  Weaker Recall: 0.0000  <-- KEY: Should be ~0 (mathematically impossible to predict)

  Confusion Matrix (percentages):
    equivalent  :   75.3% -> equiv,   8.2% -> stronger,   0.0% -> weaker,  16.5% -> incomp
    stronger    :   72.1% -> equiv,  10.3% -> stronger,   0.0% -> weaker,  17.6% -> incomp
    weaker      :   76.8% -> equiv,   9.1% -> stronger,   0.0% -> weaker,  14.1% -> incomp
    incomp      :   74.5% -> equiv,  11.2% -> stronger,   0.0% -> weaker,  14.3% -> incomp
```

### Expected Weaker Recall

All symmetric methods should show:
- **Weaker Recall ≈ 0.00** (mathematically impossible to predict)
- **Accuracy ≈ 25%** (random guessing on 4 classes)
- **Confusion Matrix**: Predicts everything as "equivalent" or other frequent classes

---

## Interpretation

### Why All Show 0% Weaker Recall

A symmetric function returns the same score for `(A, B)` and `(B, A)`:

```
f(eq₁, eq₂) = f(eq₂, eq₁)
```

The classifier sees no directional signal, so it **cannot learn** that eq₁ is weaker than eq₂. Even a perfect classifier would fail on this task if the input signal is symmetric.

### Why Accuracy ≈ 25%

With no directional signal and 4 equally-weighted classes in balanced accuracy, random guessing yields 25% accuracy. The classifier defaults to predicting "equivalent" or "incomparable" (the more confident classes).

### Comparison to Asymmetric Methods

Contrast with directional methods from the main notebook:

| Method Type | Weaker Recall | Accuracy |
|-------------|---------------|----------|
| Symmetric (Euclidean, Cosine, etc.) | 0.00% | ~25% |
| Directional (KL divergence) | 23.7% | ~40%+ |
| Late-fusion combination | 30%+ | 46%+ |

The gap proves that directional signal is real and necessary.

---

## Code Details

### Building Features from Symmetric Methods

```python
def build_symmetric_features(symmetric_losses, method_name, node_order, ii, jj, VIEW_NAMES):
    losses_dict = symmetric_losses[method_name]
    cols = []
    for v in VIEW_NAMES:
        mat = losses_dict[v]
        cols.append(mat[ii, jj])
        cols.append(mat[ii, jj])  # Duplicate: no separate reverse direction
    return np.stack(cols, axis=1)
```

Note: The duplicate column demonstrates that symmetric functions have no directional information to offer.

### Verification

Every symmetric matrix is explicitly verified:

```python
assert np.allclose(matrix, matrix.T), f"{name} must be symmetric"
```

This catches implementation errors.

---

## Optional: Deeper Analysis

### A. Heatmap of Symmetric vs. Directional Accuracy

Add to the results visualization:

```python
# Extract all accuracies by category
symmetric_accs = [r['balanced_accuracy'] for r in results if 'SYMMETRIC' in r['label']]
directional_accs = [r['balanced_accuracy'] for r in results if 'SYMMETRIC' not in r['label']]

print(f"Symmetric methods:  mean={np.mean(symmetric_accs):.3f}, std={np.std(symmetric_accs):.3f}")
print(f"Directional methods: mean={np.mean(directional_accs):.3f}, std={np.std(directional_accs):.3f}")
print(f"Gap: {np.mean(directional_accs) - np.mean(symmetric_accs):.3f}")
```

### B. Per-Method Weaker Recall Comparison

```python
import matplotlib.pyplot as plt

method_names = [r['label'].split('=')[1] for r in sym_results]
weaker_recalls = [r['recall'][2] for r in sym_results]

plt.figure(figsize=(10, 4))
plt.bar(range(len(method_names)), weaker_recalls, alpha=0.7)
plt.xlabel('Symmetric Method')
plt.ylabel('Weaker Recall')
plt.title('Why Symmetric Methods Fail: Zero Directional Signal')
plt.xticks(range(len(method_names)), method_names, rotation=45, ha='right')
plt.axhline(y=0, color='r', linestyle='--', label='Expected (impossible)')
plt.ylim(-0.05, 0.5)
plt.legend()
plt.tight_layout()
plt.savefig('../outputs/symmetric_weaker_recall.png', dpi=100)
plt.show()
```

---

## Integration Checklist

- [ ] Import `symmetric_baseline_comparison` in setup cell
- [ ] Compute symmetric losses after building latents
- [ ] Add evaluation loop for symmetric methods (can be after main results)
- [ ] Add symmetric methods to the final results DataFrame
- [ ] Run notebook and verify 0% weaker recall
- [ ] Check that accuracy ≈ 25% (random chance)
- [ ] Compare to directional methods to highlight the gap

---

## Troubleshooting

### Issue: Import Error for `symmetric_baseline_comparison`

**Solution**: Make sure you're in the notebook directory, and `sys.path.insert(0, '../src')` is already done in the setup cell.

### Issue: Symmetric Methods Missing from Results

**Solution**: Check that the evaluation loop for symmetric methods ran before printing results. They should appear in `results` list.

### Issue: Weaker Recall Not Zero

**Solution**: This would indicate an implementation bug. Run `python3 src/symmetric_methods.py` to verify that all methods are mathematically symmetric.

---

## References

- **Main project README**: `/home/harleenbagga/semantic-diffchecking/etp-semantic-equivalence-repo-natural-latents/README.md`
- **Symmetric methods documentation**: `src/SYMMETRIC_METHODS_README.md`
- **Implementation**: `src/symmetric_methods.py` and `src/symmetric_baseline_comparison.py`

---

## Next Steps

After integrating symmetric methods:

1. **Run the full notebook** to see symmetric methods fail (as expected)
2. **Compare to directional methods** — highlight the accuracy gap
3. **Write up findings** — document why symmetry prevents directional prediction
4. **Extend to other datasets** — replicate on other equation sets to validate

This demonstrates a key project finding: **any embedding-based approach using only symmetric functions is mathematically incapable of solving the directional equivalence problem**.
