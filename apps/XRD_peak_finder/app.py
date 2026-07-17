"""
app.py — XY Visualizer
Thin assembly layer. Imports local modules only (no hysprint_utils prefix).
"""

from __future__ import annotations

import logging
from pathlib import Path

import ipywidgets as widgets
from data_manager import XRDDataManager
from gui_components import (
    BatchFilterPanel,
    FileUploadPanel,
    OverlayPanel,
    SampleGridPanel,
)
from hysprint_utils.auth_manager import AuthenticationManager
from hysprint_utils.plotting_utils import WidgetFactory, create_manual
from IPython.display import display as ipydisplay

logger = logging.getLogger(__name__)

_TESTS_ROOT = Path(__file__).parent.parent.parent / "tests"
DEMO_FIXTURE_PATH = _TESTS_ROOT / "XRD_peak_finder" / "fixtures" / "api_responses.json"
class XRDApp:
    """Top-level app — call display() from the notebook."""

    def __init__(
        self,
        url_base: str,
        api_endpoint: str,
        token: str,
        manual_file: str | None = None,
    ) -> None:
        self._auth = AuthenticationManager(url_base, api_endpoint)
        self._auth.authenticate_with_token(token)

        api_url = self._auth.api_client.get_api_url()
        self._data_manager = XRDDataManager(url=api_url, token=token)
        self._manual_file = manual_file

        self._demo_btn = widgets.Button(
            description="Load demo data",
            button_style="warning",
            icon="database",
        )
        self._demo_btn.on_click(self._on_demo_load)

        # Panels created once; data UI rebuilt after load
        self._sample_grid = SampleGridPanel()
        self._overlay_panel = OverlayPanel(self._data_manager, self._sample_grid)
        self._sample_grid.set_selection_callback(self._overlay_panel.on_selection_changed)

        self._status_output = WidgetFactory.create_output(min_height="standard")
        self._data_ui_container = widgets.Output()

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def display(self) -> None:
        if self._manual_file:
            try:
                ipydisplay(create_manual(self._manual_file))
            except Exception:
                pass

        # Batch selection panel
        batch_panel = BatchFilterPanel(self._data_manager, self._on_batch_load)

        # File upload panel
        file_panel = FileUploadPanel(self._data_manager, self._rebuild_data_ui)

        header = widgets.HTML("<h2>XRD / XY Data Visualization Tool</h2>")
        instructions = widgets.HTML(
            "<p><b>Option 1:</b> Select batches via the API panel below.<br>"
            "<b>Option 2:</b> Upload local <code>.xy</code> files.<br>"
            "Then check samples you want in the overlay plot and adjust the stagger offset.</p>"
        )

        ipydisplay(
            widgets.VBox(
                [
                    header,
                    instructions,
                    self._demo_btn,
                    batch_panel.widget,
                    file_panel.widget,
                    self._status_output,
                    self._data_ui_container,
                ]
            )
        )

    # ------------------------------------------------------------------
    # Callbacks
    # ------------------------------------------------------------------

    def _on_demo_load(self, _b) -> None:
        logger.info("Loading XRD demo data from fixture...")
        ok = self._data_manager.load_offline(DEMO_FIXTURE_PATH)
        if ok:
            logger.info("Loaded %d demo sample(s).", len(self._data_manager.data))
            self._rebuild_data_ui()
        else:
            logger.warning("Demo fixture contained no valid XRD data.")

    def _on_batch_load(self, batch_ids_selector) -> None:
        logger.info("Loading XRD data...")
        self._status_output.clear_output(wait=True)

        batch_ids = list(batch_ids_selector.value)
        ok = self._data_manager.load(batch_ids)

        if ok:
            logger.info("Loaded %d sample(s).", len(self._data_manager.data))
            self._rebuild_data_ui()
        else:
            logger.warning("No XRD measurements found in the selected batches.")

    def _rebuild_data_ui(self) -> None:
        self._overlay_panel.update_slider_range()
        self._sample_grid.refresh(self._data_manager.data)

        with self._data_ui_container:
            self._data_ui_container.clear_output(wait=True)
            ipydisplay(
                widgets.VBox(
                    [
                        self._sample_grid.widget,
                        self._overlay_panel.widget,
                    ]
                )
            )
