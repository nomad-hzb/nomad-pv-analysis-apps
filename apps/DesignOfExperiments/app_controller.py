# Renamed to app.py — this shim exists so existing notebooks using app_controller still work.
# Import from app.py directly for new code.
from app import DoEApplication as DoEApplication  # noqa: F401
