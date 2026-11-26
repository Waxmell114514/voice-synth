import Statement
namespace Lib.Sample
open CollatzConjecture
theorem reaches_27 : collatzStep^[111] 27 = 1 := by native_decide
end Lib.Sample
