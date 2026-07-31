import Mathlib

set_option linter.style.header false


/-!
Generated Lean statement.

Source theorem: LADR_thm_chap_2_22
Condition: statement_only
Model: gpt-5.4
Prompt version: ladr_statement_pilot_ab_v2
-/



theorem LADR_thm_chap_2_22 {K V : Type*} [DivisionRing K] [AddCommGroup V] [Module K V] [FiniteDimensional K V] (l s : List V) (hli : LinearIndependent K (fun i : Fin l.length => l.get i)) (hs : Submodule.span K (Set.range fun i : Fin s.length => s.get i) = ⊤) : l.length ≤ s.length := by sorry
