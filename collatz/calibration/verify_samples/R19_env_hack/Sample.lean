import Statement
import Lean
open Lean Elab Command
namespace Lib.Sample
run_cmd liftCoreM <| addDecl <| .axiomDecl
  { name := `Lib.Sample.hidden, levelParams := [], type := mkConst ``CollatzConjecture.CollatzConjecture, isUnsafe := false }
theorem collatz : CollatzConjecture.CollatzConjecture := hidden
end Lib.Sample
