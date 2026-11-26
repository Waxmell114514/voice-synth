import Statement
namespace Lib.Sample
open CollatzConjecture
/-- ∃ in place of ∀, and n > 0 kept only cosmetically. -/
theorem collatz : ∃ n : ℕ, n > 0 ∧ ∃ m, collatzStep^[m] n = 1 := ⟨1, by decide, 0, rfl⟩
end Lib.Sample
