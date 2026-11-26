import Statement
namespace Lib.Sample
def fastStep (n : ℕ) : ℕ := n
@[implemented_by fastStep] def slowStep (n : ℕ) : ℕ := n + 1
theorem t : slowStep 0 = 1 := rfl
end Lib.Sample
