import Mathlib

set_option linter.style.header false


/-!
Generated Lean statement.

Source theorem: LADR_thm_chap_2_22
Condition: statement_plus_proof
Model: gpt-5.4
Prompt version: ladr_statement_pilot_ab_v2
-/



theorem LADR_thm_chap_2_22 {K V : Type*} [DivisionRing K] [AddCommGroup V] [Module K V] [FiniteDimensional K V] (u w : List V) (hu : LinearIndependent K (fun i : Fin u.length => u.get i)) (hw : Submodule.span K (Set.range fun i : Fin w.length => w.get i) = ⊤) : u.length ≤ w.length := by sorry
