import importlib.util
import sys
from pathlib import Path

_APP_DIR = Path(__file__).resolve().parent.parent.parent / "apps" / "App_dashboard"
_SHARED_DIR = _APP_DIR.parent.parent / "shared"

if str(_SHARED_DIR) not in sys.path:
    sys.path.insert(0, str(_SHARED_DIR))
if str(_APP_DIR) not in sys.path:
    sys.path.insert(0, str(_APP_DIR))


def _load(unique_name: str, filename: str):
    sys.modules.pop(filename, None)
    spec = importlib.util.spec_from_file_location(unique_name, _APP_DIR / f"{filename}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[unique_name] = module
    sys.modules[filename] = module
    spec.loader.exec_module(module)
    return module


_load("data_manager_app_dashboard", "data_manager")
