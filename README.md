# LADR Drift

This repository studies semantic drift when LLMs translate authentic textbook
mathematics into Lean 4 theorem statements.

## Current experiment

Run the same 256 LADR theorems under three conditions:

1. `statement_only`: theorem statement -> Lean statement.
2. `statement_plus_proof`: theorem statement + informal proof -> Lean statement.
3. `two_stage`: theorem + informal proof -> semantic plan -> Lean statement.

The primary comparison uses GPT-5.5 and GPT-5.6 Sol with
`reasoning.effort = none`. The separate compiler-feedback repair agent is not
part of this run.

## Repository layout

- `LADR_all_material/`: source dataset only; no generated outputs.
- `scripts/`: three current experiment entry points plus Lean checking and analysis utilities.
- `lean_checker/`: reproducible Lean 4 + Mathlib environment.
- `results/`: generated outputs grouped first by experiment, then by model and
  reasoning mode.
- `ladr_pilot_log_2026-06-25.md`: concise 27-theorem pilot findings.
- `ladr_paper_plan_2026-07-05.md`: longer-term research plan.

See `results/README.md` for the artifact layout and dry-run commands.
