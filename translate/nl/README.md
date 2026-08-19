# `translate/nl` — formal ETP equation → natural-language description

The forward half of the representation change: hand a model an ETP law and ask
it to describe the law in words. One function does the whole catalogue.

```python
from describe import describe_catalogue

describe_catalogue(
    "qwen/qwen3-30b-a3b",                       # any OpenRouter model id
    open("prompts/structural.txt").read(),      # the prompt; equation goes last
    "descriptions-qwen3.json",                  # output
)
```

That sends the same prompt 4694 times — once per ETP law, with the equation
substituted — and writes `{meta, descriptions}` to the path. Every model is
reached through **[OpenRouter](https://openrouter.ai)**: one key, one endpoint,
open and closed models on the same code path.

## Setup

```bash
# from the repo root
uv venv .venv --python 3.12
uv pip install --python .venv/bin/python openai        # the only dependency

export OPENROUTER_API_KEY=sk-or-...                    # or translate/nl/.env (gitignored)
cd translate/nl
../../.venv/bin/python describe.py --model qwen/qwen3-30b-a3b --out /tmp/x.json --dry-run
```

`--dry-run` makes no calls: it prints the cost estimate and one fully rendered
prompt. Start there whenever the prompt changes.

The ETP catalogue is located exactly as [`../../oracle`](../../oracle/README.md)
locates it (`$ETP_EQUATIONS`, else `$ETP_ROOT/data/equations.txt`, else
`~/equational_theories/…`), or pass `--equations`.

## Files

| file | role |
|---|---|
| `describe.py` | `describe_catalogue`, `describe_equation`, the prompt renderer, and the CLI |
| `openrouter.py` | transport: credentials, the SDK client, the model catalogue, parameter-drop recovery |
| `prompts/structural.txt` | default prompt — describe the structure, naming the law forbidden |
| `prompts/named.txt` | contrast prompt — naming the law allowed |

## The prompt

Prompts are plain text files, so changing one is editing a file. The equation is
substituted at `{equation}`; a prompt with no placeholder gets the equation
appended at the end, which is the "prompt with the equation last" shape.

Both the full prompt text and its hash go into the output. That is not
bookkeeping for its own sake: a description is only interpretable next to the
instruction that produced it, and two runs with different prompts must never
pool into one table by accident.

The default prompt forbids naming the law ("commutative", "associative"). That
is a deliberate measurement choice, not politeness: a named law makes the
reverse direction a lookup rather than a translation, which hides exactly the
structural drift this project is trying to see. `prompts/named.txt` is the
contrast condition — run both when the question is *how much* a name shortcuts
the task.

## CLI

```bash
# pilot: 20 equations, see what comes back
../../.venv/bin/python describe.py --model qwen/qwen3-30b-a3b \
    --prompt prompts/structural.txt --out pilot.json --limit 20

# the full sweep
../../.venv/bin/python describe.py --model qwen/qwen3-30b-a3b \
    --prompt prompts/structural.txt --out descriptions-qwen3.json --yes

# continue after an interruption
../../.venv/bin/python describe.py ... --resume
```

| flag | meaning |
|---|---|
| `--model` | OpenRouter model id (required) |
| `--prompt` | prompt template file (default `prompts/structural.txt`) |
| `--out` | output JSON path (required) |
| `--limit N`, `--nodes 43,4512` | restrict which equations are sent |
| `--form etp\|latex` | notation put in the prompt — `latex` renders via [`../latex`](../latex/README.md) |
| `--temperature`, `--max-tokens`, `--seed` | generation settings; withheld ones are recorded |
| `--concurrency N` | requests in flight (default 8) |
| `--resume` | continue from `<out>.partial.jsonl` |
| `--max-spend USD` | stop launching calls once reported spend reaches this |
| `--dry-run` | print the estimate and a rendered prompt; make no calls |
| `--yes` | skip the confirmation for a run costing over $1 |

## Output

```json
{
  "meta": {
    "model": "qwen/qwen3-30b-a3b",
    "prompt": "Describe the following identity …",
    "prompt_sha": "fff74fb17147",
    "equation_form": "etp",
    "params": { "temperature": 0.0, "max_tokens": 400, "seed": null },
    "params_withheld": null,
    "count": 4694,
    "statuses": { "ok": 4690, "empty": 3, "failed": 1 },
    "descriptions_echoing_notation": 93,
    "upstream_providers": { "Cerebras": 4694 },
    "usage": { "input_tokens": 1220440, "output_tokens": 258170,
               "cost_usd": 0.2347, "cost_includes_estimates": false },
    "started_at": "…", "finished_at": "…", "elapsed_s": 412.7
  },
  "descriptions": [
    { "node": 43, "formal": "x ◇ y = y ◇ x",
      "description": "Combining the first value with the second gives …",
      "status": "ok", "finish_reason": "stop",
      "model_reported": "qwen/qwen3-30b-a3b", "upstream_provider": "Cerebras",
      "usage": { "input_tokens": 260, "output_tokens": 55,
                 "cost_usd": 0.00005, "cost_source": "reported" },
      "latency_s": 1.83, "attempts": 1, "mentions_notation": false,
      "timestamp": "…" }
  ]
}
```

Rows are in node order and **every** equation appears. `status` is `ok`,
`empty` (the call succeeded but returned no text — usually a reasoning model
that spent its whole budget thinking, which `finish_reason` will say), `failed`
(the call errored; `error` carries the provider's words), or `skipped-budget`.
Nothing is dropped: excluding the rows a model mangled would quietly turn "the
model refused on 40 laws" into "the model described 4654 laws".

`mentions_notation` flags a description that echoes `◇`, `\diamond`, or `=`
despite being told not to. It is a flag for filtering, not a verdict — deciding
what counts as a failure is the analysis's job.

`node` is the ETP equation number, so these rows join directly against
[`../latex`](../latex/README.md)'s catalogue and against the implication graph
in [`../../oracle`](../../oracle/README.md).

## What 4694 paid calls needs that one call does not

**A cost estimate before, not after.** OpenRouter publishes per-token prices, so
the run is priced up front, and a run over $1 asks for confirmation
(`--yes` to skip). Current full-sweep estimates from the live catalogue:

| model | estimate |
|---|---|
| `openai/gpt-5-nano` | ~$0.35 |
| `qwen/qwen3-30b-a3b` | ~$0.50 |
| `anthropic/claude-opus-5` | ~$24 |

The estimate is crude on purpose (prompt characters ÷ 4, plus 160 assumed output
tokens) — an order-of-magnitude guard, not accounting. `--max-spend` is the hard
stop: once *reported* spend passes it, no further calls are launched and the
remaining equations are recorded as `skipped-budget`.

**Nothing lost to an interruption.** Each finished row is appended to
`<out>.partial.jsonl` and flushed immediately, so a killed run loses only the
calls in flight. `--resume` continues from there. The checkpoint's header
records the model, prompt hash, form, and parameters, and a resume that does not
match them **refuses** rather than blending two experiments into one file —
editing the prompt and resuming is exactly the mistake worth making impossible.

**Only parameters the model accepts.** Through OpenRouter,
`anthropic/claude-opus-5` takes `temperature` and `openai/gpt-5-nano` does not,
so `--temperature 0` is a deterministic request on one and silently impossible
on the other. The catalogue decides what is sent, and anything withheld is
recorded per row and in `meta.params_withheld`. Reasoning-capable models get
`REASONING_HEADROOM` added to `--max-tokens`, because reasoning tokens come out
of the same budget and would otherwise return an empty answer.

**Concurrency.** Eight requests in flight by default; 429s and 5xx are retried
inside the SDK with `retry-after` honoured, and the retry count lands in each
row's `attempts`.

## Verification status

No live sweep has been run — this machine has no `OPENROUTER_API_KEY`. What was
checked:

| path | how |
|---|---|
| full 4694-row sweep: output shape, node ordering, meta totals, 2.9 MB JSON | network stubbed |
| `status` handling for ok / empty / failed rows | stubbed, with injected refusals and a 500 |
| checkpoint + `--resume` | resumed a finished run: 0 new calls; extended 60 → 80: exactly 20 new calls |
| resume after editing the prompt | refuses, naming both identities |
| `--max-spend` | stopped after 5 calls at $0.005, remainder recorded `skipped-budget` |
| cost estimation, model search, unknown-model rejection | live against OpenRouter's public `/models` |
| `--dry-run`, `--form latex` | live catalogue + the sibling renderer |
| missing key | reports where to put one, before any call |

Put a key in `translate/nl/.env` and the first thing to run is
`--limit 20 --dry-run`, then `--limit 20`, before spending on the full sweep.
