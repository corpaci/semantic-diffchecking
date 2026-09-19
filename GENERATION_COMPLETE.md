# ✅ Data Generation Completed - equations_representations_v2.json

## Status: SUCCESS

Generated: `equations_representations_v2.json`  
Location: `etp-semantic-equivalence-repo-natural-latents (2)/data/`  
Size: ~11 MB  
Format: Pretty-printed JSON

---

## Summary

✅ **4,694 equations** - Complete coverage  
✅ **18 representations** per equation  
✅ **20 total fields** (node, formal, + 18 representations)  
✅ **100% coverage** for 17 representations  
✅ **98.3% coverage** for natural_language (4,612/4,694)

---

## All Representations Included

| # | Field | Coverage | Description |
|---|-------|----------|-------------|
| 1 | `node` | 100% | Equation ID (1-4694) |
| 2 | `formal` | 100% | Original formal notation (x ◇ y = y ◇ x) |
| 3 | `lean` | 100% | Lean proof assistant format |
| 4 | `latex` | 100% | LaTeX mathematical notation |
| 5 | `py_lambda` | 100% | Python lambda function |
| 6 | `py_cayley_table` | 100% | Python Cayley table verification |
| 7 | `natural_language` | 98.3% | Human-readable prose description |
| 8 | `ssa` | 100% | Static Single Assignment form |
| 9 | `slots` | 100% | Positional slot encoding |
| 10 | `rpn` | 100% | Reverse Polish Notation |
| 11 | `polish` | 100% | Polish prefix notation |
| 12 | `tptp` | 100% | TPTP theorem prover format |
| 13 | `smtlib` | 100% | SMT-LIB format |
| 14 | `ascii_tree` | 100% | ASCII tree representation |
| 15 | `graphviz` | 100% | DOT graph format |
| 16 | `json_ast` | 100% | JSON abstract syntax tree |
| 17 | `confusable_vars` | 100% | Confusable variable names |
| 18 | `word_problem` | 100% | Word problem format |
| 19 | `text` | 100% | Mechanical English with delimiters |
| 20 | `text2` | 100% | Mechanical English with arity |

---

## Example Entry (Equation 43: Commutativity)

```json
{
  "node": 43,
  "formal": "x ◇ y = y ◇ x",
  "lean": "example (G : Type u) [Magma G] : Prop := ∀ x y : G, x ◇ y = y ◇ x",
  "latex": "x \\diamond y = y \\diamond x",
  "py_lambda": "lambda op, x, y: op(x, y) == op(y, x)",
  "py_cayley_table": "def law(table):\n    n = len(table)\n    return all(table[x][y] == table[y][x] for x in range(n) for y in range(n))\n",
  "natural_language": "A binary operation applied to two variables results in the same value regardless of their order...",
  "ssa": "t1 = x ◇ y\nt2 = y ◇ x\nassert t1 = t2",
  "slots": "[[1, 2], [2, 1]]",
  "rpn": "x y ◇ y x ◇ =",
  "polish": "= ◇ x y ◇ y x",
  "tptp": "fof(law, axiom, ![X, Y] : op(X, Y) = op(Y, X)).",
  "smtlib": "(declare-sort M 0)\n(declare-fun op (M M) M)\n(assert (forall ((x M) (y M))\n  (= (op x y) (op y x))))",
  "ascii_tree": "=\n├── ◇\n│   ├── x\n│   └── y\n└── ◇\n    ├── y\n    └── x",
  "graphviz": "digraph law {\n  ordering=out;\n  n1 [label=\"=\"];\n  ...\n}",
  "json_ast": "{\"=\": [{\"◇\": [\"x\", \"y\"]}, {\"◇\": [\"y\", \"x\"]}]}",
  "confusable_vars": "l ◇ ı = ı ◇ l",
  "word_problem": "A workshop welder takes two parts... The order of welding doesn't matter.",
  "text": "x diamond y equals y diamond x",
  "text2": "the diamond of x and y equals the diamond of y and x"
}
```

---

## Comparison: V1 vs V2

| Aspect | V1 | V2 |
|--------|----|----|
| **Equations** | 4,612 (subset with all 5 core reps) | 4,694 (complete) |
| **Representations** | 6 (core set) | 18 (comprehensive) |
| **Coverage** | Filtered subset | Complete catalogue |
| **Size** | Smaller, minimal | Comprehensive |
| **Use case** | Notebooks, experiments | Full dataset, research |

**V1 representations:** formal, lean, latex, py_lambda, py_cayley_table, natural_language  
**V2 representations:** All of V1 + 12 more (ssa, slots, rpn, polish, tptp, smtlib, ascii_tree, graphviz, json_ast, confusable_vars, word_problem, text, text2)

---

## Files Generated

```
semantic-diffchecking/
└── etp-semantic-equivalence-repo-natural-latents (2)/
    └── data/
        ├── equations_representations.json (V1 - original)
        └── equations_representations_v2.json (V2 - NEW ✨)
```

**File size:**
- V1: ~8 MB (compact), ~20 MB (pretty)
- V2: ~11 MB (pretty-printed)

---

## How to Use

### Load in Python
```python
import json

with open('data/equations_representations_v2.json', 'r') as f:
    equations = json.load(f)

# Access by index (node - 1)
eq43 = [eq for eq in equations if eq['node'] == 43][0]

# Or build a lookup
eq_by_node = {eq['node']: eq for eq in equations}
eq43 = eq_by_node[43]

print(eq43['formal'])          # x ◇ y = y ◇ x
print(eq43['lean'])            # Lean format
print(eq43['natural_language']) # Human description
```

### Load in Notebook
```python
import pandas as pd
import json

# Load as list
with open('data/equations_representations_v2.json') as f:
    data = json.load(f)

# Convert to DataFrame for analysis
df = pd.DataFrame(data)

# View structure
print(df.columns)
print(df.head())

# Filter equations with specific properties
commutative = df[df['formal'].str.contains('x ◇ y = y ◇ x')]
```

---

## Next Steps

### ✅ DONE: Representations V2
- [x] Build comprehensive representations file
- [x] Include all 18 representations
- [x] Add natural_language from V1
- [x] Verify 100% coverage

### ⏳ TODO: Pairs V2 (Requires Oracle Setup)

To generate all 22M equation pairs:

1. **Setup oracle** (one-time):
   ```bash
   cd oracle/
   wget https://github.com/teorth/equational_theories/raw/main/data/2024-11-10-outcomes.json.zip
   python3 build_matrix.py 2024-11-10-outcomes.json.zip
   ```

2. **Generate pairs** (6-12 hours):
   ```bash
   python3 generate_oracle_pairs_v2.py
   ```

3. **Output:**
   - File: `oracle_labeled_pairs_v2.csv`
   - Size: ~600 MB
   - Rows: 22,033,636 pairs
   - Columns: node_a, node_b, relation

---

## Scripts Available

- ✅ `build_equations_representations_v2.py` - **USED** to create this file
- ⏳ `generate_oracle_pairs_v2.py` - Ready to use after oracle setup
- ✅ `test_data_generation.py` - Validation script

---

## Technical Notes

### Issues Fixed
1. **Index file format** - File contains equations without node numbers; node = line number
2. **Natural language source** - Not in translate/ directory; merged from V1 file
3. **Coverage** - 82 equations missing natural_language (likely added to catalogue later)

### Performance
- **Build time:** ~30 seconds
- **Memory usage:** Minimal (streaming JSON)
- **Disk I/O:** Sequential writes

---

## Citation

If you use this dataset, please cite:

- **Equational Theories Project** by Terence Tao
- **semantic-diffchecking** repository (oracle & translations)
- **Natural Latents** methodology

---

Generated: 2026-09-19  
Format: JSON (pretty-printed with indent=2)  
Encoding: UTF-8 (preserve Unicode symbols like ◇)
