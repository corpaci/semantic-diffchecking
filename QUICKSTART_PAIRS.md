# Quick Start: Generate Equation Pairs (Fast Version)

✅ **Setup Complete!** Oracle is built and equations.txt is downloaded.

---

## 🚀 Ready to Use - Pick Your Speed

### ⚡ Ultra Fast (1-10 seconds)
```bash
# 1,000 pairs - Perfect for quick testing
./generate_pairs.sh --sample-pairs 1000 --output data/pairs_1k.csv

# 10,000 pairs - Good for development
./generate_pairs.sh --sample-pairs 10000 --output data/pairs_10k.csv
```

### 🏃 Fast (1-5 minutes)
```bash
# 50,000 pairs - Good for exploratory notebooks
./generate_pairs.sh --sample-pairs 50000 --output data/pairs_50k.csv

# 100,000 pairs - Recommended for notebook experiments
./generate_pairs.sh --sample-pairs 100000 --output data/pairs_100k.csv
```

### 🚶 Medium (10-30 minutes)
```bash
# 500,000 pairs - Good for model training
./generate_pairs.sh --sample-pairs 500000 --output data/pairs_500k.csv

# 1,000,000 pairs - Large experiments
./generate_pairs.sh --sample-pairs 1000000 --output data/pairs_1M.csv

# First 1000 equations, all pairs, no reverse (~10 min)
./generate_pairs.sh --first-n 1000 --no-reverse --output data/pairs_1k_equations.csv
```

### 🐌 Slow (6-12 hours)
```bash
# All equations, no reverse pairs (~6 hours)
nohup ./generate_pairs.sh --no-reverse --output data/pairs_all_no_reverse.csv > pairs_gen.log 2>&1 &

# All equations, both directions (~12 hours)
nohup ./generate_pairs.sh --output data/pairs_all_full.csv > pairs_gen.log 2>&1 &
```

---

## 📊 What You Get

Each CSV file has this format:
```csv
node_a,node_b,relation
1,1,equivalent
1,2,weaker
2,1,stronger
43,43,equivalent
43,4512,incomparable
...
```

**Relation types:**
- `equivalent` - Both equations are logically equivalent
- `stronger` - node_a is a stronger (more general) law
- `weaker` - node_a is a weaker (more specific) law
- `incomparable` - Neither implies the other
- `unknown` - Not resolved by the oracle

---

## 🎯 Recommended Commands

### For Notebooks
```bash
# Quick development
./generate_pairs.sh --sample-pairs 10000 --output data/pairs_dev.csv

# Production notebook
./generate_pairs.sh --sample-pairs 100000 --output data/pairs_notebook.csv
```

### For Training Models
```bash
# Small model
./generate_pairs.sh --first-n 500 --output data/pairs_train_small.csv

# Medium model
./generate_pairs.sh --sample-pairs 500000 --output data/pairs_train_medium.csv

# Large model
./generate_pairs.sh --sample-pairs 2000000 --output data/pairs_train_large.csv
```

### For Research/Publication
```bash
# Representative 2M sample
./generate_pairs.sh --sample-pairs 2000000 --output data/pairs_research_2M.csv

# Complete dataset (run overnight)
nohup ./generate_pairs.sh --output data/pairs_complete_full.csv > pairs.log 2>&1 &
```

---

## ⏱️ Time Estimates

| Pairs | Command | Time |
|-------|---------|------|
| 1K | `--sample-pairs 1000` | ~1 sec |
| 10K | `--sample-pairs 10000` | ~2 sec |
| 50K | `--sample-pairs 50000` | ~7 sec |
| 100K | `--sample-pairs 100000` | ~15 sec |
| 500K | `--sample-pairs 500000` | ~1 min |
| 1M | `--sample-pairs 1000000` | ~2 min |
| 2M | `--sample-pairs 2000000` | ~5 min |
| 10M | `--no-reverse` (~11M pairs) | ~6 hrs |
| 22M | (full, both directions) | ~12 hrs |

**Rate:** ~7,000 pairs/second on test system

---

## 🔧 Advanced Options

### Use Specific Equations
```bash
# First 200 equations only
./generate_pairs.sh --first-n 200

# Random 1000 equations (reproducible seed)
./generate_pairs.sh --sample-equations 1000
```

### Skip Reverse Pairs
```bash
# Cuts pairs in half (only A→B, not B→A)
./generate_pairs.sh --no-reverse

# Useful when you don't care about directionality
./generate_pairs.sh --first-n 2000 --no-reverse
```

### Combine Options
```bash
# Sample 500 equations, get all their pairs without reverse
./generate_pairs.sh --sample-equations 500 --no-reverse

# First 1000 equations, sample 50K pairs from them
./generate_pairs.sh --first-n 1000 --sample-pairs 50000
```

---

## 📁 Output Files

Files are created in the `data/` directory by default:
```
semantic-diffchecking/
└── etp-semantic-equivalence-repo-natural-latents (2)/
    └── data/
        ├── pairs_1k.csv
        ├── pairs_10k.csv
        ├── pairs_100k.csv
        └── oracle_labeled_pairs_v2.csv (default output name)
```

---

## 🔍 Monitor Long-Running Jobs

If you run with `nohup` in background:
```bash
# Check progress
tail -f pairs_gen.log

# Check if still running
ps aux | grep generate_oracle_pairs

# Count pairs generated so far
wc -l data/oracle_labeled_pairs_v2.csv
```

---

## ✅ Verify Output

```bash
# Count lines (subtract 1 for header)
wc -l data/pairs_100k.csv

# Check format
head -5 data/pairs_100k.csv

# Count by relation type
tail -n +2 data/pairs_100k.csv | cut -d, -f3 | sort | uniq -c
```

---

## 💡 Tips

1. **Start small** - Test with `--sample-pairs 1000` first
2. **Use wrapper script** - `./generate_pairs.sh` handles environment setup
3. **Name your outputs** - Use `--output data/pairs_YOURNAME.csv`
4. **Resume if interrupted** - Add `--resume` to continue
5. **Check relation distribution** - Use `cut`/`sort`/`uniq` to analyze

---

## 🆘 Troubleshooting

### Script not found
```bash
chmod +x generate_pairs.sh
./generate_pairs.sh --help
```

### "Oracle not found"
The oracle should already be built. If not:
```bash
cd oracle/
python3 build_matrix.py
```

### "equations.txt not found"
The wrapper script downloads it automatically. If it fails:
```bash
wget -O oracle/equations.txt https://raw.githubusercontent.com/teorth/equational_theories/main/data/equations.txt
```

---

## 📖 More Information

- **Full documentation:** See `SAMPLING_OPTIONS.md`
- **Data generation guide:** See `DATA_GENERATION_README.md`
- **Setup instructions:** See `SETUP_INSTRUCTIONS.md`

---

**Ready to generate!** Start with a quick test:
```bash
./generate_pairs.sh --sample-pairs 1000 --output data/test.csv
head data/test.csv
```
