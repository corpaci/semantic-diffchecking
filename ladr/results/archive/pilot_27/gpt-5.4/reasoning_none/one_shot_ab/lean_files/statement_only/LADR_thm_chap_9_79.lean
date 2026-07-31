import Mathlib

set_option linter.style.header false


/-!
Generated Lean statement.

Source theorem: LADR_thm_chap_9_79
Condition: statement_only
Model: gpt-5.4
Prompt version: ladr_statement_pilot_ab_v2
-/



theorem LADR_thm_chap_9_79 {𝕜 V W U : Type*} [Field 𝕜] [AddCommGroup V] [Module 𝕜 V] [AddCommGroup W] [Module 𝕜 W] [AddCommGroup U] [Module 𝕜 U] :
  ((∀ Γ : V → W → U, (∀ v₁ v₂ w, Γ (v₁ + v₂) w = Γ v₁ w + Γ v₂ w) → (∀ a v w, Γ (a • v) w = a • Γ v w) → (∀ v w₁ w₂, Γ v (w₁ + w₂) = Γ v w₁ + Γ v w₂) → (∀ a v w, Γ v (a • w) = a • Γ v w) →
    ∃! T : TensorProduct 𝕜 V W →ₗ[𝕜] U, ∀ v w, T (TensorProduct.tmul 𝕜 v w) = Γ v w) ∧
   (∀ T : TensorProduct 𝕜 V W →ₗ[𝕜] U,
    ∃! Γ : V → W → U, (∀ v₁ v₂ w, Γ (v₁ + v₂) w = Γ v₁ w + Γ v₂ w) ∧ (∀ a v w, Γ (a • v) w = a • Γ v w) ∧
      (∀ v w₁ w₂, Γ v (w₁ + w₂) = Γ v w₁ + Γ v w₂) ∧ (∀ a v w, Γ v (a • w) = a • Γ v w) ∧
      (∀ v w, Γ v w = T (TensorProduct.tmul 𝕜 v w)))) := by sorry
