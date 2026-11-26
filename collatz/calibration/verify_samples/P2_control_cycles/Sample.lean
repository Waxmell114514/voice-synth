import Statement

namespace Lib.Sample

/-- The 3n−1 map on ℕ (the control map). -/
def step3m1 (n : ℕ) : ℕ := if Even n then n / 2 else 3 * n - 1
/-- The 5n+1 map on ℕ. -/
def step5p1 (n : ℕ) : ℕ := if Even n then n / 2 else 5 * n + 1
/-- The 3n+1 map on ℤ. -/
def step3p1Z (n : ℤ) : ℤ := if Even n then n / 2 else 3 * n + 1

/-- 5 → 14 → 7 → 20 → 10 → 5 under 3n−1. -/
theorem cycle_3m1_5 : step3m1^[5] 5 = 5 ∧ ∀ k, 0 < k → k < 5 → step3m1^[k] 5 ≠ 5 := by
  refine ⟨by decide +kernel, ?_⟩
  intro k h0 h5
  interval_cases k <;> decide +kernel

/-- The cycle of 3n−1 through 17 has length 18. -/
theorem cycle_3m1_17 : step3m1^[18] 17 = 17 := by decide +kernel

/-- 13 → 66 → 33 → 166 → 83 → 416 → 208 → 104 → 52 → 26 → 13 under 5n+1. -/
theorem cycle_5p1_13 : step5p1^[10] 13 = 13 := by decide +kernel

/-- Cycles of 3n+1 on the negative integers through −1, −5, −17. -/
theorem cycles_3p1_neg :
    step3p1Z^[2] (-1) = -1 ∧ step3p1Z^[5] (-5) = -5 ∧ step3p1Z^[18] (-17) = -17 := by
  refine ⟨?_, ?_, ?_⟩ <;> decide +kernel

end Lib.Sample
