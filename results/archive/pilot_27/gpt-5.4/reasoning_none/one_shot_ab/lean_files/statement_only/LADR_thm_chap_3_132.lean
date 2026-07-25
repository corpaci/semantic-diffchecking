import Mathlib

set_option linter.style.header false


/-!
Generated Lean statement.

Source theorem: LADR_thm_chap_3_132
Condition: statement_only
Model: gpt-5.4
Prompt version: ladr_statement_pilot_ab_v2
-/



theorem LADR_thm_chap_3_132 {K V W : Type*} [Field K] [AddCommGroup V] [Module K V] [FiniteDimensional K V] [AddCommGroup W] [Module K W] [FiniteDimensional K W] (T : V →ₗ[K] W) : LinearMap.toMatrix' (LinearMap.dualMap T) = Matrix.transpose (LinearMap.toMatrix' T) := by sorry
