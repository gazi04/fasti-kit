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
@user_router.get("/me", response_model=UserResponse)
async def get_user(user: User = Depends(get_current_user)) -> User:
    return user
```

Paths are resource-style: a plural noun for the collection, `/{id}` for one item, `/me` for the caller's own record, and the HTTP method for the action (`POST /users`, `PATCH /users/me`, `GET /products/{id}`). No verbs in paths (`/create`, `/get`, `/update`, `/delete`, `/list`). A sub-resource nests under its parent (`/users/{id}/orders`). Actions that aren't CRUD, like `/auth/login`, are the exception.

If the endpoint needs a new repository/service method, add it to `<domain>/repositories/*.py` / `<domain>/services/*.py` first — routes call services, services call repositories, never skip a layer (`import-linter`'s `"DDD layers one-way"` contract enforces this at `uv run lint-imports` time).

## 3. Auth and scopes

- Full auth requirement: `payload: TokenPayload = Depends(auth.token_required(type="access", locations=["headers"]))`, then `UUID(payload.sub)` for the user id — see `PATCH /users/me`, `DELETE /users/me`, `GET /users` in `user_router.py`.
- Need the full user entity, not just the token payload: use `Depends(get_current_user)` instead (does the DB lookup + `is_active` check for you) — see `GET /users/me`.
- Scope-gated (admin-only, etc.): `Depends(require_scopes("scope:name"))` from `auth/dependencies.py` — see the `admin:read` guard on `dlq_router` in `core/dead_letter/router.py`.
- Refresh-token-only endpoints (e.g. `/refresh`): `locations=["cookies"]`, `type="refresh"`.

## 4. Error handling

Errors are raised as `DomainException` subclasses, never `HTTPException`:

- `core/exception.py`: `EntityNotFoundError` (404), `UnauthorizedActionError` (403), `ConflictError` (409), `BadRequestError` (400).
- `auth/exceptions.py`: `InvalidCredentialsError` (401), `InvalidTokenError` (400).
- Need another case? Add a subclass with its own `status_code`, `type_str` (e.g. `errors/rate-plan-exceeded`) and `title`, next to the domain that owns it.

Where they're raised:
- **Services and repositories** raise them for business rules and data errors (missing record, duplicate, bad token). Repositories turn `IntegrityError` into `ConflictError`.
- **Dependencies** raise them too: `get_current_user` (`EntityNotFoundError` / `UnauthorizedActionError`), `require_scopes` (`UnauthorizedActionError`).
- **Routes** don't raise or catch errors. They call one service method and let the exception propagate.

`install_problem_handlers` (`core/problem.py`) turns every one into an RFC 7807 `application/problem+json` response, with `type` from `type_str` and the correlation id attached. Never build an error body by hand. Clients branch on `type`, so reuse an existing subclass when the meaning matches.

For OpenAPI docs, declare non-2xx responses explicitly with `core/openapi.py`'s `problem_responses(*status_codes)`:
```python
@auth_router.post("/login", responses=problem_responses(401, 422, 500))
```

## 5. Rate limiting

Sensitive/abuse-prone endpoints (login, registration, password reset, verification) use:
```python
@user_router.post("", response_model=UserResponse)
@limiter.limit("5/minute")
async def create_user(request: Request, ...):
```
`request: Request` must be a parameter for `slowapi` to key on it. Only add this where abuse is a real concern — not every endpoint needs it (`GET /users/me`, `GET /users` don't have it).

## 6. Read-after-write consistency

Routes never touch `force_primary_var`, and can't: import-linter forbids routes and services from importing `core.database`. If a read must see the latest write (e.g. checking a user row before issuing a token), the repository method takes `consistent=True` and pins the read to primary itself. See `UserRepository.get` / `get_by_email`, as called by `AuthService.refresh` and `SecurityService.authenticate`. Plain reads (`GET /users/me`, `GET /users`) are fine going to the replica.

## 7. Verify

```bash
uv run pyright
uv run lint-imports
```
Manually exercise the new endpoint against the dev server (`uv run main.py`) with `curl` — there's no OpenAPI-driven test generation, and `docs/` guides show this pattern for reference.
