import Mathlib

set_option linter.style.header false


/-!
Generated Lean statement.

Source theorem: LADR_thm_chap_3_22
Condition: statement_plus_proof
Model: gpt-5.4
Prompt version: ladr_statement_pilot_ab_v2
-/



theorem LADR_thm_chap_3_22 {K V W : Type*} [DivisionRing K] [AddCommGroup V] [Module K V] [AddCommGroup W] [Module K W] [FiniteDimensional K V] [FiniteDimensional K W] (h : FiniteDimensional.finrank K V > FiniteDimensional.finrank K W) : ∀ T : V →ₗ[K] W, ¬ Function.Injective T := by sorry
