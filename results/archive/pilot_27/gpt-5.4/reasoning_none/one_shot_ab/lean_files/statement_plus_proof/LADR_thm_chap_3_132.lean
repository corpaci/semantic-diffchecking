import Mathlib

set_option linter.style.header false


/-!
Generated Lean statement.

Source theorem: LADR_thm_chap_3_132
Condition: statement_plus_proof
Model: gpt-5.4
Prompt version: ladr_statement_pilot_ab_v2
-/



theorem LADR_thm_chap_3_132 {K V W : Type*} [Field K] [AddCommGroup V] [Module K V] [AddCommGroup W] [Module K W] [FiniteDimensional K V] [FiniteDimensional K W] (T : V →ₗ[K] W) : LinearMap.toMatrix (Module.Free.ChooseBasisIndex K (Module.Dual K W)) (Module.Free.ChooseBasisIndex K (Module.Dual K V)) (LinearMap.dualMap T) = Matrix.transpose (LinearMap.toMatrix (Module.Free.ChooseBasisIndex K V) (Module.Free.ChooseBasisIndex K W) T) := by sorry
