import Mathlib

set_option linter.style.header false


/-!
Generated Lean statement.

Source theorem: LADR_thm_chap_4_16
Condition: statement_only
Model: gpt-5.4
Prompt version: ladr_statement_pilot_ab_v2
-/



theorem LADR_thm_chap_4_16 (p : Polynomial ℝ) (hp : ¬ IsUnit p) :
  ∃ c : ℝ, ∃ s : Multiset ℝ, ∃ t : Multiset (ℝ × ℝ),
    p = C c * (s.map fun r => (X - C r)).prod * (t.map fun bc => (X ^ 2 + C bc.1 * X + C bc.2)).prod ∧
    (∀ bc ∈ t, bc.1 ^ 2 < 4 * bc.2) ∧
    ∀ c' : ℝ, ∀ s' : Multiset ℝ, ∀ t' : Multiset (ℝ × ℝ),
      p = C c' * (s'.map fun r => (X - C r)).prod * (t'.map fun bc => (X ^ 2 + C bc.1 * X + C bc.2)).prod →
      (∀ bc ∈ t', bc.1 ^ 2 < 4 * bc.2) →
      c' = c ∧ s' = s ∧ t' = t := by sorry
