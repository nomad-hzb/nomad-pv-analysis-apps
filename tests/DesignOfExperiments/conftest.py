import importlib.util
import sys
from pathlib import Path

_APP_DIR = Path(__file__).resolve().parent.parent.parent / "apps" / "DesignOfExperiments"
_SHARED_DIR = _APP_DIR.parent.parent / "shared"

if str(_SHARED_DIR) not in sys.path:
    sys.path.insert(0, str(_SHARED_DIR))
if str(_APP_DIR) not in sys.path:
    sys.path.insert(0, str(_APP_DIR))

sys.modules.pop("data_manager", None)
_spec = importlib.util.spec_from_file_location("dm_doe", _APP_DIR / "data_manager.py")
_dm = importlib.util.module_from_spec(_spec)
sys.modules["dm_doe"] = _dm
sys.modules["data_manager"] = _dm
_spec.loader.exec_module(_dm)

sys.modules.pop("plot_manager", None)
_pm_spec = importlib.util.spec_from_file_location("pm_doe", _APP_DIR / "plot_manager.py")
_pm = importlib.util.module_from_spec(_pm_spec)
sys.modules["pm_doe"] = _pm
sys.modules["plot_manager"] = _pm
_pm_spec.loader.exec_module(_pm)
