---
name: validate-before-done
description: Before reporting any fasti-kit task complete, verify it — don't claim success unverified. Run the check-all quality gate (pyright/ruff/lint-imports/deptry/pytest), write and actually run a test for new logic (not just write one), manually exercise routes/APIs (curl/httpx/dev server) rather than trusting the code reads right, and if something can't be verified in this environment say so explicitly instead of implying it works. Use before saying a task is done, fixed, working, or ready — for code, bug fixes, or new endpoints alike.
---

# Validate before calling it done

"I edited the code and it looks right" is not done. Verify, then report.

## What counts as validated

- **`check-all` gate.** For any change touching application code, run (or ask to run) the `check-all` skill's checks — pyright, ruff check, ruff format --check, lint-imports, deptry, pytest — before calling the task complete. Don't report success on the basis of the diff alone.
- **Tests actually run, not just written.** New logic (repository method, service behavior, route) gets a test per the `write-test` skill's conventions — and that test must be run and shown passing, not just present in the diff. A written-but-unrun test is not verification.
- **Routes/APIs get exercised, not just read.** For anything touching a route, don't stop at "the code reads correctly" — hit it (dev server + curl/httpx, or a `client`-fixture test) and check the actual response, including the error path. UI changes similarly need an actual browser check per the top-level agent instructions, not a type-check-passed inference.
- **Say so when you can't verify.** If there's no way to verify in this environment (no reachable Postgres for pytest, no way to run the dev server, etc.), state that explicitly and say what's unverified — never imply something works when it was only inspected.

## Process

1. Make the change.
2. Run the narrowest relevant check immediately (single test, `uv run pyright <file>`, curl the one endpoint) rather than batching verification to the end of a large change — this is what keeps small-steps-then-verify actually small.
3. Before the final report, run `check-all`'s full gate if the change is more than trivial.
4. Report what was verified and how — not just "done."

## Why

Past friction: under-verifying — claiming something is fixed/working without actually confirming it (running tests, hitting the route, checking the failure path). This skill exists to make "validated" a checked step, not an assumption. See [[plan-before-code]] for the small-steps loop this plugs into, and [[debug-root-cause]] for verifying a bug fix specifically.
