"""Shared fixtures for File_Uploader tests -- never hits the real API."""
import importlib.util
import os
import sys
from pathlib import Path

import pytest

# Must be set before data_manager is imported so get_token() returns immediately.
os.environ.setdefault("NOMAD_CLIENT_ACCESS_TOKEN", "test-token")

_APP_DIR = Path(__file__).parent.parent.parent / "apps" / "File_Uploader"
_SHARED_DIR = Path(__file__).parent.parent.parent / "shared"

# Add shared so hysprint_utils is importable (safe -- shared across all apps).
if str(_SHARED_DIR) not in sys.path:
    sys.path.insert(0, str(_SHARED_DIR))

# Load File_Uploader's data_manager via importlib so we do NOT add apps/File_Uploader
# to sys.path.  Adding that directory at sys.path[0] would cause other apps'
# conftest.py files (NMR_Analysis, TRPL_Analysis, …) to resolve *their* bare
# `data_manager` import to this module instead of their own, changing pre-existing
# ModuleNotFoundError failures into misleading ImportError failures.
if "data_manager" not in sys.modules or not hasattr(sys.modules["data_manager"], "AppState"):
    _spec = importlib.util.spec_from_file_location("data_manager", _APP_DIR / "data_manager.py")
    _dm_module = importlib.util.module_from_spec(_spec)
    sys.modules["data_manager"] = _dm_module
    _spec.loader.exec_module(_dm_module)

from data_manager import AppState  # noqa: E402

FIXTURE_JSON = {
    "parameters": {"instrument": "test_jv_setup"},
    "data": [
        {"sample": "JM434", "cell": "1", "direction": "fw", "card": "A", "channel": "1", "efficiency": 15.2},
        {"sample": "JM434", "cell": "1", "direction": "rv", "card": "A", "channel": "1", "efficiency": 14.9},
        {"sample": "JM435", "cell": "2", "direction": "fw", "card": "B", "channel": "2", "efficiency": 16.1},
    ],
}


@pytest.fixture
def fixture_json():
    return FIXTURE_JSON


@pytest.fixture
def fresh_state():
    """A clean AppState instance for each test."""
    return AppState()
