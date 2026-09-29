tailwind_version := "4.3.3"

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

tailwind-install:
  #!/usr/bin/env bash
  set -euo pipefail
  if [ -x web/tailwindcss ] && web/tailwindcss --help 2>&1 | grep -q "v{{tailwind_version}}"; then
    echo "web/tailwindcss v{{tailwind_version}} already installed"
    exit 0
  fi
  case "{{arch()}}" in
    x86_64) cpu=x64 ;;
    aarch64) cpu=arm64 ;;
    *) echo "unsupported architecture: {{arch()}}" >&2; exit 1 ;;
  esac
  case "{{os()}}" in
    linux|macos) ;;
    *) echo "unsupported OS: {{os()}} (use WSL on Windows)" >&2; exit 1 ;;
  esac
  asset="tailwindcss-{{os()}}-$cpu"
  base="https://github.com/tailwindlabs/tailwindcss/releases/download/v{{tailwind_version}}"
  tmp="$(mktemp)"
  trap 'rm -f "$tmp"' EXIT
  curl -fsSL "$base/$asset" -o "$tmp"
  expected="$(curl -fsSL "$base/sha256sums.txt" | awk -v f="./$asset" '$2 == f {print $1}')"
  actual="$( (sha256sum "$tmp" 2>/dev/null || shasum -a 256 "$tmp") | awk '{print $1}')"
  if [ -z "$expected" ] || [ "$expected" != "$actual" ]; then
    echo "checksum mismatch for $asset" >&2
    exit 1
  fi
  install -m 755 "$tmp" web/tailwindcss
  echo "installed web/tailwindcss v{{tailwind_version}} ($asset)"

css:
  web/tailwindcss -i web/static/src.css -o web/static/app.css --minify

css-watch:
  web/tailwindcss -i web/static/src.css -o web/static/app.css --minify --watch
