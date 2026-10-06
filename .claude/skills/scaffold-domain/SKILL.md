---
name: scaffold-domain
description: Scaffold a new fasti-kit domain end to end — run the create-domain/create-all CLI (which wires the domain into core/models.py, core/api_versions.py and every pyproject.toml list itself), generate and review the migration, then verify with lint-imports, pyright and the generated tests. Use when the user asks to add/create/scaffold a new domain or entity, e.g. "add a billing domain", "scaffold a new domain called X".
---

# Scaffold a new domain

The `uv run create-domain`/`uv run create-all` CLI (see `scripts/`) generates a domain's files **and** wires them in. This skill covers the full loop: generate → migrate → verify.

## Process

1. **Ask/confirm scope if not given**: domain name (lowercase snake_case, not one of `alembic`, `core`, `docs`, `main`, `scripts`, `tests`), first entity name + fields (`name:type` pairs, e.g. `price:float,is_active:bool=True` — see `scripts/_boilerplate.py`'s `parse_fields` for supported types: `str`, `int`, `float`, `bool`, `uuid`).
2. **Generate** (flags only — the commands take no positional args):
   ```bash
   uv run create-domain -d <domain>
   uv run create-all -d <domain> -n <entity> -f "<fields>"
   ```
   Repeat `create-all` for more entities in the same domain. Both commands are idempotent, so re-running is safe. Single-layer commands (`create-entity`, `create-model`, `create-repository`, `create-schema`, `create-service`, `create-route`, `create-dependencies`) exist for adding one piece to a domain that already exists.
3. **Check the wiring the CLI did** (`git diff`), don't redo it:
   - `core/models.py` imports the new model (Alembic sees the table).
   - `core/api_versions.py` imports and mounts `<entity>_router`.
   - `pyproject.toml` lists the domain in setuptools `include`, ruff `known-first-party`, coverage `source`, deptry `known_first_party`, import-linter `root_packages`, the `"DDD layers one-way"` `containers`, and `<domain>.entities` in the `"entities stay DB-agnostic"` contract.
   If the CLI printed a "Couldn't wire … automatically" warning, apply the lines it printed by hand.
4. **Generate the migration**:
   ```bash
   uv run create-migration -m "add <domain> <entity> table" -d <domain>
   ```
   Review the generated migration file before applying — autogenerate can miss things or generate spurious diffs.
5. **Verify**:
   ```bash
   uv run create-test -d <domain> -n <entity>   # repository/service/route tests; exits non-zero on failure
   uv run lint-imports                           # layering is enforced for the new domain
   uv run pyright
   ```
6. **Report** what was generated and wired, and remind the user that `docs/README.md`'s per-topic guides are opt-in — only add one if the domain has a non-obvious design decision worth recording (this skill does not create docs by default).

## What the generated code already does

- Routes: `/create`, `/get/{id}`, `/update/{id}`, `/delete/{id}`, cursor-paginated `/list`. Create/update/delete require an access token via `auth.token_required`; get/list are public. Tighten with `require_scopes(...)` from `auth/dependencies.py` if the domain needs it.
- Routes get the service from `<domain>/dependencies.py` (`get_<entity>_service`), never by constructing `Service(Repository(db))` inline.
- Repositories pin `force_primary_var` on writes, take `auto_commit`, and flush through the `_flush_or_raise` savepoint.

## Common follow-ups (do only if asked)

- Rate limiting: `@limiter.limit("N/period")` from `core/limiter.py`, applied under the route decorator.
- Cross-domain reads (e.g. a new domain needing user data): go through the other domain's repository (e.g. `UserRepository`), never its routes/services/models directly — that's what the `auth` → `user` import-linter contract enforces, and the same discipline should extend to any new domain.
