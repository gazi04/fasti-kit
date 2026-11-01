# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

`fasti-kit` is a FastAPI starter kit built around a scaffolding CLI that generates DDD-style domain folders (routes/schemas/entities/models/repositories/services). Two domains exist today: `auth`, `user`. It's meant as a reusable project template, but it's grown well past a bare skeleton — it also carries production-shaped infrastructure (RFC 7807 problem details, primary/replica DB routing, a transactional outbox, a dead-letter queue, N+1 query detection, rate limiting, response caching, background jobs, cursor pagination, path versioning, `import-linter`-enforced layering) that new domains are expected to plug into rather than reinvent.

Keeping this file in sync: use the `/refresh-claude-md` skill (`.claude/skills/refresh-claude-md/`) to re-audit it against current repo state — don't hand-patch it piecemeal when drift is found.

Project skills in `.claude/skills/`: `/refresh-claude-md` (this file), `/scaffold-domain` (generate a new domain via the CLI, which wires it in itself, then add the migration and verify), `/check-all` (run pyright/ruff/lint-imports/deptry/pytest and report failures, no auto-fix), `/add-route` (route→service→repository wiring, resource-style URLs, auth/scopes, error handling, rate limiting), `/write-repo-method` (entity conversion, replica routing, cursor pagination conventions), `/write-test` (transactional `db`/`client` fixture conventions, runs the test after writing it). Workflow skills (auto-trigger, not task-specific): `/plan-before-code` (investigate + state scope before editing on nontrivial work), `/debug-root-cause` (reproduce first, root cause before fix, watch primary/replica routing), `/validate-before-done` (don't claim done unverified — run check-all, actually run tests, exercise routes), `/commit-style` (this repo's gitmoji convention, atomic commits, never auto-commit). `fastapi` and `library-skills` are third-party reference skills, not project conventions. If a skill and the Architecture section below disagree, the Architecture section wins.

## Commands

Environment is managed with `uv` (Python >=3.13, package name `fasti-kit`, installed as a package via `[tool.uv] package = true`). A `Justfile` wraps the common ones (`just dev`, `just worker`, `just test`, `just lint`, `just lint-fix`, `just format`, `just pre-commit`, `just migrate "msg"`, `just seed`, `just scaffold-smoke`, `just docker`, `just docker-app`).

```bash
# Run the dev server
uv run main.py                       # uvicorn on 127.0.0.1:8000, uvloop, reads .env via core/setting.py

# Background job worker (saq) — needed for anything queued via core/queue.py's task_queue,
# and it also runs the outbox relay (see core/outbox below)
uv run saq core.worker.main.settings

# Infra via docker-compose: postgres-primary (host 5433), postgres-replica (5434),
# redis, mailpit (SMTP catcher, UI at :8025), pgadmin (:8888), prometheus (:9090),
# grafana (:3000), dozzle (:8008 log viewer), caddy (reverse proxy w/ *.fasti.localhost hosts,
# upstream set by API_UPSTREAM, default host.docker.internal:8000)
# The app itself + its worker also exist as compose services (`app`, `worker`, built from the
# root Dockerfile) but sit behind the `app` profile and never start on a plain `docker compose
# up` — bare-metal `uv run main.py` stays the default dev workflow, by design (see README's
# "Running the API in Docker" section). Opt in with `docker compose --profile app up -d --build`.
docker compose up -d postgres-primary postgres-replica redis mailpit
uv run alembic upgrade head                            # apply migrations
uv run alembic revision --autogenerate -m "message"     # new migration (prefer create-migration below)

# Dev container: .devcontainer/ (compose-based) joins the infra network, so the app reaches
# services by name (postgres-primary, redis, mailpit) instead of localhost; post-create.sh
# installs deps, creates fasti_kit_test, migrates, installs pre-commit.

# Seed local/staging data (guarded by core/safety.py — refuses destructive ops
# against production unless --allow-production is passed explicitly)
uv run seed

# Scaffolding a new domain (see Architecture below)
# Every create-* command takes -d/--domain, -n/--name, -f/--fields flags (no positional args)
# and prompts for any that are missing.
uv run create-domain -d <domain>            # 6 layer packages + empty dependencies.py, wired into pyproject.toml
uv run create-all -d <domain> -n <name> -f "title:str,price:float"
                                             # every layer + Depends() factories, model registered in
                                             # core/models.py, router mounted in core/api_versions.py, ruff run
uv run create-entity -d <domain> -n <name>  # or one layer at a time: create-{entity,model,repository,schema,
                                             # service,route,dependencies}; refuses a domain that doesn't exist
uv run create-migration -m "message" [--domain <domain>] [--apply]  # alembic autogenerate, guarded: checks
                                                                     # core/models.py registration first, lints the
                                                                     # generated file for drop/nullable footguns
uv run create-factory -d <domain> -n <name>  # polyfactory Create/Update request factories for a domain's schemas
uv run create-test -d <domain> -n <name>    # repository/service/route tests via the db/client fixtures, using
                                             # create-factory's output; runs them and exits non-zero on failure
just scaffold-smoke                          # scripts/smoke_scaffold.sh (also in CI): generate a domain in a temp
                                             # copy, check it boots + passes every gate + its generated tests,
                                             # and that a second create-all changes nothing

# Quality gates (all configured in pyproject.toml)
uv run pyright                       # type checking
uv run ruff check .                  # lint (E,F,I,B,UP,S,ASYNC,SIM,RUF)
uv run ruff format .                 # format
uv run lint-imports                  # enforce DDD layering contracts, see below
uv run deptry .                      # unused/missing dependency check (DEP002 ignores runtime-only
                                     # packages nothing imports: uvloop, httptools, asyncpg, sqlakeyset, aiohttp)
uv run pip-audit                     # dependency vulnerability scan
uv run detect-secrets-hook --baseline .secrets.baseline <files>   # pre-commit hook; new hits fail
                                     # the commit. Intentional dev/test placeholders live in
                                     # .secrets.baseline — regenerate with
                                     # `uv run detect-secrets scan --baseline .secrets.baseline`,
                                     # audit the diff, `git add` it. No inline pragma comments.
                                     # Rerun after editing tests that hold fake passwords — shifted
                                     # line numbers alone make the hook rewrite the baseline and fail.
uv run pre-commit run --all-files    # pre-commit hooks: file hygiene, ruff check/format, pyright,
                                     # import-linter, detect-secrets. CI runs this, then lint-imports,
                                     # pip-audit, deptry, pytest --cov and scripts/smoke_scaffold.sh

# Tests — requires a real Postgres reachable at DATABASE_URL, using the database named
# "<DATABASE_URL's db>_test" (e.g. fasti_kit -> fasti_kit_test, see tests/conftest.py), never
# the dev database itself; that test database must already exist (CI creates it with psql, the
# dev container's post-create.sh with asyncpg). Each test runs inside a rolled-back SAVEPOINT so
# no test data persists. Redis must be reachable too (rate limiter, cache, outbox heartbeat).
uv run pytest
uv run pytest tests/test_user_domain.py::test_name    # single test
uv run pytest --cov                                    # coverage (fail_under = 85, see pyproject.toml)
```

Config comes from `.env` (see `.env.example` for the full key list — DB primary/replica URLs and pool sizing, `ALLOWED_ORIGINS`, `JWT_SECRET_KEY`/`JWT_COOKIE_SECURE`, mail SMTP settings, Redis, `SHUTDOWN_TIMEOUT`, outbox/dead-letter/task-retry tuning, and a commented-out `API_UPSTREAM` for Caddy), loaded via `core/setting.py`'s `pydantic-settings` `Settings` (cached with `@lru_cache`, use `get_settings()` everywhere rather than instantiating directly). Real environment variables override `.env`, which is how the compose `app`/`devcontainer` services repoint the DB/Redis/mail hosts. Every DB URL must use `postgresql+asyncpg://` — there is no sync driver installed (Alembic's `env.py` uses `async_engine_from_config` too). `get_replica_url` falls back to `database_url.replace("5433", "5434")` when `DATABASE_REPLICA_URL` is unset — only correct for the bundled compose ports. `environment` is `local` or `production` only.

The app's OpenAPI title, summary and version come from the installed package metadata (`importlib.metadata.metadata("fasti-kit")` in `main.py`), i.e. from `pyproject.toml`'s `name`/`description`/`version` — change them there, not in `main.py`.

## Architecture

### Domain-per-folder DDD

Each domain (`auth/`, `user/`) is a top-level namespace package (no top-level `__init__.py`) with up to six identically-named subpackages, each with its own `__init__.py` that re-exports its symbols (kept up to date by the scaffolding scripts, not hand-maintained imports):

- `entities/` — plain `@dataclass` domain objects (DB-agnostic), e.g. `user/entities/user.py`
- `models/` — SQLAlchemy `Mapped`/`mapped_column` ORM classes bound to `core.database.Base`
- `repositories/` — DB access layer; takes an `AsyncSession` in `__init__`, returns entities (not models) to callers, converts via a `_to_entity` static method
- `schemas/` — Pydantic request/response models for FastAPI
- `services/` — business logic, orchestrates repositories, called from routes
- `routes/` — `APIRouter` instances, aggregated into `core/api_versions.py`'s `v1_router` (mounted at `/api/v1`), which is included once in `main.py`

Layers are called through each other in one direction: route → service → repository → model, with entities as the return type crossing back up. Routes get dependencies via `Depends()` factories in each domain's `dependencies.py` (e.g. `user/dependencies.py`'s `get_user_service`, `get_current_user`; `auth/dependencies.py`'s `get_auth_service`, `get_auth_session`) rather than constructing `Service(Repository(db))` inline.

**Who owns what** (a decision recorded in `docs/reliability-scalability-maintainability-review.md`):

| Layer | Owns | Must not |
|---|---|---|
| Route | Parsing, validation, calling one service method, shaping the response (cookies, status) | Take `db`, commit, hold business rules |
| Service | Business rules, orchestration, hashing, token creation, cache invalidation | Touch the session, commit, raise `HTTPException` |
| Repository | All DB access, **the transaction**, primary/replica pinning, turning `IntegrityError` into `ConflictError` | Hold business rules |

- Every public repository method is one atomic unit: it wraps its writes in `async with transaction(self.db):` (`core/database.py` — commits on success, rolls back on error). There is no `auto_commit` flag and no caller-side `db.commit()`.
- `stage_*` methods (`UserRepository.stage_add`/`stage_update`/`stage_deactivate`, `RevokedTokenRepository.stage_add`/`stage_add_if_absent`, `OutboxRepository.stage_add`) flush without committing. They are building blocks for another repository method's transaction only — a service calling one directly would silently write nothing, and the `stage_` name is the guard.
- A flow that writes several tables is a single repository method, not several service calls: `UserRepository.register` (user + verification jti + outbox row), and `auth/repositories/account_repository.py`'s `AccountRepository` (verify-email, reset-password, start email verification / password reset, revoke tokens, close account — spanning `users`, `revoked_tokens` and `outbox_events`). It lives in `auth` because `auth` may import `user.repositories` but not `user.models`.
- Read-after-write freshness is `consistent=True` on `UserRepository.get`/`get_by_email`, which pins the read to primary. Routes and services never touch `force_primary_var`; repositories set it themselves before writes.
- Below the route layer, raise `DomainException` subclasses (see `core/exception.py` below), never `HTTPException`. The `Depends()` guards do too: `get_current_user` raises `EntityNotFoundError`/`UnauthorizedActionError`, `require_scopes` raises `UnauthorizedActionError`.

This layering is not just convention — `pyproject.toml`'s `[tool.importlinter]` has six contracts, run via `uv run lint-imports` (also a pre-commit hook):
1. one-way `routes → services → repositories → models` layers per domain (`containers = ["auth", "user"]`, `exhaustive = false`);
2. entities forbidden from importing `sqlalchemy`/`fastapi`/`pydantic`;
3. `auth` forbidden from importing `user.routes`/`user.services`/`user.models` directly (`allow_indirect_imports = true` on purpose — `auth → user.repositories → user.models` is a structural chain that can't be removed, so don't delete or tighten it);
4. `auth` forbidden from reaching `user.routes` even transitively;
5. `*.routes` and `*.services` (plus `core.dead_letter.router`/`.service`) can't import `sqlalchemy` or `core.database`;
6. `*.services` and `*.repositories` (plus `core.dead_letter.service`/`.repository`) can't import `fastapi`.

`core.dead_letter.*` is named explicitly in 5 and 6 because the `*.routes`-style wildcards don't match its flat module names. Nothing restricts the other direction between domains: `user` currently imports `auth` (`auth.dependencies.auth` for token guards, `SecurityService`/`EmailVerificationService` in `UserService.register`, and `AuthService` for `DELETE /users/me`).

**URLs are resource-style.** Plural noun for the collection, `/{id}` for one record, `/me` for the caller's own record, HTTP method for the action — no verbs in paths. `user_router` (prefix `/users`): `POST /users` (register, rate-limited), `GET /users` (cursor-paginated list, `admin:read` scope — every user holds `users:read` by default, so that scope guards nothing), `GET`/`PATCH`/`DELETE /users/me`. Non-CRUD actions like `/auth/login` are the exception.

**Scaffolding CLI (`scripts/`)** — one generator path. Each `create_<layer>.py` has a pure `generate_<layer>(domain, name, fields)` function that holds the template and returns the paths it touched, plus a thin typer `create_<layer>` wrapper (prompts, validation, `ruff` via `format_paths`) registered as a `uv run create-*` console script in `pyproject.toml`'s `[project.scripts]`. Orchestrators (`create_all`, `create_test`) call only the pure functions — calling a typer-decorated function directly hands it `OptionInfo` defaults, which is what broke `create-all` before. `scripts/_boilerplate.py` holds the shared helpers: case conversion, a naive `pluralize` (appends `s`; used for both the table name and the URL prefix, so `category` → `categorys`), name validation (lowercase identifiers only; `RESERVED_DOMAINS` = `alembic`, `core`, `docs`, `main`, `scripts`, `tests`), `write_new_file` (skips existing files), an `ast`-based `update_init`/`merge_imports`, and the idempotent wiring helpers `register_pyproject` (adds the domain to all seven pyproject lists that name domains, verified with `tomllib`, never touching the auth-only contracts), `register_model` and `register_router`. Generated code follows the conventions above: repositories pin `force_primary_var` on writes, wrap each write in `transaction()`, translate `IntegrityError` to `ConflictError` in `_flush_or_raise`, and expose a cursor-paginated `list`; services raise `EntityNotFoundError` for missing records; routes live under `/<plural>` (`POST`/`GET /products`, `GET`/`PATCH`/`DELETE /products/{id}`), get the service from `<domain>/dependencies.py`, and require an access token on create/update/delete. Covered by `tests/test_scaffolding.py` (incl. a check that every console script resolves) and `scripts/smoke_scaffold.sh`.

### Request pipeline (`main.py`)

Middleware order matters. Starlette runs the last `add_middleware` call outermost, so `main.py` adds them as `GZipMiddleware`, `SecurityHeadersMiddleware`, `CorrelationIdMiddleware`, `N1DetectorMiddleware`, `CORSMiddleware`, and a request passes through them in the reverse order — CORS first, GZip last:
- `CORSMiddleware` — `allow_origins=settings.allowed_origins`, credentials allowed.
- `N1DetectorMiddleware` (`core/middlewares/n1_detector.py`, **local environment only**) — counts queries per request via SQLAlchemy `before_cursor_execute` events, sets `X-Query-Count`, logs a warning above `threshold=10`.
- `CorrelationIdMiddleware` (`core/middlewares/correlation.py`) — generates/propagates `X-Request-ID`, and catches middleware-stack crashes and returns RFC 7807 JSON.
- `SecurityHeadersMiddleware` (`core/middlewares/security_headers.py`) — HSTS only when `environment == "production"`.
- `GZipMiddleware` (`minimum_size=1000`).

Exception handlers are installed via `install_problem_handlers` (`core/problem.py`) and `install_auth_error_handlers` (`auth/errors.py`) — every API error path, including validation errors, rate-limit 429s, `DomainException`s and unhandled 500s, is normalized into a single `ProblemDetails` (RFC 7807 / `application/problem+json`) shape with a `correlation_id`. `core/openapi.py`'s `setup_openapi` replaces FastAPI's schema builder (it passes `title`/`summary`/`version`/`description` through explicitly, so a new `FastAPI(...)` info field must be added there too) and types every 4xx/5xx response as `ProblemDetails`; `problem_responses(*codes)` declares them per route. `prometheus-fastapi-instrumentator` exposes `/metrics`. `add_pagination(app)` enables `fastapi-pagination`.

Routers included in `main.py`: `health_router` (`core/health.py`: `/health/live`, `/health/ready` which probes primary DB, replica DB and Redis with 2s timeouts, and `/health/workers` which probes the SAQ worker, the outbox relay's Redis heartbeat (written by `relay_loop` after each successful dispatch) and the age of the oldest pending outbox row (`OutboxRepository.oldest_pending_age`, via the request's injected session) against `outbox_max_lag_seconds` — kept separate from `/ready` so a dead worker doesn't pull API instances out of rotation), `dlq_router` (`/api/admin/tasks/dlq`) and `v1_router` (`/api/v1`).

Startup runs `check_database`, `check_mail_config`, `check_jwt_config` (`core/startup_checks.py`) inside the `lifespan` and refuses to boot if any fail. Shutdown disposes the DB engines and closes Redis, each in its own try so one failure doesn't skip the other; `SHUTDOWN_TIMEOUT` is uvicorn's graceful-shutdown window.

### `core/` — cross-cutting infrastructure

- **`core/database.py`** — `AsyncResilientRoutingSession` auto-routes `SELECT`s to `replica_engine` and writes to `primary_engine`, "stickies" a request to primary for the rest of its lifetime once any write happens (via the `force_primary_var` contextvar; a `before_flush` listener sets it for ORM flushes too), and fails over reads to primary on a replica `OperationalError` — including `scalar()`/`get()`, not just `execute()`, and only when the session holds no pending/dirty/deleted objects a rollback would destroy. `transaction(db)` is the commit/rollback context manager repositories use. `get_db` yields a session via `db_session()`, which resets `force_primary_var` per request. `AsyncSessionLocal()` is also opened directly, outside request DI, by `auth/dependencies.py`'s `is_token_revoked`, `core/worker/tasks.py`, `core/outbox/relay.py` and `core/dead_letter/hook.py`. `bind_override_var` is a test-only escape hatch (see Testing).
- **`core/exception.py`** / **`core/problem.py`** — `DomainException(detail, status_code, type_str, title)` and its subclasses `EntityNotFoundError` (404), `UnauthorizedActionError` (403), `ConflictError` (409), `BadRequestError` (400); `auth/exceptions.py` adds `InvalidCredentialsError` (401) and `InvalidTokenError` (400). Raised in services, repositories and `Depends()` guards; `core/problem.py` turns them into RFC 7807 responses with `type` set from `type_str` (e.g. `errors/conflict`).
- **`core/cache.py`** — `@cache(ttl=..., tags=[...])` decorator for Redis cache-aside on functions with a return type annotation (required — used to build a `TypeAdapter` for serialization); `invalidate_tags(...)` wipes everything tagged. No function uses `@cache` today; `tests/test_cache.py` covers it. Don't cache entities that hold secrets — a cached `User` would put `password_hash` in Redis.
- **`core/queue.py`** / **`core/worker/`** — `task_queue` (saq/Redis) for background jobs; register new job functions in `core/worker/main.py`'s `functions` list (today `process_welcome_email`, `send_email_task`). Enqueue through `enqueue_task(name, key=..., **kwargs)` rather than `task_queue.enqueue` directly — it applies the project retry policy (`task_max_retries` / `task_retry_delay` / `task_retry_backoff`), without which SAQ's `retries=1` default means a job never actually retries. The worker's daily cron jobs purge revoked tokens (03:00), dispatched outbox rows (03:30) and retried dead-letter rows (04:00). The worker calls `logging.basicConfig(force=True)`, replacing `core/logging`'s config, so worker log lines carry no correlation id.
- **`core/outbox/`** — transactional outbox. `OutboxRepository.stage_add(task_name, payload)` records a queued task as an `outbox_events` row inside the calling repository's transaction instead of enqueueing directly, so the side effect commits atomically with the business write (repositories hold their own `OutboxRepository`; `get_outbox_repository` injects one into `/health/workers`). `relay_loop` (spawned in the SAQ worker's `startup` hook) polls with `FOR UPDATE SKIP LOCKED`, forwards rows to `task_queue` with a deterministic `key=f"outbox:{id}"` for at-least-once delivery, and parks poison rows in `failed_at` after `outbox_max_attempts`. `cleanup_outbox_task` purges dispatched rows past `outbox_retention_days`. Anything that needs an email sent goes through an outbox row, not `BackgroundTasks`. The relay's `dispatch_pending`/`cleanup_dispatched` call `db.commit()` directly — they sit outside the domain layers.
- **`core/dead_letter/`** — dead-letter queue for background jobs that exhaust their retries, laid out like a domain (`entity`, `model`, `repository`, `service`, `schema`, `router`, `dependencies`) plus `hook.py`. `record_dead_letter` is wired as the SAQ worker's `after_process` hook; when a job's terminal status is `FAILED`/`ABORTED` it writes the function, kwargs, traceback and attempt count to `dead_letter_jobs`. `dlq_router` (`/api/admin/tasks/dlq`, gated by `require_scopes("admin:read")` — the reference for the scope-guard pattern) lists / inspects / retries / deletes / purges rows; `DeadLetterJobService` holds the rules and raises `EntityNotFoundError` / `ConflictError` (retrying twice) / `BadRequestError` (unbounded purge). Retry is one `DeadLetterJobRepository.retry` transaction: a conditional `UPDATE … SET retried_at WHERE retried_at IS NULL` claims the row (so concurrent retries get one 200 and one 409) and stages an outbox row with payload `{"kwargs": …}` — wrapped so stored kwargs named like SAQ `Job` fields still reach the task — which the relay enqueues with `key=f"outbox:{id}"` on its next poll. `cleanup_dead_letter_task` purges retried rows past `dead_letter_retention_days`. Not captured: jobs aborted by SAQ's `sweep` (worker hard-killed mid-job).
- **`core/limiter.py`** — `slowapi` `Limiter` backed by Redis, keyed on `get_remote_address`; apply with `@limiter.limit("5/minute")` under the route decorator, with `request: Request` as a parameter (every `auth_router` route except `/logout`, plus `POST /users`). Behind a proxy without uvicorn `--proxy-headers`, every client shares the proxy's IP — an open reliability gap.
- **`core/deprecation.py`** — `route_class=DeprecationRoute` + `@deprecated(sunset=...)` marks a route deprecated in OpenAPI and injects `Deprecation`/`Sunset` response headers. No route uses it today; `tests/test_deprecation.py` covers it.
- **`core/safety.py`** — `ensure_safe_operation(...)` guards destructive/dev-only CLI commands (e.g. `seed --reset`) from running against production without an explicit `--allow-production` flag; also warns on non-local DB hosts outside production.
- **`core/logging/`** — logging config with a console handler plus a `FileHandler` to `logs/app.log` (unrotated, gitignored); correlation id on every line via `RequestIdFilter`.
- **`core/factories/`** — polyfactory factories (used by `seed`, `create-factory`, tests).
- **`core/models.py`** — manifest-only: imports `Base` and every domain's models so `Base.metadata` is fully populated for Alembic autogenerate and app startup. When adding a new domain with its own models, import it here too (`create-all` does it for you).
- **`core/setting.py`** — `pydantic-settings` `Settings`, cached via `get_settings()`. `backend_url` gets an auto-prepended `http://` scheme if none is given.
- Also: `core/mail.py` (SMTP sending), `core/redis.py` (shared pool + `close_redis`), `core/api_versions.py` (`v1_router`, `API_V1_PREFIX`).

### Auth (`auth/`)

Uses `authx` (`auth/dependencies.py` configures `AuthX` with `JWT_TOKEN_LOCATION=['headers', 'cookies']`, HS256, `JWT_COOKIE_CSRF_PROTECT=True`). Access tokens travel via `Authorization: Bearer` header; refresh tokens are set as an HTTP-only cookie via `auth.set_refresh_cookies`. `auth/routes/auth_router.py` covers `/login`, `/refresh`, `/logout`, `/verify-email`, `/resend-verification`, `/forgot-password`, `/reset-password`; each calls one `AuthService` method (`auth/services/auth_service.py`). Token minting and cookie setting stay in the route. `require_scopes(*scopes, all_required=True)` (`auth/dependencies.py`) wraps `auth.token_required` and checks `TokenPayload.has_scopes`; scopes are stored space-delimited on the user row, exposed as `User.scope_list`, and embedded into the access token at login/refresh. `get_auth_session` collects the access token's and (if present) the refresh cookie's `jti`/expiry into an `AuthSession` for logout and account closing.

Auth persists its own state: `auth/entities/models/repositories` hold `RevokedTokenRepository`, used both for logout/delete token revocation by `jti` (inserts use `ON CONFLICT DO NOTHING`, so revoking an already-revoked token is a no-op) and for one-time email-verification / password-reset tokens (a verify/reset token is inserted into the same revoked-token table once consumed, so replay is rejected; a newer request supersedes an older link via `pending_verification_jti` / `pending_password_reset_jti` on the user). `is_token_revoked` is registered as authx's blocklist callback and opens its own session on every authenticated request; `RevokedTokenRepository.exists()` pins that read to primary. Auth reads user data through `user`'s `UserRepository` rather than owning user storage; `AccountRepository` (see Architecture) owns the cross-table writes.

Password hashing is `bcrypt` via `auth/services/security_service.py` — `hashpw`/`checkpw` require `bytes`, so `hash_password`/`check_password` encode/decode at the boundary; don't pass `str` into the bcrypt functions directly. Both are async and run bcrypt in a worker thread via `asyncio.to_thread`, so a hash doesn't block the event loop — `await` them. `_DUMMY_PASSWORD_HASH` is computed with the sync `_hash` at import time.

**Login enforces identical failure responses.** `SecurityService.authenticate` returns `None` for unknown email, wrong password, inactive or unverified account, and `AuthService.login` turns every `None` into the same `InvalidCredentialsError` (401, `Invalid credentials`). An unknown email is still checked against a precomputed `_DUMMY_PASSWORD_HASH`, so response timing doesn't leak whether the account exists either. Preserve both properties when touching login. `/resend-verification` and `/forgot-password` follow the same shape: they return an identical generic message regardless of whether the email exists.

### Testing (`tests/`)

`tests/conftest.py` provides `db_engine` (creates `Base.metadata` against a real `<db>_test` database derived from `DATABASE_URL`, refusing to run if it can't derive one — no mocking, no testcontainers despite that dep group existing), `db` (builds the real `AsyncResilientRoutingSession` with `bind_override_var` pointed at the test connection, wrapped in an outer transaction + SAVEPOINT via `join_transaction_mode="create_savepoint"`, rolled back at teardown even though repositories call `commit()`), `client` (an `httpx.AsyncClient` against the ASGI app with `get_db` overridden by an async generator that resets `force_primary_var` per request, and `auth.dependencies.AsyncSessionLocal` patched so the token-blocklist check hits the test session), and `query_counter` (counts SQL statements executed during a test, for asserting no N+1 regressions — pair with `X-Query-Count` for manual checks against the dev server). Autouse fixtures dispose the Redis pool and the primary/replica engine pools after every test (asyncpg/redis-py bind connections to the event loop that created them, and pytest-asyncio gives each test a fresh loop). `pyproject.toml` sets `pythonpath = ["."]` and `asyncio_mode = "auto"`. Because the shared test connection hides a missing commit, `tests/test_transaction_ownership.py` counts `commit`/`rollback` calls directly. Middleware/handler tests (`test_security_headers.py`, `test_deprecation.py`, `tests/core/test_problem.py`) build a standalone `FastAPI()` with `TestClient` instead of using the fixtures.

Known sharp edge: `test_worker_tasks.py`, `test_dead_letter.py` and `test_lifespan.py` reach `AsyncSessionLocal()` through code that isn't patched, so they hit the dev database, and `test_health_workers.py` shares Redis with other tests. A test that starts a background task on the shared `db` session must `await` the task after cancelling it, or the fixture closes the session mid-commit (`IllegalStateChangeError`) and the next DB test fails with `PendingRollbackError` — that was the old heartbeat/cleanup-test "flake".

### Docs (`docs/`)

`docs/README.md` indexes the flat set of working notes: `reliability-scalability-maintainability-review.md` (current assessment, with the transaction-ownership decision record and the open gap lists), `audit-findings.md`, `improvement-recommendations.md`, `roadmap.md`, `transaction-and-routing-fixes.md`, `rw-split-analysis.md`, `typescript-types.md`, feature brainstorms, a historical bug report, plus the superseded `frontend-options.md`/`jinja-htmx-setup.md` from the removed admin UI. These record *why* a feature was built the way it was, including superseded decisions with reasoning intact — check there before re-deciding something that's already been settled (e.g. cursor pagination via `fastapi-pagination`+`sqlakeyset` over hand-rolled, `authx` scopes over Casbin for authorization, repositories owning the transaction). Several predate work that has since landed (`roadmap.md`, `current-state.md`, `new-features*.md` still list built features as planned) — trust the code over a stale doc claim.
