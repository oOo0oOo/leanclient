-- Define a simple theorem: for any natural number n, n + 0 = n
theorem add_zero_custom (n : Nat) : n + 0 = n := by
  -- Use induction on n
  induction n with
  | zero =>
    -- Base case: 0 + 0 = 0
    rfl
  | succ n' ih =>
    -- Inductive step: assume n' + 0 = n', prove (n' + 1) + 0 = (n' + 1)
    rw [Nat.add_succ, ih]

theorem add_zero_custom' (n : Nat) : n + 0 = n := by sorry
