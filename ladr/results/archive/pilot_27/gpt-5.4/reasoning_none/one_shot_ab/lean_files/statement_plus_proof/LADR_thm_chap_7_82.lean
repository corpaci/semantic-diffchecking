import Mathlib

set_option linter.style.header false


/-!
Generated Lean statement.

Source theorem: LADR_thm_chap_7_82
Condition: statement_plus_proof
Model: gpt-5.4
Prompt version: ladr_statement_pilot_ab_v2
-/



theorem LADR_thm_chap_7_82 {V W : Type*} [NormedAddCommGroup V] [InnerProductSpace ℂ V] [CompleteSpace V] [NormedAddCommGroup W] [InnerProductSpace ℂ W] [CompleteSpace W] (T : V →L[ℂ] W) (s₁ : ℝ) (hs₁ : s₁ = sSup {r : ℝ | ∃ v : V, ‖v‖ = 1 ∧ ‖T v‖ = r}) : ∀ v : V, ‖T v‖ ≤ s₁ * ‖v‖ := by sorry
