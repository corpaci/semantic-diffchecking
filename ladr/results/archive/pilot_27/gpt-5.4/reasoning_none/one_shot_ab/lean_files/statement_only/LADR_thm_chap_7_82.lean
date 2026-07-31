import Mathlib

set_option linter.style.header false


/-!
Generated Lean statement.

Source theorem: LADR_thm_chap_7_82
Condition: statement_only
Model: gpt-5.4
Prompt version: ladr_statement_pilot_ab_v2
-/



theorem LADR_thm_chap_7_82 {V W : Type*} [NormedAddCommGroup V] [InnerProductSpace ℝ V] [NormedAddCommGroup W] [InnerProductSpace ℝ W] (T : V →L[ℝ] W) (s₁ : ℝ) (hs₁ : IsGreatest {s : ℝ | IsSingularValue T s} s₁) : ∀ v : V, ‖T v‖ ≤ s₁ * ‖v‖ := by sorry
