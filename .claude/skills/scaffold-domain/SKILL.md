---
name: scaffold-domain
description: Scaffold a new fasti-kit domain end to end — run the create-domain/create-all CLI, then do the manual wiring the CLI does NOT do (core/models.py import, core/api_versions.py router mount, import-linter contract entries), then verify with lint-imports and pyright. Use when the user asks to add/create/scaffold a new domain or entity, e.g. "add a billing domain", "scaffold a new domain called X".
---

# Scaffold a new domain

The `uv run create-domain`/`uv run create-all` CLI (see `scripts/`) generates a domain's files but leaves several cross-cutting registration points untouched. This skill covers the full loop: generate → wire → verify.

## Process

1. **Ask/confirm scope if not given**: domain name, first entity name + fields (`name:type` pairs, e.g. `price:float,is_active:bool=True` — see `scripts/_boilerplate.py`'s `parse_fields` for supported types: `str`, `int`, `float`, `bool`, `uuid`).
2. **Generate**:
   ```bash
   uv run create-domain <domain>
   uv run create-all <domain> <entity>
   ```
   (Repeat `create-all`/single-layer `create-<layer>` commands for additional entities in the same domain.)
3. **Wire it in** — these are the steps the CLI does not do, all required for the domain to actually be live and enforced:
   - **`core/models.py`**: add `from <domain>.models import <ModelClass>  # noqa: F401` to the manifest, alongside the existing `auth`/`user` imports. Without this, Alembic autogenerate won't see the new table.
   - **`core/api_versions.py`**: import the new domain's router and `v1_router.include_router(<domain>_router)`, matching how `auth_router`/`user_router` are mounted. Without this, the routes are unreachable.
   - **`pyproject.toml` `[tool.importlinter]`**: add the new domain to `root_packages` in the top-level settings, and to `containers` in the `"DDD layers one-way"` contract (currently `containers = ["auth", "user"]`). If the new domain has entities, also add `<domain>.entities` to the `source_modules` list of the `"entities stay DB-agnostic"` contract (currently `["user.entities", "auth.entities"]`). Skipping this means the layering rules exist for the new domain in spirit only — `lint-imports` won't actually check it.
4. **Generate a migration**:
   ```bash
   uv run alembic revision --autogenerate -m "add <domain> <entity> table"
   ```
   Review the generated migration file before applying — autogenerate can miss things or generate spurious diffs.
5. **Verify**:
   ```bash
   uv run lint-imports   # confirms the new domain's layering is actually enforced, not just declared
   uv run pyright         # confirms types across the new files
   ```
6. **Report** what was generated, what was wired, and remind the user that `docs/README.md`'s per-topic guides are opt-in — only add one if the domain has a non-obvious design decision worth recording (this skill does not create docs by default).

## Common follow-ups (do only if asked)

- Adding auth protection to a new route: use `Depends(auth.token_required(...))` or `Depends(require_scopes(...))` from `auth/dependencies.py`, following `user/routes/user_router.py`'s pattern — don't build a parallel auth mechanism.
- Rate limiting: `@limiter.limit("N/period")` from `core/limiter.py`, applied under the route decorator.
- Cross-domain reads (e.g. a new domain needing user data): go through the other domain's repository (e.g. `UserRepository`), never its routes/services/models directly — that's what the `auth` → `user` import-linter contract enforces, and the same discipline should extend to any new domain.
