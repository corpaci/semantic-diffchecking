# BankAccount pilot protocol

The task comes from ClassEval_8 at the commit in `requirements.json`.
This pilot uses a clarified request. It does not use the unchanged ClassEval prompt.
Both conditions receive the same public request, including every clarification.
The request contains no reference code, executable checks, or expected test outputs.

## Requirements and tests

`requirements.json` lists 13 requirements and their origins.
Each requirement states observable behavior or an interface constraint.
It identifies additions that clarify the source specification.
`checks.py` maps 25 independent tests to requirement IDs through `@covers`.
The original 22 ClassEval tests remain a separate comparison signal.

The checks include successful operations and rejected operations.
They check exact errors, balance preservation, zero amounts, full withdrawals, conservation, repeated reads, and operation sequences.
The scope excludes floating-point amounts, invalid types, concurrent operations, self-transfers, and custom account subclasses.
These exclusions define this pilot's evaluation scope, not unrestricted correctness.

The case preparation command writes these files:

- `public_task.json`: the exact common request for both conditions.
- `frozen_case.json`: request, requirement, check, and dataset hashes, plus the test mapping.
- `requirement-test-map.md`: a readable requirement list and test map.
- `stage_tracking.json`: a requirement-by-stage table before generation.

## Conditions

1. Direct: the selected model generates code directly from the public request.
2. MetaGPT: the same model processes the request through native software-company roles.

Use identical model, provider endpoint, temperature, maximum output tokens, and reasoning settings.
The conditions differ in system prompts, call counts, and intermediate context by design.
Report those differences and measured usage. Do not claim a matched-compute causal comparison.
Start with one funded pair to test the complete integration.
Later repetition requires a recorded run schedule and preserves this case's frozen inputs.

## Intermediate artifacts

Use these labels: preserved, omitted, contradicted, unclear, not_applicable, and unassessed.
Use the original request as the cumulative reference.
Also compare each artifact with the inputs actually observed by its producing role.

Preserved means the artifact states or unambiguously entails the requirement within its intended scope.
Omitted means an artifact should carry the requirement but supplies no supporting statement.
Contradicted means it specifies incompatible behavior.
Unclear means the text cannot support a confident decision.
Not_applicable means the artifact's scope does not need that requirement.
Unassessed means nobody has reviewed the artifact yet.

For every assessed row, record the reviewer, exact quote, line numbers, artifact hash, and rationale.
An omission needs a scope rationale. Absence of matching words is insufficient evidence.
Quotes must come from the saved artifact, not an agent's later explanation.
Record important additions separately. They may introduce behavior absent from the request.
Record both loss and later restoration. A later agent can recover a requirement from another input.

The packet command lists observed artifact versions and actual role inputs.
It leaves all semantic labels unassessed. It does not assign blame automatically.
Expected stages without artifacts remain not_generated in the initial table.
Two reviewers should assess substantive cases independently before resolving disagreements.

## Failure attribution

Report the first observed document change separately from the first failing executable checkpoint.
A final test failure alone cannot identify the responsible agent.
Missing information in one document can remain available in other messages.
Inspect the actual received messages and complete prompt before proposing a mechanism.

For a promising case, restore the requirement at the suspected handoff and repeat downstream generation.
Compare that controlled replay with the original run before making a causal claim.
Provider-exposed reasoning is supporting inspection material. It is not proof of causal responsibility.

## OpenRouter and budget

The proposed first model is Qwen3-235B-A22B-Thinking-2507, with Apache-2.0 open weights.
The configuration pins its OpenRouter provider endpoint and disables routing fallbacks.
Recheck endpoint availability, supported parameters, limits, and prices immediately before generation.
If the endpoint disappears, select and document a replacement before running either condition.

The experiment has a $50 total limit and a $5 per-run default.
Use one shared persistent budget ledger across both conditions and all future models.
Create a dedicated non-resetting OpenRouter key with a limit of $50 or less as the final setup step.
The code checks that key limit before generation and reserves a conservative amount for each request.
Settle reservations from actual response costs. Missing costs and ambiguous requests require reconciliation.
Do not delete the ledger or start another ledger to bypass unresolved requests.

Requests do not retry automatically. A failed model response stops subsequent requests in that run.
Preserve raw responses, errors, generation IDs, token counts, cost, and reasoning fields.
Missing reasoning, empty answers, truncation, refusals, unexpected tool calls, and model mismatches are explicit errors.
Reasoning tokens share the output-token budget. They can exhaust it before code appears.

Generation uses non-streaming requests so reasoning and usage metadata remain together in the saved response.
The transport serializes requests to protect the shared spending ledger.
These choices change transport timing, not native role prompt content.

## Before interpreting results

The reference must pass both original and independent checks.
Controlled mutations must fail their mapped requirement checks.
Mocked network tests must cover expected API errors and budget behavior.
No offline check is evidence of actual agent requirement loss.
The first funded run must still establish live endpoint compatibility and complete artifact generation.
