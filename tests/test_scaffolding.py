import subprocess
from pathlib import Path

import pytest

from scripts.create_factory import create_factory
from scripts.create_migration import _check_domain_registered, _lint_migration_file
from scripts.create_repository import create_repository
from scripts.create_test import create_test


def test_create_repository_matches_user_repository_pattern(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    create_repository(domain="scratch", name="widget", fields="title:str")

    content = Path("scratch/repositories/widget_repository.py").read_text()

    assert "from core.database import force_primary_var" in content
    assert content.count("force_primary_var.set(True)") == 4
    assert "auto_commit: bool = True" in content
    assert "_flush_or_raise" in content
    assert "if value is None:" not in content


def test_create_repository_fallback_fields_signature(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    create_repository(domain="scratch", name="widget", fields="")

    content = Path("scratch/repositories/widget_repository.py").read_text()

    assert "self, auto_commit: bool = True, **fields" in content


def test_create_factory_matches_user_factory_pattern(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    create_factory(domain="scratch", name="widget")

    content = Path("core/factories/widget_factory.py").read_text()

    assert (
        "class CreateWidgetRequestFactory(BasePydanticFactory[CreateWidgetRequest]):"
        in content
    )
    assert (
        "class UpdateWidgetRequestFactory(BasePydanticFactory[UpdateWidgetRequest]):"
        in content
    )
    assert content.count("__use_defaults__ = True") == 2


def _stub_run(*args, **kwargs):
    return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")


def test_create_test_writes_new_domain_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("scripts.create_test.subprocess.run", _stub_run)

    create_test(domain="scratch", name="widget")

    content = Path("tests/test_scratch_domain.py").read_text()

    assert "async def test_widget_repository_add_and_get(db) -> None:" in content
    assert "async def test_widget_service_force_delete(db) -> None:" in content
    assert "from core.factories.widget_factory import (" in content
    assert Path("core/factories/widget_factory.py").exists()


def test_create_test_appends_to_existing_domain_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("scripts.create_test.subprocess.run", _stub_run)

    existing = Path("tests/test_scratch_domain.py")
    existing.parent.mkdir(parents=True)
    existing.write_text(
        '"""Existing domain tests."""\n\nimport uuid\n\n\ndef test_placeholder():\n    pass\n'
    )

    create_test(domain="scratch", name="widget")

    content = existing.read_text()
    assert "def test_placeholder():" in content
    assert "async def test_widget_repository_add_and_get(db) -> None:" in content
    assert content.count("import uuid") == 1


def test_create_test_is_idempotent(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("scripts.create_test.subprocess.run", _stub_run)

    create_test(domain="scratch", name="widget")
    content_before = Path("tests/test_scratch_domain.py").read_text()

    create_test(domain="scratch", name="widget")
    content_after = Path("tests/test_scratch_domain.py").read_text()

    assert content_before == content_after
    assert "skip:" in capsys.readouterr().out


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
