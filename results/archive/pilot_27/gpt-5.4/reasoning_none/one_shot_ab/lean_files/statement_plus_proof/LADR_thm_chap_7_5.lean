import Mathlib

set_option linter.style.header false


/-!
Generated Lean statement.

Source theorem: LADR_thm_chap_7_5
Condition: statement_plus_proof
Model: gpt-5.4
Prompt version: ladr_statement_pilot_ab_v2
-/



theorem LADR_thm_chap_7_5 {𝕜 V W U : Type*} [RCLike 𝕜] [NormedAddCommGroup V] [InnerProductSpace 𝕜 V] [FiniteDimensional 𝕜 V] [NormedAddCommGroup W] [InnerProductSpace 𝕜 W] [FiniteDimensional 𝕜 W] [NormedAddCommGroup U] [InnerProductSpace 𝕜 U] [FiniteDimensional 𝕜 U] (T : V →L[𝕜] W) :
  (∀ S : V →L[𝕜] W, ContinuousLinearMap.adjoint (S + T) = ContinuousLinearMap.adjoint S + ContinuousLinearMap.adjoint T) ∧
  (∀ λ : 𝕜, ContinuousLinearMap.adjoint (λ • T) = conj λ • ContinuousLinearMap.adjoint T) ∧
  (ContinuousLinearMap.adjoint (ContinuousLinearMap.adjoint T) = T) ∧
  (∀ S : W →L[𝕜] U, ContinuousLinearMap.adjoint (S.comp T) = (ContinuousLinearMap.adjoint T).comp (ContinuousLinearMap.adjoint S)) ∧
  (ContinuousLinearMap.adjoint (ContinuousLinearMap.id 𝕜 V) = ContinuousLinearMap.id 𝕜 V) ∧
  (Function.Bijective T → Function.Bijective (ContinuousLinearMap.adjoint T) ∧ ContinuousLinearMap.adjoint (LinearEquiv.ofBijective T ‹Function.Bijective T›).symm.toContinuousLinearMap = (LinearEquiv.ofBijective (ContinuousLinearMap.adjoint T) (show Function.Bijective (ContinuousLinearMap.adjoint T) from by sorry)).symm.toContinuousLinearMap) := by sorry
