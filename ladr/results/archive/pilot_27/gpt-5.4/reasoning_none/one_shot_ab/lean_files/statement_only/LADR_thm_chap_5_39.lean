import Mathlib

set_option linter.style.header false


/-!
Generated Lean statement.

Source theorem: LADR_thm_chap_5_39
Condition: statement_only
Model: gpt-5.4
Prompt version: ladr_statement_pilot_ab_v2
-/



theorem LADR_thm_chap_5_39 {K V : Type} [Field K] [AddCommGroup V] [Module K V] (n : ℕ) (v : Fin n → V) (T : V →ₗ[K] V) (hv : Basis (Fin n) K V v) : ((∀ i j : Fin n, j < i → hv.repr (T (v j)) i = 0) ↔ ((∀ k : Fin n, ∀ x ∈ Submodule.span K (Set.range fun i : Fin (k.val + 1) => v ⟨i.val, Nat.lt_trans i.is_lt k.is_lt⟩), T x ∈ Submodule.span K (Set.range fun i : Fin (k.val + 1) => v ⟨i.val, Nat.lt_trans i.is_lt k.is_lt⟩)) ↔ ∀ k : Fin n, T (v k) ∈ Submodule.span K (Set.range fun i : Fin (k.val + 1) => v ⟨i.val, Nat.lt_trans i.is_lt k.is_lt⟩))) := by sorry
