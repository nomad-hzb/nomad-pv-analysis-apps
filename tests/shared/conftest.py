"""Test hysprint_utils from shared/ in this checkout, never an older installed copy."""

import sys
from pathlib import Path

_SHARED_DIR = Path(__file__).resolve().parent.parent.parent / "shared"

while str(_SHARED_DIR) in sys.path:
    sys.path.remove(str(_SHARED_DIR))
sys.path.insert(0, str(_SHARED_DIR))

# If an installed copy was already imported (e.g. a non-editable install in the venv),
# drop it so the imports below resolve to shared/.
# hysprint_utils is a namespace package (no __init__.py), so look at __path__, not __file__.
_loaded = sys.modules.get("hysprint_utils")
_loaded_from = [Path(p).resolve() for p in getattr(_loaded, "__path__", [])]
if _loaded is not None and not any(path.parent == _SHARED_DIR for path in _loaded_from):
    for _name in [
        n for n in sys.modules if n == "hysprint_utils" or n.startswith("hysprint_utils.")
    ]:
        del sys.modules[_name]
