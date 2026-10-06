"""Shared fixtures for smart_databaser tests -- never hits the real API."""

import importlib.util
import os
import sys
from pathlib import Path

import pytest

# Must be set before data_manager is imported so get_token() returns immediately.
os.environ.setdefault("NOMAD_CLIENT_ACCESS_TOKEN", "test-token")

_APP_DIR = Path(__file__).parent.parent.parent / "apps" / "smart_databaser"
_SHARED_DIR = Path(__file__).parent.parent.parent / "shared"

# Add shared so hysprint_utils is importable (safe -- shared across all apps).
if str(_SHARED_DIR) not in sys.path:
    sys.path.insert(0, str(_SHARED_DIR))

# data_manager imports the Excel_creator sheet builders through excel_creator_modules,
# which loads them from apps/Excel_creator by file path; register it under its bare name
# the same way as alias_config below.
if "excel_creator_modules" not in sys.modules:
    _spec = importlib.util.spec_from_file_location(
        "excel_creator_modules", _APP_DIR / "excel_creator_modules.py"
    )
    _ecm_module = importlib.util.module_from_spec(_spec)
    sys.modules["excel_creator_modules"] = _ecm_module
    _spec.loader.exec_module(_ecm_module)

# alias_config has no dependency on data_manager and must load first, since data_manager
# does `from alias_config import resolve_progress_units`.
if "alias_config" not in sys.modules or not hasattr(
    sys.modules["alias_config"], "resolve_progress_units"
):
    _spec = importlib.util.spec_from_file_location("alias_config", _APP_DIR / "alias_config.py")
    _ac_module = importlib.util.module_from_spec(_spec)
    sys.modules["alias_config"] = _ac_module
    _spec.loader.exec_module(_ac_module)

# Load smart_databaser's data_manager via importlib so we do NOT add
# apps/smart_databaser to sys.path (would shadow other apps' bare `data_manager` imports).
if "data_manager" not in sys.modules or not hasattr(sys.modules["data_manager"], "ExperimentState"):
    _spec = importlib.util.spec_from_file_location("data_manager", _APP_DIR / "data_manager.py")
    _dm_module = importlib.util.module_from_spec(_spec)
    sys.modules["data_manager"] = _dm_module
    _spec.loader.exec_module(_dm_module)

# Same approach for gui_components -- it does `from data_manager import ...`, which
# resolves against sys.modules["data_manager"] injected above regardless of sys.path.
if "gui_components" not in sys.modules or not hasattr(
    sys.modules["gui_components"], "ProcessSequenceBuilder"
):
    _spec = importlib.util.spec_from_file_location("gui_components", _APP_DIR / "gui_components.py")
    _gc_module = importlib.util.module_from_spec(_spec)
    sys.modules["gui_components"] = _gc_module
    _spec.loader.exec_module(_gc_module)

# Same approach for app.py -- it does `from data_manager import ...` / `from
# gui_components import ...`, both already registered in sys.modules above.
if "app" not in sys.modules or not hasattr(sys.modules["app"], "initialize_ui"):
    _spec = importlib.util.spec_from_file_location("app", _APP_DIR / "app.py")
    _app_module = importlib.util.module_from_spec(_spec)
    sys.modules["app"] = _app_module
    _spec.loader.exec_module(_app_module)

from data_manager import ExperimentState  # noqa: E402


@pytest.fixture
def fresh_state():
    """A clean ExperimentState instance for each test."""
    return ExperimentState()
