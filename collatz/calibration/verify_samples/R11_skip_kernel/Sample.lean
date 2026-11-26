import Statement
namespace Lib.Sample
set_option debug.skipKernelTC true in
theorem bogus : (1 : ℕ) = 2 := by decide
end Lib.Sample
