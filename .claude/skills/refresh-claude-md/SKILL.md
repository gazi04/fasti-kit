---
name: refresh-claude-md
description: Audit fasti-kit's CLAUDE.md against the actual current repo state and rewrite it to fix drift — stale claims, missing subsystems, renamed/moved files. Use when the user asks to update, refresh, audit, sync, or regenerate CLAUDE.md, or after noticing CLAUDE.md contradicts the code (e.g. "there's no test suite" when tests/ exists).
---

# Refresh CLAUDE.md

Bring `/home/gazi/Documents/projects/fasti-kit/CLAUDE.md` back in sync with the repo as it stands right now. This is a drift audit + rewrite, not a from-scratch `/init` — read the existing file first and treat every claim in it as a hypothesis to verify, not ground truth.

## Process

1. **Read the current `CLAUDE.md` in full.** Note every concrete claim it makes: commands, host/ports, file paths, "this doesn't exist yet" statements, architecture descriptions.
2. **Verify against live repo state, not git history.** Use `find`/`grep`/`Read` on the actual files — `pyproject.toml`, `main.py`, `core/`, each domain's subpackages, `tests/`, `docs/`, `.env.example`, docker-compose/Caddyfile if present. Do not consult `git log` — file/directory state is the only source of truth for this audit.
3. **Cast a wide net before writing anything.** Specifically check for drift in these categories, since they're the ones that go stale silently:
   - Commands section: does every listed command still exist (console scripts in `pyproject.toml`, dev-tool configs), and are there new quality-gate tools configured (linters, type checkers, import-boundary tools, dependency auditors, pre-commit hooks) that aren't mentioned yet?
   - "No test suite exists" / "no X exists yet" type claims — these are the most likely to have been silently invalidated.
   - New top-level dirs or domains added since the doc was last written.
   - Middleware/request-pipeline changes in the app entrypoint (order matters — note it).
   - New cross-cutting `core/`-style infrastructure (caching, queues, rate limiting, versioning, safety guards, etc.) that new code is expected to plug into.
   - Config/env keys added or removed relative to `.env.example`.
   - Auth/domain-specific behavioral rules called out in the doc (e.g. identical-failure-response security properties) — confirm they still hold in the code, don't just carry them forward.
   - A `docs/` directory or similar knowledge base — check its index for whether individual guides are themselves stale (e.g. a guide claiming "no tests yet" when tests now exist); flag that the code wins over a stale doc, don't just copy the doc's claim in.
4. **Rewrite the full file** (not a patch) once you've built an accurate picture — stale structure inherited from a full rewrite is easier to spot and fix than trying to patch a doc whose organization no longer fits. Keep the required prefix:
   ```
   # CLAUDE.md

   This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.
   ```
5. **Just write it** — no confirmation checkpoint before overwriting. The user reviews via `git diff` afterward.
6. **Report a short summary** of what changed and why (drift found), not the full new file contents — the user will read the file/diff directly.

## What NOT to do

- Don't pad with generic advice ("write tests", "handle errors") — every line should be something a future Claude Code instance couldn't figure out in 10 seconds by reading one file.
- Don't list every file/component — focus on structure and connections that span multiple files (the stuff `/init`'s own instructions call out).
- Don't invent sections like "Common Development Tasks" unless the repo's own docs already state them.
- Don't trust a stale doc's self-description (including `docs/` guides) over what the code actually does right now.
