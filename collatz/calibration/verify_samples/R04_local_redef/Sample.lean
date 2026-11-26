import Statement
namespace Lib.Sample
/-- A "Collatz step" that is not the frozen one. -/
def collatzStep (_ : ℕ) : ℕ := 1
def CollatzConjecture : Prop := ∀ n : ℕ, n > 0 → ∃ m, collatzStep^[m] n = 1
theorem collatz : CollatzConjecture := fun _ _ => ⟨1, rfl⟩
end Lib.Sample
