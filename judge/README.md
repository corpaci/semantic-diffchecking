# `judge` — a trained relation judge for the ETP fragment

Classifies the logical relation between two equational laws:

```
equivalent | weaker | stronger | incomparable
```

The label describes **B relative to A**, matching `oracle/`'s convention
(`weaker` = B drops constraints).

This replaces a stack of prompted LLMs with a single measurable artifact: known
training data, a known split, and weights we own and can probe. It is trained on
the ETP implication matrix, where every label is Lean-verified rather than judged.

**No GPU required to use it.** One comparison is a couple of seconds on CPU;
CUDA and Apple-Silicon MPS are used automatically when available.

---

## Quickstart

```bash
pip install torch transformers peft
huggingface-cli login          # Gemma is gated: accept the license first

export JUDGE_ADAPTER=/path/to/judge-v0/adapter-final
python3 judge.py compare "x * y = y * x" "a * b = b * a"
```

```
A: x * y = y * x
B: a * b = b * a

  equivalent   (confidence 1.000)

  equivalent      1.000  ########################################
  weaker          0.000
  stronger        0.000
  incomparable    0.000
```

First run downloads the ~5 GB base model. The adapter itself is ~113 MB.

### Commands

| command | purpose |
|---|---|
| `compare A B` | score one pair; `--json` for machine output |
| `batch pairs.jsonl` | score a JSONL of `{text_a, text_b}` rows; reports accuracy if `label` present |
| `rank intended candidates.txt` | order candidates by `P(equivalent)` — what best-of-n selection actually does |

`rank` is the one to reach for when using the judge as a *checker*:

```
$ python3 judge.py rank "x * y = y * x" candidates.txt
intended: x * y = y * x

    1. p(equiv)=0.9997  [equivalent  ]  p * q = q * p
    2. p(equiv)=0.9996  [equivalent  ]  a * b = b * a
    3. p(equiv)=0.0383  [weaker      ]  x = x
    4. p(equiv)=0.0017  [incomparable]  x * (y * z) = (x * y) * z
```

### As a library

Downstream interpretability tooling should import rather than shell out:

```python
from judge import Judge

j = Judge("path/to/adapter-final")          # base model read from adapter_config.json
v = j.compare("x * y = y * x", "a * b = b * a")
v.label, v.confidence, v.probs

j.probs([(a, b), ...])                      # (n, 4) array, no argmax applied
j.rank(intended, candidates)                # [(candidate, p_equivalent, pred), ...]
j.model                                     # the live PeftModel, for hooks/probing
```

`Judge.model` is exposed deliberately: activation capture, SAE work, and
ablations attach there.

---

## How it works

Prompt is `"A: {eq}\nB: {eq}\nRelation:"`. The label is a **single next token**
with loss masked to that token alone. At inference the logits are **restricted to
the four label tokens** before the argmax, so the judge cannot emit an invalid
answer — a wrong prediction is always one of the other three, never gibberish.

`unknown` is not a class. The 190 unresolved matrix cells are never sampled, so
the judge cannot abstain. If you need abstention, threshold on `confidence` —
but note calibration is mediocre (see Caveats).

---

## Training data

Built by `build_pair_dataset.py` from `oracle/`'s matrix. Labels are two byte
reads from the Lean-verified implication matrix — **no prover runs at training
time**; the certification is a frozen artifact of the
`2024-11-10-outcomes` snapshot.

```bash
cd judge
python3 build_pair_dataset.py --out data/
```

Requires `oracle/data/matrix.bin` — see `oracle/README.md` to build it.
The generated `data/` is gitignored (39 MB, fully regenerable).

### The split is the important part

**By equivalence class, never by pair.** 1,415 classes → **1,064 train / 140 val
/ 211 test**. Laws inside a class are mutually derivable, so a random pair split
puts the same law on both sides and a lookup table scores perfectly.

The `x = y` class alone is **1,496 laws — 31.9% of the catalogue** — and is
*pinned into training*. A random split could otherwise have removed a third of
all laws from training.

Four splits, and the contrast between two of them is the measurement:

| split | composition | measures |
|---|---|---|
| `train` | 240,000 pairs from train classes | — |
| `pairs_val` | new pairings of **familiar** laws | interpolation |
| `classes_val` | ≥1 law from held-out classes | novel theories |
| `test` | ≥1 law from test classes, never selected on | final |

**`pairs_val − classes_val` is the memorization measurement.** Everything else is
held constant; only law familiarity varies. A pair-level memoriser fails
`pairs_val`; a law-level lookup passes it and fails `classes_val`. Only a
relational model passes both.

---

## Results

Trained models, `test_acc` on 211 held-out equivalence classes (chance = 0.25):

| config | Gemma-2-2B | Llama-3.1-8B |
|---|---|---|
| **baseline** (r16, all layers, all modules) | **0.9619** | **0.9649** |
| rank 4 | 0.9566 | 0.9596 |
| rank 64 | 0.9625 | 0.9647 |
| early layers only | 0.9414 | 0.9619 |
| middle layers only | 0.9494 | 0.9457 |
| **late layers only** | **0.8625** | **0.8491** |
| attention only | 0.9523 | 0.9629 |
| MLP only | 0.9601 | 0.9631 |

Memorization gap: **1.91 pp** (Gemma), **1.25 pp** (Llama). Both trained a judge,
not a lookup table.

**Neither base model can be contaminated.** ETP launched 2024-09-25; Gemma-2 was
released 2024-06-27 and Llama-3.1 on 2024-07-23. Both predate the project's
existence, which is a stronger guarantee than any stated data cutoff.

### What replicates across both families

- **Rank saturates at or below 16.** Quadrupling the adapter moves accuracy
  +0.06 pp / −0.01 pp. Cutting to r=4 costs exactly −0.53 pp on both.
- **Late-only collapses** — 5–6× worse than any other layer choice. The relation
  is built in the front two-thirds, not decided at the end. Note `late` has
  *more* adapted layers than `early` (10 vs 8 on Gemma), so this is positional,
  not a capacity effect.
- **MLP-only is nearly free** — −0.18 pp in both.

### What does NOT replicate — do not claim

- **The attention/MLP asymmetry is a Gemma artifact.** Gemma: attention-only cost
  5× more than MLP-only. Llama: they are equivalent. "The computation lives in
  the MLP" does not survive replication.
- **Early-vs-middle ordering flips** between families.

---

## Retraining

Any CUDA box with **≥ 40 GB** works. Memory is dominated by the vocabulary-sized
logits plus retained activations for every adapted layer.

```bash
python3 train_judge.py --data data --out runs/judge-v0 \
    --micro-batch 64 --grad-accum 2 --eval-rows 2000 --keep-checkpoints 0
```

Measured, so you don't rediscover it:

| model | micro-batch | peak VRAM | outcome |
|---|---|---|---|
| Gemma-2-2B | 128 | > 47 GB | **OOM** on a 48 GB A6000 |
| Gemma-2-2B | 64 | 28.6 GB | fine, ~50 min |
| Llama-3.1-8B | 64 | 43.8 GB | fine, ~50 min on an A100 80 GB |

Gemma-2's 256k vocabulary is what makes it expensive — the logits tensor alone is
~13.7 GB at micro-batch 128 (bf16 + fp32 upcast + gradient). Llama's 128k vocab
halves that.

Keep `--grad-accum` × `--micro-batch` = 128 so runs stay comparable: gradient
accumulation is mathematically equivalent at a fixed effective batch, since each
example contributes exactly one unmasked loss token.

`--keep-checkpoints 0` retains every checkpoint (10 per run at the default
`--eval-every 200`), which the interpretability work needs for trajectories.

### Ablation sweep

`sweep.sh` reproduces the table above, one variable per run, seed fixed:

```bash
MODEL=meta-llama/Llama-3.1-8B OUT=runs/sweep-llama MB=64 GA=2 \
  SKIP_RUNS=baseline bash sweep.sh run
bash sweep.sh summary
```

Finished runs are skipped, so it is safe to re-invoke after a crash.

---

## Evaluation beyond accuracy

`eval_judge.py` reports what training-time accuracy cannot — confusion matrix,
precision (training reports recall only), the false-equivalence rate, the
`equivalent` tier split, symmetry, and best-of-n ranking:

```bash
python3 eval_judge.py --adapter runs/judge-v0/adapter-final --data data
```

Findings for judge-v0 (Gemma):

- **False-equivalence rate 0.0077** — the dangerous error, where a drifted
  candidate is accepted. Missed-equivalence runs at 0.044, so the judge errs
  toward caution by **5.7 : 1**. That is the right asymmetry for a checker.
- **`equivalent` is 50% trivial.** Same-node rows (the identical law re-rendered)
  score **1.000**; cross-node rows score **0.912**. The reported 0.956 is their
  average — **quote 0.912** for genuine equivalence detection.
- **Dominant failure is over-predicting `incomparable`**: recall 0.977 but
  precision 0.899, absorbing 69% of all errors.
- **Symmetry 0.978** — `label(A,B)=weaker` implies `label(B,A)=stronger`.

---

## Caveats

- **Single seed.** No variance estimate on any number here.
- **Calibration is mediocre** — 39.7% of errors are held above 0.9 confidence, so
  a confidence threshold will not cleanly filter dangerous errors.
- **The best-of-n exploitation rate is not yet valid.** The current test uses
  same-node faithful candidates, which the judge never misses (1.000). It must be
  rebuilt with cross-node candidates (0.912) before being quoted.
- **`classes_val` is only 27% both-novel**; 73% pair one novel law with a
  familiar one, so the memorization gap is a *lower bound*.
- **Out-of-fragment behaviour is untrained and unknown.** Training contains only
  the 4,694 catalogued laws. Order > 4 identities, multi-operation expressions,
  and chained equalities never appear.
- **Layer results show where adaptation is *needed*, not where computation
  *lives*.** A frozen late layer may still be doing essential work.

---

## Files

| file | purpose |
|---|---|
| `judge.py` | library + CLI (`compare`, `batch`, `rank`) |
| `train_judge.py` | training; LoRA rank / layer / module flags |
| `build_pair_dataset.py` | builds the splits from `oracle/`'s matrix |
| `eval_judge.py` | post-hoc evaluation |
| `sweep.sh` | ablation sweep driver |
| `infra/` | optional GPU-rental helpers — see `infra/INFRA.md` |
