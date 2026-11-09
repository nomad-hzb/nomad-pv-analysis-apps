# app.py
# Thin orchestrator: wires data_manager state + gui_components widgets together. No
# business logic lives here.

import logging
from pathlib import Path

import gui_components
import ipywidgets as widgets

from hysprint_utils.manual import manual_panel
from hysprint_utils.widget_cleanup import UiRebuild

logger = logging.getLogger(__name__)

_TESTS_ROOT = Path(__file__).parent.parent.parent / "tests"
DEMO_FIXTURE_PATH = _TESTS_ROOT / "Entry_Auditor" / "fixtures" / "sample_batch.json"

# A re-run of the cell first closes the widgets of the previous run (see UiRebuild).
_ui = UiRebuild()


def initialize_ui(url: str, token: str) -> widgets.Widget:
    with _ui.build():
        ui = widgets.VBox(
            [
                manual_panel(__file__),
                gui_components.create_entry_auditor_ui(url, token, DEMO_FIXTURE_PATH),
            ]
        )
    return ui
