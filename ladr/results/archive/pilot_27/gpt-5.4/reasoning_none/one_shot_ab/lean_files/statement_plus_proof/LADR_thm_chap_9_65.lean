import Mathlib

set_option linter.style.header false


/-!
Generated Lean statement.

Source theorem: LADR_thm_chap_9_65
Condition: statement_plus_proof
Model: gpt-5.4
Prompt version: ladr_statement_pilot_ab_v2
-/



theorem LADR_thm_chap_9_65 {K V : Type*} [Field K] [Fintype K] [AddCommGroup V] [Module K V] [FiniteDimensional K V] (T : Module.End K V) :
  ∃ p : Polynomial K, LinearMap.charpoly T = p ∧ Polynomial.natDegree p = FiniteDimensional.finrank K V ∧ p.coeff (FiniteDimensional.finrank K V) = 1 ∧ p.coeff (FiniteDimensional.finrank K V - 1) = - LinearMap.trace K V T ∧ p.coeff 0 = (-1) ^ (FiniteDimensional.finrank K V) * LinearMap.det T := by sorry
