# Quick Start Guide - Data Generation V2

## What You Have Now

✅ **3 new scripts created:**
1. `generate_oracle_pairs_v2.py` - Generate all 22M equation pairs with oracle labels
2. `build_equations_representations_v2.py` - Combine all representations into v2 JSON
3. `test_data_generation.py` - Validate setup before running

✅ **Current Status** (from validation):
- ✓ 4,694 equations loaded from index
- ✓ 3/4 translation files found (lean, latex, py_lambda)
- ✓ Output directories writable
- ⚠️ Oracle matrix NOT built yet (required for pairs generation)

---

## Quick Commands

### 1. Test Current Setup
```bash
python3 test_data_generation.py
```

### 2. Build Representations V2 (Ready Now!)
```bash
# This will work immediately - doesn't need oracle
python3 build_equations_representations_v2.py --pretty
```

**Output:** `etp-semantic-equivalence-repo-natural-latents (2)/data/equations_representations_v2.json`

**Time:** ~1-2 minutes  
**Size:** ~50-150 MB

### 3. Generate All Pairs V2 (Needs Oracle Setup First)
```bash
# First, build oracle matrix (one-time setup):
cd oracle/
python3 build_matrix.py /path/to/outcomes.json.zip
cd ..

# Then generate all pairs:
python3 generate_oracle_pairs_v2.py
```

**Output:** `etp-semantic-equivalence-repo-natural-latents (2)/data/oracle_labeled_pairs_v2.csv`

**Time:** 6-12 hours for all 22M pairs  
**Size:** ~500-600 MB CSV

---

## What Each Script Does

### `build_equations_representations_v2.py`

**Combines all these representations into one JSON:**
- ✓ formal (from index)
- ✓ lean (found)
- ✓ latex (found)
- ✓ py_lambda (found)
- ✓ py_cayley_table (will check)
- ✗ natural_language (missing - but can extract from v1)
- Plus 12+ more if available (ssa, slots, rpn, etc.)

**Each equation gets all available representations:**
```json
{
  "node": 43,
  "formal": "x ◇ y = y ◇ x",
  "lean": "∀ x y : G, x ◇ y = y ◇ x",
  "latex": "x \\diamond y = y \\diamond x",
  "py_lambda": "lambda op, x, y: op(x, y) == op(y, x)",
  ...
}
```

### `generate_oracle_pairs_v2.py`

**Creates ALL possible pairs with relationships:**
- 4,694 equations × 4,694 equations = 22,033,636 pairs
- Each labeled: `equivalent`, `stronger`, `weaker`, `incomparable`, `unknown`
- Includes both directions (A→B and B→A)

**Output format:**
```csv
node_a,node_b,relation
1,43,weaker
43,1,stronger
43,43,equivalent
```

---

## Oracle Setup (Required for Pairs Generation)

The oracle needs two files from the Equational Theories Project:

### Option 1: Download Just What You Need (Recommended)
```bash
cd oracle/

# Download equations.txt (~200 KB)
wget https://raw.githubusercontent.com/teorth/equational_theories/main/data/equations.txt

# Download outcomes file (~2 MB)
wget https://github.com/teorth/equational_theories/raw/main/data/2024-11-10-outcomes.json.zip

# Build the matrix
python3 build_matrix.py 2024-11-10-outcomes.json.zip
```

### Option 2: Use Existing ETP Checkout
```bash
# If you have the repo at ~/equational_theories:
cd oracle/
python3 build_matrix.py

# Or set environment variable:
export ETP_ROOT=/path/to/your/equational_theories
python3 build_matrix.py
```

**What this creates:**
- `data/matrix.bin` (~22 MB)
- `data/matrix_meta.json` (metadata)

---

## Example Workflow

### Start Now (Without Oracle)

```bash
# 1. Validate setup
python3 test_data_generation.py

# 2. Build v2 representations (works now!)
python3 build_equations_representations_v2.py --pretty

# 3. Check the output
head etp-semantic-equivalence-repo-natural-latents\ \(2\)/data/equations_representations_v2.json

# 4. Get statistics
python3 -c "import json; data=json.load(open('etp-semantic-equivalence-repo-natural-latents (2)/data/equations_representations_v2.json')); print(f'{len(data)} equations'); print('Keys:', list(data[0].keys()))"
```

### Later (After Oracle Setup)

```bash
# 5. Build oracle (one-time)
cd oracle/
wget https://github.com/teorth/equational_theories/raw/main/data/2024-11-10-outcomes.json.zip
python3 build_matrix.py 2024-11-10-outcomes.json.zip
cd ..

# 6. Test oracle works
python3 test_data_generation.py

# 7. Generate all pairs (overnight run)
nohup python3 generate_oracle_pairs_v2.py > pairs_generation.log 2>&1 &

# 8. Monitor progress
tail -f pairs_generation.log

# 9. Resume if interrupted
python3 generate_oracle_pairs_v2.py --resume
```

---

## Files Created

```
semantic-diffchecking/
├── generate_oracle_pairs_v2.py          # Script 1
├── build_equations_representations_v2.py # Script 2
├── test_data_generation.py              # Validation script
├── DATA_GENERATION_README.md            # Full documentation
├── SETUP_INSTRUCTIONS.md                # This file
│
├── oracle/
│   └── data/
│       ├── matrix.bin                   # ← Build this first
│       └── matrix_meta.json
│
└── etp-semantic-equivalence-repo-natural-latents (2)/data/
    ├── equations_representations_v2.json # ← Output 1
    └── oracle_labeled_pairs_v2.csv       # ← Output 2
```

---

## Troubleshooting

### "missing etp_relation_matrix.bin"
→ See "Oracle Setup" section above

### "No translation files found"
→ Check that `translate/` directory exists with subdirectories:
```bash
ls translate/lean/etp_equations_lean.json
ls translate/latex/etp_equations_latex.json
```

### Out of disk space
- Representations v2: ~150 MB
- Pairs v2: ~600 MB
- Total needed: ~1 GB free space

### Script takes too long
- Representations: Should finish in 1-2 minutes
- Pairs: Expected to take 6-12 hours for all 22M pairs
  - Use `--batch-size 50000` for more frequent updates
  - Run with `nohup` or `screen` for long sessions

---

## Next Steps

1. **Run now:** `build_equations_representations_v2.py`
2. **Setup oracle:** Download files and build matrix
3. **Run overnight:** `generate_oracle_pairs_v2.py`
4. **Use the data:** Load CSVs and JSON in your notebooks!

---

## Questions?

- See `DATA_GENERATION_README.md` for full documentation
- Check `oracle/README.md` for oracle-specific setup
- Run `python3 <script> --help` for command-line options
