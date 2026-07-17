# app.py
# Thin orchestrator: wires data_manager state + gui_components widgets together. No
# business logic lives here.

import logging
from pathlib import Path

import gui_components
import ipywidgets as widgets

logger = logging.getLogger(__name__)

_TESTS_ROOT = Path(__file__).parent.parent.parent / "tests"
DEMO_FIXTURE_PATH = _TESTS_ROOT / "Entry_Auditor" / "fixtures" / "sample_batch.json"

# Widgets created by the previous call to initialize_ui() are explicitly closed before
# building new ones, mirroring smart_databaser's app.py pattern: clear_output() only
# hides widgets from display, it doesn't destroy them, so stale on_click/observe
# handlers from prior cell re-runs would otherwise all fire simultaneously on one click.
_ui_widget_ids: set = set()


def initialize_ui(url: str, token: str) -> widgets.Widget:
    global _ui_widget_ids
    for widget_id in list(_ui_widget_ids):
        widget = widgets.Widget.widgets.get(widget_id)
        if widget is not None:
            try:
                widget.close()
            except Exception:
                logger.exception("Failed to close stale widget %s", widget_id)
    _ui_widget_ids = set()
    ids_before = set(widgets.Widget.widgets.keys())

    ui = gui_components.create_entry_auditor_ui(url, token, DEMO_FIXTURE_PATH)

    _ui_widget_ids = set(widgets.Widget.widgets.keys()) - ids_before
    return ui
