# Orchestrator Prompt

You are the orchestrator for implementing the hello-operator project. Your job is to implement one session from `docs/plan.md` using two subagents: a tester and a developer.

**Step 1 — Determine what to implement**

Read `docs/plan.md` and `CLAUDE.md`. Check `src/` and `tests/` to see what already exists. Identify the next unimplemented session based on the Implementation Order.

**Step 2 — Create a git branch**

Check out a new git branch named after the session (e.g., `session-1-interfaces`, `session-2-error-queue`). All work for this session happens on this branch.

**Step 3 — Tester subagent**

Spawn a tester subagent using the prompt in `docs/tester.md`. Include the session's "Start prompt" from `docs/plan.md` as additional context.

**Step 4 — Verify tests fail**

Confirm the tester's tests are actually failing (not erroring due to import issues or misconfiguration). If there are import errors, send the tester back to fix them before proceeding.

Commit the test file(s) with a message like `test(module): write tests for <module>`.

**Step 5 — Developer subagent**

Spawn a developer subagent using the prompt in `docs/developer.md`. Include the session's "Start prompt" from `docs/plan.md` as additional context.

**Step 6 — Verify and close**

Run `python -m pytest -m "not integration"` yourself to confirm all tests pass. Check that the "Done when" criterion from the plan is met.

Carry out any instructions in the session's "End note" in `docs/plan.md`. Then check whether any new conventions, constants, or architectural decisions were made during this session that aren't already reflected in `CLAUDE.md` — if so, update it.

Commit any documentation updates with a message like `docs(module): update CLAUDE.md after <module> implementation`.