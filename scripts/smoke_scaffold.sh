#!/usr/bin/env bash
# Generate a throwaway domain in a copy of the project and prove it boots,
# passes every quality gate, and that re-running the generator changes nothing.
# Runs against the real test database, so Postgres and Redis must be up.
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
BIN="$REPO/.venv/bin"
PY="$BIN/python"
WORK="$(mktemp -d)"
TMP="$WORK/project"
trap 'rm -rf "$WORK"' EXIT

step() { printf '\n==> %s\n' "$1"; }

step "Copy project to $TMP"
mkdir -p "$TMP"
(cd "$REPO" && git ls-files --cached --others --exclude-standard -z \
  | xargs -0 cp -P --parents -t "$TMP")
[ -f "$REPO/.env" ] && cp "$REPO/.env" "$TMP/.env"
for f in pyproject.toml core/models.py core/api_versions.py; do
  cp "$TMP/$f" "$TMP/$f.orig"
done

cd "$TMP"
export PYTHONPATH="$TMP"

step "Generate shop/product"
"$PY" -m scripts.create_domain -d shop
"$PY" -m scripts.create_all -d shop -n product -f "title:str,price:float"

step "App imports and mounts the generated routes"
"$PY" - <<'PY'
import main

paths = set(main.app.openapi()["paths"])
expected = {
    "/api/v1/product/create",
    "/api/v1/product/get/{id}",
    "/api/v1/product/update/{id}",
    "/api/v1/product/delete/{id}",
    "/api/v1/product/list",
}
missing = expected - paths
assert not missing, f"routes not mounted: {sorted(missing)}"
PY

step "Wiring only touched the expected lines"
"$PY" - <<'PY'
import difflib
from pathlib import Path

expected_removed = {"pyproject.toml": 7, "core/models.py": 0, "core/api_versions.py": 0}
for name, removed in expected_removed.items():
    before = Path(f"{name}.orig").read_text().splitlines()
    after = Path(name).read_text().splitlines()
    diff = list(difflib.unified_diff(before, after, lineterm="", n=0))
    added = [l for l in diff if l.startswith("+") and not l.startswith("+++")]
    gone = [l for l in diff if l.startswith("-") and not l.startswith("---")]
    assert added and all("shop" in l or "product" in l for l in added), f"{name}: unexpected {added}"
    assert len(gone) == removed, f"{name}: expected {removed} replaced lines, got {gone}"
PY
rm pyproject.toml.orig core/models.py.orig core/api_versions.py.orig

step "ruff, pyright, import-linter, deptry"
"$BIN/ruff" check .
"$BIN/ruff" format --check .
"$BIN/pyright" --pythonpath "$PY" shop
"$BIN/lint-imports"
"$BIN/deptry" .

step "Generated tests pass"
"$PY" -m scripts.create_test -d shop -n product

step "Re-running create-all changes nothing"
cp -a "$TMP" "$WORK/snapshot"
"$PY" -m scripts.create_all -d shop -n product -f "title:str,price:float"
diff -r --no-dereference -x __pycache__ -x .ruff_cache -x .pytest_cache "$WORK/snapshot" "$TMP"

step "Scaffolding smoke test passed"
