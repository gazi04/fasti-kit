#!/usr/bin/env bash
set -euo pipefail

sudo chown vscode:vscode .venv

uv sync --all-groups

if grep -q '^JWT_SECRET_KEY=$' .env; then
    sed -i "s|^JWT_SECRET_KEY=$|JWT_SECRET_KEY=$(openssl rand -hex 32)|" .env
fi

uv run python - <<'PY' || echo "WARNING: could not create fasti_kit_test; create it manually before running pytest" >&2
import asyncio
import os

import asyncpg


async def main() -> None:
    conn = await asyncpg.connect(os.environ["DATABASE_URL"].replace("+asyncpg", ""))
    try:
        exists = await conn.fetchval(
            "SELECT 1 FROM pg_database WHERE datname = 'fasti_kit_test'"
        )
        if not exists:
            await conn.execute("CREATE DATABASE fasti_kit_test")
    finally:
        await conn.close()


asyncio.run(main())
PY

uv run alembic upgrade head

uv run pre-commit install

uv tool install rust-just
uv tool update-shell
