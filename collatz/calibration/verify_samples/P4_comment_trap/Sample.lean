import Statement
namespace Lib.Sample
/- This comment mentions sorry, native_decide, unsafe and axiom /- nested -/ but is harmless. -/
-- sorry in a line comment
def msg : String := "sorry native_decide unsafe"
theorem t : msg.length = 26 := by decide
end Lib.Sample
