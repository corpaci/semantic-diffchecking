# `translate/nl_test` — description → formal equation, graded by the oracle

The closing half of the round trip. [`../nl`](../nl/README.md) turned each ETP
law into a description; this package hands a model the **description alone** —
the formula is never shown — asks for the identity back, and lets the formal
oracle in [`../../oracle`](../../oracle/README.md) say how the reconstruction
relates to the law it came from.

```python
from reconstruct import run_catalogue

run_catalogue(
    "qwen/qwen3-30b-a3b",                          # the reconstructing model
    "../nl/descriptions-qwen3.json",               # a translate/nl output file
    open("prompts/reconstruct.txt").read(),        # the prompt; description goes last
    "results-qwen3.json",                          # output
)
```

One call per description, graded, checkpointed, and summarized into:

| verdict | meaning for the round trip |
|---|---|
| `equivalent` | the law survived the trip through English |
| `weaker` | the model **under**-specified — the original implies its answer, not conversely |
| `stronger` | the model **over**-specified |
| `incomparable` | neither law implies the other |
| `unknown` | both are catalogue laws, but the implication graph does not settle the pair |

`weaker`/`stronger` are stated from the *reconstruction's* point of view, which
is the oracle's convention.

## Setup

Same as [`../nl`](../nl/README.md) — the same virtualenv, the same OpenRouter
key, the same `equations.txt`. The one extra requirement is the oracle's
implication matrix (`oracle/data/matrix.bin`), which is built once with
`python3 build_matrix.py`.

```bash
cd translate/nl_test
../../.venv/bin/python reconstruct.py --model qwen/qwen3-30b-a3b \
    --descriptions ../nl/descriptions-qwen3.json --out /tmp/x.json --dry-run
```

`--dry-run` makes no calls: it prints the cost estimate and one fully rendered
prompt. Start there whenever the prompt changes.

## Files

| file | role |
|---|---|
| `reconstruct.py` | `run_catalogue`, `check_description`, `grade`, the summary, and the CLI |
| `prompts/reconstruct.txt` | default prompt — recover the identity, one line, explicit parentheses |

Transport (`openrouter.py`) and the sweep machinery — payload building, cost
estimation, checkpointing — are imported from [`../nl`](../nl/README.md) rather
than copied, so the two halves of the round trip cannot drift apart.

## One pair at a time

```python
from reconstruct import check

record = check("qwen/qwen3-30b-a3b", "x ◇ y = y ◇ x", "Combining two values …")
record["label"]                      # 'equivalent'
record["extracted"]                  # 'x ◇ y = y ◇ x'
record["oracle"]["evidence"]         # 'both map to Equation 43'
```

The intended law may be its text or its ETP number. The same thing from the
shell:

```bash
../../.venv/bin/python reconstruct.py --model qwen/qwen3-30b-a3b \
    --formal 43 --description "Combining two values in either order gives …"
```

## Reading the equation out of the answer

A model told to emit one line usually does — but not always. Candidates are
tried in order (the whole answer; fenced code blocks; the `=`-bearing lines from
the bottom up, each also with a leading `Answer:`-style label removed) until one
maps to a catalogue node.

Nothing in that step alters operators or grouping, so a candidate is either the
model's equation or fails to parse. Every row records `extraction`
(`verbatim` — the answer was used as written — or `scanned`) and
`candidates_tried`, so any accuracy figure can be recomputed over the verbatim
rows alone. `--strict` turns scanning off entirely, which is the honest
comparison when the question is how often a model *follows the instruction*.

Normalization noise below that level — `a * b = b * a` vs `x ◇ y = y ◇ x`,
LaTeX wrappers, `∀ x y,` prefixes, markdown fences — is the oracle's own job and
is handled in [`../../oracle`](../../oracle/README.md).

## CLI

```bash
# pilot: 20 descriptions
../../.venv/bin/python reconstruct.py --model qwen/qwen3-30b-a3b \
    --descriptions ../nl/descriptions-qwen3.json --out pilot.json --limit 20

# the full sweep
../../.venv/bin/python reconstruct.py --model qwen/qwen3-30b-a3b \
    --descriptions ../nl/descriptions-qwen3.json --out results-qwen3.json --yes

# continue after an interruption
../../.venv/bin/python reconstruct.py ... --resume

# reprint the summary of a finished run; makes no calls
../../.venv/bin/python reconstruct.py --summarize results-qwen3.json
```

| flag | meaning |
|---|---|
| `--model` | OpenRouter model id of the **reconstructing** model |
| `--descriptions` | a `translate/nl` output JSON |
| `--out` | output JSON path |
| `--prompt` | prompt template file (default `prompts/reconstruct.txt`) |
| `--formal`, `--description` | grade a single pair instead of a file |
| `--limit N`, `--nodes 43,4512` | restrict which descriptions are sent |
| `--strict` | grade the answer verbatim; do not scan prose for an equation |
| `--equations` | path to `equations.txt` (default: the oracle's resolution) |
| `--temperature`, `--max-tokens`, `--seed` | generation settings; withheld ones are recorded |
| `--concurrency N` | requests in flight (default 8) |
| `--resume` | continue from `<out>.partial.jsonl` |
| `--max-spend USD` | stop launching calls once reported spend reaches this |
| `--dry-run` | print the estimate and a rendered prompt; make no calls |
| `--summarize FILE` | recompute and print the summary of an existing results file |
| `--yes` | skip the confirmation for a run costing over $1 |

The reconstructing model need not be the one that wrote the descriptions —
`meta.model` and `meta.descriptions.model` record both, and a cross-model run
(qwen describes, opus reconstructs) is the interesting experiment.

## Output

```json
{
  "meta": {
    "model": "qwen/qwen3-30b-a3b",
    "prompt_sha": "0acd24cfa424",
    "extraction": "scan-for-equation",
    "descriptions": { "path": "../nl/descriptions-qwen3.json",
                      "model": "qwen/qwen3-30b-a3b", "prompt_sha": "fff74fb17147" },
    "oracle": { "equations": "…/equations.txt",
                "matrix": { "n": 4694, "source": "2024-11-10-outcomes.json.zip" } },
    "usage": { "input_tokens": 2231, "output_tokens": 15829, "cost_usd": 0.0084 }
  },
  "summary": { "…": "see below" },
  "results": [
    { "node": 387, "formal": "x ◇ y = (y ◇ y) ◇ x",
      "description": "The left side combines the first variable with …",
      "answer": "x ◇ y = (y ◇ y) ◇ x",
      "extracted": "x ◇ y = (y ◇ y) ◇ x", "extraction": "verbatim",
      "candidates_tried": 1, "status": "ok", "label": "equivalent",
      "oracle": { "label": "equivalent", "forward": "proof_true", "backward": "proof_true",
                  "evidence": "both map to Equation 387",
                  "intended_node": 387, "generated_node": 387,
                  "generated_normalized": "x ◇ y = (y ◇ y) ◇ x",
                  "generated_status": "mapped", "generated_order": 3 },
      "usage": { "…": "…" }, "latency_s": 5.9, "timestamp": "…" }
  ]
}
```

Rows are in node order and **every** description appears, including the ones
there was nothing to send for. `status` is `ok`, `empty` (the call returned no
text — usually a reasoning model that spent its whole budget thinking, which
`finish_reason` will say), `failed`, `skipped-budget`, or `no-description` (the
forward half produced none for that law). Dropping those would quietly turn "the
model failed on 80 laws" into a better score on the rest.

### The summary

```
rows: 4694  answered: 4530  statuses: {'ok': 4530, 'empty': 82, 'no-description': 82}
resolved by the oracle: 4102
  correct   equivalent   3180
  incorrect weaker       340
  incorrect stronger     210
  incorrect incomparable 372
unresolved: 428 {'parse-failure': 190, 'outside-fragment': 231, 'internal-error': 7}
not attempted: 164
equivalent share: 77.5% of resolved, 70.2% of answered
same catalogue node: 3174   extraction: {'verbatim': 4401, 'scanned': 129}
```

(Illustrative shape, not a measured result.) Three tiers, deliberately kept
apart:

* **resolved** — the implication graph proved a relation in both directions.
  `equivalent` is the success count; the split of the rest into weaker /
  stronger / incomparable is the finding worth having, because it says *how* a
  round trip fails rather than only that it did.
* **unresolved** — the model answered, but the answer never reached a verdict:
  it did not parse, it was a real magma law with more than four operation
  symbols (`outside-fragment`, which the graph simply cannot address), or the
  pair is one of the handful the graph leaves open (`unknown`). Not evidence in
  either direction.
* **not attempted** — there was no answer to grade at all.

Both accuracy figures are printed because neither is obviously the right one:
over `resolved` it answers "when the oracle can judge, how often is the round
trip faithful"; over `answered` it charges every unparseable answer as a miss.
`same catalogue node` is `equivalent` minus the pairs proved equivalent across
two *different* nodes.

One category is worth knowing in advance: a model that answers with a
**tautology** (`x ◇ x = x ◇ x`, both sides the same term) has written a law that
holds in every magma, but the ETP catalogue lists only `x = x` for that, so the
mapper reports `internal-error` — "normalizer bug, please report". It is not
one. Those rows carry `oracle.generated_tautology: true` and are counted on the
`unresolved` line, so they stay distinguishable from a genuine mapper bug.

## What 4612 paid calls needs that one call does not

Everything [`../nl`](../nl/README.md#what-4694-paid-calls-needs-that-one-call-does-not)
lists, by reusing the same code: a pre-flight estimate, `--max-spend` as a hard
stop, a flushed `<out>.partial.jsonl` checkpoint after every row, and a
`--resume` that **refuses** when the model, prompt, parameters, extraction rule,
or the source descriptions have changed since the checkpoint was written.

**Trust `--max-spend`, not the estimate, on a reasoning model.** The estimate
assumes 40 output tokens per answer, which is true of the answer and false of
the thinking in front of it. Measured on live `qwen/qwen3-30b-a3b` calls: ~2,000
output tokens and ~$0.001 apiece, which puts the full 4,612-call sweep on the
order of **$5** against an estimate of $0.28. The estimate is an
order-of-magnitude guard, and on a reasoning model it is off by one.

For the same reason `--max-tokens` defaults to 1000 here rather than the answer's
actual length: at 200, two of eight sampled laws came back empty, both cut off
at exactly the limit, and both answered when the budget was raised. A cap costs
nothing on a model that does not use it.

## Verification status

| path | how |
|---|---|
| extraction: bare line, code fence, `Answer:` label, prose tail, bold, bullet | live oracle, no calls |
| every verdict label — equivalent / weaker / stronger / incomparable / parse-failure / outside-fragment | live oracle, no calls |
| tautology flag vs. real mapping failure | live oracle, no calls |
| 60-row sweep: node ordering, every row present, statuses, meta totals | network stubbed with correct / prose-wrapped / junk / empty / 500 answers |
| checkpoint + `--resume` | resumed a finished 60-row run: 0 new calls |
| resume after editing the prompt | refuses, naming both identities |
| `--max-spend` | stopped after 6 calls at $0.0005, remainder recorded `skipped-budget` |
| `--summarize` on a finished file | recomputed identically |
| **11 live calls** (`qwen/qwen3-30b-a3b`, nodes 1, 2, 3, 43, 387, 1000, 4512, 4694, plus `--formal/--description`) | real OpenRouter, $0.014 total |

The live sample: 5 of 6 answered laws came back `equivalent` (the sixth was the
tautology described above); the two `empty` rows both answered `ok` on a retry
with `--max-tokens 1200`, one `equivalent` and one `weaker`. No full sweep has
been run.
