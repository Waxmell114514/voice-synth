/-
Frozen final check. statement/verify.py substitutes the token CLAIMED_PROOF with `@<theorem>`
and elaborates the result in a scratch file. The type annotation refers to the frozen
definition in Statement.lean; a definition of the same name anywhere else cannot satisfy it.
-/
import Statement
import Lib

example : _root_.CollatzConjecture.CollatzConjecture := CLAIMED_PROOF
