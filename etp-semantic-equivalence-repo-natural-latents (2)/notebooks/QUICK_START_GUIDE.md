# Quick Start Guide: Adding Advanced Metrics to Your Notebook

## What You Have Now

I've created two files for you:

1. **`../src/advanced_metrics.py`** - Complete implementation of all new methods
2. **`new_cells_to_insert.md`** - Ready-to-paste notebook cells with explanations

## How to Use

### Step 1: Install Dependencies (if needed)

Run this in a notebook cell:
```python
!pip install POT  # For optimal transport (Wasserstein distance)
```

### Step 2: Copy-Paste Cells

Open `new_cells_to_insert.md` and copy cells one by one into your notebook after Section 7B.

**Pro tip:** Copy one section at a time (e.g., all Wasserstein cells together), run them, verify the output looks good, then move to the next section.

### Step 3: Run and Compare

The cells will automatically:
- Compute all new metrics
- Evaluate them with 5-fold cross-validation
- Add results to your existing `results` list
- Regenerate the summary table with everything ranked

---

## What Each Method Does (Plain English)

### 1. Wasserstein Distance (Optimal Transport)
**Time:** ~5-10 minutes for all combos  
**Features:** 15 per method (5 views × 3 variants)

**Intuition:** Instead of KL's harsh "different = bad", Wasserstein asks "how much work to reshape A into B?"

**Expected:** Should beat KL on edge cases where equations are "close but not identical"

---

### 2. Algebraic Properties
**Time:** ~30 seconds  
**Features:** 1-2 features (depending on symmetric/directional)

**Intuition:** Extract semantic facts like "uses 3 variables", "has 2 nested operators", "looks commutative"

**Expected:** Won't beat KL alone, but adds orthogonal signal when combined

---

### 3. Compression Distance (NCD)
**Time:** ~2-3 minutes  
**Features:** 1-2 features

**Intuition:** If gzip can compress two equations together efficiently, they share structure

**Expected:** Surprisingly competitive for a zero-parameter method! Around 30-35% accuracy

---

### 4. Edit Script Features
**Time:** ~1 minute  
**Features:** 7 features (types of edits)

**Intuition:** "How did we transform A→B?" (renamed vars? changed depth? added tokens?)

**Expected:** Enriches the existing tree edit distance baseline

---

### 5. Tree Convolution Kernel
**Time:** ~1 minute  
**Features:** 1 feature (symmetric)

**Intuition:** Count how many sub-patterns (like "x ◇ y" or nested parens) they share

**Expected:** Better than raw tree edit distance, still symmetric so can't predict direction

---

### 6. Super-Model (Combined)
**Time:** Same as training any other Random Forest  
**Features:** 64 total (40 Mix + 15 Wasserstein + 2 algebraic + 7 edit)

**Intuition:** Let the Random Forest learn which feature to trust in which situation

**Expected:** Best overall performance, around 52-54% balanced accuracy (vs 51.2% baseline)

---

## Expected Results Summary

Based on what each method captures, here's my prediction:

| Method | Balanced Acc (est.) | Why |
|--------|---------------------|-----|
| **Baseline (Mix, domain, resampled)** | 51.2% | Your current best |
| Wasserstein (domain, resampled) | 49-52% | Better geometry, similar signal to KL |
| Algebraic Properties (subsumption) | 30-35% | Weak alone, useful combined |
| Compression NCD | 28-33% | Simple but captures similarity |
| Compression Gain (directional) | 32-37% | Directional helps a bit |
| Edit Script Features | 35-40% | Richer than tree edit distance |
| Tree Kernel | 32-36% | Still symmetric, limited |
| **Super-Model (all combined)** | **52-55%** | Best: diverse signal fusion |

---

## Quick Troubleshooting

### If POT library installation fails:
The code will automatically fall back to scipy's `wasserstein_distance` (1D only, slower but works).

### If computation is too slow:
- Wasserstein is the slowest part (~5-10 min)
- You can skip it and just run the other methods
- Or reduce `SAMPLE_SIZE` from 1200 to 500 equations for faster iteration

### If you want to test just one method:
Just copy the specific section from `new_cells_to_insert.md`. For example:
1. Import cell
2. Algebraic properties extraction
3. Build features
4. Evaluate

Each method is independent!

---

## Interpreting Results

### Look for these patterns:

1. **Symmetric vs Directional:**
   - Symmetric methods (NCD, tree kernel) should have identical stronger/weaker confusion rows
   - Directional methods (Wasserstein directional, compression gain) should distinguish them

2. **Weaker Recall:**
   - Symmetric: ~0% to 30% (can't distinguish direction)
   - Directional: 30% to 45% (captures asymmetry)
   - Super-model: should match or beat best single method

3. **Standard Deviation:**
   - If std > 0.03, that method is unstable across splits
   - Super-model should have lower std (more robust)

---

## What to Report

After running all cells, you can say:

> "We evaluated 7 additional sophisticated metrics beyond the original KL/CrossEntropy approach:
> - Optimal Transport (Wasserstein distance)
> - Algebraic property extraction
> - Compression-based similarity (NCD and directional compression gain)
> - Enhanced edit script features
> - Tree convolution kernel
> - A combined super-model fusing all feature families
>
> The super-model achieved **X.X%** balanced accuracy (±Y.Y%), a **Z.Z point** improvement
> over the best single-method baseline. This confirms that equation equivalence is best
> captured through late fusion of diverse signal sources: distributional (learned latents),
> structural (tree patterns), and semantic (algebraic properties)."

---

## Next Steps After Running

1. **Check the confusion matrices** - Which classes improved most?
2. **Look at feature importance** - Which features does Random Forest weight highest?
3. **Error analysis** - Which pairs does even the super-model get wrong?

Want me to add feature importance analysis cells too?
