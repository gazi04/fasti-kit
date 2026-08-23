---
name: write-test
description: Write a pytest test in fasti-kit following the transactional db/client fixture conventions from tests/conftest.py, then run it to confirm it passes. Use when the user asks to add/write a test, or test coverage for a repository/service/route.
---

# Write a test

Ground truth: `tests/conftest.py`, `tests/test_user_domain.py`, `tests/test_n1_detector.py`.

## Which fixture to use

- **`db`** (an `AsyncSession`) — for repository/service-layer tests that call the layer directly (no HTTP). Wrapped in an outer transaction + SAVEPOINT (`join_transaction_mode="create_savepoint"`); everything rolls back at teardown even if the code under test calls `commit()`. Freely `db.add(...)`/`await repo.method(...)` — no cleanup code needed.
- **`client`** (an `httpx.AsyncClient` against the ASGI app) — for route/integration tests. Built on top of `db` with `get_db` overridden, so it shares the same transactional rollback.
- **`query_counter`** — pair with `db` or `client` to assert query-count budgets (regression guard against N+1s): `assert query_counter["count"] <= N`.
- **`db_engine`** — rarely used directly; it's what `db` is built on. Only reach for it if you need a second, independent connection (see `test_transactional_isolation.py`'s leakage test).

No mocking of the database — tests hit a real Postgres at `fasti_kit_test` (see Commands in the project `CLAUDE.md`). Don't introduce `unittest.mock` for repository/service calls; write against the real fixture instead.

## Conventions

- Tests are plain `async def test_...(fixture_args) -> None:` — no `@pytest.mark.asyncio` needed (`asyncio_mode = "auto"` in `pyproject.toml`).
- Generate unique data per test (e.g. `_make_email()` helper using `uuid.uuid4().hex[:8]`) rather than hardcoded values — tests in the same run share the transaction stack but not data, and hardcoded emails collide across parametrized/repeated runs.
- One behavior per test, docstring states the behavior being verified in one line (see every test in `test_user_domain.py`) — not a description of the test steps.
- Group related tests with a `# --- Section ---` comment banner (repository tests, then service tests, then dependency tests) when a file covers a whole domain, matching `test_user_domain.py`'s layout.
- Asserting on error responses: raised exceptions are typically `HTTPException` — assert via `pytest.raises(HTTPException) as exc_info` then check `exc_info.value.status_code`, not the response body (see `test_get_current_user_raises_404_for_unknown_sub`). For full HTTP-level `ProblemDetails` shape assertions through `client`, check `response.json()["title"]`/`["status"]`/`["detail"]`.
- If a test needs to bypass `authx`'s token-blocklist callback (which opens its own non-test `AsyncSessionLocal`), call the dependency function directly with explicit args rather than going through `client` + real headers — see the `get_current_user` tests' comment block explaining why.

## After writing

Run it to confirm it actually passes before reporting done:
```bash
uv run pytest tests/<file>.py -v
```
If the DB isn't reachable, say so explicitly (connection error, not a real test failure) rather than reporting the test as broken — check `docker compose up -d postgres-primary postgres-replica` first if needed.
