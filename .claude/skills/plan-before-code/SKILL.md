---
name: plan-before-code
description: Investigate before proposing, and propose before editing, on any nontrivial fasti-kit task (multi-file change, new endpoint/domain logic, anything touching more than one layer). Read the relevant code/tests/docs first, state which files and layers will be touched, check docs/ and CLAUDE.md for a prior decision on the same question, then state the plan in text and wait before calling Edit/Write. Skip for single-line/typo-scale fixes the user pointed at directly.
---

# Plan before code

For anything beyond a one-line fix, don't jump straight to Edit/Write. Investigate, then propose, then act.

## Process

1. **Read before deciding.** Open the actual files involved — the domain layer(s) in question, existing tests covering the area, and any related repository/service/route. Don't infer behavior from the file name or CLAUDE.md's summary alone; CLAUDE.md describes the shape of the system, not the current state of every file.
2. **Check for a prior decision.** `docs/README.md` indexes design docs by topic (`authorization/`, `authentication/`, `architecture/`, `versioning/`, `pagination/`, `seeding/`, `safety/`, `testing/`, `tooling/`). If the task touches one of these areas, check there before proposing an approach — a past doc may already explain why the obvious approach was rejected (e.g. cursor pagination over hand-rolled, `authx` scopes over Casbin). Trust the code over a stale doc claim, but don't re-litigate a settled decision without saying so.
3. **State scope explicitly.** Before editing, say which files/layers the change will touch (e.g. "this needs `user/services/user_service.py` and a new repository method — not routes"). This is the main guard against scope creep: if the plan mentions a file that turns out to be unnecessary, or misses one that turns out to be necessary, that mismatch should surface before code changes, not after.
4. **Propose, then wait, for nontrivial work.** "Nontrivial" = new domain, new route, cross-layer change, anything touching auth/security/DB routing, or anything where two reasonable approaches exist. State the plan in a few sentences (approach + files touched), then wait for a go-ahead. Skip this step only for small, unambiguous fixes the user already pointed at directly (e.g. "line 42 has a typo").
5. **Small steps, verify as you go.** Prefer a tight loop — change, run/check, next change — over one large edit across many files with no checkpoint in between. See [[validate-before-done]] for what "verify" means here.

## Why

Past friction on this project: wrong-scope edits (touching more files than asked, unsolicited refactors) and style drift from the repo's existing DDD layering conventions. Both come from acting before reading enough of the surrounding code and without confirming scope first.
