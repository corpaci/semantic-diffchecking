import Mathlib

set_option linter.style.header false


/-!
Generated Lean statement.

Source theorem: LADR_thm_chap_4_16
Condition: statement_plus_proof
Model: gpt-5.4
Prompt version: ladr_statement_pilot_ab_v2
-/



theorem LADR_thm_chap_4_16 (p : Polynomial ℝ) (hp : ¬ IsConstant p) : ∃ (c : ℝ) (m M : ℕ) (λ : Fin m → ℝ) (b : Fin M → ℝ) (cq : Fin M → ℝ), p = Polynomial.C c * (∏ i : Fin m, (Polynomial.X - Polynomial.C (λ i))) * ∏ k : Fin M, (Polynomial.X ^ 2 + Polynomial.C (b k) * Polynomial.X + Polynomial.C (cq k)) ∧ (∀ k : Fin M, (b k)^2 < 4 * cq k) := by sorry
