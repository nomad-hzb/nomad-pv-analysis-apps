import importlib.util
import sys
from pathlib import Path

import pandas as pd
import pytest

_APP_DIR = Path(__file__).parent.parent.parent / "apps" / "MPPT_Analysis"
_SHARED_DIR = _APP_DIR.parent.parent / "shared"

if str(_SHARED_DIR) not in sys.path:
    sys.path.insert(0, str(_SHARED_DIR))
if str(_APP_DIR) not in sys.path:
    sys.path.insert(0, str(_APP_DIR))

sys.modules.pop("data_manager", None)
_spec = importlib.util.spec_from_file_location("dm_mppt", _APP_DIR / "data_manager.py")
_dm = importlib.util.module_from_spec(_spec)
sys.modules["dm_mppt"] = _dm
sys.modules["data_manager"] = _dm
_spec.loader.exec_module(_dm)

from app_state import AppState  # noqa: E402
from data_manager import DataManager  # noqa: E402
from plot_manager import PlotManager  # noqa: E402

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "api_responses.json"

FIXTURE_ROWS = [
    {"time": 0.0, "power_density": 15.2, "voltage": 0.92, "current_density": -16.5},
    {"time": 0.5, "power_density": 14.8, "voltage": 0.91, "current_density": -16.3},
    {"time": 1.0, "power_density": 14.4, "voltage": 0.90, "current_density": -16.0},
    {"time": 1.5, "power_density": 14.1, "voltage": 0.89, "current_density": -15.8},
    {"time": 2.0, "power_density": 13.9, "voltage": 0.88, "current_density": -15.7},
]


@pytest.fixture
def loaded_manager():
    dm = DataManager(url="http://mock", token="mock-token")
    dm.load_offline(FIXTURE_PATH)
    return dm


@pytest.fixture
def mppt_dataframe():
    """Multi-index DataFrame matching the structure DataManager produces."""
    df = pd.DataFrame(FIXTURE_ROWS)
    sample_id = "batch1&sample1"
    curve_df = pd.concat([df], keys=[0], names=["curve_id", "point"])
    return curve_df, sample_id


@pytest.fixture
def loaded_app_state(mppt_dataframe):
    """AppState pre-loaded with fixture curve data and a selected sample."""
    curves_df, sample_id = mppt_dataframe
    full_curves = pd.concat([curves_df], keys=[sample_id])
    sample_ids = pd.Series([sample_id])
    state = AppState()
    state.set_api_config("https://nomad-hzb-se.de", "test-token")
    state.load_curves_data(full_curves, sample_ids, pd.DataFrame(), pd.DataFrame())
    state.set_selected_samples([sample_id])
    return state


@pytest.fixture
def mock_data_manager():
    """DataManager instance with no live API connectivity."""
    dm = DataManager.__new__(DataManager)
    dm.url = "https://nomad-hzb-se.de/nomad-oasis/api/v1"
    dm.token = "test-token"
    return dm


@pytest.fixture
def plot_manager(loaded_app_state, mock_data_manager):
    """PlotManager wired to loaded_app_state and mock_data_manager."""
    return PlotManager(loaded_app_state, mock_data_manager)
