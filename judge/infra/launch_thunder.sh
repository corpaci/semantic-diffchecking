#!/usr/bin/env bash
# Provision a Thunder Compute instance and stage the judge finetune on it.
# Laptop side. Run `tnr login` once before the first use.
#
#   ./launch_thunder.sh up            # create the instance, print its id
#   ./launch_thunder.sh push <id>     # upload finetune/ (scripts + 39 MB data)
#   ./launch_thunder.sh token <id>    # copy the local HF token up (never printed)
#   ./launch_thunder.sh pull <id>     # download runs/ back to the laptop
#   ./launch_thunder.sh down <id>     # delete the instance (stops billing)
#
# Training itself runs on the instance: `tnr connect <id>` then
# `bash ~/finetune/remote_run.sh smoke` and `... remote_run.sh train`.
set -euo pipefail

GPU="${GPU:-a6000}"          # a6000 (48 GB) is ample for 2B + LoRA; a100 if you want headroom
VCPUS="${VCPUS:-8}"
DISK="${DISK:-200}"          # merged bf16 model (~5 GB) + checkpoints + HF cache
TEMPLATE="${TEMPLATE:-base}"

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# tnr lives in ~/.local/bin, which only non-login shells that source .zshrc see.
command -v tnr >/dev/null 2>&1 || export PATH="$HOME/.local/bin:$PATH"

die() { echo "error: $*" >&2; exit 1; }

case "${1:-}" in
  up)
    # tnr >= 2.0.71 dropped --mode and renamed --disk-size-gb to --disk.
    tnr create --gpu "$GPU" --vcpus "$VCPUS" \
               --template "$TEMPLATE" --disk "$DISK" -y
    echo
    echo "Instance list:"
    tnr status --no-wait
    ;;

  push)
    ID="${2:?usage: $0 push <instance-id>}"
    # runs/ holds tens of GB the instance never needs, and syncing it has twice
    # caused trouble: once uploading a 5.8 GB archive, once overwriting a log a
    # live job was writing. Stash it for the duration of the sync.
    STASH=""
    if [ -d "$HERE/runs" ]; then
      STASH="$(dirname "$HERE")/.runs_stash_$$"
      mv "$HERE/runs" "$STASH"
      trap 'mv "$STASH" "$HERE/runs" 2>/dev/null' EXIT INT TERM
    fi
    tnr scp "$HERE" "$ID:~/"
    rc=$?
    if [ -n "$STASH" ]; then
      trap - EXIT INT TERM
      mv "$STASH" "$HERE/runs"
    fi
    [ "$rc" -eq 0 ] || die "push failed (rc=$rc); runs/ restored"
    echo "uploaded $HERE -> $ID:~/finetune  (runs/ excluded)"
    ;;

  token)
    ID="${2:?usage: $0 token <instance-id>}"
    TOKFILE="$HOME/.cache/huggingface/token"
    [ -f "$TOKFILE" ] || die "no HF token at $TOKFILE — run 'hf auth login' first"
    tnr scp "$TOKFILE" "$ID:~/hf_token"
    echo "token copied to $ID:~/hf_token (remote_run.sh reads it from there)"
    ;;

  pull)
    ID="${2:?usage: $0 pull <instance-id>}"
    mkdir -p "$HERE/runs"
    tnr scp "$ID:~/finetune/runs" "$HERE/"
    echo "downloaded runs/ -> $HERE/runs"
    ;;

  down)
    ID="${2:?usage: $0 down <instance-id>}"
    tnr delete "$ID"
    ;;

  *)
    sed -n '2,12p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
    exit 1
    ;;
esac
