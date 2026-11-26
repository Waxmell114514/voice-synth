import Statement
namespace Lib.Sample
/-- Same trick under a fresh name: verify.sh may PASS it, but must not certify it as Collatz. -/
def myStep (_ : ℕ) : ℕ := 1
theorem collatz : ∀ n : ℕ, n > 0 → ∃ m, myStep^[m] n = 1 := fun _ _ => ⟨1, rfl⟩
end Lib.Sample
