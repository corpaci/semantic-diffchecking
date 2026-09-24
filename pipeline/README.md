# Configurable judge pipeline

One YAML or JSON configuration controls data generation, training, and evaluation.
Call the same workflow from Python or the command line.

```python
from pipeline.run import run

plan = run("configs/judge-v0-baseline.yaml", stage="all", dry_run=True)
print(plan["adapter_dir"])
```

`dry_run=True` prints planned commands without building data or launching training.
Remove it only when the data, dependencies, and compute are prepared.

```bash
python -m pipeline.run --config configs/rep-lean.yaml --stage all --dry-run
```

## Configuration

The defaults are defined in `config.py`. Unknown keys and unsupported metric names fail before work starts.

| Section | Controls |
|---|---|
| `data` | Output directory, label counts, class split fractions, pinned-class threshold |
| `render` | Infix, Lean, LaTeX, Python lambda, or function-call equation notation; renaming and equality reversal |
| `prompt` | Exact training/inference template; fixed label identifiers |
| `model` | Base checkpoint and LoRA rank, layer placement, and modules |
| `train` | Learning rate, batches, steps, evaluation interval, checkpoint retention, output directory |
| `eval` | Dataset splits and selected accuracy, error-rate, per-label, and per-tier metrics |

`function_call` is an equation representation, separate from the Python API.
The current public pipeline supports the original sampler only.
Shape-balanced data construction and shape-specific diagnostics from the research workspace are not included in this interface update.
It does not claim to reproduce the later v2/v3 experiments.

Relative artifact paths resolve against this repository root, independent of the caller's working directory.
Configuration file paths resolve from the caller's working directory.
Data generation defaults to this checkout's `oracle/`; `SDC_ORACLE` can override that directory.
Prepare its catalogue and matrix using [oracle setup](../oracle/README.md).

## Reuse and checkpoints

```python
from pipeline.config import load
from pipeline.run import run

config = load("configs/judge-v0-baseline.yaml")
config.train["out_dir"] = "judge/runs/new-run"
# run(config, stage="train")  # Executes actual training when enabled.
```

Stages are `data`, `train`, `eval`, and `all`.
The function revalidates Config objects and returns artifact paths after the requested stages succeed.
Failures propagate to the caller. Evaluation failures cannot silently become successful summaries.

The data stage reuses a complete dataset only when its saved pipeline recipe matches.
Changing representation or sampling settings requires a fresh data directory.
For pre-existing datasets without a recipe, run only `train` or `eval` explicitly.
The recipe records configuration, not a cryptographic identity of the underlying oracle files.
Changing oracle artifacts requires a fresh data directory.

Training refuses to overwrite an existing final adapter or its saved configuration.
`resolved_config.yaml` can be loaded again with `load()`.
Intermediate checkpoints and the final adapter carry their prompt and tokenizer.
`keep_checkpoints=0` retains all training checkpoints; positive values limit retained checkpoints.

## Metrics

`eval_summary.json` contains the selected metrics and sample counts for each requested split.

- False equivalence: non-equivalent examples predicted equivalent, divided by all non-equivalent examples.
- Missed equivalence: equivalent examples predicted non-equivalent, divided by all equivalent examples.
- Per-label metrics: precision, recall, gold support, and prediction count.
- Per-tier metrics: separate summaries for the dataset's tier labels.

Undefined rates are `null`, not zero. Every scored row needs a resolved oracle label.
The pipeline also writes the scored JSONL rows for independent analysis.
It does not treat judge predictions as verified labels.
