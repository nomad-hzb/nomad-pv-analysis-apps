"""Shared fixtures for Entry_Auditor tests -- never hits the real API."""

import importlib.util
import os
import sys
from pathlib import Path

import pytest

# Must be set before data_manager is imported so get_token() returns immediately.
os.environ.setdefault("NOMAD_CLIENT_ACCESS_TOKEN", "test-token")

_APP_DIR = Path(__file__).parent.parent.parent / "apps" / "Entry_Auditor"
_SHARED_DIR = Path(__file__).parent.parent.parent / "shared"

# Add shared so hysprint_utils is importable (safe -- shared across all apps).
if str(_SHARED_DIR) not in sys.path:
    sys.path.insert(0, str(_SHARED_DIR))

# Load Entry_Auditor's data_manager via importlib so we do NOT add apps/Entry_Auditor
# to sys.path (would shadow other apps' bare `data_manager` imports).
if "data_manager" not in sys.modules or not hasattr(
    sys.modules["data_manager"], "EntryAuditSession"
):
    _spec = importlib.util.spec_from_file_location("data_manager", _APP_DIR / "data_manager.py")
    _dm_module = importlib.util.module_from_spec(_spec)
    sys.modules["data_manager"] = _dm_module
    _spec.loader.exec_module(_dm_module)

# Same approach for gui_components -- it does `from data_manager import ...`, which
# resolves against sys.modules["data_manager"] injected above regardless of sys.path.
if "gui_components" not in sys.modules or not hasattr(
    sys.modules["gui_components"], "create_entry_auditor_ui"
):
    _spec = importlib.util.spec_from_file_location("gui_components", _APP_DIR / "gui_components.py")
    _gc_module = importlib.util.module_from_spec(_spec)
    sys.modules["gui_components"] = _gc_module
    _spec.loader.exec_module(_gc_module)

from data_manager import EntryAuditSession  # noqa: E402

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "sample_batch.json"


@pytest.fixture
def fresh_session():
    """A clean EntryAuditSession instance for each test."""
    return EntryAuditSession()
