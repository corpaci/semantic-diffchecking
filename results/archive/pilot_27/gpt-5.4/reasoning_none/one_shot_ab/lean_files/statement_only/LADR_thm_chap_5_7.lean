import Mathlib

set_option linter.style.header false


/-!
Generated Lean statement.

Source theorem: LADR_thm_chap_5_7
Condition: statement_only
Model: gpt-5.4
Prompt version: ladr_statement_pilot_ab_v2
-/



theorem LADR_thm_chap_5_7 {𝕜 V : Type*} [Field 𝕜] [AddCommGroup V] [Module 𝕜 V] [FiniteDimensional 𝕜 V] (T : Module.End 𝕜 V) (λ : 𝕜) : (∃ v : V, v ≠ 0 ∧ T v = λ • v) ↔ ¬ Function.Injective (T - λ • LinearMap.id) ∧ ¬ Function.Surjective (T - λ • LinearMap.id) ∧ ¬ IsUnit (T - λ • LinearMap.id) := by sorry
