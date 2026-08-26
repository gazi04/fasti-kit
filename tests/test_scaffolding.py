from pathlib import Path

from scripts.create_repository import create_repository


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
