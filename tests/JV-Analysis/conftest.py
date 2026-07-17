# tests/JV-Analysis/conftest.py
import importlib.util
import sys
from pathlib import Path

import pandas as pd
import pytest

_APP_DIR = Path(__file__).parent.parent.parent / "apps" / "JV-Analysis"
_SHARED_DIR = _APP_DIR.parent.parent / "shared"

if str(_SHARED_DIR) not in sys.path:
    sys.path.insert(0, str(_SHARED_DIR))

sys.modules.pop("data_manager", None)
_spec = importlib.util.spec_from_file_location("dm_jv", _APP_DIR / "data_manager.py")
_dm = importlib.util.module_from_spec(_spec)
sys.modules["dm_jv"] = _dm
sys.modules["data_manager"] = _dm
_spec.loader.exec_module(_dm)

from data_manager import DataManager  # noqa: E402

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "api_responses.json"


@pytest.fixture
def loaded_manager(mock_auth_manager):
    """DataManager populated via load_offline() from the JSON fixture."""
    dm = DataManager(mock_auth_manager)
    dm.load_offline(FIXTURE_PATH)
    return dm


@pytest.fixture
def jvc_dataframe(loaded_manager):
    """JVC DataFrame from the fixture (mirrors the old inline FIXTURE_ROWS)."""
    return loaded_manager.data["jvc"].copy()


@pytest.fixture
def empty_jvc_dataframe():
    """Empty DataFrame with correct columns."""
    cols = [
        "Voc(V)", "Jsc(mA/cm2)", "FF(%)", "PCE(%)", "V_mpp(V)",
        "J_mpp(mA/cm2)", "P_mpp(mW/cm2)", "R_series(Ohmcm2)", "R_shunt(Ohmcm2)",
        "sample", "batch", "condition", "cell", "direction", "ilum", "status", "sample_id",
    ]
    return pd.DataFrame(columns=cols)


@pytest.fixture
def mock_auth_manager(mocker):
    """Minimal mock auth manager -- never hits the network."""
    manager = mocker.MagicMock()
    manager.get_token.return_value = "fake-token"
    manager.get_url.return_value = "https://fake-nomad-oasis"
    manager.is_authenticated.return_value = True
    return manager
