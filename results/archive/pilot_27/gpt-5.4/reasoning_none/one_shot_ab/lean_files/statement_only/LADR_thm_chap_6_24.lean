import Mathlib

set_option linter.style.header false


/-!
Generated Lean statement.

Source theorem: LADR_thm_chap_6_24
Condition: statement_only
Model: gpt-5.4
Prompt version: ladr_statement_pilot_ab_v2
-/



theorem LADR_thm_chap_6_24 {𝕜 V : Type*} [RCLike 𝕜] [NormedAddCommGroup V] [InnerProductSpace 𝕜 V] (m : ℕ) (e : Fin m → V) (horth : Orthornormal 𝕜 e) (a : Fin m → 𝕜) : ‖∑ i, a i • e i‖ ^ 2 = ∑ i, ‖a i‖ ^ 2 := by sorry
