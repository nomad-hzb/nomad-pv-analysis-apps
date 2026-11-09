"""The local token file (nomad_secrets.py, or the old secrets.py): read as data, nearest first,
never past the repo root."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "shared"))

from hysprint_utils import access_token  # noqa: E402


def _checkout(tmp_path):
    """A fake checkout: tmp_path/repo (with bootstrap.py) and an app folder inside it."""
    repo = tmp_path / "repo"
    app = repo / "apps" / "Some_App"
    app.mkdir(parents=True)
    (repo / "bootstrap.py").write_text("", encoding="utf-8")
    return repo, app


def test_reads_the_token_without_running_the_file(tmp_path, monkeypatch):
    repo, app = _checkout(tmp_path)
    (repo / "nomad_secrets.py").write_text(
        'import os\nos.environ["PWNED"] = "1"\nraise SystemExit\nNOMAD_TOKEN = " tok "\n',
        encoding="utf-8",
    )
    monkeypatch.chdir(app)
    monkeypatch.delenv("PWNED", raising=False)
    assert access_token._load_token_from_secrets_file() == "tok"
    assert "PWNED" not in __import__("os").environ


def test_new_name_wins_and_the_old_name_still_works_with_a_warning(tmp_path, monkeypatch, caplog):
    repo, app = _checkout(tmp_path)
    monkeypatch.chdir(app)
    (repo / "secrets.py").write_text('NOMAD_TOKEN = "old"\n', encoding="utf-8")
    with caplog.at_level("WARNING"):
        assert access_token._load_token_from_secrets_file() == "old"
    assert "please rename it to nomad_secrets.py" in caplog.text

    (repo / "nomad_secrets.py").write_text('NOMAD_TOKEN = "new"\n', encoding="utf-8")
    assert access_token._load_token_from_secrets_file() == "new"


def test_nearest_file_wins(tmp_path, monkeypatch):
    repo, app = _checkout(tmp_path)
    (repo / "nomad_secrets.py").write_text('NOMAD_TOKEN = "root"\n', encoding="utf-8")
    (app / "nomad_secrets.py").write_text('NOMAD_TOKEN = "app"\n', encoding="utf-8")
    monkeypatch.chdir(app)
    assert access_token._load_token_from_secrets_file() == "app"


def test_search_stops_at_the_repo_root(tmp_path, monkeypatch):
    _repo, app = _checkout(tmp_path)
    (tmp_path / "nomad_secrets.py").write_text('NOMAD_TOKEN = "outside"\n', encoding="utf-8")
    monkeypatch.chdir(app)
    assert access_token._load_token_from_secrets_file() is None


def test_outside_a_checkout_only_the_current_folder_counts(tmp_path, monkeypatch):
    here = tmp_path / "a" / "b"
    here.mkdir(parents=True)
    (tmp_path / "nomad_secrets.py").write_text('NOMAD_TOKEN = "far"\n', encoding="utf-8")
    monkeypatch.chdir(here)
    assert access_token._load_token_from_secrets_file() is None
    (here / "nomad_secrets.py").write_text('NOMAD_TOKEN = "here"\n', encoding="utf-8")
    assert access_token._load_token_from_secrets_file() == "here"


def test_unusable_files_warn_instead_of_failing_silently(tmp_path, monkeypatch, caplog):
    repo, app = _checkout(tmp_path)
    monkeypatch.chdir(app)
    (app / "nomad_secrets.py").write_text("NOMAD_TOKEN = (\n", encoding="utf-8")
    no_literal = "OTHER = 1\nNOMAD_TOKEN = some_call()\n"
    (repo / "nomad_secrets.py").write_text(no_literal, encoding="utf-8")
    with caplog.at_level("WARNING"):
        assert access_token._load_token_from_secrets_file() is None
    assert "Could not read the token file" in caplog.text
    assert 'has no NOMAD_TOKEN = "..." line' in caplog.text
