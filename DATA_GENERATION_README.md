# Data Generation Scripts - V2

This directory contains scripts to generate comprehensive datasets for the ETP semantic equivalence project.

## Scripts

### 1. `generate_oracle_pairs_v2.py`

Generates **all possible equation pairs** (4694 × 4694 = 22,033,636 pairs) with their semantic relationships determined by the oracle.

#### Features:
- **Complete coverage**: All ordered pairs (A→B and B→A are different)
- **Oracle-labeled**: Each pair labeled as: `equivalent`, `stronger`, `weaker`, `incomparable`, or `unknown`
- **Resumable**: Can resume from interrupted runs
- **Progress tracking**: Real-time progress updates and ETA
- **Memory efficient**: Streams output to CSV, doesn't load everything into memory

#### Usage:

```bash
# Generate all pairs (will take several hours)
python3 generate_oracle_pairs_v2.py

# Custom output location
python3 generate_oracle_pairs_v2.py --output data/my_pairs.csv

# Resume interrupted run
python3 generate_oracle_pairs_v2.py --resume

# Adjust batch size for progress updates
python3 generate_oracle_pairs_v2.py --batch-size 50000
```

#### Output Format:

CSV file with columns: `node_a,node_b,relation`

```csv
node_a,node_b,relation
1,1,equivalent
1,2,weaker
1,3,incomparable
2,1,stronger
...
```

#### Performance:
- **Estimated runtime**: ~6-12 hours for all 22M pairs (depends on system)
- **Output size**: ~500-600 MB CSV file
- **Rate**: Approximately 500-1000 pairs/second

---

### 2. `build_equations_representations_v2.py`

Combines all available representation translations into a single comprehensive JSON file.

#### Features:
- **Multi-representation**: Aggregates 15+ different equation representations
- **Complete coverage**: All 4694 equations
- **Extensible**: Automatically includes all available translations
- **Metadata tracking**: Reports coverage statistics per representation

#### Representations Included:

| Representation | Description |
|----------------|-------------|
| `formal` | Original formal notation (x ◇ y = y ◇ x) |
| `lean` | Lean proof assistant format |
| `latex` | LaTeX mathematical notation |
| `py_lambda` | Python lambda function |
| `py_cayley_table` | Python Cayley table verification |
| `natural_language` | Human-readable prose |
| `ssa` | Static Single Assignment form |
| `slots` | Positional slot encoding |
| `rpn` | Reverse Polish Notation |
| `polish` | Polish prefix notation |
| `tptp` | TPTP theorem prover format |
| `smtlib` | SMT-LIB format |
| `ascii_tree` | ASCII tree representation |
| `graphviz` | DOT graph format |
| `json_ast` | JSON abstract syntax tree |
| `confusable_vars` | Confusable variable names |
| `word_problem` | Word problem format |
| `text` | Mechanical English with delimiters |
| `text2` | Mechanical English with arity |

#### Usage:

```bash
# Generate v2 representations file
python3 build_equations_representations_v2.py

# Pretty-print JSON (easier to read, larger file)
python3 build_equations_representations_v2.py --pretty

# Custom output location
python3 build_equations_representations_v2.py --output data/my_representations.json
```

#### Output Format:

JSON array of equation objects:

```json
[
  {
    "node": 1,
    "formal": "x = x",
    "lean": "example (G : Type u) [Magma G] : Prop := ∀ x : G, x = x",
    "latex": "x = x",
    "py_lambda": "lambda op, x: x == x",
    "py_cayley_table": "def law(table):\n    n = len(table)\n    return all(x == x for x in range(n))\n",
    "natural_language": "A single variable is present on both sides...",
    "ssa": "assert x = x",
    "slots": "[1, 1]",
    "rpn": "x x =",
    ...
  },
  ...
]
```

#### Performance:
- **Runtime**: ~30 seconds to 2 minutes
- **Output size**: ~50-100 MB (compact) or ~150-200 MB (pretty-printed)

---

## Prerequisites

### 1. Oracle Matrix

Both scripts require the oracle matrix to be built:

```bash
cd oracle/
python3 build_matrix.py
```

This creates the `etp_relation_matrix.bin` file that the oracle queries.

### 2. Translation Catalogues

For `build_equations_representations_v2.py`, ensure translation catalogues are built:

```bash
cd translate/lean/
python3 build_catalogue.py

cd ../latex/
python3 build_catalogue.py

# Repeat for other representations as needed
```

Most should already be built if you cloned the repository with data.

---

## Workflow

### Complete Data Generation Pipeline:

```bash
# 1. Ensure oracle is built
cd oracle/
python3 build_matrix.py
cd ..

# 2. Build representations v2 (fast)
python3 build_equations_representations_v2.py

# 3. Generate all pairs v2 (slow - run overnight)
python3 generate_oracle_pairs_v2.py

# 4. Check results
wc -l etp-semantic-equivalence-repo-natural-latents\ \(2\)/data/oracle_labeled_pairs_v2.csv
ls -lh etp-semantic-equivalence-repo-natural-latents\ \(2\)/data/equations_representations_v2.json
```

---

## Differences from V1

### `oracle_labeled_pairs_v2.csv` vs `oracle_labeled_pairs.csv`:
- ✅ **V2: ALL pairs** (22M pairs, complete)
- ❌ **V1: Sample** (~15K pairs, for notebooks)

### `equations_representations_v2.json` vs `equations_representations.json`:
- ✅ **V2: 15+ representations** (comprehensive)
- ❌ **V1: 6 representations** (core set only)

---

## Troubleshooting

### "missing etp_relation_matrix.bin"
```bash
cd oracle/
python3 build_matrix.py
```

### "Index file not found"
Check paths in the script match your directory structure, or use `--index-file` to specify the correct path.

### "Out of memory"
The scripts are designed to stream data, so memory shouldn't be an issue. If it occurs:
- For pairs generation: Reduce `--batch-size`
- For representations: Process in chunks (modify script)

### Resuming interrupted pair generation
```bash
python3 generate_oracle_pairs_v2.py --resume
```

The script will continue from where it left off.

---

## Citation

If you use these datasets, please cite:

- **Equational Theories Project**: Terry Tao's catalogue of 4694 magma equations
- **semantic-diffchecking**: The oracle and translation infrastructure
- **Natural Latents**: The representation learning methodology

---

## License

Same as parent project - see repository root for license details.
