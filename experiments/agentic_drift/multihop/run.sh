#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../../.."
execute=false
for argument in "$@"; do
  [[ "$argument" != --execute ]] || execute=true
done
if "$execute" && [[ -z "${DRIFT_API_KEY:-}" ]]; then
  read -r -s -p 'OpenRouter experiment key (hidden): ' DRIFT_API_KEY
  echo
  export DRIFT_API_KEY
fi
exec .venv-agentic/bin/python -u -m experiments.agentic_drift.multihop.study run "$@"
