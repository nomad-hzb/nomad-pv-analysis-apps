"""Shared fixtures for ISA_Previewer tests. Never hits NOMAD and never opens an h5."""

import importlib.util
import os
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# Set before the app modules import, so nothing tries to obtain a real token or user.
os.environ.setdefault("NOMAD_CLIENT_ACCESS_TOKEN", "test-token")
os.environ.setdefault("NOMAD_CLIENT_USER", "tester@example.org")

_REPO_ROOT = Path(__file__).parent.parent.parent
_APP_DIR = _REPO_ROOT / "apps" / "ISA_Previewer"
_SHARED_DIR = _REPO_ROOT / "shared"

if str(_SHARED_DIR) not in sys.path:
    sys.path.insert(0, str(_SHARED_DIR))

_MODULES: dict = {}
"""This app's loaded modules, keyed by bare name. Held here rather than in sys.modules, which
is shared with every other app's tests."""

_DISPLACED: dict = {}
"""What sys.modules held under those bare names before we borrowed them, so another app's
already-registered module can be put back exactly as it was."""


def _stub_insitu_analyser() -> None:
    """Register a stand-in for insitu_analyser before the app imports from it.

    The real package is a git dependency of the app, not of this repo, so it is absent in a
    plain checkout and in CI. Everything the tests exercise is the app's own logic; the
    calls into insitu_analyser are the boundary being mocked, so a stub is the honest shape
    here rather than a reason to install a heavy dependency.
    """
    if "insitu_analyser" in sys.modules:
        return

    package = types.ModuleType("insitu_analyser")
    package.__path__ = []
    utils = types.ModuleType("insitu_analyser.utils")
    utils.__path__ = []
    preview = types.ModuleType("insitu_analyser.Preview")
    preview.__path__ = []

    api_calls = types.ModuleType("insitu_analyser.utils.nomad_api_calls")
    for name in (
        "get_sample_description",
        "get_samples_in_upload",
        "get_specific_data_of_sample",
        "get_uploads_with_entry_type",
    ):
        setattr(api_calls, name, MagicMock(name=name))

    search_bar = types.ModuleType("insitu_analyser.utils.search_bar_widget")
    search_bar.create_spinner = MagicMock(name="create_spinner")

    previewer = types.ModuleType("insitu_analyser.Preview.perfect_previewer")
    previewer.PERFECTPREVIEWER = MagicMock(name="PERFECTPREVIEWER")

    utils.nomad_api_calls = api_calls
    utils.search_bar_widget = search_bar
    preview.perfect_previewer = previewer
    package.utils = utils
    package.Preview = preview

    sys.modules.update(
        {
            "insitu_analyser": package,
            "insitu_analyser.utils": utils,
            "insitu_analyser.utils.nomad_api_calls": api_calls,
            "insitu_analyser.utils.search_bar_widget": search_bar,
            "insitu_analyser.Preview": preview,
            "insitu_analyser.Preview.perfect_previewer": previewer,
        }
    )


def _load(module_name: str, marker: str):
    """Load one of this app's modules from its file, without putting the app dir on sys.path.

    A module has to sit in sys.modules under its bare name while it loads, because these
    modules import each other that way ("import data_manager"), which is the repo's import
    convention for app-local modules. The bare names are removed again afterwards by
    _release_bare_names: several apps have a module called data_manager, and leaving ours
    registered would hand it to whichever app's tests import theirs next.
    """
    cached = _MODULES.get(module_name)
    if cached is not None and hasattr(cached, marker):
        return cached
    spec = importlib.util.spec_from_file_location(module_name, _APP_DIR / f"{module_name}.py")
    module = importlib.util.module_from_spec(spec)
    _DISPLACED.setdefault(module_name, sys.modules.get(module_name))
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    _MODULES[module_name] = module
    return module


def _release_bare_names() -> None:
    """Put sys.modules back the way we found it, keeping the loaded objects in _MODULES.

    Safe once loading is done: the modules have already bound their references to each
    other, and the fixtures hand out the cached objects rather than re-importing. Restoring
    rather than deleting matters because another app's conftest may already have registered
    its own data_manager under that name, and its test module imports it later.
    """
    for module_name, module in _MODULES.items():
        if sys.modules.get(module_name) is not module:
            continue
        displaced = _DISPLACED.get(module_name)
        if displaced is None:
            del sys.modules[module_name]
        else:
            sys.modules[module_name] = displaced


_stub_insitu_analyser()
_load("config", "VARIANTS")
_load("data_manager", "upload_id_from_path")
_load("gui_components", "build_sections")
_release_bare_names()


@pytest.fixture
def cfg():
    """The app's config module."""
    return _load("config", "VARIANTS")


@pytest.fixture
def dm():
    """The app's data_manager module."""
    return _load("data_manager", "upload_id_from_path")


@pytest.fixture
def gui():
    """The app's gui_components module."""
    return _load("gui_components", "build_sections")
