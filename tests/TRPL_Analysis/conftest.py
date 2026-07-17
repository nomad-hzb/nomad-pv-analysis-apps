"""Shared fixtures -- never hits the real API."""
import importlib.util
import sys
from pathlib import Path

import pytest

_APP_DIR = Path(__file__).parent.parent.parent / "apps" / "TRPL_Analysis"
_SHARED_DIR = _APP_DIR.parent.parent / "shared"

if str(_SHARED_DIR) not in sys.path:
    sys.path.insert(0, str(_SHARED_DIR))

sys.modules.pop("data_manager", None)
_spec = importlib.util.spec_from_file_location("dm_trpl", _APP_DIR / "data_manager.py")
_dm = importlib.util.module_from_spec(_spec)
sys.modules["dm_trpl"] = _dm
sys.modules["data_manager"] = _dm
_spec.loader.exec_module(_dm)

from data_manager import TRPLDataManager  # noqa: E402

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "api_responses.json"


@pytest.fixture
def loaded_manager():
    """TRPLDataManager populated via load_offline() from the JSON fixture."""
    dm = TRPLDataManager(url="http://mock", token="mock-token")
    dm.load_offline(FIXTURE_PATH)
    return dm


@pytest.fixture
def sample_df(loaded_manager):
    """Pre-built DataFrame identical in shape to what load() returns."""
    return loaded_manager.data.copy()
