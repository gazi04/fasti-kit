default:
  @just --list

dev:
  docker-compose up -d postgres-primary postgres-replica redis mailpit dozzle caddy
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

scaffold-smoke:
  ./scripts/smoke_scaffold.sh

pre-commit:
  uv run pre-commit run --all-files

migrate message="":
  uv run alembic revision --autogenerate -m "{{message}}"
  uv run alembic upgrade head

seed:
  uv run seed --reset

docker:
  docker-compose up -d

docker-app:
  docker-compose --profile app up -d --build

compose_load := "docker compose -f docker-compose.yml -f docker-compose.loadtest.yml"
load_password := "load-test-password"

# k6 against N app replicas behind Caddy; see docs/load-testing.md
loadtest replicas="3" vus="50" duration="3m" users="100":
  {{compose_load}} --profile app up -d --build --wait --scale app={{replicas}} postgres-primary postgres-replica redis mailpit caddy prometheus app worker
  {{compose_load}} restart caddy prometheus
  {{compose_load}} run --rm --no-deps app seed --count {{users}} --password {{load_password}} --email-prefix load --force
  mkdir -p loadtest/results && chmod a+w loadtest/results
  VUS={{vus}} DURATION={{duration}} USERS={{users}} LOAD_PASSWORD={{load_password}} {{compose_load}} run --rm k6

loadtest-down:
  {{compose_load}} --profile app rm --stop --force app worker
