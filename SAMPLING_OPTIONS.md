# Sampling Options for generate_oracle_pairs_v2.py

The script now supports multiple sampling strategies to reduce runtime while still generating useful datasets.

---

## Quick Examples

### 🚀 Fastest: Random Pair Sample
```bash
# Generate exactly 10,000 random pairs (~10 seconds)
python3 generate_oracle_pairs_v2.py --sample-pairs 10000

# Generate 100,000 pairs (~2 minutes)
python3 generate_oracle_pairs_v2.py --sample-pairs 100000

# Generate 1 million pairs (~20 minutes)
python3 generate_oracle_pairs_v2.py --sample-pairs 1000000
```

### ⚡ Fast: Small Equation Subset
```bash
# First 100 equations → 10,000 pairs (~10 seconds)
python3 generate_oracle_pairs_v2.py --first-n 100

# First 500 equations → 250,000 pairs (~5 minutes)
python3 generate_oracle_pairs_v2.py --first-n 500

# Random 1000 equations → 1,000,000 pairs (~20 minutes)
python3 generate_oracle_pairs_v2.py --sample-equations 1000
```

### 💡 Efficient: No Reverse Pairs
```bash
# All equations but no reverse pairs (~6 hours instead of 12)
python3 generate_oracle_pairs_v2.py --no-reverse

# First 1000 equations, no reverse → 500,500 pairs (~10 minutes)
python3 generate_oracle_pairs_v2.py --first-n 1000 --no-reverse
```

### 🔥 Combined: Maximum Speed
```bash
# 100 equations, no reverse, sample 5000 pairs (~5 seconds)
python3 generate_oracle_pairs_v2.py --first-n 100 --no-reverse --sample-pairs 5000

# 500 equations, sample 50,000 pairs (~1 minute)
python3 generate_oracle_pairs_v2.py --sample-equations 500 --sample-pairs 50000
```

---

## Detailed Options

### `--sample-pairs N`
**Randomly sample N pairs from all possible pairs**

- ✅ **Fastest** option for getting a dataset quickly
- ✅ Good statistical distribution across relation types
- ✅ Works with any equation set
- ⚠️ May miss rare edge cases

**Example:**
```bash
python3 generate_oracle_pairs_v2.py --sample-pairs 50000
```

**Time estimates:**
- 1,000 pairs: ~1 second
- 10,000 pairs: ~10 seconds
- 100,000 pairs: ~2 minutes
- 1,000,000 pairs: ~20 minutes

---

### `--first-n N`
**Use only the first N equations from the catalogue**

- ✅ **Deterministic** - same equations every time
- ✅ Early equations tend to be simpler (good for testing)
- ✅ Easy to reason about which equations are included
- ⚠️ Biased toward simpler laws

**Example:**
```bash
python3 generate_oracle_pairs_v2.py --first-n 200
```

**Pairs generated:** N × N (or N×(N+1)/2 with `--no-reverse`)

**Time estimates:**
| Equations | Pairs (both dir) | Pairs (no reverse) | Time (both) | Time (no rev) |
|-----------|------------------|---------------------|-------------|---------------|
| 100 | 10,000 | 5,050 | 10 sec | 5 sec |
| 200 | 40,000 | 20,100 | 40 sec | 20 sec |
| 500 | 250,000 | 125,250 | 4 min | 2 min |
| 1,000 | 1,000,000 | 500,500 | 17 min | 8 min |
| 2,000 | 4,000,000 | 2,001,000 | 67 min | 33 min |

---

### `--sample-equations N`
**Randomly sample N equations from the full catalogue**

- ✅ **Representative** - covers full range of complexity
- ✅ Good for unbiased testing
- ✅ Seed is fixed (42) for reproducibility
- ⚠️ Different subset than `--first-n`

**Example:**
```bash
python3 generate_oracle_pairs_v2.py --sample-equations 500
```

**Pairs generated:** N × N (or N×(N+1)/2 with `--no-reverse`)

**Time estimates:** Same as `--first-n`

---

### `--no-reverse`
**Only generate A→B pairs, skip B→A**

- ✅ **Cuts runtime in half** (~6 hours instead of 12 for full dataset)
- ✅ Good if you only care about relationships, not directionality
- ⚠️ Loses directional information (can't distinguish "stronger" vs "weaker")

**Example:**
```bash
python3 generate_oracle_pairs_v2.py --no-reverse
```

**Note:** For the full 4,694 equations:
- With reverse: 22,033,636 pairs
- No reverse: 11,022,965 pairs (includes diagonal A=A)

---

## Recommended Workflows

### 🧪 Quick Test (5 seconds)
```bash
python3 generate_oracle_pairs_v2.py --first-n 100 --sample-pairs 5000
```
**Output:** 5,000 pairs from first 100 equations  
**Use:** Quick validation, testing notebooks

---

### 📊 Small Dataset for Notebook (1 minute)
```bash
python3 generate_oracle_pairs_v2.py --sample-equations 500 --sample-pairs 50000
```
**Output:** 50,000 pairs sampled from 500 random equations  
**Use:** Development, exploratory analysis

---

### 📈 Medium Dataset (10 minutes)
```bash
python3 generate_oracle_pairs_v2.py --first-n 1000 --no-reverse
```
**Output:** 500,500 pairs from first 1,000 equations  
**Use:** Training models, experiments

---

### 📚 Large Representative Sample (30 minutes)
```bash
python3 generate_oracle_pairs_v2.py --sample-pairs 2000000
```
**Output:** 2 million pairs randomly sampled from all equations  
**Use:** Large-scale experiments, paper results

---

### 🌐 Full Dataset - One Direction (6 hours)
```bash
python3 generate_oracle_pairs_v2.py --no-reverse
```
**Output:** 11 million pairs (all equations, no reverse)  
**Use:** Complete dataset without directionality

---

### 🔬 Full Dataset - Both Directions (12 hours)
```bash
python3 generate_oracle_pairs_v2.py
```
**Output:** 22 million pairs (complete)  
**Use:** Final production dataset, research archive

---

## Performance Estimates

**Oracle query rate:** ~500-1000 pairs/second (depends on cache, system)

| Pairs | Time (estimate) | Command |
|-------|----------------|---------|
| 1K | 1 sec | `--sample-pairs 1000` |
| 10K | 10 sec | `--sample-pairs 10000` |
| 50K | 1 min | `--sample-pairs 50000` |
| 100K | 2 min | `--sample-pairs 100000` |
| 500K | 8 min | `--first-n 1000 --no-reverse` |
| 1M | 17 min | `--sample-pairs 1000000` |
| 2M | 33 min | `--sample-pairs 2000000` |
| 11M | 6 hrs | `--no-reverse` |
| 22M | 12 hrs | (full, both directions) |

---

## Output Filenames

Add custom output names for different samples:

```bash
# Quick test
python3 generate_oracle_pairs_v2.py --first-n 100 \
    --output data/pairs_test_100eq.csv

# Medium sample
python3 generate_oracle_pairs_v2.py --sample-pairs 100000 \
    --output data/pairs_sample_100k.csv

# Large representative
python3 generate_oracle_pairs_v2.py --sample-pairs 2000000 \
    --output data/pairs_sample_2M.csv
```

---

## Reproducibility

All sampling uses **seed=42** for reproducibility:
- Same `--sample-equations N` always selects same equations
- Same `--sample-pairs N` always selects same pairs

To change the seed, edit the script or we can add a `--seed` parameter.

---

## When to Use What?

| Goal | Strategy | Command |
|------|----------|---------|
| Test scripts work | First 100 equations | `--first-n 100` |
| Quick notebook | Random 50K pairs | `--sample-pairs 50000` |
| Train small model | 1000 equations, no reverse | `--first-n 1000 --no-reverse` |
| Representative sample | Random 2M pairs | `--sample-pairs 2000000` |
| Complete archive | Full dataset | `python3 generate_oracle_pairs_v2.py` |

---

## Combining Options

Options can be combined:

```bash
# Sample 500 equations, generate all their pairs, no reverse
python3 generate_oracle_pairs_v2.py --sample-equations 500 --no-reverse

# First 1000 equations, sample 100K pairs from them
python3 generate_oracle_pairs_v2.py --first-n 1000 --sample-pairs 100000

# Random 2000 equations, no reverse, sample 500K pairs
python3 generate_oracle_pairs_v2.py --sample-equations 2000 --no-reverse --sample-pairs 500000
```

---

## Check Your Options

Run with `--help` to see all options:
```bash
python3 generate_oracle_pairs_v2.py --help
```

---

Generated: 2026-09-19  
Compatible with: generate_oracle_pairs_v2.py
