### F-20 · Bound the phone number generation retry loop

**Background**
`PhoneBook._generate_unique_number()` retries indefinitely until a unique number is found. While the number space (9 million entries) makes exhaustion implausible, an unbounded loop is fragile.

**Changes required**

Add a maximum iteration count (e.g., 1000). If exceeded, raise `RuntimeError("Phone book number space exhausted")`. This is a hard-fail condition that should never occur in practice but provides a safe termination instead of an infinite loop.

**Acceptance criteria**
- Normal assignment succeeds within a small number of iterations.
- Forcing all numbers to be "taken" (via a mock) causes `RuntimeError` after the iteration limit, not an infinite loop.