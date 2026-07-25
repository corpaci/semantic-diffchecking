import Mathlib

set_option linter.style.header false


/-!
Generated Lean statement.

Source theorem: LADR_thm_chap_9_55
Condition: statement_plus_proof
Model: gpt-5.4
Prompt version: ladr_statement_pilot_ab_v2
-/



theorem LADR_thm_chap_9_55 {V : Type*} [NormedAddCommGroup V] [NormedSpace ℂ V] [FiniteDimensional ℂ V] (T : V →ₗ[ℂ] V) : LinearMap.det T = ∏ i in Finset.range (FiniteDimensional.finrank ℂ V), (LinearMap.toMatrix (Basis.ofVectorSpace ℂ V) (Basis.ofVectorSpace ℂ V) T) i i := by sorry
