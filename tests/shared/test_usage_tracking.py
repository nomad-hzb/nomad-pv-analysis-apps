"""Tests for hysprint_utils.usage_tracking: where the logs go and that logging never raises."""

from pathlib import Path

import pytest

from hysprint_utils import access_token, usage_tracking


@pytest.fixture(autouse=True)
def _no_real_legacy_logs(tmp_path, monkeypatch):
    """Never let the one-time move pick up the real logs next to the installed module."""
    monkeypatch.setattr(usage_tracking, "_PACKAGE_DIR", tmp_path / "empty_package_dir")


@pytest.fixture
def log_dir(tmp_path, monkeypatch):
    folder = tmp_path / "usage"
    monkeypatch.setenv(usage_tracking.USAGE_LOG_DIR_ENV, str(folder))
    monkeypatch.setenv("NOMAD_CLIENT_USER", "alice")
    monkeypatch.setenv("VOILA_REQUEST_URL", "/voila/render/apps/JV-Analysis/jv-analysis.ipynb")
    monkeypatch.delenv("JPY_SESSION_NAME", raising=False)
    return folder


def _lines(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8").splitlines()


def test_default_folder_is_shared_usage(monkeypatch):
    monkeypatch.delenv(usage_tracking.USAGE_LOG_DIR_ENV, raising=False)
    folder = usage_tracking.usage_log_dir()
    assert folder.name == "usage"
    assert (folder.parent / "hysprint_utils" / "usage_tracking.py").is_file()
    assert not folder.exists() or folder.is_dir()  # resolving the path creates nothing


def test_notebook_usage_creates_folder_and_writes_header_once(log_dir):
    usage_tracking.log_notebook_usage()
    usage_tracking.log_notebook_usage()
    lines = _lines(log_dir / usage_tracking.NOTEBOOK_LOG)
    assert lines[0] == "Date,Time,User,App,File"
    assert len(lines) == 3
    assert lines[1].endswith(",alice,voila,jv-analysis")


def test_button_usage_writes_its_own_file(log_dir):
    usage_tracking.log_button_usage("open_project:X", user="bob")
    lines = _lines(log_dir / usage_tracking.BUTTON_LOG)
    assert lines[0] == "Date,Time,User,Action"
    assert lines[1].endswith(",bob,open_project:X")


def test_button_usage_falls_back_to_environment_user(log_dir):
    usage_tracking.log_button_usage("back_to_dashboard")
    assert _lines(log_dir / usage_tracking.BUTTON_LOG)[1].endswith(",alice,back_to_dashboard")


def test_old_log_next_to_the_module_is_moved_once(log_dir, tmp_path, monkeypatch):
    package_dir = tmp_path / "hysprint_utils"
    package_dir.mkdir()
    legacy = package_dir / usage_tracking.NOTEBOOK_LOG
    legacy.write_text(
        "Date,Time,User,App,File\n2026-01-01,10:00:00,old,voila,x\n", encoding="utf-8"
    )
    monkeypatch.setattr(usage_tracking, "_PACKAGE_DIR", package_dir)

    usage_tracking.log_notebook_usage()

    assert not legacy.exists()
    lines = _lines(log_dir / usage_tracking.NOTEBOOK_LOG)
    assert lines[:2] == ["Date,Time,User,App,File", "2026-01-01,10:00:00,old,voila,x"]
    assert len(lines) == 3


def test_logging_failure_never_raises(tmp_path, monkeypatch, caplog):
    blocker = tmp_path / "not_a_folder"
    blocker.write_text("", encoding="utf-8")
    monkeypatch.setenv(usage_tracking.USAGE_LOG_DIR_ENV, str(blocker / "usage"))
    usage_tracking.log_notebook_usage()
    usage_tracking.log_button_usage("x")
    assert "Error logging notebook usage" in caplog.text
    assert "Error logging button usage" in caplog.text


def test_access_token_still_exports_the_logging_functions():
    assert access_token.log_notebook_usage is usage_tracking.log_notebook_usage
    assert access_token.log_button_usage is usage_tracking.log_button_usage
