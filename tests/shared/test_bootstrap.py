"""bootstrap.py: the shared-install marker and the proxy log line.

The module runs its install steps at import time, so the functions are loaded from the
source up to that tail instead of importing it.
"""

import logging
from pathlib import Path

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
