import Mathlib

set_option linter.style.header false


/-!
Generated Lean statement.

Source theorem: LADR_thm_chap_8_12
Condition: statement_plus_proof
Model: gpt-5.4
Prompt version: ladr_statement_pilot_ab_v2
-/



theorem LADR_thm_chap_8_12 {𝕜 V : Type*} [Field 𝕜] [AddCommGroup V] [Module 𝕜 V] [FiniteDimensional 𝕜 V] (T : V →ₗ[𝕜] V) (n : ℕ) (v : Fin n → V) (μ : Fin n → 𝕜) (hgen : ∀ i, ∃ k : ℕ, 0 < k ∧ ((T - μ i • LinearMap.id : V →ₗ[𝕜] V) ^ k) (v i) = 0 ∧ v i ≠ 0) (hdist : Function.Injective μ) : LinearIndependent 𝕜 v := by sorry
