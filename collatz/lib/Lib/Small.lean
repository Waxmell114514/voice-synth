import Statement

namespace Lib.Small
open CollatzConjecture

/-- 27 reaches 1 after 111 steps of `collatzStep` (checked by the kernel). -/
theorem reaches_27 : collatzStep^[111] 27 = 1 := by
  decide +kernel

end Lib.Small
