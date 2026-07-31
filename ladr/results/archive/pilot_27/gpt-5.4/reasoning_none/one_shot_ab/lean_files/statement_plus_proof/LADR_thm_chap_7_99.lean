import Mathlib

set_option linter.style.header false


/-!
Generated Lean statement.

Source theorem: LADR_thm_chap_7_99
Condition: statement_plus_proof
Model: gpt-5.4
Prompt version: ladr_statement_pilot_ab_v2
-/



theorem LADR_thm_chap_7_99 {V : Type*} [NormedAddCommGroup V] [InnerProductSpace ℝ V] [FiniteDimensional ℝ V] (T : V →ₗ[ℝ] V) (hT : Function.Bijective T) : ∃ (n : ℕ) (s : Fin n → ℝ) (f : Fin n → V), Set.Image {v : V | ‖v‖ < 1} T = {w : V | ∑ i : Fin n, ‖⟪w, f i⟫_ℝ‖^2 / (s i)^2 < 1} := by sorry
