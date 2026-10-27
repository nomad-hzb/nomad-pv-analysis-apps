"""bootstrap.py: the shared-install marker, the proxy log line and the tracked-tags install.

The module runs its install steps at import time, so the functions are loaded from the
source up to that tail instead of importing it.
"""

import importlib.metadata
import json
import logging
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

BOOTSTRAP = Path(__file__).resolve().parents[2] / "bootstrap.py"


class _Namespace:
    """Attribute access that reads and writes the module's globals, so monkeypatch reaches them."""

    def __init__(self, namespace):
        object.__setattr__(self, "_ns", namespace)

    def __getattr__(self, name):
        return self._ns[name]

    def __setattr__(self, name, value):
        self._ns[name] = value


@pytest.fixture
def bs(tmp_path, monkeypatch):
    source = BOOTSTRAP.read_text(encoding="utf-8").split("_local_config = _load_local_config()")[0]
    namespace = {"__file__": str(BOOTSTRAP), "__name__": "bootstrap_under_test"}
    exec(compile(source, str(BOOTSTRAP), "exec"), namespace)  # noqa: S102
    monkeypatch.setattr(namespace["tempfile"], "gettempdir", lambda: str(tmp_path))
    namespace["REPO_ROOT"] = tmp_path
    (tmp_path / "shared").mkdir()
    (tmp_path / "shared" / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
    (tmp_path / "shared" / "mod.py").write_text("x = 1\n", encoding="utf-8")
    return _Namespace(namespace)


def test_shared_install_runs_once_then_is_skipped(bs, monkeypatch):
    calls = []
    monkeypatch.setattr(bs, "_pip_install", lambda target: calls.append(target) or (0, ""))
    bs._install_shared()
    bs._install_shared()
    assert len(calls) == 1


def test_shared_install_reruns_when_shared_changes(bs, monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(bs, "_pip_install", lambda target: calls.append(target) or (0, ""))
    bs._install_shared()
    (tmp_path / "shared" / "mod.py").write_text("x = 2\n", encoding="utf-8")
    bs._install_shared()
    assert len(calls) == 2


def test_failed_shared_install_writes_no_marker(bs, monkeypatch):
    calls = []
    monkeypatch.setattr(bs, "_pip_install", lambda target: calls.append(target) or (1, "boom"))
    monkeypatch.setattr(bs.importlib.util, "find_spec", lambda name: object())
    bs._install_shared()
    bs._install_shared()
    assert len(calls) == 2


def test_marker_hit_still_puts_shared_on_sys_path(bs, monkeypatch, tmp_path):
    monkeypatch.setattr(bs, "_pip_install", lambda target: (0, ""))
    bs._install_shared()
    monkeypatch.setattr(bs.sys, "path", [p for p in bs.sys.path if p != str(tmp_path / "shared")])
    bs._install_shared()
    assert bs.sys.path[0] == str(tmp_path / "shared")


def test_http_proxy_only_does_not_raise(bs, monkeypatch, caplog):
    for key in ("HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("HYSPRINT_URL_BASE", "https://other.example.org")
    with caplog.at_level(logging.INFO):
        bs._apply_proxy_env({"HTTP_PROXY": "http://proxy.example.org:3128"})
    assert "http://proxy.example.org:3128" in caplog.text


# =============================================================================
# Tracked tags: _newest_tag, _installed_tag, _read_track_tags, _install_tracked_tags
# =============================================================================

URL = "https://git.example.org/insitu_analyser.git"


def _ls_remote(monkeypatch, bs, tags, returncode=0, stderr=""):
    """Answer `git ls-remote --tags --refs` with *tags*; returns the recorded calls."""
    calls = []

    def run(args, **kwargs):
        calls.append((args, kwargs))
        stdout = "".join(f"{n:040x}\trefs/tags/{tag}\n" for n, tag in enumerate(tags))
        return SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)

    monkeypatch.setattr(bs.subprocess, "run", run)
    return calls


@pytest.mark.parametrize("series", ["", "v0.2"])
def test_newest_tag_orders_numerically(bs, monkeypatch, series):
    _ls_remote(monkeypatch, bs, ["v0.2.9", "v0.2.10", "v0.2.2"])
    assert bs._newest_tag(URL, series) == "v0.2.10"


def test_newest_tag_without_series_picks_the_newest_line(bs, monkeypatch):
    _ls_remote(monkeypatch, bs, ["v0.1.65", "v0.2.18", "v0.3.0", "v0.2.20"])
    assert bs._newest_tag(URL) == "v0.3.0"


def test_newest_tag_ignores_other_series_and_non_release_tags(bs, monkeypatch):
    _ls_remote(monkeypatch, bs, ["v0.2.1", "v0.3.0", "v0.2", "v0.2.0-rc1", "v0.20.1", "latest"])
    assert bs._newest_tag(URL, "v0.2") == "v0.2.1"


def test_newest_tag_without_series_ignores_non_release_tags(bs, monkeypatch):
    _ls_remote(monkeypatch, bs, ["v0.2.1", "v0.3.0-rc1", "release-9", "0.9.0", "latest"])
    assert bs._newest_tag(URL) == "v0.2.1"


@pytest.mark.parametrize("series", ["", "v0.4"])
def test_newest_tag_none_without_matching_tag(bs, monkeypatch, series):
    _ls_remote(monkeypatch, bs, ["v0.2.1-rc1", "v0.3.0-rc1", "latest"])
    assert bs._newest_tag(URL, series) is None


def test_newest_tag_four_numbers_is_newer(bs, monkeypatch):
    _ls_remote(monkeypatch, bs, ["v0.2.7", "v0.2.7.1", "v0.2.6.9"])
    assert bs._newest_tag(URL, "v0.2") == "v0.2.7.1"


def test_newest_tag_uses_the_short_timeout(bs, monkeypatch):
    calls = _ls_remote(monkeypatch, bs, ["v0.2.1"])
    bs._newest_tag(URL)
    (args, kwargs) = calls[0]
    assert args == ["git", "ls-remote", "--tags", "--refs", URL]
    assert kwargs["timeout"] == bs.GIT_LS_REMOTE_TIMEOUT_S <= 10


def test_newest_tag_git_error_warns(bs, monkeypatch, caplog):
    _ls_remote(monkeypatch, bs, [], returncode=128, stderr="fatal: unable to access")
    with caplog.at_level(logging.WARNING):
        assert bs._newest_tag(URL) is None
    assert "unable to access" in caplog.text


@pytest.mark.parametrize(
    "error", [OSError("git not found"), subprocess.TimeoutExpired(["git"], 10)]
)
def test_newest_tag_missing_git_or_timeout_warns(bs, monkeypatch, caplog, error):
    def run(*args, **kwargs):
        raise error

    monkeypatch.setattr(bs.subprocess, "run", run)
    with caplog.at_level(logging.WARNING):
        assert bs._newest_tag(URL) is None
    assert "could not list the tags" in caplog.text


def _distributions(monkeypatch, bs, installed):
    """importlib.metadata.distribution answering from {name: direct_url.json text or None}."""

    def distribution(name):
        if name not in installed:
            raise importlib.metadata.PackageNotFoundError(name)
        return SimpleNamespace(read_text=lambda filename: installed[name])

    monkeypatch.setattr(bs.importlib.metadata, "distribution", distribution)


def test_installed_tag_reads_requested_revision(bs, monkeypatch):
    record = {"url": URL, "vcs_info": {"vcs": "git", "requested_revision": "v0.2.18"}}
    _distributions(monkeypatch, bs, {"insitu_analyser": json.dumps(record)})
    assert bs._installed_tag("insitu_analyser") == "v0.2.18"


def test_installed_tag_editable(bs, monkeypatch):
    record = {"url": "file:///d/insitu_analyser", "dir_info": {"editable": True}}
    _distributions(monkeypatch, bs, {"insitu_analyser": json.dumps(record)})
    assert bs._installed_tag("insitu_analyser") == "editable"


def test_installed_tag_none_when_missing_or_not_a_url_install(bs, monkeypatch):
    _distributions(monkeypatch, bs, {})
    assert bs._installed_tag("insitu_analyser") is None
    _distributions(monkeypatch, bs, {"insitu_analyser": None})  # a PyPI install
    assert bs._installed_tag("insitu_analyser") is None


@pytest.mark.parametrize("dist_name", ["insitu_analyser", "insitu-analyser"])
def test_installed_tag_finds_either_spelling(bs, monkeypatch, dist_name):
    record = {"url": URL, "vcs_info": {"vcs": "git", "requested_revision": "v0.2.18"}}
    _distributions(monkeypatch, bs, {dist_name: json.dumps(record)})
    assert bs._installed_tag("insitu_analyser") == "v0.2.18"


def test_read_track_tags(bs, tmp_path):
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        "[project]\nname = 'x'\n\n[tool.hysprint.track-tags]\n"
        f'insitu_analyser = {{ url = "{URL}" }}\n'
        f'other = {{ url = "{URL}", series = "v1.4" }}\n',
        encoding="utf-8",
    )
    assert bs._read_track_tags(pyproject) == {
        "insitu_analyser": {"url": URL},
        "other": {"url": URL, "series": "v1.4"},
    }
    pyproject.write_text("[project]\nname = 'x'\n", encoding="utf-8")
    assert bs._read_track_tags(pyproject) == {}


@pytest.fixture
def app(bs, monkeypatch, tmp_path):
    """An app directory as cwd, with the network-facing helpers recorded instead of run."""
    app_dir = tmp_path / "app"
    app_dir.mkdir()
    monkeypatch.setattr(bs.Path, "cwd", lambda: app_dir)
    state = SimpleNamespace(dir=app_dir, newest={}, installed={}, pip_exit={}, lookups=[], pips=[])

    def newest_tag(url, series=""):
        state.lookups.append((url, series))
        return state.newest.get(url)

    def pip_install(target):
        state.pips.append(target)
        return state.pip_exit.get(target, 0), "pip output"

    monkeypatch.setattr(bs, "_newest_tag", newest_tag)
    monkeypatch.setattr(bs, "_installed_tag", lambda name: state.installed.get(name))
    monkeypatch.setattr(bs, "_pip_install", pip_install)

    def write(entries):
        lines = "".join(f"{name} = {entry}\n" for name, entry in entries.items())
        (app_dir / "pyproject.toml").write_text(
            f"[project]\nname = 'app'\n\n[tool.hysprint.track-tags]\n{lines}", encoding="utf-8"
        )

    state.write = write
    return state


def test_install_tracked_tags_installs_a_newer_tag(bs, app):
    app.write({"insitu_analyser": f'{{ url = "{URL}" }}'})
    app.installed["insitu_analyser"] = "v0.2.18"
    app.newest[URL] = "v0.3.0"
    bs._install_tracked_tags()
    assert app.lookups == [(URL, "")]
    assert app.pips == [f"insitu_analyser @ git+{URL}@v0.3.0"]


def test_install_tracked_tags_passes_the_series(bs, app):
    app.write({"insitu_analyser": f'{{ url = "{URL}", series = "v0.2" }}'})
    app.newest[URL] = "v0.2.18"
    bs._install_tracked_tags()
    assert app.lookups == [(URL, "v0.2")]
    assert app.pips == [f"insitu_analyser @ git+{URL}@v0.2.18"]


def test_install_tracked_tags_up_to_date_does_not_install(bs, app):
    app.write({"insitu_analyser": f'{{ url = "{URL}" }}'})
    app.installed["insitu_analyser"] = app.newest[URL] = "v0.2.18"
    bs._install_tracked_tags()
    assert app.pips == []


def test_install_tracked_tags_leaves_an_editable_install_alone(bs, app):
    app.write({"insitu_analyser": f'{{ url = "{URL}" }}'})
    app.installed["insitu_analyser"] = "editable"
    app.newest[URL] = "v0.3.0"
    bs._install_tracked_tags()
    assert app.lookups == []
    assert app.pips == []


def test_install_tracked_tags_unreachable_remote_keeps_the_installed_version(bs, app, caplog):
    app.write({"insitu_analyser": f'{{ url = "{URL}" }}'})
    app.installed["insitu_analyser"] = "v0.2.18"
    with caplog.at_level(logging.WARNING):
        bs._install_tracked_tags()
    assert app.pips == []
    assert "keeping v0.2.18" in caplog.text


def test_install_tracked_tags_failed_pip_warns_and_continues(bs, app, caplog):
    other_url = "https://git.example.org/other.git"
    app.write({"insitu_analyser": f'{{ url = "{URL}" }}', "other": f'{{ url = "{other_url}" }}'})
    app.newest.update({URL: "v0.3.0", other_url: "v1.0.0"})
    app.pip_exit[f"insitu_analyser @ git+{URL}@v0.3.0"] = 1
    with caplog.at_level(logging.WARNING):
        bs._install_tracked_tags()
    assert app.pips == [f"insitu_analyser @ git+{URL}@v0.3.0", f"other @ git+{other_url}@v1.0.0"]
    assert "could not install insitu_analyser v0.3.0" in caplog.text


def test_install_tracked_tags_skips_an_entry_without_url(bs, app, caplog):
    app.write({"broken": '{ series = "v0.2" }', "insitu_analyser": f'{{ url = "{URL}" }}'})
    app.newest[URL] = "v0.3.0"
    with caplog.at_level(logging.WARNING):
        bs._install_tracked_tags()
    assert app.pips == [f"insitu_analyser @ git+{URL}@v0.3.0"]
    assert "broken has no url" in caplog.text


def test_install_tracked_tags_broken_toml_warns(bs, app, caplog):
    (app.dir / "pyproject.toml").write_text("[tool.hysprint.track-tags\n", encoding="utf-8")
    with caplog.at_level(logging.WARNING):
        bs._install_tracked_tags()
    assert app.lookups == app.pips == []
    assert "could not read [tool.hysprint.track-tags]" in caplog.text


def test_install_tracked_tags_without_table_or_pyproject_does_nothing(bs, app):
    bs._install_tracked_tags()  # no pyproject.toml
    (app.dir / "pyproject.toml").write_text("[project]\nname = 'nmr'\n", encoding="utf-8")
    bs._install_tracked_tags()  # an app without track-tags, e.g. NMR_Analysis
    assert app.lookups == app.pips == []


def test_container_no_proxy_is_kept(bs, monkeypatch):
    for key in ("HTTP_PROXY", "HTTPS_PROXY"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.delenv("HYSPRINT_URL_BASE", raising=False)
    monkeypatch.setenv("NO_PROXY", "oasis.example.org,localhost")
    bs._apply_proxy_env({})
    assert bs.os.environ["NO_PROXY"] == "oasis.example.org,localhost"
    assert bs.os.environ["HTTPS_PROXY"] == bs.HZB_SE_PROXY
