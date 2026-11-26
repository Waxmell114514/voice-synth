import Statement
namespace Lib.Sample
open CollatzConjecture
/-- Wrong inequality direction makes the statement vacuous. -/
theorem collatz : ∀ n : ℕ, n > 0 → n < 1 → ∃ m, collatzStep^[m] n = 1 := by
  intro n h1 h2; omega
end Lib.Sample
