# ETP relation judge: Python API and CLI

Load a trained adapter once, then score equation pairs from another Python program.
The output describes **B relative to A**: equivalent, weaker, stronger, or incomparable.

## Python interface

Run from the repository root:

```python
from judge import Judge

judge = Judge("judge/runs/judge-v0/adapter-final")
verdict = judge("x * y = y * x", "a * b = b * a")
print(verdict.label, verdict.confidence)
print(verdict.to_dict())

results = judge.compare_many([
    ("x * y = y * x", "a * b = b * a"),
    ("x * y = y * x", "x = x"),
], batch_size=2)
```

`compare(a, b)` and `judge(a, b)` are equivalent.
`compare_many` preserves input order. `probs` returns an `(n, 4)` NumPy array.
Its label order is `equivalent`, `weaker`, `stronger`, `incomparable`.
Empty inputs return an empty list or `(0, 4)` array.
`rank(intended, candidates)` sorts candidates by their equivalence score.

Use a Llama adapter directory to select the Llama backbone.
The loader reads `base_model_name_or_path` from the adapter configuration.
It supports CPU, CUDA, and MPS. Runtime and memory depend on the model and hardware.

## Installation and artifacts

```bash
python -m pip install -r judge/requirements.txt -r pipeline/requirements.txt
```

Base weights and trained adapters are not committed.
Obtain an adapter directory from the experiment owner or train one using the pipeline.
A usable adapter includes `adapter_config.json` and `adapter_model.safetensors`.
Base models may require Hugging Face authentication and acceptance of their licenses.
First load downloads uncached base weights.

## Command line

```bash
python -m judge compare "x * y = y * x" "x = x" --adapter judge/runs/judge-v0/adapter-final --json
python -m judge batch pairs.jsonl --adapter judge/runs/judge-v0/adapter-final --out scored.jsonl
python -m judge rank intended.txt candidates.txt --adapter judge/runs/judge-v0/adapter-final
```

The original `python judge/judge.py ...` invocation remains supported.

## Training and evaluation

See [the configurable pipeline](../pipeline/README.md).
It exposes `run(config, stage=..., dry_run=...)` and the equivalent CLI.
The original scripts remain available for data building, training, detailed evaluation, and LoRA sweeps.

New training saves `prompt_template.json` with the final adapter and each training checkpoint.
It also saves checkpoint tokenizers, resolved configuration, final metrics, and training-state logs.
Older adapters without prompt metadata use `A: {a}\nB: {b}\nRelation:`.
Change representations during data generation, then train an adapter for the chosen input format.
The inference API does not translate arbitrary Lean or Python inputs into infix.

## Interpretability and limitations

`judge.model` exposes the live PEFT model for hooks and interventions.
`judge.tok` exposes the tokenizer. `judge.format_prompt(a, b)` uses the saved template.

These models predict a relation token; they do not generate chain-of-thought text.
Training uses the distinct first token of each label, with loss masked to the answer position.
Inference normalizes scores over those four label tokens.
Confidence is not a calibrated correctness guarantee. There is no unknown class or automatic oracle check.

The existing sampler balances label counts, not syntax-label associations.
It permits repeated underlying pairs and includes same-law equivalences.
Class-held-out evaluation requires at least one novel endpoint, not necessarily both.
These limitations prevent interpreting accuracy alone as proof of semantic generalization.
Corrected sampling and causal interpretability experiments remain separate research work.

The [historical report](HISTORICAL_RESULTS.md) preserves the original numbers with explicit qualifications.
This interface update does not establish new model accuracy, calibration, or causal mechanisms.

## Verification

```bash
python -m unittest discover -s tests -v
python -m pipeline.run --config configs/judge-v0-baseline.yaml --stage all --dry-run
```

Tests cover synthetic scoring, batching, representation controls, configuration, metrics, and failure propagation.
They do not validate the trained Gemma or Llama weights.
A real-model inference smoke test and a GPU training smoke test remain outstanding.
