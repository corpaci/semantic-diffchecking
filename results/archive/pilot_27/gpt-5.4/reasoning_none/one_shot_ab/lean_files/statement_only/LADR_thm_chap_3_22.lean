import Mathlib

set_option linter.style.header false


/-!
Generated Lean statement.

Source theorem: LADR_thm_chap_3_22
Condition: statement_only
Model: gpt-5.4
Prompt version: ladr_statement_pilot_ab_v2
-/



theorem LADR_thm_chap_3_22 {𝕜 V W : Type*} [DivisionRing 𝕜] [AddCommGroup V] [Module 𝕜 V] [AddCommGroup W] [Module 𝕜 W] [FiniteDimensional 𝕜 V] [FiniteDimensional 𝕜 W] (T : V →ₗ[𝕜] W) (h : FiniteDimensional.finrank 𝕜 W < FiniteDimensional.finrank 𝕜 V) : ¬ Function.Injective T := by sorry
