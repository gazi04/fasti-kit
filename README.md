# fasti-kit

A FastAPI starter kit built around a scaffolding CLI that generates DDD-style domain
folders — routes, schemas, entities, models, repositories, services — so a new domain
follows the same shape every time, and plugs into production-shaped infrastructure that's
already there: RFC 7807 error responses, primary/replica DB routing, rate limiting,
response caching, background jobs with a transactional outbox, cursor pagination, path
versioning, and import-linter-enforced layering.

## Why this exists

Every new FastAPI project started the same way: wire up auth, error handling, DB
sessions, pagination, rate limiting, background jobs — the same boilerplate, rebuilt from
scratch, every single time. It got repetitive fast, and repetitive setup is exactly the
kind of work that should only be done once.

Before FastAPI, most of my backend work was in Laravel — a framework where the
batteries are included. Auth, queues, mail, migrations, rate limiting: all there on day
one, so you spend your time on the actual business logic instead of re-plumbing
infrastructure. Python's ecosystem doesn't hand you that out of the box — FastAPI gives
you a great foundation for routing and validation, but everything past that (how
sessions are scoped, how errors are shaped, how a new feature is structured) is a
decision you make yourself, every time.

`fasti-kit` is my attempt to close that gap for FastAPI: a starting point that already
has the infrastructure a real project ends up needing, plus a CLI that scaffolds new
domains into a consistent structure instead of hand-rolling folders and imports each
time. It's meant to be cloned and built on, not read once and discarded — enforced
import boundaries and a full test/lint/type-check pipeline are there so the project
stays coherent as it grows past the two example domains (`auth`, `user`) it ships with.

---

## Table of contents

- [Features](#features)
- [Project structure](#project-structure)
- [How it works](#how-it-works)
  - [Request pipeline](#request-pipeline)
  - [Database: primary/replica routing](#database-primaryreplica-routing)
  - [Errors](#errors)
  - [Background jobs and the outbox](#background-jobs-and-the-outbox)
  - [Caching, rate limiting, pagination](#caching-rate-limiting-pagination)
  - [Auth](#auth)
- [Getting started](#getting-started)
- [Scaffolding a new domain](#scaffolding-a-new-domain)
- [API overview](#api-overview)
- [Testing](#testing)
- [Quality gates](#quality-gates)
- [Docs](#docs)

---

## Features

- **Domain scaffolding CLI** — `uv run create-domain`, `create-all`, and per-layer
  generators (`create-entity`, `create-model`, `create-repository`, `create-schema`,
  `create-service`, `create-route`) produce a new domain or a new piece of an existing
  one in the project's DDD shape, instead of copy-pasting an existing domain by hand.
- **RFC 7807 problem details** — every error path (validation errors, rate-limit 429s,
  domain exceptions, unhandled 500s) is normalized into a single `application/problem+json`
  shape with a correlation ID, via `core/problem.py`.
- **Primary/replica DB routing** — reads go to a replica, writes go to primary, and a
  request that writes "stickies" to primary for the rest of its lifetime so it never
  reads its own write from a lagging replica. Replica failures fail over to primary
  automatically.
- **N+1 query detection** — a local-only middleware counts SQL statements per request,
  exposes the count via an `X-Query-Count` header, and logs a warning past a threshold.
- **Rate limiting** — Redis-backed, applied per-route with a decorator
  (`@limiter.limit("5/minute")`).
- **Response caching** — a `@cache(ttl=..., tags=[...])` decorator for Redis
  cache-aside, with tag-based invalidation.
- **Background jobs + transactional outbox** — jobs run through SAQ/Redis with a real
  retry policy; anything that needs to happen atomically with a DB write (e.g. "send
  this email after the signup commits") goes through an outbox table instead of
  `BackgroundTasks`, so the side effect can't fire before the transaction it depends on
  actually commits.
- **Dead-letter queue** — jobs that exhaust their retries land in a `dead_letter_jobs`
  table, inspectable and retriable through an admin API.
- **Cursor pagination** — `fastapi-pagination` + `sqlakeyset`, used consistently across
  list endpoints instead of offset pagination.
- **Path-based API versioning** — routes are mounted under `/api/v1`, structured so a
  `v2` can be added without breaking `v1`.
- **Enforced layering** — `import-linter` contracts (`routes → services → repositories →
  models`, one-way; entities forbidden from importing SQLAlchemy/FastAPI/Pydantic;
  cross-domain import rules) are checked in CI and pre-commit, not just documented.
- **JWT auth with scopes** — `authx`-based, access token via `Authorization: Bearer`,
  refresh token via HTTP-only cookie, route-level `require_scopes(...)` dependency,
  email verification and password reset flows, enumeration-safe login/reset responses.
- **Server-rendered admin UI** — a small Jinja2 + HTMX + Tailwind app mounted at
  `/admin`, built on top of the same domain services/repositories rather than a separate
  API client.
- **Observability** — Prometheus metrics via `prometheus-fastapi-instrumentator`,
  correlation IDs on every request/log line, structured logging, and a docker-compose
  stack with Grafana, Prometheus, Dozzle (log viewer), and Mailpit (SMTP catcher).
- **Safety rails for destructive ops** — seeding and other dev-only CLI commands refuse
  to run against what looks like production unless explicitly overridden.

## Project structure

```
fasti-kit/
├── auth/                # domain: authentication, token revocation
├── user/                # domain: user accounts
│   ├── entities/         # dataclasses — plain domain objects, DB-agnostic
│   ├── models/            # SQLAlchemy ORM classes
│   ├── repositories/     # DB access, returns entities (not models) to callers
│   ├── schemas/           # Pydantic request/response models
│   ├── services/          # business logic, orchestrates repositories
│   ├── routes/             # APIRouter instances
│   └── dependencies.py    # Depends() factories (get_user_service, get_current_user, ...)
├── core/                 # cross-cutting infrastructure, shared by every domain
│   ├── database.py         # AsyncResilientRoutingSession — primary/replica routing
│   ├── problem.py           # RFC 7807 error formatting
│   ├── exception.py         # DomainException and subclasses
│   ├── cache.py              # Redis cache-aside decorator
│   ├── limiter.py            # rate limiting
│   ├── queue.py / worker/   # background jobs (SAQ)
│   ├── outbox/                # transactional outbox
│   ├── dead_letter/           # dead-letter queue + admin API
│   ├── middlewares/           # correlation ID, security headers, N+1 detector
│   ├── api_versions.py       # mounts each domain's router under /api/v1
│   ├── models.py               # imports every domain's models (Alembic manifest)
│   └── setting.py               # pydantic-settings, get_settings()
├── web/                  # server-rendered admin UI (Jinja2 + HTMX), not a domain
├── scripts/               # the create-* CLI generators + seed/migration helpers
├── alembic/                # DB migrations
├── tests/                   # pytest, real Postgres, transactional rollback per test
├── docs/                     # design/decision docs, see docs/README.md
└── main.py                    # FastAPI app, middleware stack, lifespan
```

New domains follow the same six-folder shape as `auth`/`user`. Layers only ever call
downward — route → service → repository → model, with entities as the return type
crossing back up — and that direction is enforced by `import-linter`, not just
convention.

## How it works

### Request pipeline

`main.py` builds the middleware stack outermost-last (the last `add_middleware` call
runs first on a request):

```
GZip → SecurityHeaders → CorrelationId → N1Detector (local only) → CORS
```

`CorrelationIdMiddleware` generates/propagates an `X-Request-ID` and also catches
crashes elsewhere in the middleware stack, returning RFC 7807 JSON instead of a bare
500. Exception handlers installed via `install_problem_handlers` and
`install_auth_error_handlers` cover every error path with the same shape.

Startup runs `check_database`, `check_mail_config`, `check_jwt_config` inside the
app's `lifespan` — the app refuses to boot if any of them fail, rather than starting up
and failing on the first request.

### Database: primary/replica routing

`core/database.py`'s `AsyncResilientRoutingSession` inspects each statement: `SELECT`s
go to the replica engine, writes go to primary. Once a request performs any write, the
session "stickies" to primary for the rest of that request (via a contextvar) so a
later read in the same request can't see stale replica data. If a route needs
read-after-write consistency *before* an actual write runs — e.g. reading a row it's
about to check, ahead of updating it — it can force primary explicitly rather than
relying on the sticky flag. Replica `OperationalError`s fail reads over to primary
automatically.

### Errors

Service and repository code raises `DomainException` subclasses
(`EntityNotFoundError`, `UnauthorizedActionError`, `ConflictError`) instead of
`HTTPException` — they get RFC 7807 formatting for free at the boundary, so the error
shape stays consistent whether the failure came from a validation error, a rate limit,
or business logic several layers down.

### Background jobs and the outbox

Jobs run through `core/queue.py`'s `task_queue` (SAQ + Redis), registered in
`core/worker/main.py`. Anything enqueued through `enqueue_task(...)` gets the project's
retry policy applied automatically — SAQ's own default (`retries=1`) effectively never
retries, so this matters.

For work that has to happen atomically with a DB write (send a verification email after
signup, only if the signup actually commits), `core/outbox/`'s `OutboxRepository.add(...)`
writes a row into the same transaction as the business write instead of enqueueing
directly. A relay loop polls that table with `FOR UPDATE SKIP LOCKED` and forwards rows
to the real queue, so the side effect is delivered at-least-once and never fires ahead
of the write it depends on.

Jobs that exhaust their retries are captured by `core/dead_letter/` and inspectable
through an admin API (list / inspect / retry / purge), gated behind an `admin:read`
scope.

### Caching, rate limiting, pagination

- `@cache(ttl=..., tags=[...])` wraps a function, serializes its return value via a
  `TypeAdapter` built from its return type annotation, and stores it in Redis;
  `invalidate_tags(...)` clears everything under a tag at once.
- `@limiter.limit("5/minute")` applies Redis-backed rate limiting per route.
- List endpoints return `fastapi-pagination`'s `CursorPage`, backed by `sqlakeyset`,
  rather than offset/limit pagination.

### Auth

JWTs via `authx`: access tokens travel in the `Authorization: Bearer` header, refresh
tokens are set as an HTTP-only cookie. `require_scopes(*scopes)` wraps token validation
and checks the token's embedded scopes. Login, resend-verification, and forgot-password
all return identical responses regardless of whether the account exists, to avoid
leaking which emails are registered. Auth keeps its own revoked-token table — used both
for logout/delete token revocation and for one-time email-verification/password-reset
tokens — but reads user data through `user`'s repository rather than owning user
storage itself.

## Getting started

Requires Python ≥3.13 and [`uv`](https://docs.astral.sh/uv/).

```bash
# 1. install dependencies
uv sync

# 2. copy env config and fill in the blanks (JWT secret, DB creds, etc.)
cp .env.example .env

# 3. start infra: postgres primary+replica, redis, mailpit (SMTP catcher)
docker compose up -d postgres-primary postgres-replica redis mailpit

# 4. apply migrations
uv run alembic upgrade head

# 5. (optional) seed local data — refuses to run against production without --allow-production
uv run seed

# 6. run the API
uv run main.py                       # http://127.0.0.1:8000

# 7. (optional) run the background job worker, needed for anything queued
uv run saq core.worker.main.settings
```

The rest of the docker-compose stack (`pgadmin`, `prometheus`, `grafana`, `dozzle`,
`caddy`) is optional and can be brought up the same way when you need it:

```bash
docker compose up -d pgadmin prometheus grafana dozzle caddy
```

| Service | URL |
|---|---|
| API | http://localhost:8000 |
| Admin UI | http://localhost:8000/admin |
| API docs (OpenAPI) | http://localhost:8000/docs |
| Mailpit (catches outgoing mail) | http://localhost:8025 |
| pgAdmin | http://localhost:8888 |
| Grafana | http://localhost:3000 |
| Prometheus | http://localhost:9090 |
| Dozzle (log viewer) | http://localhost:8008 |

## Scaffolding a new domain

```bash
uv run create-domain billing              # empty routes/schemas/entities/models/repositories/services dirs
uv run create-all billing invoice         # entity + model + repository + schema + service + route, all at once
# — or generate a single layer:
uv run create-entity billing invoice
uv run create-model billing invoice
uv run create-repository billing invoice
uv run create-schema billing invoice
uv run create-service billing invoice
uv run create-route billing invoice
```

`create-domain` only creates the empty folder skeleton. After scaffolding, a new domain
still needs to be wired in by hand: imported into `core/models.py` (so Alembic and
startup see its tables), mounted in `core/api_versions.py`, and added to the
`import-linter` contracts in `pyproject.toml`. Migrations, once a domain has models,
are generated the same guarded way:

```bash
uv run create-migration -m "add invoices table" --domain billing --apply
```

This checks that the new models are actually registered in `core/models.py` before
autogenerating, and lints the generated migration for common footguns (drops, silently
non-nullable columns) before applying it.

For test scaffolding:

```bash
uv run create-factory billing invoice    # polyfactory Create/Update request factories
uv run create-test billing invoice       # repository+service tests, run immediately after writing
```

## API overview

All domain routes are mounted under `/api/v1`.

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/v1/auth/login` | Login, sets refresh cookie |
| POST | `/api/v1/auth/refresh` | Rotate access token from refresh cookie |
| POST | `/api/v1/auth/logout` | Revoke current token |
| GET | `/api/v1/auth/verify-email` | Consume email verification token |
| POST | `/api/v1/auth/resend-verification` | Resend verification email (enumeration-safe) |
| POST | `/api/v1/auth/forgot-password` | Start password reset (enumeration-safe) |
| POST | `/api/v1/auth/reset-password` | Consume password reset token |
| GET | `/api/v1/auth/protected` | Reference route for `require_scopes(...)` |
| POST | `/api/v1/user/create` | Create a user |
| GET | `/api/v1/user/get` | Fetch a user |
| PATCH | `/api/v1/user/update` | Update a user |
| DELETE | `/api/v1/user/delete` | Delete a user |
| GET | `/api/v1/user/list` | Cursor-paginated user list |
| GET/POST | `/admin/login` | Admin UI login (cookie session) |
| GET | `/admin/users` | Admin user list (server-rendered) |
| GET | `/api/admin/tasks/dlq` | List dead-letter jobs (`admin:read` scope) |
| POST | `/api/admin/tasks/dlq/{id}/retry` | Retry a dead-lettered job |

Full, current request/response schemas are in the generated OpenAPI docs at `/docs` once
the app is running.

## Testing

```bash
uv run pytest                                        # full suite
uv run pytest tests/test_user_domain.py::test_name   # single test
uv run pytest --cov                                   # coverage, fails under 70%
```

Tests run against a real Postgres database (`DATABASE_URL` with `fasti_kit` swapped for
`fasti_kit_test`) — no mocking, no testcontainers. Each test runs inside an outer
transaction plus a `SAVEPOINT` that's rolled back at teardown, so nothing persists
between tests even if the code under test calls `commit()`.

## Quality gates

```bash
uv run pyright                       # type checking
uv run ruff check .                  # lint
uv run ruff format .                 # format
uv run lint-imports                  # enforce DDD layering contracts
uv run deptry .                      # unused/missing dependency check
uv run pip-audit                     # dependency vulnerability scan
uv run pre-commit run --all-files    # all of the above, wired as pre-commit hooks
```
