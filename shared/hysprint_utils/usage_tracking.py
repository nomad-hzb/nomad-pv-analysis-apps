"""Usage logging for the apps: one CSV line per notebook launch (log_notebook_usage) and per
in-app navigation click (log_button_usage).

Logs go to one folder, shared/log/ next to this package, so every app in the same
upload writes to the same two files instead of each installed copy of hysprint_utils
keeping its own. bootstrap.py exports HYSPRINT_USAGE_LOG_DIR pointing there; set it in
oasis_local_config.py or the container to log somewhere else.

Logging must never break an app: every failure is caught and logged, never raised.
"""

import csv
import datetime
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

USAGE_LOG_DIR_ENV = "HYSPRINT_USAGE_LOG_DIR"
NOTEBOOK_LOG = "notebook_usage.log"
BUTTON_LOG = "button_usage.log"

_PACKAGE_DIR = Path(__file__).resolve().parent
_DEFAULT_DIR = _PACKAGE_DIR.parent / "log"


def usage_log_dir() -> Path:
    """Folder the usage logs are written to."""
    configured = os.environ.get(USAGE_LOG_DIR_ENV)
    return Path(configured) if configured else _DEFAULT_DIR


def _log_path(filename: str) -> Path:
    """Path of one log file, creating the folder on first use. A log left next to this
    module by older versions is moved over once, so its history is kept."""
    folder = usage_log_dir()
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / filename
    legacy = _PACKAGE_DIR / filename
    if not path.exists() and legacy.is_file() and legacy != path:
        try:
            legacy.replace(path)
        except OSError:
            logger.warning("Could not move the old usage log %s to %s", legacy, path)
    return path


def _append(filename: str, header: list[str], row: list[str]) -> None:
    """Append row (with header first in a new file) as one CSV line. csv.writer quotes a
    value that holds a comma, a quote or a line break, so it can never shift the columns."""
    path = _log_path(filename)
    with open(path, "a", encoding="utf-8", newline="") as f:
        writer = csv.writer(f, lineterminator="\n")
        if path.stat().st_size == 0:
            writer.writerow(header)
        writer.writerow(row)


def _now() -> tuple[str, str]:
    now = datetime.datetime.now()
    return now.strftime("%Y-%m-%d"), now.strftime("%H:%M:%S")


def _current_notebook() -> tuple[str, str]:
    """(app_type, file) of the running notebook, from Jupyter or Voila environment
    variables, falling back to the notebooks in the working directory."""
    session_name = os.environ.get("JPY_SESSION_NAME", "Unknown")
    if session_name != "Unknown":
        return "jupyter", session_name.split("/", 5)[-1].split(".")[0]

    voila_url = os.environ.get("VOILA_REQUEST_URL", "")
    if voila_url:
        # URLs look like /voila/render/notebook.ipynb or /notebook.ipynb
        file = voila_url.split("/", 12)[-1].replace(".ipynb", "")
        if not file:  # URL ends with /
            file = voila_url.split("/")[-2].replace(".ipynb", "")
        return "voila", file

    cwd = os.getcwd()
    folder_name = os.path.basename(cwd)
    notebooks = list(Path(cwd).glob("*.ipynb"))
    if len(notebooks) == 1:
        return "voila", notebooks[0].stem
    if notebooks:
        return "voila", f"{folder_name}_voila"
    return "unknown", folder_name if folder_name else "Unknown_voila"


def log_notebook_usage(log_filename: str = NOTEBOOK_LOG) -> None:
    """Append one line (date, time, user, app type, notebook) for a notebook launch."""
    try:
        date_str, time_str = _now()
        user = os.environ.get("NOMAD_CLIENT_USER", "Unknown")
        app_type, file = _current_notebook()
        _append(
            log_filename,
            ["Date", "Time", "User", "App", "File"],
            [date_str, time_str, user, app_type, file],
        )
    except Exception:
        logger.exception("Error logging notebook usage")


def log_button_usage(action: str, user: str | None = None, log_filename: str = BUTTON_LOG) -> None:
    """Append one line (date, time, user, action) for an in-app navigation event, e.g.
    "open_project:Slot-die coater ML" or "back_to_dashboard". user falls back to
    NOMAD_CLIENT_USER."""
    try:
        date_str, time_str = _now()
        resolved_user = user if user is not None else os.environ.get("NOMAD_CLIENT_USER", "Unknown")
        _append(
            log_filename,
            ["Date", "Time", "User", "Action"],
            [date_str, time_str, resolved_user, action],
        )
    except Exception:
        logger.exception("Error logging button usage")
