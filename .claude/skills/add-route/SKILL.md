---
name: add-route
description: Add a new FastAPI route to an existing fasti-kit domain, following the route→service→repository call pattern, error handling, auth, and rate-limiting conventions from user_router.py/auth_router.py. Use when the user asks to add/create a new endpoint, API, or route.
---

# Add a route

## 1. Decide the starting point

- **New entity/domain with no route yet**: start from `uv run create-route <domain> <name>` (see `scripts/create_route.py`), then customize the generated stub.
- **New endpoint on an existing router** (e.g. another verb on `user_router`, a new action on `auth_router`): hand-edit the domain's `routes/<domain>_router.py` directly — don't regenerate.

## 2. Wire dependencies via `Depends()`, not inline construction

Each domain has a `dependencies.py` with factory functions (`get_user_repository`, `get_user_service`, `get_current_user` in `user/dependencies.py`). Add new endpoints as parameters using these, following:

```python
@user_router.get("/get", response_model=UserResponse)
async def get_user(user: User = Depends(get_current_user)) -> User:
    return user
```

If the endpoint needs a new repository/service method, add it to `<domain>/repositories/*.py` / `<domain>/services/*.py` first — routes call services, services call repositories, never skip a layer (`import-linter`'s `"DDD layers one-way"` contract enforces this at `uv run lint-imports` time).

## 3. Auth and scopes

- Full auth requirement: `payload: TokenPayload = Depends(auth.token_required(type="access", locations=["headers"]))`, then `UUID(payload.sub)` for the user id — see `/update`, `/delete`, `/list` in `user_router.py`.
- Need the full user entity, not just the token payload: use `Depends(get_current_user)` instead (does the DB lookup + `is_active` check for you) — see `/get`.
- Scope-gated (admin-only, etc.): `Depends(require_scopes("scope:name"))` from `auth/dependencies.py` — see `/protected` in `auth_router.py`.
- Refresh-token-only endpoints (e.g. `/refresh`): `locations=["cookies"]`, `type="refresh"`.

## 4. Error handling

Two valid patterns exist in this codebase — pick based on what's already nearby, don't mix silently within one router:

- **`HTTPException(status, detail=...)`** — what every current route actually uses (`auth_router.py`, `user_router.py`). Gets auto-formatted into RFC 7807 `ProblemDetails` by `core/problem.py`'s `http_exception_handler`. Default choice for new endpoints unless you have a reason to reach for the below.
- **`DomainException` subclasses** (`core/exception.py`: `EntityNotFoundError`, `UnauthorizedActionError`, `ConflictError`, or a new subclass) — defined and handler-installed (`install_problem_handlers` in `main.py`) but **not yet used by any route or service**. These carry a `type_str`/`title` for a more specific RFC 7807 `type` URI. Prefer these if you're writing service/repository-layer code that shouldn't need to know an HTTP status code, or if the existing generic `about:blank` type isn't descriptive enough for a client to branch on.

Either way, never construct a raw JSON error body by hand — always go through one of these two so `X-Request-ID`/correlation id and `application/problem+json` formatting stay consistent.

For OpenAPI docs, declare non-2xx responses explicitly with `core/openapi.py`'s `problem_responses(*status_codes)`:
```python
@auth_router.post("/login", responses=problem_responses(401, 422, 500))
```

## 5. Rate limiting

Sensitive/abuse-prone endpoints (login, registration, password reset, verification) use:
```python
@user_router.post("/create", response_model=UserResponse)
@limiter.limit("5/minute")
async def create_user(request: Request, ...):
```
`request: Request` must be a parameter for `slowapi` to key on it. Only add this where abuse is a real concern — not every endpoint needs it (`/get`, `/list` don't have it).

## 6. Read-after-write consistency

If the endpoint reads data it (or a token) depends on being immediately fresh right before a write happens — e.g. checking a user row before issuing a token — call `force_primary_var.set(True)` (from `core/database.py`) at the top of the handler, before the read. See `/login`, `/refresh`, `/verify-email` in `auth_router.py`. Skip this for plain reads (`/get`, `/list`) — they're fine going to the replica.

## 7. Verify

```bash
uv run pyright
uv run lint-imports
```
Manually exercise the new endpoint against the dev server (`uv run main.py`) with `curl` — there's no OpenAPI-driven test generation, and `docs/` guides show this pattern for reference.
