"""Monorepo-wide pytest configuration.

The repo root has its own ``secrets.py`` (used by
``hysprint_utils.access_token.get_token()`` for the local-login fallback).
When pytest is invoked from the repo root, Python's default sys.path[0]
(the empty string, meaning "current directory") lets that file shadow the
stdlib ``secrets`` module for every test. Recent numpy/plotly versions
import ``secrets.randbits``/``secrets.token_hex`` internally, so without this
guard almost any test that touches pandas, numpy, or plotly fails with
``ImportError: cannot import name 'randbits'/'token_hex' from 'secrets'``.

Strip the repo-root entry before any test module (and therefore any
app's data_manager/plot_manager) gets imported, so the real stdlib
``secrets`` resolves normally. This never touches secrets.py itself or its
walk-up discovery in get_token(), which is Path-based, not sys.path-based.
"""

import sys
from pathlib import Path

_REPO_ROOT = str(Path(__file__).resolve().parent.parent)

for _entry in ("", _REPO_ROOT):
    while _entry in sys.path:
        sys.path.remove(_entry)


# ---------------------------------------------------------------------------
# One process, many apps: keep each app's bare module names pointing at that app
# ---------------------------------------------------------------------------
# Every app names its modules data_manager, plot_manager, gui_components, ... (rule 3),
# and each tests/<App>/conftest.py registers its own under those bare names. In a run
# that spans several apps the last conftest wins, so string patch targets
# ("data_manager.requests.get") and imports done inside functions would hit another
# app's module. The hooks below record which module objects belong to which app while
# collecting, and an autouse fixture binds that app's bare names for each of its tests
# (monkeypatch restores them afterwards).

import pytest  # noqa: E402

_APPS_DIR = Path(_REPO_ROOT) / "apps"
_TESTS_DIR = Path(__file__).resolve().parent
_APP_MODULES: dict[str, dict[str, object]] = {}


def _app_of_test_path(path) -> str | None:
    try:
        relative = Path(path).resolve().relative_to(_TESTS_DIR)
    except ValueError:
        return None
    app = relative.parts[0] if len(relative.parts) > 1 else None
    return app if app is not None and (_APPS_DIR / app).is_dir() else None


def _record_app_modules(owner_app: str | None = None) -> None:
    """Remember every loaded module whose file lives directly in apps/<App>/. The first
    module object seen for a file is kept, so a later re-import of the same file does
    not replace the one the tests already imported. owner_app is the app whose conftest
    just ran: its bare-named modules are exactly what that conftest set up, so they win."""
    for name, module in list(sys.modules.items()):
        file = getattr(module, "__file__", None)
        if not file:
            continue
        path = Path(file)
        if path.parent.parent != _APPS_DIR:
            continue
        app = path.parent.name
        modules = _APP_MODULES.setdefault(app, {})
        if path.stem not in modules or (app == owner_app and name == path.stem):
            modules[path.stem] = module


def _release_bare_app_names() -> None:
    """Drop bare-named app modules from sys.modules, so the next app's conftest starts
    clean instead of picking up this app's utils/config/... by accident. The bindings
    below put the right ones back for each test module and test."""
    for name, module in list(sys.modules.items()):
        file = getattr(module, "__file__", None)
        if file and Path(file).parent.parent == _APPS_DIR and name == Path(file).stem:
            del sys.modules[name]


def pytest_plugin_registered(plugin, manager):
    file = getattr(plugin, "__file__", None)
    if file:
        _record_app_modules(owner_app=_app_of_test_path(file))
        _release_bare_app_names()


def pytest_collectreport(report):
    _record_app_modules()


def pytest_collectstart(collector):
    # When several test folders are passed explicitly, pytest loads all their conftests
    # before importing any test module, so bind the right app's names before each
    # test module's own top-level imports run.
    if isinstance(collector, pytest.Module):
        sys.modules.update(_APP_MODULES.get(_app_of_test_path(collector.path), {}))


@pytest.fixture(autouse=True)
def _bind_app_bare_module_names(request, monkeypatch):
    app = _app_of_test_path(request.node.path)
    for stem, module in _APP_MODULES.get(app, {}).items():
        monkeypatch.setitem(sys.modules, stem, module)
