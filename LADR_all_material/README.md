# LADR Dataset

This directory contains the source data extracted from *Linear Algebra Done
Right*. Generated model outputs do not belong here; they are stored under
`../results/`.

## Files

- `LADR_defs_136.jsonl`: 136 definitions.
- `LADR_thms_256.jsonl`: 256 theorems with informal proofs.
- `LADR_examples_134.jsonl`: 134 worked examples.
- `LADR_exercises_733.jsonl`: 733 exercises.
- `LADR_pilot_27.jsonl`: the 27-theorem pilot subset.

Each file uses JSON Lines format. Common fields are `name`, `domain`, and
`nl_statement`; theorem records also contain `informal_proof`.

The current experiments use `LADR_thms_256.jsonl`. See the repository README
and `../results/README.md` for the experimental conditions and artifact layout.
