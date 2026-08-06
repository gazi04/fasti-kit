default:
    @just --list

dev:
    uv run uvicorn core.main:app --reload

lint:
    uv run ruff check .
    uv run pyright

format:
    uv run ruff format .

test:
    uv run pytest --cov

pre-commit:
    uv run pre-commit run --all-files

migrate message="":
    uv run alembic revision --autogenerate -m "{{message}}"
    uv run alembic upgrade head
