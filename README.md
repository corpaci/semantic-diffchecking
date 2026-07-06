# semantic-drift-autoformalization

This repo explores semantic drift and formalization strategies.

## Start here (project bird's-eye view, updated 2026-07-05)

**Thesis:** LLM-generated Lean 4 statements can *compile* yet not be *faithful* to the source theorem — and in textbook mathematics, faithfulness itself is context-dependent (chapter-level standing assumptions). We measure this on *Linear Algebra Done Right* and meta-evaluate automatic faithfulness metrics. Target: ICLR 2027.

Read in this order:

1. **`ladr_paper_plan_2026-07-05.md`** — the complete research plan: thesis, RQs, takeaways (§0), study design (2×2 conditions SO/SP/SC/SPC), annotation protocol, stats plan, paper skeleton, timeline, task backlog, and a **step-by-step execution runbook (Appendix A — start there to run experiments)**, glossary (App. B), prompt templates (App. C).
2. **`api_usage_proposal_2026-07-05.md`** — compute budget (expected ≈ $200–230, cap $650), model lineup and roles, per-phase spend gates, cost-control policy.
3. **`ladr_pilot_log_2026-06-25.md`** — completed 27-theorem pilot: compiler-feedback repair lifts compilation to ~85%; informal proofs do NOT improve compilation; faithfulness question left open → motivates the plan above.

## LADR dataset
We added `LADR_all_material/`, a small dataset collected from my other project based on the undergraduate textbook “Linear Algebra Done Right.” It contains JSONL files for definitions, theorems (with informal proofs), examples, and exercises to support Lean 4 formalization experiments.

- Folder README: see `LADR_all_material/README.md` for schema, experiment design, and evaluation metrics (baseline NL→Lean, NL+informal_proof→Lean, and a multi-stage pipeline).
