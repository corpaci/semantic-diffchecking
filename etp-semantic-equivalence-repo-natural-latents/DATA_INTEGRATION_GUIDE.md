# Data Integration Guide

## Overview
This guide explains how all data components in the semantic equivalence checking pipeline are interconnected and how to use them together.

## Data Files and Their Relationships

### Core Data Files

1. **`data/equations_representations.json`** (5.4 MB)
   - Contains 4,694 ETP equations with 5 representations each:
     - `lean`: Formal Lean syntax
     - `latex`: LaTeX mathematical notation  
     - `py_lambda`: Python lambda expressions
     - `py_cayley_table`: Python Cayley table representation
     - `natural_language`: Human-readable description
   - Each equation has a unique `node` ID

2. **`data/matrix.bin`** + **`data/decode_matrix.py`** (22 MB)
   - Binary matrix containing ALL ~22M pairwise relationships
   - Relations: `equivalent`, `stronger`, `weaker`, `incomparable`, `unresolved`
   - Use `decode_matrix.py` to query: `relation_for(matrix, node_a, node_b)`

3. **`data/pairs_200k.csv`** (NEW - 45K pairs)
   - Pre-generated pairs with ground truth labels
   - Format: `node_a,node_b,relation`
   - Subset of the complete matrix for faster experimentation
   - **Location**: Now copied to local `data/` directory

4. **`data/oracle_labeled_pairs.csv`** (50K pairs)
   - Original pre-sampled pairs used in earlier experiments
   - Same format as pairs_200k.csv

## How the Notebook Uses Data

### Original Workflow (Generate Pairs On-the-Fly)
```
equations_representations.json 
    ↓ (load & sample 1,200 equations)
sample_equations
    ↓ (generate pairs from matrix)
matrix.bin + decode_matrix.py
    ↓ (create 15,000 labeled pairs)
pairs DataFrame
    ↓ (embed & train)
results
```

### New Workflow (Use Pre-Generated Pairs)
```
equations_representations.json     pairs_200k.csv
    ↓                                    ↓
sample_equations              (filter to sample_nodes)
    ↓                                    ↓
    +─────────────────────────────────────+
                    ↓
              pairs DataFrame
                    ↓
            (embed & train)
                    ↓
               results
```

## Using the Modified Notebook

### Option 1: Use Pre-Generated Pairs (Faster)

Open **`notebooks/notebook_with_pairs200k.ipynb`** and set:
```python
USE_PREGENERATED_PAIRS = True
```

**Advantages:**
- ✅ Faster execution (no matrix generation)
- ✅ Reproducible pair selection
- ✅ Can use larger pair sets pre-filtered by quality
- ✅ Easier to share exact experimental setup

**Process:**
1. Loads 1,200 sampled equations from `equations_representations.json`
2. Reads `pairs_200k.csv`
3. Filters pairs to only those where both nodes are in the sample
4. Uses filtered pairs for training/evaluation

### Option 2: Generate Pairs On-the-Fly (Original Method)

Set:
```python
USE_PREGENERATED_PAIRS = False
```

**Advantages:**
- ✅ Guaranteed all pairs involve sampled equations
- ✅ Control over pair distribution (stronger/weaker/equivalent ratio)
- ✅ Can enforce symmetric pair inclusion

**Process:**
1. Loads 1,200 sampled equations
2. Queries `matrix.bin` for all pairs among sampled nodes
3. Samples 15,000 pairs ensuring both directions included
4. Uses generated pairs for training/evaluation

## Data Interconnection Flow Chart

```
                     ┌─────────────────────────────┐
                     │  equations_representations  │
                     │         .json               │
                     │  (4,694 equations × 5 reps) │
                     └──────────┬──────────────────┘
                                │
                     ┌──────────▼──────────┐
                     │  Sample 1,200 eqns  │
                     │  (node IDs: set)    │
                     └──────┬───────┬──────┘
                            │       │
          ┌─────────────────┘       └────────────────┐
          │                                           │
┌─────────▼─────────┐                    ┌───────────▼───────────┐
│  matrix.bin       │                    │   pairs_200k.csv      │
│  + decode_matrix  │                    │   (pre-generated)     │
│  (all 22M pairs)  │                    │   (44,997 pairs)      │
└─────────┬─────────┘                    └───────────┬───────────┘
          │                                           │
          │  relation_for(a, b)            Filter: both nodes in sample
          │                                           │
          └──────────┬────────────────────────────────┘
                     │
          ┌──────────▼──────────┐
          │  Filtered pairs DF  │
          │  (node_a, node_b,   │
          │   relation)         │
          └──────────┬──────────┘
                     │
          ┌──────────▼──────────┐
          │  Embed all 5 views  │
          │  (generic/domain)   │
          └──────────┬──────────┘
                     │
          ┌──────────▼──────────┐
          │  Natural Latents    │
          │  resampling         │
          └──────────┬──────────┘
                     │
          ┌──────────▼──────────┐
          │  Train & Evaluate   │
          │  (RF classifier)    │
          └─────────────────────┘
```

## Key Integration Points

### 1. Node ID Mapping
- All datasets use integer `node` IDs (1-4694)
- **Critical**: Ensure node IDs in pairs match nodes in equations file
- Filter pairs: `pairs[pairs['node_a'].isin(sample_nodes)]`

### 2. Representations Lookup
```python
representations = {}
for view in ['lean', 'latex', 'py_lambda', 'py_cayley_table', 'natural_language']:
    representations[view] = {e['node']: e[view] for e in sample_equations}
```

### 3. Embedding Generation
```python
# For each pair (node_a, node_b):
embed_a = resampler.embed(
    [representations[view][node_a] for view in views]
)
embed_b = resampler.embed(
    [representations[view][node_b] for view in views]
)
```

## Quick Start Commands

### Run with pre-generated pairs:
```bash
cd notebooks
jupyter notebook notebook_with_pairs200k.ipynb
# Set USE_PREGENERATED_PAIRS = True in Cell 5
# Run all cells
```

### Run with on-the-fly generation:
```bash
cd notebooks  
jupyter notebook notebook_with_pairs200k.ipynb
# Set USE_PREGENERATED_PAIRS = False in Cell 5
# Run all cells
```

### Verify data integrity:
```bash
cd notebooks
python3 << 'EOF'
import pandas as pd
import json

# Check pairs_200k.csv nodes exist in equations file
pairs = pd.read_csv('../data/pairs_200k.csv')
with open('../data/equations_representations.json') as f:
    equations = json.load(f)

nodes_in_eqs = {e['node'] for e in equations}
nodes_in_pairs = set(pairs['node_a']) | set(pairs['node_b'])

print(f"Nodes in equations: {len(nodes_in_eqs)}")
print(f"Nodes in pairs_200k: {len(nodes_in_pairs)}")
print(f"Pairs nodes NOT in equations: {nodes_in_pairs - nodes_in_eqs}")
print(f"✅ All nodes valid!" if nodes_in_pairs.issubset(nodes_in_eqs) else "❌ Invalid nodes found")
EOF
```

## Performance Comparison

| Method | Pair Generation Time | Total Pairs Available | Filtering Required |
|--------|---------------------|----------------------|-------------------|
| **Pre-generated** | 0s (already done) | 44,997 | Yes (to sample) |
| **On-the-fly** | ~2-5s | Generated as needed | No |

## Troubleshooting

### Issue: "Pairs contain nodes not in sample"
**Solution**: The filtering step automatically handles this. Check that:
```python
pairs = pairs[pairs['node_a'].isin(sample_nodes) & 
              pairs['node_b'].isin(sample_nodes)]
```

### Issue: "Not enough pairs after filtering"
**Solution**: Either:
- Increase `SAMPLE_SIZE` (more equations → more valid pairs)
- Use `USE_PREGENERATED_PAIRS = False` to generate all possible pairs

### Issue: "Relation labels don't match"
**Solution**: Verify relation format matches: `equivalent`, `stronger`, `weaker`, `incomparable`

## Advanced Usage

### Create custom pair sets:
```python
from decode_matrix import load_matrix, relation_for

matrix, meta = load_matrix()

# Generate pairs for specific node ranges
custom_pairs = []
for a in range(1, 1000):
    for b in range(1000, 2000):
        rel = relation_for(matrix, a, b)
        if rel != 'unresolved':
            custom_pairs.append({'node_a': a, 'node_b': b, 'relation': rel})

custom_df = pd.DataFrame(custom_pairs)
custom_df.to_csv('../data/custom_pairs.csv', index=False)
```

### Merge multiple pair sources:
```python
pairs1 = pd.read_csv('../data/oracle_labeled_pairs.csv')
pairs2 = pd.read_csv('../data/pairs_200k.csv')

# Combine and deduplicate
all_pairs = pd.concat([pairs1, pairs2])
all_pairs = all_pairs.drop_duplicates(subset=['node_a', 'node_b'])
```

## Files Modified/Created

- ✅ **Created**: `notebooks/notebook_with_pairs200k.ipynb` - Modified notebook with pair loading option
- ✅ **Copied**: `data/pairs_200k.csv` - Pre-generated pairs from parent directory
- ✅ **Created**: `DATA_INTEGRATION_GUIDE.md` - This guide

## Next Steps

1. **Run the verification script** above to ensure data integrity
2. **Try both methods** (pre-generated vs on-the-fly) to compare results
3. **Experiment with pair counts** - does 45K pairs vs 15K change accuracy?
4. **Create custom pair sets** for specific relation types or node ranges
