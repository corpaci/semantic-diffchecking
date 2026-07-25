import Mathlib

set_option linter.style.header false


/-!
Generated Lean statement.

Source theorem: LADR_thm_chap_4_6
Condition: statement_only
Model: gpt-5.4
Prompt version: ladr_statement_pilot_ab_v2
-/



theorem LADR_thm_chap_4_6 {F : Type*} [Field F] (m : ℕ) (hm : 0 < m) (p : Polynomial F) (hp : p.natDegree = m) (λ : F) : p.eval λ = 0 ↔ ∃ q : Polynomial F, q.natDegree = m - 1 ∧ p = (Polynomial.X - Polynomial.C λ) * q := by sorry
