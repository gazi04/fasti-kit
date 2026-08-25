---
name: debug-root-cause
description: Root-cause approach for diagnosing bugs, errors, or unexpected behavior in fasti-kit. Reproduce first (test/log/repro script, not a guess), explain what's actually broken and why before showing the fix, never swallow an exception just to make an error disappear, and for anything involving the database consider primary/replica routing (core/database.py) since stale-replica-read and write-not-stickied bugs are a known sharp edge here. Use whenever debugging, fixing a bug, or investigating an error/stack trace/failing test.
---

# Debug via root cause, not patch

## Non-negotiables

1. **Reproduce before fixing.** Don't patch based on a guess at what's wrong. Reproduce the failure — run the failing test, add a repro script, or read the actual stack trace/log — before writing a fix. If reproduction isn't possible (e.g. can't access the failing environment), say that explicitly rather than fixing blind.
2. **Explain root cause before the fix.** State what's actually broken and why (the mechanism, not just the symptom) before showing the change. If the explanation doesn't account for the observed behavior, the diagnosis is probably wrong — don't paper over that gap with a fix that happens to make the symptom go away.
3. **No silent exception swallowing.** Never wrap something in `try/except` (or catch a broader exception than needed) just to stop an error from surfacing. If an exception is genuinely expected and recoverable, catch the specific type and handle it meaningfully (log, translate to a `DomainException` subclass per `core/exception.py`, etc.) — don't use a bare `except` as a way to avoid understanding why it's raised.
4. **Check DB routing for anything DB-related.** `core/database.py`'s `AsyncResilientRoutingSession` auto-routes reads to the replica and writes to primary, stickying to primary for the rest of a request once a write happens. A lot of "the data isn't there" or "stale read" bugs here are actually replica-lag or missing-stickiness issues, not application logic bugs — check whether the route needs `force_primary_var.set(True)` (see `auth_router.py`'s `/login`, `/refresh`, `/verify-email` for the pattern) before assuming the bug is elsewhere.

## Process

1. Reproduce (test, repro script, or read the actual error/log — not inference from code alone).
2. State the root cause in one or two sentences: what broke, why, and why it produces the observed symptom.
3. Fix the cause, not the symptom.
4. Verify the fix actually resolves it — see [[validate-before-done]].

## Why

Past friction: under-verifying (claiming a fix works without confirming) and being sensitive to the primary/replica split — most subtle bugs in this codebase's history (see recent `:bug:` commits) trace back to atomicity/routing issues, not obvious logic errors.
