---
name: write-repo-method
description: Write a new repository method in a fasti-kit domain, following UserRepository's conventions — entity conversion, replica/primary routing, error translation, cursor pagination. Use when the user asks to add a repository method, query, or DB access function.
---

# Write a repository method

Ground truth reference: `user/repositories/user_repository.py`.

## Shape

```python
class <Domain>Repository:
    def __init__(self, db) -> None:
        self.db: AsyncSession = db

    async def <verb>(self, ...) -> <Entity> | None:
        ...

    @staticmethod
    def _to_entity(model: <Model>) -> <Entity>:
        return <Entity>(...)
```

- Constructor takes the `AsyncSession` — never opens its own session (that's what `core.database.get_db`/`AsyncSessionLocal` are for at the dependency-injection boundary).
- **Always return entities, never SQLAlchemy models**, to callers — convert via `_to_entity` (a `@staticmethod`) right before returning. Callers (services, routes) must never import the domain's `models` module.
- Return `None` for "not found" on lookups/mutations of a specific id — don't raise. Let the service/route layer decide whether "not found" is a 404, a no-op, or something else.

## Replica/primary routing

With the `read_replica` add-on (`core/replica/routing.py`), plain `SELECT`s go to the replica, writes go to the primary, and once a session writes, every later read in it stays on the primary. Repositories never pin by hand:
- Put every write, and the read it depends on (e.g. the `db.get` before an update), inside `async with transaction(self.db):`. `transaction()` runs its body on the primary.
- A read that must see the latest committed row without a transaction (e.g. `RevokedTokenRepository.exists`) goes in `with use_primary(self.db):`, imported from `core.database`.
- A consistent lookup that should also hand its connection back takes `consistent=True` and runs in its own `transaction()` (see `UserRepository._find`).

Without the add-on, both helpers still work: `use_primary` is a no-op and there is one engine.

## Error translation

Wrap commits that can hit a DB constraint in a helper that translates `IntegrityError` into something callers can act on without importing SQLAlchemy:

```python
async def _commit_or_raise(self) -> None:
    try:
        await self.db.commit()
    except IntegrityError as err:
        await self.db.rollback()
        if "email" in str(err.orig).lower():
            raise ValueError("Email taken") from err
        raise
```
Match this pattern (inspect `err.orig` for the constraint that fired) rather than letting a raw `IntegrityError` propagate to the service layer.

## Soft vs hard delete

If the entity has an `is_active` flag, default to soft delete (`user.is_active = False`, commit, return the entity) and offer a separate `force_delete` that actually `db.delete(...)`s the row — see `delete`/`force_delete` in `UserRepository`. Don't silently hard-delete unless the domain has no active/inactive concept.

## Cursor pagination (list endpoints)

Use `fastapi-pagination`'s `apaginate` + `sqlakeyset`, not hand-rolled offset pagination:

```python
async def list(self, params: CursorParams | None = None) -> CursorPage[<Entity>]:
    return await apaginate(
        self.db,
        select(<Model>).order_by(<Model>.created_at.desc(), <Model>.id.desc()),
        params=params or CursorParams(),
        transformer=lambda models: [self._to_entity(m) for m in models],
    )
```
The `order_by` must end in a unique tiebreaker column (`.id.desc()` after the primary sort) — cursor pagination breaks silently without one. `created_at DESC, id DESC` is the established default across this codebase; keep it unless the caller has a specific reason to sort differently.

## Verify

```bash
uv run pyright
uv run lint-imports   # confirms nothing outside repositories/ imports this domain's models
```
Then write/extend tests per the `write-test` skill — repository methods are tested directly against a real transactional `db` fixture, not mocked.
