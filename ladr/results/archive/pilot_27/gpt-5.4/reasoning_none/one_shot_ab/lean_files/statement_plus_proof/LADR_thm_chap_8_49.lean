import Mathlib

set_option linter.style.header false


/-!
Generated Lean statement.

Source theorem: LADR_thm_chap_8_49
Condition: statement_plus_proof
Model: gpt-5.4
Prompt version: ladr_statement_pilot_ab_v2
-/



theorem LADR_thm_chap_8_49 {R : Type*} [CommSemiring R] {m n : Type*} [Fintype m] [Fintype n] [DecidableEq m] [DecidableEq n] (A : Matrix m n R) (B : Matrix n m R) : Matrix.trace (A ⬝ B) = Matrix.trace (B ⬝ A) := by sorry
