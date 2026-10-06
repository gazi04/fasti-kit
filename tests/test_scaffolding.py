import ast
import importlib
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest
import typer
from typer.testing import CliRunner

from scripts._boilerplate import (
    _pyproject_lists,
    format_paths,
    register_model,
    register_pyproject,
    register_router,
    update_init,
)
from scripts.create_all import generate_all
from scripts.create_dependencies import generate_dependencies
from scripts.create_domain import DOMAIN_LAYERS, generate_domain
from scripts.create_entity import create_entity
from scripts.create_factory import generate_factory
from scripts.create_migration import _check_domain_registered, _lint_migration_file
from scripts.create_repository import generate_repository
from scripts.create_test import generate_test

REPO = Path(__file__).resolve().parents[1]
WIRED_FILES = ("pyproject.toml", "core/models.py", "core/api_versions.py")


@pytest.fixture
def project(tmp_path, monkeypatch) -> Path:
    """A tmp dir holding copies of the files the generators wire domains into."""
    for name in WIRED_FILES:
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(REPO / name, target)
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _snapshot(root: Path) -> dict[str, str]:
    return {
        str(p.relative_to(root)): p.read_text()
        for p in [*sorted(root.rglob("*.py")), root / "pyproject.toml"]
        if p.is_file() and "__pycache__" not in p.parts
    }


def _defined_names(module: Path) -> set[str]:
    names: set[str] = set()
    for node in ast.parse(module.read_text()).body:
        if isinstance(node, ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            names.add(node.name)
        elif isinstance(node, ast.Assign):
            names.update(t.id for t in node.targets if isinstance(t, ast.Name))
    return names


def test_every_console_script_resolves():
    scripts = tomllib.loads((REPO / "pyproject.toml").read_text())["project"]["scripts"]
    for command, target in scripts.items():
        module_name, attr = target.split(":")
        module = importlib.import_module(module_name)
        assert callable(getattr(module, attr, None)), f"{command} -> {target}"


def test_generate_repository_matches_user_repository_pattern(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    generate_repository("scratch", "widget", "title:str")

    content = Path("scratch/repositories/widget_repository.py").read_text()

    assert "from core.database import force_primary_var" in content
    assert content.count("force_primary_var.set(True)") == 4
    assert "auto_commit: bool = True" in content
    assert "_flush_or_raise" in content
    assert "async def list(" in content
    assert "if value is None:" not in content


def test_generate_repository_fallback_fields_signature(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    generate_repository("scratch", "widget", "")

    content = Path("scratch/repositories/widget_repository.py").read_text()

    assert "self, auto_commit: bool = True, **fields" in content


def test_generate_factory_builds_real_update_values(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    generate_factory("scratch", "widget")

    content = Path("core/factories/widget_factory.py").read_text()

    assert (
        "class CreateWidgetRequestFactory(BasePydanticFactory[CreateWidgetRequest]):"
        in content
    )
    assert (
        "class UpdateWidgetRequestFactory(BasePydanticFactory[UpdateWidgetRequest]):"
        in content
    )
    assert "__allow_none_optionals__ = False" in content


def test_generate_test_writes_new_domain_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    generate_test("scratch", "widget")

    content = Path("tests/test_scratch_domain.py").read_text()

    assert "async def test_widget_repository_add_and_get(db) -> None:" in content
    assert "async def test_widget_service_force_delete(db) -> None:" in content
    assert "async def test_widget_route_create_requires_token(client)" in content
    assert "from core.factories.widget_factory import (" in content
    assert Path("core/factories/widget_factory.py").exists()


def test_generate_test_appends_to_existing_domain_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    existing = Path("tests/test_scratch_domain.py")
    existing.parent.mkdir(parents=True)
    existing.write_text(
        '"""Existing domain tests."""\n\nimport uuid\n\n\ndef test_placeholder():\n    pass\n'
    )

    generate_test("scratch", "widget")

    content = existing.read_text()
    assert "def test_placeholder():" in content
    assert "async def test_widget_repository_add_and_get(db) -> None:" in content
    assert content.count("import uuid") == 1


def test_generate_test_is_idempotent(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)

    generate_test("scratch", "widget")
    content_before = Path("tests/test_scratch_domain.py").read_text()

    generate_test("scratch", "widget")
    content_after = Path("tests/test_scratch_domain.py").read_text()

    assert content_before == content_after
    assert "skip:" in capsys.readouterr().out


def test_generate_domain_creates_layers_and_wires_pyproject(project):
    generate_domain("shop")

    for layer in DOMAIN_LAYERS:
        assert (project / "shop" / layer / "__init__.py").exists()
    assert (project / "shop" / "dependencies.py").exists()
    assert not (project / "shop" / "__init__.py").exists()

    lists = _pyproject_lists(tomllib.loads((project / "pyproject.toml").read_text()))
    expected = ["shop*", "shop", "shop", "shop", "shop", "shop", "shop.entities"]
    for value, found in zip(expected, lists, strict=True):
        assert value in found


def test_generate_domain_is_idempotent(project):
    generate_domain("shop")
    before = _snapshot(project)

    generate_domain("shop")

    assert _snapshot(project) == before


def test_register_pyproject_leaves_auth_only_contracts_alone(project):
    register_pyproject("shop")

    contracts = tomllib.loads((project / "pyproject.toml").read_text())["tool"][
        "importlinter"
    ]["contracts"]
    auth_only = [c for c in contracts if c.get("source_modules") == ["auth"]]
    assert len(auth_only) == 2


def test_register_pyproject_does_not_write_when_a_list_is_missing(project):
    pyproject = project / "pyproject.toml"
    pyproject.write_text('[project]\nname = "x"\n')

    assert register_pyproject("shop") == []
    assert pyproject.read_text() == '[project]\nname = "x"\n'


def test_register_model_and_router_are_idempotent(project):
    register_model("shop", "ProductModel")
    register_router("shop", "product_router")
    first = _snapshot(project)

    assert register_model("shop", "ProductModel") == []
    assert register_router("shop", "product_router") == []
    assert _snapshot(project) == first

    api_versions = (project / "core/api_versions.py").read_text()
    assert api_versions.count("from shop.routes import product_router") == 1
    assert api_versions.count("v1_router.include_router(product_router)") == 1


def test_register_router_without_anchor_does_not_write(project):
    api_versions = project / "core/api_versions.py"
    api_versions.write_text("x = 1\n")

    assert register_router("shop", "product_router") == []
    assert api_versions.read_text() == "x = 1\n"


def test_generate_all_writes_one_router_and_consistent_exports(project):
    generate_all("shop", "product", "title:str,price:float")

    routes = sorted(p.name for p in (project / "shop/routes").glob("*.py"))
    assert routes == ["__init__.py", "product_router.py"]

    for init in (project / "shop").glob("*/__init__.py"):
        for node in ast.parse(init.read_text()).body:
            if isinstance(node, ast.ImportFrom) and node.level == 1:
                module = init.parent / f"{node.module}.py"
                missing = {a.name for a in node.names} - _defined_names(module)
                assert not missing, f"{init} exports undefined {missing}"


def test_generate_all_output_is_lint_clean(project):
    paths = generate_all("shop", "product", "title:str,price:float,sku:uuid")
    format_paths(paths)

    for args in (["check"], ["format", "--check"]):
        result = subprocess.run(  # noqa: S603
            [sys.executable, "-m", "ruff", *args, "shop", "core"],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stdout + result.stderr


def test_generate_all_is_idempotent(project):
    format_paths(generate_all("shop", "product", "title:str"))
    first = _snapshot(project)

    format_paths(generate_all("shop", "product", "title:str"))

    assert _snapshot(project) == first


def test_generate_dependencies_merges_into_existing_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    deps = Path("shop/dependencies.py")
    deps.parent.mkdir()
    deps.write_text(
        "from fastapi import Depends, HTTPException\n\n\n"
        "def existing() -> None:\n    raise HTTPException(400)\n"
    )

    generate_dependencies("shop", "product")

    tree = ast.parse(deps.read_text())
    kinds = [type(node) for node in tree.body]
    first_function = kinds.index(ast.FunctionDef)
    assert all(k not in (ast.Import, ast.ImportFrom) for k in kinds[first_function:]), (
        "imports must stay above the functions"
    )
    functions = [n.name for n in tree.body if isinstance(n, ast.FunctionDef)]
    assert functions == ["existing", "get_product_repository", "get_product_service"]


def test_update_init_reads_back_a_ruff_formatted_file(tmp_path):
    init = tmp_path / "__init__.py"
    init.write_text(
        "from .widget_schema import (\n"
        "    CreateWidgetRequest,\n"
        "    UpdateWidgetRequest,\n"
        ")\n\n"
        "__all__ = [\n"
        '    "CreateWidgetRequest",\n'
        '    "UpdateWidgetRequest",\n'
        "]\n"
    )

    update_init(init, "gadget_schema", ["GadgetResponse"])

    content = init.read_text()
    for name in ("CreateWidgetRequest", "UpdateWidgetRequest", "GadgetResponse"):
        assert content.count(name) == 2


@pytest.mark.parametrize("domain", ["my-shop", "Shop", "1shop", "core", "main"])
def test_generate_domain_rejects_invalid_names(project, domain):
    with pytest.raises(ValueError):
        generate_domain(domain)


def test_layer_command_refuses_missing_domain(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    app = typer.Typer()
    app.command()(create_entity)

    result = CliRunner().invoke(app, ["-d", "nope", "-n", "widget", "-f", ""])

    assert result.exit_code == 1
    assert "create-domain -d nope" in result.output
    assert not Path("nope").exists()


def test_check_domain_registered_raises_when_missing():
    with pytest.raises(Exception, match=r"doesn't import scratch\.models"):
        _check_domain_registered("scratch", "from user.models import UserModel\n")


def test_check_domain_registered_passes_when_present():
    _check_domain_registered("scratch", "from scratch.models import ScratchModel\n")


def test_lint_migration_file_flags_no_changes():
    warnings = _lint_migration_file("def upgrade():\n    pass\n")
    assert any("No schema changes" in w for w in warnings)


def test_lint_migration_file_flags_drop_column_and_table():
    content = "op.drop_column('widgets', 'title')\nop.drop_table('widgets')\n"
    warnings = _lint_migration_file(content)
    assert any("Dropping a column" in w for w in warnings)
    assert any("Dropping a table" in w for w in warnings)


def test_lint_migration_file_flags_not_null_without_default():
    content = (
        'op.add_column("widgets", sa.Column("title", sa.String(), nullable=False))'
    )
    warnings = _lint_migration_file(content)
    assert any("existing rows may fail to backfill" in w for w in warnings)


def test_lint_migration_file_clean_migration_has_no_warnings():
    content = (
        'op.add_column("widgets", sa.Column("title", sa.String(), '
        'nullable=False, server_default=""))'
    )
    assert _lint_migration_file(content) == []
