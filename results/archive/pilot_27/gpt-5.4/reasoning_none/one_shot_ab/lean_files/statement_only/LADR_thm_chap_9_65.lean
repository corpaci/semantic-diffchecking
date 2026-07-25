import Mathlib

set_option linter.style.header false


/-!
Generated Lean statement.

Source theorem: LADR_thm_chap_9_65
Condition: statement_only
Model: gpt-5.4
Prompt version: ladr_statement_pilot_ab_v2
-/



theorem LADR_thm_chap_9_65 {K V : Type*} [Field K] [Fintype K] [DecidableEq K] [AddCommGroup V] [Module K V] [FiniteDimensional K V] (T : Module.End K V) :
  ∃ p : Polynomial K, p = LinearMap.charpoly T ∧
    ∀ z : K, Polynomial.eval z p =
      z ^ (FiniteDimensional.finrank K V) -
      (LinearMap.trace K V T) * z ^ (FiniteDimensional.finrank K V - 1) +
      ∑ i in Finset.Icc 0 (FiniteDimensional.finrank K V - 2), 0 +
      (-1 : K) ^ (FiniteDimensional.finrank K V) * LinearMap.det T := by sorry
