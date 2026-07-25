# Results

Generated artifacts are grouped first by experimental condition. Source data
stays in `LADR_all_material/`.

## Layout

```text
results/
  statement_only/
    <model>/reasoning_<effort>/generations.jsonl
  statement_plus_proof/
    <model>/reasoning_<effort>/generations.jsonl
  two_stage/
    <model>/reasoning_<effort>/generations.jsonl
  archive/
    pilot_27/
    full_256_partial/
```

The primary comparison uses `gpt-5.5` and `gpt-5.6-sol`, both with
`reasoning.effort = none`. Reasoning-enabled runs are optional follow-ups.

## Dry runs

Each experiment has its own entry point:

```bash
python3 scripts/statement_only.py \
  --model gpt-5.5 --reasoning-effort none --dry-run

python3 scripts/statement_plus_proof.py \
  --model gpt-5.5 --reasoning-effort none --dry-run

python3 scripts/two_stage.py \
  --model gpt-5.5 --reasoning-effort none --dry-run
```

Replace `gpt-5.5` with `gpt-5.6-sol` for the second model. JSONL files are
resumable; rerunning the same condition, model, and reasoning mode skips
completed records.
