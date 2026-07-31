/-!
Example file showing that the checker accepts mathlib imports and `sorry`.
-/

import Mathlib

#check Real

example : 1 + 1 = 2 := by
  norm_num

example : False := by
  sorry
