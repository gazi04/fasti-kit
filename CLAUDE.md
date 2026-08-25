# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

`fasti-kit` is a FastAPI starter kit built around a scaffolding CLI that generates DDD-style domain folders (routes/schemas/entities/models/repositories/services). Two domains exist today: `auth`, `user`. It's meant as a reusable project template, but it's grown well past a bare skeleton — it also carries production-shaped infrastructure (RFC 7807 problem details, primary/replica DB routing, N+1 query detection, rate limiting, response caching, background jobs, cursor pagination, path versioning, `import-linter`-enforced layering) that new domains are expected to plug into rather than reinvent.

Keeping this file in sync: use the `/refresh-claude-md` skill (`.claude/skills/refresh-claude-md/`) to re-audit it against current repo state — don't hand-patch it piecemeal when drift is found.

Project skills in `.claude/skills/`: `/refresh-claude-md` (this file), `/scaffold-domain` (generate a new domain via the CLI, then wire it into `core/models.py`, `core/api_versions.py`, and the import-linter contracts — steps the scaffolding CLI doesn't do itself), `/check-all` (run pyright/ruff/lint-imports/deptry/pytest and report failures, no auto-fix), `/add-route` (route→service→repository wiring, auth/scopes, error-handling choice, rate limiting), `/write-repo-method` (entity conversion, replica routing, cursor pagination conventions), `/write-test` (transactional `db`/`client` fixture conventions, runs the test after writing it). Workflow skills (auto-trigger, not task-specific): `/plan-before-code` (investigate + state scope before editing on nontrivial work), `/debug-root-cause` (reproduce first, root cause before fix, watch primary/replica routing), `/validate-before-done` (don't claim done unverified — run check-all, actually run tests, exercise routes), `/commit-style` (this repo's gitmoji convention, atomic commits, never auto-commit).

## Commands

Environment is managed with `uv` (Python >=3.13, package name `fasti-kit`).

```bash
# Run the dev server
uv run main.py                       # uvicorn on 127.0.0.1:8000, uvloop, reads .env via core/setting.py

# Background job worker (saq) — needed for anything queued via core/queue.py's task_queue
uv run saq core.worker.main.settings

# Infra via docker-compose: postgres-primary (host 5433), postgres-replica (5434),
# redis, mailpit (SMTP catcher, UI at :8025), pgadmin (:8888), prometheus (:9090),
# grafana (:3000), dozzle (:8008 log viewer), caddy (reverse proxy w/ *.fasti.localhost hosts)
docker compose up -d postgres-primary postgres-replica redis mailpit
uv run alembic upgrade head                            # apply migrations
uv run alembic revision --autogenerate -m "message"     # new migration

# Seed local/staging data (guarded by core/safety.py — refuses destructive ops
# against production unless --allow-production is passed explicitly)
uv run seed

# Scaffolding a new domain (see Architecture below)
uv run create-domain <name>                 # empty routes/schemas/entities/models/repositories/services dirs
uv run create-all <domain> <name>           # generates entity+model+repository+schema+service+route for <name> inside <domain>
uv run create-entity <domain> <name>        # or generate a single layer individually
uv run create-model <domain> <name>
uv run create-repository <domain> <name>
uv run create-schema <domain> <name>
uv run create-service <domain> <name>
uv run create-route <domain> <name>

# Quality gates (all configured in pyproject.toml; also wired as pre-commit hooks)
uv run pyright                       # type checking
uv run ruff check .                  # lint (E,F,I,B,UP,S,ASYNC,SIM,RUF)
uv run ruff format .                 # format
uv run lint-imports                  # enforce DDD layering contracts, see below
uv run deptry .                      # unused/missing dependency check
uv run pip-audit                     # dependency vulnerability scan
uv run pre-commit run --all-files    # run all of the above hooks at once

# Tests — requires a real Postgres reachable at DATABASE_URL with "fasti_kit" swapped
# for "fasti_kit_test" in the name (see tests/conftest.py); each test runs inside a
# rolled-back SAVEPOINT so no test data persists
uv run pytest
uv run pytest tests/test_user_domain.py::test_name    # single test
uv run pytest --cov                                    # coverage (fail_under = 70, see pyproject.toml)
```

Config comes from `.env` (see `.env.example` for the full key list — DB primary/replica URLs and pool sizing, `ALLOWED_ORIGINS`, `JWT_SECRET_KEY`, mail SMTP settings, Redis), loaded via `core/setting.py`'s `pydantic-settings` `Settings` (cached with `@lru_cache`, use `get_settings()` everywhere rather than instantiating directly).

## Architecture

### Domain-per-folder DDD

Each domain (`auth/`, `user/`) is a top-level package with up to six identically-named subpackages, each with its own `__init__.py` that re-exports its symbols (kept up to date by the scaffolding scripts, not hand-maintained imports):

- `entities/` — plain `@dataclass` domain objects (DB-agnostic), e.g. `user/entities/user.py`
- `models/` — SQLAlchemy `Mapped`/`mapped_column` ORM classes bound to `core.database.Base`
- `repositories/` — DB access layer; takes an `AsyncSession` in `__init__`, returns entities (not models) to callers, converts via a `_to_entity` static method
- `schemas/` — Pydantic request/response models for FastAPI
- `services/` — business logic, orchestrates repositories, called from routes
- `routes/` — `APIRouter` instances, aggregated into `core/api_versions.py`'s `v1_router` (mounted at `/api/v1`), which is included once in `main.py`

Layers are called through each other in one direction: route → service → repository → model, with entities as the return type crossing back up. Routes get dependencies via `Depends()` factories in each domain's `dependencies.py` (e.g. `user/dependencies.py`'s `get_user_service`, `get_current_user`) rather than constructing `Service(Repository(db))` inline.

This layering is not just convention — `pyproject.toml`'s `[tool.importlinter]` contracts enforce it via `uv run lint-imports` (also a pre-commit hook): a one-way `routes → services → repositories → models` layer contract per domain, entities forbidden from importing `sqlalchemy`/`fastapi`/`pydantic`, and `auth` forbidden from importing `user.routes`/`user.services`/`user.models` (it may go through `user.repositories`, since `auth` reads user data via `UserRepository` rather than owning its own user storage).

**Scaffolding CLI (`scripts/`)** — `scripts/_boilerplate.py` has the shared helpers (case conversion, `write_new_file` which skips existing files rather than overwriting, `update_init` which merges new symbols into a domain layer's `__init__.py` non-destructively). Each `create_<layer>.py` is a small argparse script with a hardcoded string template for that layer, registered as a `uv run create-*` console script in `pyproject.toml`'s `[project.scripts]`. `create_all.py` just calls the other five in sequence plus route. New domains start via `create-domain`, which only makes the empty directory skeleton; populating a domain's layers is a separate step via `create-all`/`create-<layer>`.

### Request pipeline (`main.py`)

Middleware order matters and is applied outermost-last (last `add_middleware` call runs first): `GZipMiddleware` → `SecurityHeadersMiddleware` (`core/middlewares/security_headers.py`, HSTS only when `environment == "production"`) → `CorrelationIdMiddleware` (`core/middlewares/correlation.py`, generates/propagates `X-Request-ID`, also catches middleware-stack crashes and returns RFC 7807 JSON) → `N1DetectorMiddleware` (`core/middlewares/n1_detector.py`, **local environment only**, counts queries per request via SQLAlchemy `before_cursor_execute` events, sets `X-Query-Count` header, logs a warning above `threshold`) → `CORSMiddleware`. Exception handlers are installed via `install_problem_handlers` (`core/problem.py`) and `install_auth_error_handlers` (`auth/errors.py`) — every error path, including validation errors, rate-limit 429s, and unhandled 500s, is normalized into a single `ProblemDetails` (RFC 7807 / `application/problem+json`) shape with a `correlation_id`.

Startup runs `check_database`, `check_mail_config`, `check_jwt_config` (`core/startup_checks.py`) inside the `lifespan` and refuses to boot if any fail.

### `core/` — cross-cutting infrastructure

- **`core/database.py`** — `AsyncResilientRoutingSession` auto-routes `SELECT`s to `replica_engine` and writes to `primary_engine`, "stickies" a request to primary for the rest of its lifetime once any write happens (via the `force_primary_var` contextvar), and fails over reads to primary on a replica `OperationalError`. If a route needs read-after-write consistency before an actual write statement runs (e.g. login reading the row it's about to check), set `force_primary_var.set(True)` explicitly — see `auth_router.py`'s `/login`, `/refresh`, `/verify-email`.
- **`core/problem.py`** / **`core/exception.py`** — `DomainException` (and subclasses `EntityNotFoundError`, `UnauthorizedActionError`, `ConflictError`) is the base for service/repository-layer errors; raise these rather than `HTTPException` below the route layer so they get RFC 7807 formatting for free.
- **`core/cache.py`** — `@cache(ttl=..., tags=[...])` decorator for Redis cache-aside on functions with a return type annotation (required — used to build a `TypeAdapter` for serialization); `invalidate_tags(...)` wipes everything tagged.
- **`core/queue.py`** / **`core/worker/`** — `task_queue` (saq/Redis) for background jobs; register new job functions in `core/worker/main.py`'s `functions` list.
- **`core/limiter.py`** — `slowapi` `Limiter` backed by Redis; apply with `@limiter.limit("5/minute")` under the route decorator (see auth/user routers).
- **`core/deprecation.py`** — `route_class=DeprecationRoute` + `@deprecated(sunset=...)` marks a route deprecated in OpenAPI and injects `Deprecation`/`Sunset` response headers (used on `auth_router`).
- **`core/safety.py`** — `ensure_safe_operation(...)` guards destructive/dev-only CLI commands (e.g. `seed --reset`) from running against production without an explicit `--allow-production` flag; also warns on non-local DB hosts outside production.
- **`core/models.py`** — manifest-only: imports `Base` and every domain's models so `Base.metadata` is fully populated for Alembic autogenerate and app startup. When adding a new domain with its own models, import it here too.
- **`core/setting.py`** — `pydantic-settings` `Settings`, cached via `get_settings()`. `backend_url` gets an auto-prepended `http://` scheme if none is given.

### Auth (`auth/`)

Uses `authx` (`auth/dependencies.py` configures `AuthX` with `JWT_TOKEN_LOCATION=['headers', 'cookies']`, HS256, `JWT_COOKIE_CSRF_PROTECT=True`). Access tokens travel via `Authorization: Bearer` header; refresh tokens are set as an HTTP-only cookie via `auth.set_refresh_cookies`. `auth/routes/auth_router.py` covers `/login`, `/refresh`, `/logout`, `/verify-email`, `/resend-verification`, `/forgot-password`, `/reset-password`, plus `/protected` as a reference route for the `Depends(require_scopes(...))` pattern. `require_scopes(*scopes, all_required=True)` (`auth/dependencies.py`) wraps `auth.token_required` and checks `TokenPayload.has_scopes`; scopes are stored space-delimited on the user row and embedded into the access token at login/refresh.

Auth persists its own state now: `auth/entities/models/repositories` hold `RevokedTokenRepository`, used both for logout/delete token revocation by `jti` (via `TokenService`) and for one-time email-verification / password-reset tokens (a verify/reset token is inserted into the same revoked-token table once consumed, so replay is rejected). `auth/repositories`, `auth/entities`, `auth/models` are otherwise still empty for anything that isn't token-revocation state — auth reads user data through `user`'s `UserRepository` rather than owning user storage.

Password hashing is `bcrypt` via `auth/services/security_service.py` — `hashpw`/`checkpw` require `bytes`, so `hash_password`/`check_password` encode/decode at the boundary; don't pass `str` into the bcrypt functions directly.

**Login enforces identical failure responses** for "user not found" vs "wrong password" (both raise the same `HTTPException(401, detail='Invalid credentials')`) to avoid user enumeration via response content — preserve this when touching `auth_router.py`'s `/login`. `/resend-verification` and `/forgot-password` follow the same shape: they return an identical generic message regardless of whether the email exists.

### Testing (`tests/`)

`tests/conftest.py` provides `db_engine` (creates `Base.metadata` against a real `fasti_kit_test` database — no mocking, no testcontainers despite that dep group existing), `db` (wraps each test in an outer transaction + SAVEPOINT via `join_transaction_mode="create_savepoint"`, rolled back at teardown even if app code calls `commit()`), `client` (an `httpx.AsyncClient` against the ASGI app with `get_db` overridden to the transactional `db` session), and `query_counter` (counts SQL statements executed during a test, for asserting no N+1 regressions — pair with `core/middlewares/n1_detector.py`'s `X-Query-Count` header for manual checks against the dev server).

### Docs (`docs/`)

`docs/README.md` is the index of design/build guides grouped by topic (`authorization/`, `authentication/`, `architecture/`, `versioning/`, `pagination/`, `seeding/`, `safety/`, `testing/`, `tooling/`). These record *why* a feature was built the way it was, including superseded decisions with reasoning intact — check there before re-deciding something that's already been settled (e.g. cursor pagination via `fastapi-pagination`+`sqlakeyset` over hand-rolled, `authx` scopes over Casbin for authorization). Some docs predate work that has since landed (e.g. the testing guide's "no tests exist yet" — they now do); trust the code over a stale doc claim.
