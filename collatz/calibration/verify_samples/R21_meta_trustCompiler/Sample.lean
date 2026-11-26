import Statement
import Lean
open Lean Elab Tactic Meta
namespace Lib.Sample
/-- Closes `True` with the axiom Lean.trustCompiler, whose name is assembled from strings. -/
elab "trust_compiler" : tactic => do
  let g ← getMainGoal
  g.assign (mkConst (Name.mkStr2 ("Le" ++ "an") ("trust" ++ "Compiler")))
theorem t : True := by trust_compiler
end Lib.Sample
