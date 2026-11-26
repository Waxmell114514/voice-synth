import Statement
namespace Lib.Sample
/-- A registered O-class gap. verify.sh PASSes with the gap listed, final must be n/a. -/
axiom gap_test : CollatzConjecture.CollatzConjecture
theorem collatz_of_gap : CollatzConjecture.CollatzConjecture := gap_test
end Lib.Sample
