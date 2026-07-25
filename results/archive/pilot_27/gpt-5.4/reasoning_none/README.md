# LADR Pilot 27 Generated Artifacts

This folder contains the generated outputs for the 27-theorem LADR pilot.
All conditions used GPT-5.4 with the API default `reasoning.effort = none`.

## one_shot_ab

Direct one-shot statement generation.

- `lean_statement_pilot_ab.jsonl`: raw model outputs for `statement_only` and `statement_plus_proof`.
- `lean_statement_pilot_ab_checked.jsonl`: Lean check results for the raw outputs.
- `lean_error_analysis.tsv`: error taxonomy summary from the checked outputs.
- `lean_files/`: per-theorem Lean files emitted during checking/debugging.

## repair_agent_ab

Direct statement generation with compiler-feedback repair.

- `lean_statement_agent_ab.jsonl`: final outputs, attempts, message history, validation, and Lean results for `statement_only` and `statement_plus_proof`.

## multistage_skeleton

Two-pass proof-skeleton condition.

- `lean_statement_multistage_skeleton.jsonl`: Stage 1 proof-skeleton attempts and Stage 2 final statement extraction attempts.

