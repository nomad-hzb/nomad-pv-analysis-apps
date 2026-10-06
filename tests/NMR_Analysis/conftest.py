"""Shared fixtures -- never hits the real API."""

import importlib.util
import sys
from pathlib import Path

import pytest

_APP_DIR = Path(__file__).parent.parent.parent / "apps" / "NMR_Analysis"
_SHARED_DIR = _APP_DIR.parent.parent / "shared"

if str(_SHARED_DIR) not in sys.path:
    sys.path.insert(0, str(_SHARED_DIR))

sys.modules.pop("data_manager", None)
_spec = importlib.util.spec_from_file_location("dm_nmr", _APP_DIR / "data_manager.py")
_dm = importlib.util.module_from_spec(_spec)
sys.modules["dm_nmr"] = _dm
sys.modules["data_manager"] = _dm
_spec.loader.exec_module(_dm)

# The tests also import plot_manager by bare name; load it from this app the same way.
sys.modules.pop("plot_manager", None)
_pm_spec = importlib.util.spec_from_file_location("pm_nmr", _APP_DIR / "plot_manager.py")
_pm = importlib.util.module_from_spec(_pm_spec)
sys.modules["pm_nmr"] = _pm
sys.modules["plot_manager"] = _pm
_pm_spec.loader.exec_module(_pm)

from data_manager import NMRDataManager  # noqa: E402

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "api_responses.json"


@pytest.fixture
def loaded_manager():
    """NMRDataManager populated via load_offline() from the JSON fixture."""
    dm = NMRDataManager()
    dm.load_offline(FIXTURE_PATH)
    return dm
