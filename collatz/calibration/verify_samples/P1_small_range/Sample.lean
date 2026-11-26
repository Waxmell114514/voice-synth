import Statement

namespace Lib.Sample
open CollatzConjecture

/-- Fuel-bounded check that `n` reaches 1. -/
def reachesOne : ℕ → ℕ → Bool
  | 0, n => n == 1
  | f + 1, n => n == 1 || reachesOne f (collatzStep n)

theorem reachesOne_sound : ∀ (f n : ℕ), reachesOne f n = true → ∃ m, collatzStep^[m] n = 1 := by
  intro f
  induction f with
  | zero => intro n h; exact ⟨0, by simpa [reachesOne] using h⟩
  | succ f ih =>
    intro n h
    simp only [reachesOne, Bool.or_eq_true, beq_iff_eq] at h
    rcases h with h | h
    · exact ⟨0, h⟩
    · obtain ⟨m, hm⟩ := ih _ h
      exact ⟨m + 1, by rw [Function.iterate_succ_apply]; exact hm⟩

theorem check_upto : ((List.range 201).all fun n => n == 0 || reachesOne 200 n) = true := by
  decide +kernel

/-- Every `n` with `0 < n ≤ 200` reaches 1. -/
theorem collatz_upto_200 : ∀ n : ℕ, n > 0 → n ≤ 200 → ∃ m, collatzStep^[m] n = 1 := by
  intro n hn hle
  have h := check_upto
  rw [List.all_eq_true] at h
  have := h n (List.mem_range.mpr (by omega))
  simp only [Bool.or_eq_true, beq_iff_eq] at this
  rcases this with h0 | h1
  · omega
  · exact reachesOne_sound _ _ h1

end Lib.Sample
