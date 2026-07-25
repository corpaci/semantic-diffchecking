import Mathlib

set_option linter.style.header false


/-!
Generated Lean statement.

Source theorem: LADR_thm_chap_5_39
Condition: statement_plus_proof
Model: gpt-5.4
Prompt version: ladr_statement_pilot_ab_v2
-/



theorem LADR_thm_chap_5_39 {K V : Type*} [Field K] [AddCommGroup V] [Module K V] (n : ℕ) (v : Fin n → V) (T : Module.End K V) (hv : Basis (Fin n) K V v) : (Matrix.upperTriangular (LinearMap.toMatrix hv hv T) ↔ ∀ k : Fin n, T (v k) ∈ Submodule.span K (Set.range fun i : Fin (k.1 + 1) => v ⟨i.1, Nat.lt_trans i.2 k.2⟩)) ∧ ((∀ k : Fin n, Submodule.map T.toLinearMap (Submodule.span K (Set.range fun i : Fin (k.1 + 1) => v ⟨i.1, Nat.lt_trans i.2 k.2⟩)) ≤ Submodule.span K (Set.range fun i : Fin (k.1 + 1) => v ⟨i.1, Nat.lt_trans i.2 k.2⟩)) ↔ ∀ k : Fin n, T (v k) ∈ Submodule.span K (Set.range fun i : Fin (k.1 + 1) => v ⟨i.1, Nat.lt_trans i.2 k.2⟩)) := by sorry
