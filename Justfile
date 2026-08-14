default:
  @just --list

dev:
  docker-compose up -d postgres redis mailpit dozzle caddy
  uv run uvicorn main:app --reload --host 0.0.0.0 --port 8000

worker:
  uv run watchfiles "saq core.worker.main.settings" core/ user/ auth/

lint path=".":
  uv run ruff check {{path}}
  uv run pyright {{path}}

lint-fix path=".":
  uv run ruff check --fix {{path}}

format path=".":
  uv run ruff format {{path}}

test:
  uv run python -m pytest --cov

pre-commit:
  uv run pre-commit run --all-files

migrate message="":
  uv run alembic revision --autogenerate -m "{{message}}"
  uv run alembic upgrade head

seed:
  uv run seed --reset

docker:
  docker-compose up -d
