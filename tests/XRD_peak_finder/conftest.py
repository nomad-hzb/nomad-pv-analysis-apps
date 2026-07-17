"""Shared fixtures -- never hits the real API."""
import importlib.util
import sys
from pathlib import Path

import pytest

_APP_DIR = Path(__file__).parent.parent.parent / "apps" / "XRD_peak_finder"
_SHARED_DIR = _APP_DIR.parent.parent / "shared"

if str(_SHARED_DIR) not in sys.path:
    sys.path.insert(0, str(_SHARED_DIR))

sys.modules.pop("data_manager", None)
_spec = importlib.util.spec_from_file_location("dm_xrd", _APP_DIR / "data_manager.py")
_dm = importlib.util.module_from_spec(_spec)
sys.modules["dm_xrd"] = _dm
sys.modules["data_manager"] = _dm
_spec.loader.exec_module(_dm)

from data_manager import XRDDataManager  # noqa: E402

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "api_responses.json"


@pytest.fixture
def loaded_manager():
    """XRDDataManager populated via load_offline() from the JSON fixture."""
    mgr = XRDDataManager(url="http://mock", token="mock-token")
    mgr.load_offline(FIXTURE_PATH)
    return mgr


@pytest.fixture
def sample_data_dict(loaded_manager):
    """Pre-built data dict identical in shape to what load() produces."""
    return {k: dict(v) for k, v in loaded_manager.data.items()}
