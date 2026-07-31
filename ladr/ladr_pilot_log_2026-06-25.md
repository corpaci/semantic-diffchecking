# LADR Pilot Log: Statement Autoformalization (Week June 28 - June 5)
I asked the model to back translate the Lean4 code to a card, which i can read, I have to go over this to see the informal proof really helps the translation to be more faithful, even though its not compiling. In order to this, I asked AI to come up a script for back translatio and a HTML format script so i can compare easily.


________________________________________________________________________________________________


# LADR Pilot Log: Statement Autoformalization (Week June 21 - June 28)
Initial piloti on the LADR theorems.

## Setup 

Dataset: Extracted textbook 256 theorems and the inforaml proof, piloted on `LADR_pilot_27`.

Model: GPT-5.4, with "lake env lean --stdin --json", only compile or not (succinct info, not like REPL)

Task: generate a Lean 4 theorem statement from each LADR theorem, with proof replaced by `:= by sorry`.

Conditions:

- `statement_only`: prompt contains only the theorem statement.
- `statement_plus_proof`: prompt contains the theorem statement plus the informal proof, with instructions to use the proof only for disambiguation.

## One-Shot Result

| Condition | Compiled | Failed | Compile Rate |
|---|---:|---:|---:|
| `statement_only` | 10 / 27 | 17 / 27 | 37.0% |
| `statement_plus_proof` | 9 / 27 | 18 / 27 | 33.3% |
Pair outcomes:

- both compile: 8
- both fail: 16
- `statement_only` only: 2
- `statement_plus_proof` only: 1

## Repair-Agent Result

The repair agent used Lean compiler feedback as conversation history. For each failed attempt, the next user message contained the Lean 4 output and any local format-validation notes. The maximum number of attempts was 3.

| Condition | Compiled | Failed | Compile Rate |
|---|---:|---:|---:|
| `statement_only` | 23 / 27 | 4 / 27 | 85.2% |
| `statement_plus_proof` | 20 / 27 | 7 / 27 | 74.1% |


## Multistage Skeleton Result

We added a third experimental condition, `multistage_skeleton`, to test whether the informal proof is more useful as an intermediate representation than as raw appended context.

Design:

- First pass: theorem + informal proof -> Lean proof skeleton following the proof logic, with unfinished steps filled by `sorry`.
- Second pass: natural-language theorem + compiled Lean sketch proof -> clean Lean theorem statement ending with `:= by sorry`.
- Both passes use the same retry pattern: if validation or Lean typechecking fails, append the feedback and ask the model to revise the same answer, with up to 3 attempts per pass.

Prompt cleanup:

- Stage 1 now requires real Lean proof structure such as `have`, `suffices`, or `calc`; comment-only skeletons do not pass validation.
- Stage 2 no longer receives the raw informal proof, so this condition tests the Lean sketch as the intermediate signal.
- The old special `REPAIR_PROMPT` was replaced by a generic retry prompt shared across both passes.

| Condition | Compiled | Failed | Compile Rate |
|---|---:|---:|---:|
| `multistage_skeleton` | 15 / 27 | 12 / 27 | 55.6% |

Stage-level outcome:

- Stage 1 proof skeleton: 15 ok, 12 failed
- Stage 2 final statement extraction: 15 ok, 12 skipped
- Whenever Stage 1 compiled, Stage 2 extraction succeeded.

Compared with direct `statement_plus_proof` repair:

- direct ok -> multistage ok: 13
- direct ok -> multistage failed: 7
- direct failed -> multistage ok: 2
- direct failed -> multistage failed: 5

## Observation

Appending the informal proof did not improve Lean compilation rate. This holds both in the one-shot setting and after compiler-feedback repair.

Takeaway: in this pilot, informal proof does not help the LLM generate Lean 4 code that compiles. It does not appear to help with the Lean coding/interface part of formalization.

The error taxonomy also shows no clear qualitative difference between the direct `statement_only` and `statement_plus_proof` conditions. Both are dominated by similar Lean/mathlib failure modes, mainly syntax issues, unknown constants or identifiers, and API/type mismatches.

Compiler-feedback repair substantially improved compilation, raising success from 19 / 54 to 43 / 54. Of the 35 one-shot failures, 24 were repaired successfully.

Multistage proof-skeleton formalization did not improve compilation. It was harder than direct statement repair: 15 / 27 compiled, compared with 20 / 27 for direct `statement_plus_proof` repair and 23 / 27 for direct `statement_only` repair.

## Interpretation

The immediate compilation bottleneck appears to be mapping textbook linear algebra into the correct Lean/mathlib interface, rather than understanding the theorem from the informal proof. Many failures are repairable coding/interface errors: syntax, namespace/API names, type mismatches, and typeclass issues.

The multistage result suggests that asking for a Lean-checkable proof skeleton adds substantial proof-engineering difficulty. Its possible value is therefore not compile recovery, but semantic faithfulness: the skeleton condition may force the model to encode intermediate proof structure before producing the final statement.

This does not resolve the semantic-faithfulness question. Compile success only means that Lean accepts the generated statement; it does not prove that the statement faithfully matches the LADR theorem.

Therefore, these experiments do not show that informal proof is useless for faithfulness. They show that informal proof is not an effective tool for the Lean coding/interface problem. To study faithfulness more cleanly, we need to reduce the coding bottleneck first; compiler-feedback repair is a useful mechanism for doing that, because it lets later evaluation focus more directly on whether the compiled statement preserves the theorem's meaning.

## Next Step

Evaluate semantic faithfulness on the compiled outputs, especially:

- paired `statement_only` and `statement_plus_proof` direct-agent outputs;
- the 15 compiled `multistage_skeleton` outputs;
- the 13 cases where both direct `statement_plus_proof` and `multistage_skeleton` compiled.

The key remaining question is whether informal proof context improves the correctness or specificity of the formal statement, even though it does not improve compilation.
