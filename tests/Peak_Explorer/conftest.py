"""Shared fixtures for Peak_Explorer tests. Never hits NOMAD; H5 files are synthetic."""

import importlib.util
import sys
import types
from pathlib import Path

import numpy as np
import pytest

_REPO_ROOT = Path(__file__).parent.parent.parent
APP_DIR = _REPO_ROOT / "apps" / "Peak_Explorer"

# Load order matters: each module imports the ones before it by bare name.
_MODULE_ORDER = (
    "config",
    "utils",
    "exporters",
    "data_manager",
    "fitting_engine",
    "plot_manager",
    "gui_components",
    "gui_layouts",
)

_MODULES: dict = {}
"""This app's loaded modules, keyed by bare name. Held here rather than in sys.modules, which
is shared with every other app's tests."""

_DISPLACED: dict = {}
"""What sys.modules held under those bare names before we borrowed them."""

_NO_LOG = object()


def _stub_usage_log():
    """data_manager calls hysprint_utils.access_token.log_notebook_usage() on import, which
    appends to a real usage log. Hand it a no-op for the duration of the load instead."""
    saved = {
        name: sys.modules.get(name, _NO_LOG)
        for name in ("hysprint_utils", "hysprint_utils.access_token")
    }
    package = sys.modules.get("hysprint_utils") or types.ModuleType("hysprint_utils")
    if not hasattr(package, "__path__"):
        package.__path__ = []
    access_token = types.ModuleType("hysprint_utils.access_token")
    access_token.log_notebook_usage = lambda *args, **kwargs: None
    sys.modules["hysprint_utils"] = package
    sys.modules["hysprint_utils.access_token"] = access_token
    return saved


def _restore(saved):
    for name, module in saved.items():
        if module is _NO_LOG:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = module


def _load_all():
    saved = _stub_usage_log()
    try:
        for name in _MODULE_ORDER:
            spec = importlib.util.spec_from_file_location(name, APP_DIR / f"{name}.py")
            module = importlib.util.module_from_spec(spec)
            _DISPLACED.setdefault(name, sys.modules.get(name))
            sys.modules[name] = module
            spec.loader.exec_module(module)
            _MODULES[name] = module
    finally:
        _restore(saved)
        _release_bare_names()


def _release_bare_names():
    """Put sys.modules back the way we found it, keeping the loaded objects in _MODULES.
    Restoring rather than deleting matters because another app's conftest may already
    have registered its own module under the same bare name."""
    for name, module in _MODULES.items():
        if sys.modules.get(name) is not module:
            continue
        displaced = _DISPLACED.get(name)
        if displaced is None:
            del sys.modules[name]
        else:
            sys.modules[name] = displaced


_load_all()


@pytest.fixture
def cfg():
    return _MODULES["config"]


@pytest.fixture
def dm():
    return _MODULES["data_manager"]


@pytest.fixture
def fe():
    return _MODULES["fitting_engine"]


@pytest.fixture
def ex():
    return _MODULES["exporters"]


@pytest.fixture
def pm():
    return _MODULES["plot_manager"]


@pytest.fixture
def gl():
    return _MODULES["gui_layouts"]


@pytest.fixture
def app_modules_importable(monkeypatch):
    """Let worker processes of the parallel fit import this app's modules.

    Spawned workers unpickle FittingModels' worker function by its module name
    ("fitting_engine") and import it from sys.path, and pickle checks that name resolves
    to the very same function object in this process. So for the duration of one test the
    bare names point at our loaded modules and the app dir is on sys.path; monkeypatch
    restores both afterwards.
    """
    monkeypatch.syspath_prepend(str(APP_DIR))
    for name, module in _MODULES.items():
        monkeypatch.setitem(sys.modules, name, module)


@pytest.fixture
def x_nm():
    return np.linspace(400, 800, 801)


@pytest.fixture
def app(gl):
    """A headless PLAnalysisApp with synthetic data attached through the public setters."""

    def _make(data, wavelengths, timestamps=None, unit="nm"):
        application = gl.PLAnalysisApp()
        dman = application.data_manager
        dman.wavelengths = np.asarray(wavelengths, dtype=float)
        dman.data_matrix = np.asarray(data, dtype=float)
        dman.timestamps = (
            np.arange(len(data), dtype=float) if timestamps is None else np.asarray(timestamps)
        )
        dman.unit = unit
        application.wavelength_unit = unit
        dman.set_current_time(0)
        slider = application.widgets["wavelength_range_slider"]
        slider.max, slider.min = 1e9, -1e9
        slider.min, slider.max = float(dman.wavelengths.min()), float(dman.wavelengths.max())
        slider.value = (slider.min, slider.max)
        return application

    return _make
