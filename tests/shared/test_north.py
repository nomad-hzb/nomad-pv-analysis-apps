import os

from hysprint_utils import north


def _cwd(monkeypatch, path):
    monkeypatch.setattr(os, "getcwd", lambda: path)


def test_unpacked_repo(monkeypatch):
    _cwd(monkeypatch, "/home/jovyan/uploads/up123/apps/Global_analyzer")
    assert north.get_upload_id() == "up123"
    assert north.get_uploads_path() == "uploads/up123/apps"


def test_git_cloned_repo_keeps_the_repo_folder(monkeypatch):
    """The fixed-depth walk used to return 'nomad-pv-analysis-apps' as the upload id."""
    _cwd(monkeypatch, "/home/jovyan/uploads/up123/nomad-pv-analysis-apps/apps/Global_analyzer")
    assert north.get_upload_id() == "up123"
    assert north.get_uploads_path() == "uploads/up123/nomad-pv-analysis-apps/apps"


def test_upload_named_uploads_does_not_shadow_the_mount(monkeypatch):
    _cwd(monkeypatch, "/home/jovyan/uploads/uploads/apps/Global_analyzer")
    assert north.get_upload_id() == "uploads"
    assert north.get_uploads_path() == "uploads/uploads/apps"


def test_windows_separators(monkeypatch):
    _cwd(monkeypatch, r"C:\home\jovyan\uploads\up123\apps\Global_analyzer")
    assert north.get_uploads_path() == "uploads/up123/apps"


def test_outside_an_uploads_mount_falls_back(monkeypatch):
    _cwd(monkeypatch, "/work/repo/apps/Global_analyzer")
    assert north.get_upload_id() == "repo"
    assert north.get_uploads_path() == "uploads/repo/apps"


def test_get_current_user(monkeypatch):
    monkeypatch.delenv("NOMAD_CLIENT_USER", raising=False)
    assert north.get_current_user() == ""
    monkeypatch.setenv("NOMAD_CLIENT_USER", "jdoe")
    assert north.get_current_user() == "jdoe"
