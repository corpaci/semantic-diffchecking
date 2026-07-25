# Scripts

## Current experiments

- `statement_only.py`: theorem statement -> Lean statement.
- `statement_plus_proof.py`: theorem statement + informal proof -> Lean statement.
- `two_stage.py`: theorem + informal proof -> semantic plan -> Lean statement.

`_statement_runner.py` is shared infrastructure for the first two scripts and is
not a command users should run directly.

## Utilities

- `check_generated_lean.py`: typecheck generated Lean statements.
- `analyze_lean_checks.py`: summarize compilation outcomes and errors.
- `backtranslate_lean_statements.py`, `build_pilot_comparison_html.py`, and
  `normalize_generated_lean_imports.py`: pilot audit utilities.
- `legacy_repair_agent.py`: old compiler-feedback experiment, excluded from the
  current three-condition run.
