# API Usage Proposal — LADR-Drift Autoformalization Study

- **Date:** 2026-07-05 · **Requester:** Ke Zhang
- **Companion doc:** `ladr_paper_plan_2026-07-05.md` (full research plan; this proposal covers only compute spend)
- **Target:** ICLR 2027 submission (late Sep 2026); all spend lands Jul–Sep 2026

## 1. Summary and ask

| | Amount |
|---|---:|
| **Expected total spend** (cost-control policy §7 enforced, batch APIs, central estimates) | **≈ $200** |
| **Requested budget cap** | **$650** |

Cap composition: expected $200 + GPT-5.5 reasoning-token worst case +$150 + slippage/re-run allowance +$150 + optional GPU scoring +$90 + **rebuttal-period reserve +$60** (reviewer-requested experiments, Nov–Dec). Vendor split (expected → cap): OpenAI ≈ $110 → $400 · Anthropic ≈ $25 → $80 · GPU (RunPod) ≈ $35 → $130; transferable between lines. Human annotation is done by the requester (no labeling spend). Unit costs are calibrated from **measured `usage` fields of a completed 27-theorem pilot**, not guesses.

**Why the gap between expected and cap is real:** reasoning-token billing is the dominant risk. Without the §7 controls (batch-only for thinking models, thinking explicitly disabled on measurement calls, no automatic retries, smoke-tested R), this same experiment would plausibly cost $600–700 — a sibling project (FEM, GPT-5.5 at default thinking) measured $0.25–0.50/call and lost ~$200 of ~$500 to the timeout-retry trap alone. The cap is set so that even partial policy slippage stays in budget.

## 2. What the money buys

We study **semantic drift in textbook autoformalization**: LLM-generated Lean 4 statements that *compile* but do not *faithfully* capture the textbook theorem — especially when the theorem's meaning depends on chapter-level standing assumptions ("𝔽 denotes ℝ or ℂ", "V, W are finite-dimensional inner product spaces"). Deliverables: a human-audited faithfulness benchmark over 256 theorems from *Linear Algebra Done Right* (2×2 context conditions × multiple models), a drift taxonomy, and a meta-evaluation of automatic faithfulness metrics. The API spend covers (a) statement generation with compiler-feedback repair, (b) the measurement layer (back-translation cards, LLM judges), and (c) open-model inference/scoring on rented GPUs.

## 3. Model lineup and roles

| Model | Price ($/MTok in/out) | Thinking default | Role | Volume |
|---|---|---|---|---|
| **GPT-5.4** | $2.50 / $15 | OFF (verified in pilot) | **Primary generator** — full 256 thms × 4 conditions; also judge family A + card channel A | ~2,250 gen calls + measurement |
| **GPT-5.5** | $5 / $30 | ON (medium) | **Secondary generator** — 64-thm stratified subset × 4 conditions. Purpose: same-vendor thinking-ON contrast → "does test-time reasoning improve faithfulness?" | ~560 calls |
| **Claude Opus 4.8** | $5 / $25 | off unless enabled | **Secondary generator** (cross-vendor frontier) — same 64×4 subset, thinking off for parity with GPT-5.4 | ~560 calls |
| **Claude Sonnet 5** | $3 / $15 (intro $2/$10 to 8/31) | **adaptive = ON by default — must be explicitly disabled** | **Measurement workhorse** — judge family B + back-translation card channel B (different vendor from channel A to control self-preference bias). All calls pinned `thinking: disabled`; left at default, adaptive thinking would silently add ~$120–185 | ~4,900 calls |
| **Claude Haiku 4.5** | $1 / $5 | — | Card-vs-card diff judge (cheap utility) | ~1,600 calls |
| **Kimina-Autoformalizer-7B** (open) | GPU rental | — | Secondary generator — the standard open autoformalizer baseline; 64×4 subset | RTX 4090 |
| **One more open 7B formalizer** (Mathesis-Autoformalizer or StepFun-Formalizer; final pick at setup per HF availability) | GPU rental | — | Secondary generator; 64×4 subset | RTX 4090 |
| *(Optional, P2)* CriticLean-32B + FormalAlign-7B | GPU rental | — | Existing trained faithfulness scorers, run as baselines in the metric meta-evaluation | 1× A100 80GB |

Design notes: (1) every generated output is judged by **both** judge families, so no output is scored only by its own vendor; (2) generators-under-test are 5 model families (2 OpenAI, 1 Anthropic, 2 open) — enough to show findings are not single-model artifacts; (3) formal probes (vacuity/triviality checks in Lean) run on our own CPU at $0.

## 4. Execution sequence (what runs when, with spend gates)

| Phase | Week (see plan §7) | What runs | Gate before proceeding | Est. spend |
|---|---|---|---|---:|
| 0. Smoke tests | W1 | 3–5 items per model/config; record R = `usage.output_tokens` | **Mandatory before every full run.** If GPT-5.5 R > 10k tok/call, re-approve its line or drop to 2 conditions | < $5 |
| 1. Primary generation | W1–2 | GPT-5.4: 256×4 one-shot + ≤3 repair rounds (batchable per round) | compile-rate sanity vs pilot (~80%) | ~$10 |
| 2. Measurement on primary | W2–3 | Cards ×2 channels, judges ×2 families ×2 settings, probes (local); human annotation starts | card-channel audit (Lean-literate spot check) | ~$45 |
| 3. Secondary generation | W4–5 | GPT-5.5 (batch only), Opus 4.8, 2 open models on 64×4 subset | smoke-tested R within budget | ~$100–200 |
| 4. Measurement on secondaries | W5–6 | Cards + judges on compiled secondary outputs | — | ~$35 |
| 5. Optional P2 scoring | W7 | CriticLean-32B / FormalAlign on all annotated items | only if cumulative spend < $300 | ~$40–90 |
| 6. Rebuttal reserve | Nov–Dec | Reviewer-requested additions (e.g. pass@k robustness on a subset, one extra model) | released only during rebuttal | ≤ $60 |

## 5. Unit economics (pilot-calibrated)

Measured on the completed gpt-5.4 pilot (27 theorems, real `usage` fields):

- One generation item (theorem × condition, incl. avg 2.2 repair attempts): **~1,650 in / ~350 out tokens** (thinking-off models).
- One back-translation card: **~1,009 in / ~518 out**. One judge call: ~900 in / ~300 out (estimate, same task family).
- GPT-5.5 (thinking-on) is budgeted by the formula `per-call ≈ R × $30/M + input × $5/M`, with R (hidden reasoning + visible output) taken from Phase-0 smoke tests. Prior from a sibling project: R ≈ 8.5k (multiple-choice) to 16.6k (optimization), max 31k. Lean repair rounds are compiler-error debugging — a reasoning-heavy task — so we budget **central R ≈ 8k, range 3k–16k**, and gate on the measured value.

## 6. Budget detail

Sync = pay-as-you-go; Batch = 50% off (both vendors), used wherever the pipeline allows (all components below are batchable; the repair loop batches per round).

| # | Component | Model | Tokens (in/out) | Sync | Batch |
|---|---|---|---|---:|---:|
| G1 | Primary gen, 256×4 + repair | GPT-5.4 | 1.7M / 0.36M | $10 | $5 |
| G2 | Secondary gen, 64×4 + repair (~600 calls) | GPT-5.5 | 0.5M / 1.8–9.6M (R-dependent) | $57–310 | **$29–155** |
| G3 | Secondary gen, 64×4 + repair | Opus 4.8 | 0.42M / 0.09M | $4 | $2 |
| G4 | Secondary gen ×2 open models | 7B on RTX 4090 ($0.34–0.69/h) | ~30 GPU-h incl. setup | $10–30 | — |
| M1 | Back-translation cards ×2 channels (~3,280 cards) | GPT-5.4 + Sonnet 5 | 3.3M / 1.7M | $29–35 | $15–18 |
| M2 | Direct judges, 2 families × {±scope} (~6,560 calls) | GPT-5.4 + Sonnet 5 | 5.9M / 2.0M | $38–46 | $19–23 |
| M3 | Card-diff judge (~1,640 calls) | Haiku 4.5 | 2.0M / 0.41M | $4 | $2 |
| M4 | Formal probes (~5k Lean checks) | local CPU | — | $0 | — |
| M5 | *(P2)* CriticLean-32B + FormalAlign scoring | A100 80GB ($1.4–2.2/h), ~15–30 h | — | $30–90 | — |

**Totals:** central-sync ≈ $250 API + $30 GPU; **with batch discipline ≈ $135 API + $30 GPU ≈ $165, ×1.4 iteration/re-run margin → expected ≈ $200–230.** The $650 cap additionally absorbs: G2 at R=16k sync (+$150), partial policy slippage such as measurement calls accidentally run with thinking on (+$150), full P2 GPU (+$90), and the rebuttal reserve (+$60).

**Declined design alternative (for transparency):** running GPT-5.5 as the *primary* full-scale generator (256×4, ~2,250 calls) would cost ≈ **$340 (batch) – $680 (sync)** for that line alone and add ~40 h of annotation. Rejected: the scientific primary needs thinking-off for a clean context-effect comparison, and annotation — not tokens — is the binding constraint. This is likely the number an intuitive estimate of "GPT-5.5 experiments" lands on; we deliberately structured around it.

## 7. Cost-control policy (enforced in code, not by intention)

1. **Smoke-test before scale.** No full run without a 3–5 item smoke test logging R; budget recomputed from measured R × 1.25.
2. **Thinking settings are pinned and logged — never left at vendor defaults.** GPT-5.4 thinking-off; Opus 4.8 thinking-off; GPT-5.5 medium (its default, and the point of including it); **Sonnet 5 measurement calls explicitly `thinking: disabled`** (its default is adaptive-ON — the one default that would silently inflate the measurement layer). Model + thinking/effort setting recorded in every output row; Phase-0 smoke tests verify zero unexpected reasoning tokens in `usage`.
3. **No client-timeout-plus-retry against reasoning models.** Server-side generation continues and bills in full after a client disconnect; the calls that time out are exactly the most expensive ones. All scripts construct the client with explicit long timeout and `max_retries=0` (SDK default is 2 automatic retries — already patched out). GPT-5.5 runs **batch-only** (also solves its 2.5–5 min/call wall-clock: 560 sync calls ≈ 23–47 h vs one 24 h batch window).
4. **Batch API by default** for generation rounds, cards, and judges (50% off, immune to the disconnect trap).
5. **Spend checkpoints:** cumulative spend reviewed after Phases 1, 3, 4; P2 (M5) proceeds only if cumulative < $250. Pre-declared cut order if over: drop M5 → GPT-5.5 to 2 conditions → drop second open model.

## 8. Assumptions and sensitivities

- Compile rate ~80% after repair (pilot: 85% statement-only, 74% +proof). Lower compile rate ⇒ *less* measurement spend (fewer cards/judges), more repair spend (bounded at 3 attempts) — roughly self-balancing.
- GPT-5.5's R on this task is the single largest uncertainty (G2 spans $57–310 sync / $29–155 batch); bounded by the Phase-0 gate and batch-only policy.
- Second-largest: thinking accidentally enabled on high-volume measurement calls (Sonnet 5 default) — controlled by §7.2 pinning + smoke-test verification.
- Sonnet 5 intro pricing ($2/$10) expires 2026-08-31; most measurement volume lands before then; ceiling uses standard pricing.
- Prices verified 2026-07-05: [OpenAI pricing](https://developers.openai.com/api/docs/pricing), Anthropic published rates, [RunPod GPU rates](https://www.runpod.io/pricing). Re-verify before Phase 3.

## 9. Approval

| Item | |
|---|---|
| Requested cap | **$650** (OpenAI $400 · Anthropic $80 · GPU $130 · rebuttal reserve $60 — transferable between lines) |
| Expected spend | ~$200–230 |
| Spend window | 2026-07 → 2026-09 (main); reserve window 2026-11 → 2026-12 (rebuttal) |
| Approved by / date | ____________________ |
