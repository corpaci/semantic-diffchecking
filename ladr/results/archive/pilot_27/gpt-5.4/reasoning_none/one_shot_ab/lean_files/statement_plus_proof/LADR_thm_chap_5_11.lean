import Mathlib

set_option linter.style.header false


/-!
Generated Lean statement.

Source theorem: LADR_thm_chap_5_11
Condition: statement_plus_proof
Model: gpt-5.4
Prompt version: ladr_statement_pilot_ab_v2
-/



theorem LADR_thm_chap_5_11 {𝕜 V : Type*} [Field 𝕜] [AddCommGroup V] [Module 𝕜 V] (T : Module.End 𝕜 V) (n : ℕ) (v : Fin n → V) (μ : Fin n → 𝕜) (hvec : ∀ i, v i ≠ 0 ∧ T (v i) = μ i • v i) (hdist : Function.Injective μ) : LinearIndependent 𝕜 v := by sorry
