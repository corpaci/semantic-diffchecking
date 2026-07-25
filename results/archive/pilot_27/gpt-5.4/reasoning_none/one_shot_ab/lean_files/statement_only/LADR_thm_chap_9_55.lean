import Mathlib

set_option linter.style.header false


/-!
Generated Lean statement.

Source theorem: LADR_thm_chap_9_55
Condition: statement_only
Model: gpt-5.4
Prompt version: ladr_statement_pilot_ab_v2
-/



theorem LADR_thm_chap_9_55 {V : Type*} [AddCommGroup V] [Module ℂ V] [FiniteDimensional ℂ V] (T : Module.End ℂ V) : LinearMap.det T = ∏ a in T.eigenvalues.toFinset, a ^ (T.eigenspace a).finrank := by sorry
