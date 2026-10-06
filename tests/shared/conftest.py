"""Test hysprint_utils from shared/ in this checkout, never an older installed copy."""

import sys
from pathlib import Path

_SHARED_DIR = Path(__file__).resolve().parent.parent.parent / "shared"

while str(_SHARED_DIR) in sys.path:
    sys.path.remove(str(_SHARED_DIR))
sys.path.insert(0, str(_SHARED_DIR))

# If an installed copy was already imported (e.g. a non-editable install in the venv),
# drop it so the imports below resolve to shared/.
_loaded = sys.modules.get("hysprint_utils")
if _loaded is not None and _SHARED_DIR not in Path(_loaded.__file__).resolve().parents:
    for _name in [
        n for n in sys.modules if n == "hysprint_utils" or n.startswith("hysprint_utils.")
    ]:
        del sys.modules[_name]
