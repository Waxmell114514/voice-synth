/-
Frozen statement for the Collatz fleet. Do not edit after phase 0.4.

The definition of `collatzStep` and the proposition below are copied verbatim from
google-deepmind/formal-conjectures, file FormalConjectures/Wikipedia/CollatzConjecture.lean
(main branch, fetched 2026-11-26; Apache License 2.0; Copyright 2025 The Formal Conjectures
Authors). An exact copy of that file is kept in statement/upstream/CollatzConjecture.lean.
The upstream file states the conjecture as a `theorem ... := by sorry`; here the same type is
packaged as a `Prop` so that it can be named. `statement_eq_upstream` below checks by `rfl`
that the two are the same proposition.
-/
import Mathlib

namespace CollatzConjecture

/--
Consider the following operation on the natural numbers:
If the number is even, divide it by two.
If the number is odd, triple it and add one.
-/
def collatzStep (n : ℕ) : ℕ :=
  if Even n then n / 2 else 3 * n + 1

set_option linter.dupNamespace false in
/-- The Collatz conjecture, as a proposition. -/
def CollatzConjecture : Prop := ∀ n : ℕ, n > 0 → ∃ m, collatzStep^[m] n = 1

set_option linter.unusedVariables false in
/-- The proposition is literally the type of upstream `collatz_conjecture`. -/
theorem statement_eq_upstream :
    CollatzConjecture = ∀ (n : ℕ) (hn : n > 0), ∃ m, collatzStep^[m] n = 1 := rfl

end CollatzConjecture
