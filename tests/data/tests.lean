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

-- Trigger code action
/-- info: 2 -/ #guard_msgs (info) in #eval 1

-- Trigger warnings using incomplete proofs
theorem incomplete (n : Nat) : n + 0 = n := by sorry
theorem incomplete' (n : Nat) : n + 1 = n + 1 := by admit

-- Trigger error using syntax errors
theorem add_zero_custom''
