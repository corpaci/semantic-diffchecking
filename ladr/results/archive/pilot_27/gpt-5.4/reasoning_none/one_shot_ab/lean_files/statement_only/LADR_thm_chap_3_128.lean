import Mathlib

set_option linter.style.header false


/-!
Generated Lean statement.

Source theorem: LADR_thm_chap_3_128
Condition: statement_only
Model: gpt-5.4
Prompt version: ladr_statement_pilot_ab_v2
-/



theorem LADR_thm_chap_3_128 {K V W : Type*} [DivisionRing K] [AddCommGroup V] [Module K V] [AddCommGroup W] [Module K W] [FiniteDimensional K V] [FiniteDimensional K W] (T : V →ₗ[K] W) : LinearMap.ker T.dualMap = Submodule.dualAnnihilator (LinearMap.range T) ∧ FiniteDimensional.finrank K (LinearMap.ker T.dualMap) = FiniteDimensional.finrank K (LinearMap.ker T) + FiniteDimensional.finrank K W - FiniteDimensional.finrank K V := by sorry
