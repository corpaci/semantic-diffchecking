#!/usr/bin/env bash
# LoRA hyperparameter sweep — runs on the Thunder instance.
#
#   bash ~/finetune/sweep.sh smoke    # 8 steps of every config (~10 min)
#   bash ~/finetune/sweep.sh run      # the real sweep, sequential (~6 h)
#   bash ~/finetune/sweep.sh summary  # table of finished runs
#
# One variable per run, seed fixed, everything else frozen. Each run is a fresh
# start from the base model -- LoRA ranks and layer sets have different shapes,
# so a run cannot be branched off another run's checkpoint.
#
# Already-finished runs are skipped, so this is safe to re-invoke after a crash.
set -uo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")"
# Overridable so the same sweep runs on a second model family:
#   MODEL=meta-llama/Llama-3.1-8B OUT=runs/sweep-llama MB=64 GA=2 \
#     SKIP_RUNS=baseline bash sweep.sh run
MODEL="${MODEL:-google/gemma-2-2b}"
OUT="${OUT:-runs/sweep}"
MB="${MB:-128}"
GA="${GA:-1}"
SKIP_RUNS="${SKIP_RUNS:-}"
COMMON="--data data --seed 0 --model $MODEL --micro-batch $MB --grad-accum $GA --eval-rows 2000 --keep-checkpoints 0"

# name          extra flags                        varies
# layers=all + modules=all is the memory peak: Gemma-2's 256k vocab puts ~13.7 GB
# in the logits region, and every adapted layer retains its input for backward.
# micro-batch 128 OOMs on a 48 GB A6000, so these three drop to 64 x 2. Effective
# batch stays 128, so they remain mathematically comparable with the rest.
CONFIGS=(
  "baseline|--rank 16 --micro-batch 64 --grad-accum 2|reference point"
  "rank4|--rank 4 --micro-batch 64 --grad-accum 2 |rank down"
  "rank64|--rank 64 --micro-batch 64 --grad-accum 2|rank up"
  "early|--rank 16 --lora-layers early            |layer position"
  "middle|--rank 16 --lora-layers middle          |layer position"
  "late|--rank 16 --lora-layers late              |layer position"
  # attn peaked at 45.3/47.4 GB at micro-batch 128 -- survived, but with no
  # margin. mlp adapts down_proj, whose input is 9216-dim vs 2304, so it stores
  # ~1.3 GB more and would almost certainly OOM. Both drop to 64 x 2.
  "attn|--rank 16 --lora-modules attn --micro-batch 64 --grad-accum 2|module type"
  "mlp|--rank 16 --lora-modules mlp --micro-batch 64 --grad-accum 2|module type"
)

load_token() {
  if [ -z "${HF_TOKEN:-}" ] && [ -f "$HOME/hf_token" ]; then
    HF_TOKEN="$(tr -d '[:space:]' < "$HOME/hf_token")"; export HF_TOKEN
  fi
  [ -n "${HF_TOKEN:-}" ] || { echo "error: no HF_TOKEN and no ~/hf_token" >&2; exit 1; }
  export HUGGING_FACE_HUB_TOKEN="$HF_TOKEN"
}

case "${1:-}" in
  smoke)
    load_token
    for c in "${CONFIGS[@]}"; do
      name="${c%%|*}"; rest="${c#*|}"; flags="${rest%%|*}"
      echo "=== smoke: $name ==="
      python3 train_judge.py $COMMON $flags --dry-run --out "$OUT/_smoke_$name" 2>&1 \
        | grep -E "LoRA:|trainable params|error|Error|Traceback" || true
    done
    echo "smoke done -- if every config printed trainable params, the sweep will run"
    ;;

  run)
    load_token
    mkdir -p "$OUT"
    START=$(date +%s)
    for c in "${CONFIGS[@]}"; do
      name="${c%%|*}"; rest="${c#*|}"; flags="${rest%%|*}"; note="${rest##*|}"
      case " $SKIP_RUNS " in *" $name "*)
        echo "=== skip $name (in SKIP_RUNS) ==="; continue ;;
      esac
      if [ -f "$OUT/$name/final_metrics.json" ]; then
        echo "=== skip $name (already finished) ==="; continue
      fi
      echo "=== $name  [$note]  $(date -u +%H:%M:%S) ==="
      python3 -u train_judge.py $COMMON $flags --out "$OUT/$name" > "$OUT/$name.log" 2>&1
      if [ -f "$OUT/$name/final_metrics.json" ]; then
        acc=$(python3 -c "import json;print(json.load(open('$OUT/$name/final_metrics.json'))['test_acc'])" 2>/dev/null)
        echo "    done  test_acc=$acc"
      else
        echo "    FAILED -- see $OUT/$name.log"; tail -5 "$OUT/$name.log"
      fi
    done
    echo "sweep finished in $(( ($(date +%s) - START) / 60 )) min"
    bash "$0" summary
    ;;

  summary)
    python3 - <<'PY'
import json, os, glob
rows = []
for f in sorted(glob.glob("runs/sweep/*/final_metrics.json")):
    name = os.path.basename(os.path.dirname(f))
    m = json.load(open(f))
    cfg = json.load(open(os.path.join(os.path.dirname(f), "run_config.json")))
    ck = len(glob.glob(os.path.join(os.path.dirname(f), "checkpoint-*")))
    rows.append((name, cfg["rank"], cfg["lora_layers"], cfg["lora_modules"],
                 m["test_acc"], m.get("test_acc_equivalent"), ck))
if not rows:
    print("no finished runs yet"); raise SystemExit
base = next((r[4] for r in rows if r[0] == "baseline"), None)
print(f"\n{'run':10s}{'r':>4s}{'layers':>9s}{'modules':>9s}{'test_acc':>10s}"
      f"{'vs base':>9s}{'equiv':>8s}{'ckpts':>7s}")
for n, r, l, mo, a, e, ck in sorted(rows, key=lambda x: -x[4]):
    d = f"{(a - base) * 100:+.2f}" if base and n != "baseline" else "--"
    print(f"{n:10s}{r:>4d}{l:>9s}{mo:>9s}{a:>10.4f}{d:>9s}"
          f"{(e or 0):>8.4f}{ck:>7d}")
PY
    ;;

  *)
    sed -n '2,12p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
    exit 1 ;;
esac
