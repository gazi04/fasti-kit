---
name: check-all
description: Run fasti-kit's full quality gate — pyright, ruff check, ruff format --check, lint-imports, deptry, pytest — and report every failure with file:line, fixing nothing automatically. Use when the user asks to check/verify/validate the codebase, run all checks, or before committing/pushing a batch of changes.
---

# Run the full quality gate

Report-only: run every check, collect all failures, summarize — don't auto-fix. The user decides what to touch.

## Process

Run each command; don't stop at the first failure — collect results from all of them so one pass gives full signal:

```bash
uv run pyright
uv run ruff check .
uv run ruff format --check .
uv run lint-imports
uv run deptry .
uv run pytest
```

Notes:
- `pytest` needs a reachable Postgres at `DATABASE_URL` with `fasti_kit_test` as the db name (see `tests/conftest.py`) — if it fails to even connect (not a test failure, a connection error), say so explicitly rather than reporting it as failing tests. Don't try to start docker services yourself; ask the user to bring them up (`docker compose up -d postgres-primary postgres-replica redis mailpit`) if the DB is unreachable.
- `ruff format .` (no `--check`) would rewrite files — don't run that variant here, this skill only reports.
- `lint-imports` failures point at `pyproject.toml`'s `[tool.importlinter]` contracts — a failure here usually means a new domain or module bypassed the DDD layering (see `scaffold-domain` skill if it's a newly added domain missing from the contracts entirely, vs. a genuine layering violation in existing code).

## Reporting

One pass, grouped by tool, each failure as `path:line: message`. End with a one-line total (`N pyright errors, N ruff violations, ...`). If everything passes, say so briefly — don't enumerate what didn't fail.

Do not run `--fix` or `--fix`-equivalent flags, and do not edit files to resolve findings unless the user separately asks you to fix them after seeing the report.
