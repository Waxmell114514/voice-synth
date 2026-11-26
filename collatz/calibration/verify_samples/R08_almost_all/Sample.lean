import Statement
namespace Lib.Sample
open CollatzConjecture
/-- A "most n" result: every n ≢ 3 (mod 4), n > 1, drops below itself. True, but not Collatz. -/
theorem collatz_most : ∀ n : ℕ, n > 1 → n % 4 ≠ 3 → ∃ m, collatzStep^[m] n < n := by
  intro n h1 h3
  have h2 : n % 2 = 0 ∨ n % 4 = 1 := by omega
  rcases h2 with he | h1'
  · refine ⟨1, ?_⟩
    have : Even n := Nat.even_iff.mpr he
    simp only [Function.iterate_one, collatzStep, this, if_true]; omega
  · refine ⟨3, ?_⟩
    have ho : ¬ Even n := by rw [Nat.not_even_iff]; omega
    have he1 : Even (3 * n + 1) := Nat.even_iff.mpr (by omega)
    have he2 : Even ((3 * n + 1) / 2) := Nat.even_iff.mpr (by omega)
    simp only [Function.iterate_succ_apply, Function.iterate_zero_apply, collatzStep, ho, he1, he2,
      if_true, if_false]
    omega
end Lib.Sample
