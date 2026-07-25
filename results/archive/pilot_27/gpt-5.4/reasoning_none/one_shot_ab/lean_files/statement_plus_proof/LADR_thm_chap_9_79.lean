import Mathlib

set_option linter.style.header false


/-!
Generated Lean statement.

Source theorem: LADR_thm_chap_9_79
Condition: statement_plus_proof
Model: gpt-5.4
Prompt version: ladr_statement_pilot_ab_v2
-/



theorem LADR_thm_chap_9_79 {𝕜 V W U : Type*} [Field 𝕜] [AddCommGroup V] [Module 𝕜 V] [AddCommGroup W] [Module 𝕜 W] [AddCommGroup U] [Module 𝕜 U] : ((V →ₗ[𝕜] W →ₗ[𝕜] U) → ∃! T : TensorProduct 𝕜 V W →ₗ[𝕜] U, ∀ v w, T (TensorProduct.tmul 𝕜 v w) = (· v) ‹V →ₗ[𝕜] W →ₗ[𝕜] U› w) ∧ ((TensorProduct 𝕜 V W →ₗ[𝕜] U) → ∃! B : V →ₗ[𝕜] W →ₗ[𝕜] U, ∀ v w, B v w = (· (TensorProduct.tmul 𝕜 v w)) ‹TensorProduct 𝕜 V W →ₗ[𝕜] U›) := by sorry
