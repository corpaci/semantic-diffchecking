# Requirement preservation in agentic pipelines

This package supports two experiments:

- **MetaGPT:** follow a fixed request through requirements, architecture, task planning, code, and review.
- **Multi-hop:** refactor correct code repeatedly, testing behavior and structural compliance at every saved hop.

Both retain intermediate artifacts, prompts, returned reasoning, and independent requirement-level checks.
Returned reasoning is provider output, not proof of the model's internal reasoning or causal responsibility.
Tests measure specified cases. Passing tests does not prove unrestricted semantic equivalence.

## Multi-hop experiment

The targeted schedule uses permissions code and code representing an ETP associativity equation.
It compares no reminders against the original requirements at every hop.
Each hop sees only the previous code, the fixed interface, and the current objective.
ETP reminders also include the original equation code. Evaluation results never enter model prompts.
The objectives alternate between expanded and compact forms, which can produce repeated code cycles.

Use Python 3.11 on macOS or Linux, Docker, and the [existing oracle data](../../oracle/README.md#setup-one-time).
Prepare `equations.txt`, `matrix.bin`, and `matrix_meta.json` in `oracle/data/`.
Alternatively, set `DRIFT_ORACLE_DATA` to the directory containing those three files.
For example, copy the downloaded catalogue into the matrix directory after building the matrix.
The runner freezes their checksums before generation.

From the repository root:

```bash
python3.11 -m venv .venv-agentic
.venv-agentic/bin/python -m pip install 'httpx==0.28.1'
docker build --platform linux/amd64 -t semantic-drift-refactor:1 \
  -f experiments/agentic_drift/multihop/Dockerfile.cpu experiments/agentic_drift/multihop

.venv-agentic/bin/python -m unittest \
  experiments.agentic_drift.test_harness \
  experiments.agentic_drift.test_contract \
  experiments.agentic_drift.test_openrouter \
  experiments.agentic_drift.multihop.test_study \
  experiments.agentic_drift.multihop.test_recovery -q

.venv-agentic/bin/python -m experiments.agentic_drift.multihop.study calibrate \
  --out experiments/agentic_drift/runs/calibration
.venv-agentic/bin/python -m experiments.agentic_drift.multihop.study prepare \
  --stage integration --calibration experiments/agentic_drift/runs/calibration/calibration.json \
  --out experiments/agentic_drift/runs/integration
```

These steps make no model requests. Calibration checks authored references and controlled defects.
`integration` schedules 12 one-hop chains. `targeted` uses two hops per chain.
`targeted_long` schedules 36 chains with 20 hops each and three repetitions per combination.
Prepare a new output folder for each schedule. Do not edit frozen sources or tasks during a study.

### Generate, evaluate, and resume

The three model configurations pin Qwen, DeepSeek, and GLM to explicit OpenRouter endpoints.
Preflight rejects unavailable providers, unsupported parameters, excessive prices, and uncapped or resetting keys.
It never silently selects a different model or provider. Configured endpoints can change availability over time.
Use a dedicated funded key capped at $50 or less. Keep one authoritative ledger for all runs.

```bash
bash experiments/agentic_drift/multihop/run.sh \
  --out experiments/agentic_drift/runs/integration --execute
```

The launcher prompts for the key without displaying it, unless `DRIFT_API_KEY` is already set.
It generates artifacts, evaluates them, and writes `summary.json` and `requirements.jsonl`.
Generation uses HTTP requests, not local model weights. No GPU is required.
Ordinary candidate execution uses a separate restricted Docker container without network access or credentials.
ETP evaluation decodes a bounded AST without executing candidate code.
The ETP oracle checks the quantified equation; finite pointwise probes provide an additional, non-universal check.

Rerun the same command to resume between saved hops. Completed chains are skipped.
Confirmed, billed output-limit failures end that chain; other chains continue without retrying the failed request.
Summaries count missing outputs separately from generated artifacts that fail evaluation.
Checkpoints within one chain are dependent observations, not independent runs.

Transport interruptions with unknown billing stop the study. Inspect `status.json`, `transport/events.jsonl`, and the shared ledger.
For a response-less transport failure, use this guarded recovery command:

```bash
.venv-agentic/bin/python -m experiments.agentic_drift.multihop.study recover \
  --out experiments/agentic_drift/runs/integration \
  --chain CHAIN_ID --request-id RESERVATION_ID
```

This defaults to inspection only. Add `--execute` to record recovery and permit one new attempt.
Recovery backs up the original state and keeps the entire unknown charge reserved against the budget.
Then rerun the launcher. Recovery does not change the model, prompt, token limit, or saved predecessor.
It rejects saved responses, changed checkpoints, other unresolved requests, and later attempts.
For verified charges, `python -m experiments.agentic_drift.budget --help` provides reconciliation commands.
Never delete a ledger to bypass a failure or spending limit.

For evaluation or summaries without generation, use the `evaluate` and `summarize` subcommands with the same `--out`.
The default ledger is `experiments/agentic_drift/runs/openrouter-budget/spend.json`.
Run on a server for unattended work. A local laptop must remain awake while its job runs.

## MetaGPT and direct-generation comparison

MetaGPT 0.8.2 runs ProductManager, Architect, ProjectManager, and one Engineer with review enabled.
QA and automatic code summarization are disabled. This is a scoped reproduction, not a published-score replication.
The software-company dependency profile omits unavailable dependencies for unrelated MetaGPT features.
It does not provide the complete MetaGPT feature set. Installed versions are recorded inside the image.

```bash
docker build --platform linux/amd64 -t semantic-drift-metagpt:0.8.2 experiments/agentic_drift
docker run --rm --platform linux/amd64 --network none \
  --memory 2g --cpus 2 --pids-limit 128 --cap-drop ALL --security-opt no-new-privileges \
  --entrypoint python semantic-drift-metagpt:0.8.2 \
  -m unittest experiments.agentic_drift.test_pipeline -q

.venv-agentic/bin/python -m experiments.agentic_drift fetch-classeval \
  --out experiments/agentic_drift/data/classeval
.venv-agentic/bin/python -m experiments.agentic_drift.case prepare \
  --dataset experiments/agentic_drift/data/classeval/ClassEval_data.json \
  --out experiments/agentic_drift/runs/bankaccount
```

The dataset downloader defaults to the case's pinned ClassEval commit and records its source and checksum.
The [BankAccount protocol](cases/bankaccount_v1/PROTOCOL.md) defines 13 requirements and 25 independent checks.
Original ClassEval tests are evaluated separately. ClassEval data uses CC BY-NC 4.0; retain upstream attribution.
Downloaded benchmark data and generated results are not included in this package.
Case preparation exports the clarified public request without reference code or private tests.
Use `case prepare --config PATH` and matching `pilot --config PATH` for another model configuration.

With `DRIFT_API_KEY` set in your environment:

```bash
.venv-agentic/bin/python -m experiments.agentic_drift.pilot \
  --case experiments/agentic_drift/runs/bankaccount --condition direct \
  --out experiments/agentic_drift/runs/direct --execute
.venv-agentic/bin/python -m experiments.agentic_drift.pilot \
  --case experiments/agentic_drift/runs/bankaccount --condition metagpt \
  --out experiments/agentic_drift/runs/metagpt --execute
```

MetaGPT supports `--contract-policy none`, `every_call`, and `planning_only`.
The last policy repeats requirements before architecture and task planning only.
Direct generation always uses the original request without this intervention.
The generation container receives no dataset, tests, reference implementation, or host credentials beyond the inference key.
`case packet --run PATH --out PATH` exports artifacts for requirement annotation; prose remains unassessed until reviewed.

Evaluate BankAccount checkpoints in a separate offline container:

```bash
docker run --rm --platform linux/amd64 --network none \
  --memory 1g --cpus 1 --pids-limit 128 --cap-drop ALL --security-opt no-new-privileges \
  --mount "type=bind,source=$PWD/experiments/agentic_drift/runs,target=/runs" \
  --mount "type=bind,source=$PWD/experiments/agentic_drift/data/classeval,target=/dataset,readonly" \
  --mount "type=bind,source=$PWD/experiments/agentic_drift/cases/bankaccount_v1,target=/checks,readonly" \
  --entrypoint python semantic-drift-metagpt:0.8.2 \
  -m experiments.agentic_drift.evaluate_run --run /runs/direct/run \
  --dataset /dataset/ClassEval_data.json --checks /checks/checks.py --out /runs/direct/evaluation
```

Trace files retain redacted prompts, raw responses, usage, errors, snapshots, and content-addressed artifact versions.
Review traces before sharing: they can contain task content and provider reasoning.
Final-code success alone does not establish preservation in requirements documents or plans.
