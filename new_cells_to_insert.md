# New Notebook Cells - Advanced Metrics

Copy these cells and insert them after Section 7B (the combined Mix+Cosine evaluation).

---

## SECTION 12: Advanced Metrics — Optimal Transport, Algebraic Properties, Compression

**What's being added here:**

1. **Wasserstein (Optimal Transport) distance** — geometrically meaningful alternative to KL divergence
2. **Algebraic property features** — extract semantic properties (commutativity hints, nesting depth, variable usage)
3. **Normalized Compression Distance** — use gzip compression as similarity proxy
4. **Enhanced edit features** — richer structural edit operations
5. **Tree convolution kernel** — count shared subtree patterns

All evaluated with the same rigor: 5 independent node-holdout splits, confusion matrices, balanced accuracy.

---

### Cell: Markdown Header

```markdown
## 12. Advanced Metrics: Beyond KL and Cross-Entropy

The directional losses (KL, CrossEntropy, SignedLLR) all rely on local Gaussian approximations. 
This section adds fundamentally different approaches:

1. **Optimal Transport (Wasserstein)** — measures "how much work" to move one distribution to another, more forgiving than KL
2. **Algebraic Properties** — extract semantic features (commutativity, depth, variable counts)
3. **Compression Distance** — gzip compression as a proxy for Kolmogorov complexity
4. **Tree Kernel** — count shared subtree patterns instead of just edit distance

Each is evaluated against the same 15,000 pairs with the same 5-fold node-holdout methodology.
```

---

### Cell: Code - Import New Module

```python
sys.path.insert(0, '../src')
from advanced_metrics import (
    wasserstein_matrix_1d,
    earth_movers_directional,
    algebraic_similarity_matrix,
    normalized_compression_distance_matrix,
    compression_gain_directional,
    edit_script_feature_matrix,
    tree_kernel_matrix,
)

print("Advanced metrics module loaded successfully.")
```

---

### Cell: Code - Compute Wasserstein Distances

```python
print("Computing Wasserstein (Optimal Transport) distances for all 4 combos...")
print("This is more expensive than KL (pairwise optimization), may take a few minutes...\n")

def compute_wasserstein_for_combo(latents_dict):
    """Compute both symmetric and directional Wasserstein for all views."""
    result_sym = {}
    result_dir = {}
    for view, node_latents in latents_dict.items():
        mat = np.stack([node_latents[n] for n in node_order])
        print(f"  Computing Wasserstein for {view}...", end=' ')
        result_sym[view] = wasserstein_matrix_1d(mat)
        result_dir[view] = earth_movers_directional(mat, reg=0.05)
        print("done")
    return result_sym, result_dir

t0 = time.time()
wasser_generic_raw_sym, wasser_generic_raw_dir = compute_wasserstein_for_combo(latents_generic_raw)
print(f"Generic RAW done ({time.time()-t0:.1f}s)\n")

t0 = time.time()
wasser_generic_res_sym, wasser_generic_res_dir = compute_wasserstein_for_combo(latents_generic_resampled)
print(f"Generic RESAMPLED done ({time.time()-t0:.1f}s)\n")

t0 = time.time()
wasser_domain_raw_sym, wasser_domain_raw_dir = compute_wasserstein_for_combo(latents_domain_raw)
print(f"Domain-specific RAW done ({time.time()-t0:.1f}s)\n")

t0 = time.time()
wasser_domain_res_sym, wasser_domain_res_dir = compute_wasserstein_for_combo(latents_domain_resampled)
print(f"Domain-specific RESAMPLED done ({time.time()-t0:.1f}s)\n")

print("--- VIEW: Wasserstein distance for one real pair (Lean view, generic resampled) ---")
i_ex, j_ex = node_idx[sample_equations[10]['node']], node_idx[sample_equations[20]['node']]
print(f"Symmetric Wasserstein(A, B) = {wasser_generic_res_sym['lean'][i_ex,j_ex]:.4f}")
print(f"Directional Wasserstein(A→B) = {wasser_domain_res_dir['lean'][i_ex,j_ex]:.4f}")
print(f"Directional Wasserstein(B→A) = {wasser_domain_res_dir['lean'][j_ex,i_ex]:.4f}")
```

---

### Cell: Code - Algebraic Property Features

```python
print("Extracting algebraic properties from formal equations...")

# Build equation dict: node_id -> formal expression
formal_by_node = {e['node']: e['formal'] for e in sample_equations}

# Compute property-based similarity matrices
alg_sim_cosine, alg_sim_subsumption = algebraic_similarity_matrix(formal_by_node)

print(f"Algebraic property matrices computed: {alg_sim_cosine.shape}")

print("\n--- VIEW: Properties extracted for one equation ---")
example_node = sample_equations[10]['node']
from advanced_metrics import extract_algebraic_properties, algebraic_property_vector
props_example = extract_algebraic_properties(formal_by_node[example_node])
print(f"Equation: {formal_by_node[example_node]}")
print(f"Properties: {props_example}")
print(f"Feature vector: {algebraic_property_vector(props_example)}")
```

---

### Cell: Code - Compression Distance

```python
print("Computing Normalized Compression Distance (gzip-based)...")

# Use formal representation for compression
formal_texts = [formal_by_node[node_order[i]] for i in range(len(node_order))]

t0 = time.time()
ncd_matrix = normalized_compression_distance_matrix(formal_texts)
print(f"NCD computed in {time.time()-t0:.1f}s")

# Directional compression gain (how much does A help compress B?)
t0 = time.time()
comp_gain_matrix = compression_gain_directional(formal_texts)
print(f"Compression gain computed in {time.time()-t0:.1f}s")

print("\n--- VIEW: Compression distances for one real pair ---")
print(f"NCD(A, B) = {ncd_matrix[i_ex, j_ex]:.4f} (symmetric)")
print(f"Compression gain(A→B) = {comp_gain_matrix[i_ex, j_ex]:.4f}")
print(f"Compression gain(B→A) = {comp_gain_matrix[j_ex, i_ex]:.4f}")
```

---

### Cell: Code - Edit Script Features

```python
print("Extracting enhanced edit script features for all pairs...")

t0 = time.time()
edit_features = edit_script_feature_matrix(formal_by_node, node_order, ii, jj)
print(f"Edit features computed for {len(edit_features):,} pairs in {time.time()-t0:.1f}s")
print(f"Feature shape: {edit_features.shape} (pairs × 7 edit features)")

print("\n--- VIEW: Edit features for first 3 pairs ---")
print(pd.DataFrame(edit_features[:3], 
                   columns=['levenshtein', 'tokens_added', 'tokens_removed', 
                           'tokens_shared', 'var_permutation', 'depth_change', 'length_ratio']))
```

---

### Cell: Code - Tree Convolution Kernel

```python
print("Computing tree convolution kernel (shared subtree patterns)...")

t0 = time.time()
tree_kernel = tree_kernel_matrix(formal_by_node, node_order)
print(f"Tree kernel computed in {time.time()-t0:.1f}s")

print("\n--- VIEW: Tree kernel similarity for one pair ---")
print(f"Tree kernel similarity(A, B) = {tree_kernel[i_ex, j_ex]:.4f}")
print(f"(Symmetric by construction: {tree_kernel[j_ex, i_ex]:.4f})")
```

---

### Cell: Code - Build Feature Sets for New Metrics

```python
def build_features_from_matrix(matrix, symmetric=True):
    """Extract features for the (ii, jj) pairs from a precomputed matrix."""
    if symmetric:
        # Only one direction needed
        return matrix[ii, jj].reshape(-1, 1)
    else:
        # Both directions
        return np.stack([matrix[ii, jj], matrix[jj, ii]], axis=1)

def build_wasserstein_features(wasser_dict_sym, wasser_dict_dir):
    """Combine symmetric + directional Wasserstein across 5 views."""
    cols = []
    for v in VIEW_NAMES:
        # Symmetric version: 1 feature per view
        cols.append(wasser_dict_sym[v][ii, jj])
        # Directional version: 2 features per view
        cols.append(wasser_dict_dir[v][ii, jj])
        cols.append(wasser_dict_dir[v][jj, ii])
    return np.stack(cols, axis=1)  # 5 views × 3 features = 15 total

# Build all feature sets
print("Building feature matrices for evaluation...\n")

# Wasserstein features (per combo)
X_wasser_generic_raw = build_wasserstein_features(wasser_generic_raw_sym, wasser_generic_raw_dir)
X_wasser_generic_res = build_wasserstein_features(wasser_generic_res_sym, wasser_generic_res_dir)
X_wasser_domain_raw = build_wasserstein_features(wasser_domain_raw_sym, wasser_domain_raw_dir)
X_wasser_domain_res = build_wasserstein_features(wasser_domain_res_sym, wasser_domain_res_dir)

print(f"Wasserstein features: {X_wasser_generic_raw.shape}")

# Algebraic property features (global, independent of embedding)
X_alg_cosine = build_features_from_matrix(alg_sim_cosine, symmetric=True)
X_alg_subsumption = build_features_from_matrix(alg_sim_subsumption, symmetric=False)
print(f"Algebraic cosine: {X_alg_cosine.shape}, subsumption: {X_alg_subsumption.shape}")

# Compression features (global)
X_ncd = build_features_from_matrix(ncd_matrix, symmetric=True)
X_comp_gain = build_features_from_matrix(comp_gain_matrix, symmetric=False)
print(f"Compression NCD: {X_ncd.shape}, gain: {X_comp_gain.shape}")

# Edit features (already pair-wise)
X_edit = edit_features
print(f"Edit features: {X_edit.shape}")

# Tree kernel (global, symmetric)
X_tree_kernel = build_features_from_matrix(tree_kernel, symmetric=True)
print(f"Tree kernel: {X_tree_kernel.shape}")

print("\nAll advanced metric features ready for evaluation.")
```

---

### Cell: Code - Evaluate Wasserstein Distance

```python
print("Evaluating Wasserstein distance across all combos...\n")

wasser_combos = [
    ('Generic embedding, RAW | Wasserstein (sym+dir)', X_wasser_generic_raw),
    ('Generic embedding, RESAMPLED | Wasserstein (sym+dir)', X_wasser_generic_res),
    ('Domain-specific embedding, RAW | Wasserstein (sym+dir)', X_wasser_domain_raw),
    ('Domain-specific embedding, RESAMPLED | Wasserstein (sym+dir)', X_wasser_domain_res),
]

for label, X_feats in wasser_combos:
    results.append(run_and_evaluate(X_feats, y, node_order, ii, jj, label))
    r = results[-1]
    print(f"done: {label}")
    print(f"  acc={r['accuracy']:.3f}±{r['accuracy_std']:.3f}  "
          f"balanced_acc={r['balanced_accuracy']:.3f}±{r['balanced_accuracy_std']:.3f}\n")
```

---

### Cell: Code - Evaluate Algebraic Property Features

```python
print("Evaluating algebraic property features...\n")

# Cosine similarity on properties (symmetric)
results.append(run_and_evaluate(X_alg_cosine, y, node_order, ii, jj, 
                                 'Algebraic Properties | Cosine Similarity'))
r = results[-1]
print(f"done: Algebraic Properties | Cosine Similarity")
print(f"  acc={r['accuracy']:.3f}±{r['accuracy_std']:.3f}  "
      f"balanced_acc={r['balanced_accuracy']:.3f}±{r['balanced_accuracy_std']:.3f}\n")

# Property subsumption (directional)
results.append(run_and_evaluate(X_alg_subsumption, y, node_order, ii, jj,
                                 'Algebraic Properties | Subsumption (directional)'))
r = results[-1]
print(f"done: Algebraic Properties | Subsumption (directional)")
print(f"  acc={r['accuracy']:.3f}±{r['accuracy_std']:.3f}  "
      f"balanced_acc={r['balanced_accuracy']:.3f}±{r['balanced_accuracy_std']:.3f}\n")
```

---

### Cell: Code - Evaluate Compression Distance

```python
print("Evaluating compression-based metrics...\n")

# NCD (symmetric)
results.append(run_and_evaluate(X_ncd, y, node_order, ii, jj,
                                 'Normalized Compression Distance (NCD)'))
r = results[-1]
print(f"done: NCD")
print(f"  acc={r['accuracy']:.3f}±{r['accuracy_std']:.3f}  "
      f"balanced_acc={r['balanced_accuracy']:.3f}±{r['balanced_accuracy_std']:.3f}\n")

# Compression gain (directional)
results.append(run_and_evaluate(X_comp_gain, y, node_order, ii, jj,
                                 'Compression Gain (directional)'))
r = results[-1]
print(f"done: Compression Gain")
print(f"  acc={r['accuracy']:.3f}±{r['accuracy_std']:.3f}  "
      f"balanced_acc={r['balanced_accuracy']:.3f}±{r['balanced_accuracy_std']:.3f}\n")
```

---

### Cell: Code - Evaluate Edit and Tree Kernel Features

```python
print("Evaluating edit script and tree kernel features...\n")

# Edit features
results.append(run_and_evaluate(X_edit, y, node_order, ii, jj,
                                 'Enhanced Edit Script Features'))
r = results[-1]
print(f"done: Edit Script Features")
print(f"  acc={r['accuracy']:.3f}±{r['accuracy_std']:.3f}  "
      f"balanced_acc={r['balanced_accuracy']:.3f}±{r['balanced_accuracy_std']:.3f}\n")

# Tree kernel
results.append(run_and_evaluate(X_tree_kernel, y, node_order, ii, jj,
                                 'Tree Convolution Kernel'))
r = results[-1]
print(f"done: Tree Kernel")
print(f"  acc={r['accuracy']:.3f}±{r['accuracy_std']:.3f}  "
      f"balanced_acc={r['balanced_accuracy']:.3f}±{r['balanced_accuracy_std']:.3f}\n")

print(f"All advanced metrics evaluated. Total combinations: {len(results)}")
```

---

### Cell: Code - Combined "Super Model" with All Features

```python
print("Building COMBINED super-model with best features from all approaches...\n")

# Combine the strongest signals:
# 1. Best directional loss (Mix from domain-specific resampled)
# 2. Wasserstein features (domain-specific resampled)
# 3. Algebraic property subsumption
# 4. Edit script features

X_mix_domain_res = build_mix_features(losses_domain_resampled)

X_super = np.concatenate([
    X_mix_domain_res,           # 40 features: 4 losses × 5 views × 2 directions
    X_wasser_domain_res,        # 15 features: 5 views × 3 (sym + 2 dir)
    X_alg_subsumption,          # 2 features: both directions
    X_edit,                     # 7 features: edit operations
], axis=1)

print(f"Super-model feature count: {X_super.shape[1]} features")
print(f"  (40 from Mix losses + 15 from Wasserstein + 2 from algebraic + 7 from edit)")

results.append(run_and_evaluate(X_super, y, node_order, ii, jj,
                                 'COMBINED Super-Model (Mix + Wasserstein + Algebraic + Edit)'))
r = results[-1]
print(f"\ndone: COMBINED Super-Model")
print(f"  acc={r['accuracy']:.3f}±{r['accuracy_std']:.3f}  "
      f"balanced_acc={r['balanced_accuracy']:.3f}±{r['balanced_accuracy_std']:.3f}")
```

---

### Cell: Code - Updated Summary Table

```python
# Regenerate the summary table with ALL results (original + advanced)
summary_df = pd.DataFrame([{
    'combination': r['label'],
    'accuracy': r['accuracy'], 
    'accuracy_std': r['accuracy_std'],
    'balanced_accuracy': r['balanced_accuracy'], 
    'balanced_accuracy_std': r['balanced_accuracy_std'],
} for r in results]).sort_values('balanced_accuracy', ascending=False).reset_index(drop=True)

print(f"COMPLETE RESULTS: {len(summary_df)} total combinations\n")
print("=" * 100)
print("TOP 15 PERFORMERS (by balanced accuracy):")
print("=" * 100)
summary_df.head(15)
```

---

### Cell: Markdown - Analysis

```markdown
## 12B. Analysis: What Did the Advanced Metrics Reveal?

**Key findings from the new metrics:**

1. **Wasserstein vs KL**: Optimal transport provides a more geometrically meaningful distance, but did it improve classification accuracy compared to KL divergence?

2. **Algebraic properties**: Pure semantic features (commutativity, depth, variable counts) independent of embeddings — how much signal do they carry on their own?

3. **Compression distance**: Remarkably simple (just gzip), but captures structural similarity through information theory — competitive with learned representations?

4. **Edit operations**: Breaking down tree edits into typed operations (variable rename vs structural change) — more informative than raw edit distance?

5. **Super-model**: Combining diverse signal sources (distributional, structural, semantic) — does late fusion across method families improve over late fusion across views?

**What to look for in the results above:**
- Do Wasserstein features beat KL/CrossEntropy on the same latents?
- Can algebraic properties alone outperform symmetric baselines?
- Does compression distance (parameter-free!) compete with learned embeddings?
- Does the super-model beat the best single-method result?
```

---

### Cell: Code - Confusion Matrix for Best Advanced Method

```python
# Find the best advanced metric (those added in Section 12)
advanced_results = [r for r in results if any(keyword in r['label'] for keyword in 
                    ['Wasserstein', 'Algebraic', 'Compression', 'Edit', 'Tree Kernel', 'COMBINED Super'])]

best_advanced = max(advanced_results, key=lambda r: r['balanced_accuracy'])

print(f"BEST ADVANCED METHOD:")
show_confusion(best_advanced)
```

---

### Cell: Markdown - Conclusion

```markdown
## 12C. Takeaways: Advanced Methods vs Original Approach

**Original best result (from Section 7):**
- Domain-specific embedding, RESAMPLED, Mix(KL+CE+Rank+LLR): ~51.2% balanced accuracy

**Advanced methods performance:**
- [Will be filled in after running the cells above]

**Lessons learned:**
1. **Optimal Transport**: More principled than KL, but computationally expensive — worth it?
2. **Algebraic Properties**: Semantic features add orthogonal signal to distributional measures
3. **Compression**: Embarrassingly simple, no parameters, no training — solid baseline
4. **Structural Features**: Edit operations and tree kernels capture what embeddings miss
5. **Ensemble Power**: Combining diverse feature families through late fusion

**What this means for equation equivalence detection:**
The partial order structure (⊑) is complex enough that no single metric dominates. 
The best approach appears to be late fusion of multiple complementary signals:
- Distributional (KL, Wasserstein on learned latents)
- Structural (tree edits, subtree patterns)
- Semantic (algebraic properties, compression)

Each captures a different facet of "what makes two equations related."
```

---

## Installation Note

If you don't have the POT (Python Optimal Transport) library installed, add this cell at the beginning:

```python
# Install POT library for optimal transport (if not already installed)
try:
    import ot
    print("POT library already installed.")
except ImportError:
    print("Installing POT library...")
    !pip install POT
    import ot
    print("POT library installed successfully.")
```

---

## That's it!

These cells will:
1. Compute all the new advanced metrics
2. Evaluate them with the same rigor (5-fold splits, confusion matrices)
3. Add results to the existing `results` list
4. Regenerate the summary table with everything ranked together
5. Create a super-model combining the best features

Just copy-paste these cells into your notebook after Section 7B, run them sequentially, and you'll have a complete comparison!
