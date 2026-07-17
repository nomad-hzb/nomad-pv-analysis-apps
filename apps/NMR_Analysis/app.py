"""
app.py – NMR Plotter
Thin assembly layer. Imports local modules only (no hysprint_utils prefix).
"""

from __future__ import annotations

import logging
from pathlib import Path

import data_manager
import gui_components
import ipywidgets as widgets
from hysprint_utils.auth_manager import AuthenticationManager
from hysprint_utils.error_handler import ErrorHandler
from hysprint_utils.plotting_utils import WidgetFactory
from IPython.display import display as ipydisplay

logger = logging.getLogger(__name__)

_TESTS_ROOT = Path(__file__).parent.parent.parent / "tests"
DEMO_FIXTURE_PATH = _TESTS_ROOT / "NMR_Analysis" / "fixtures" / "api_responses.json"
class NMRPlotterApp:
    """Top-level app. Call display() from the notebook."""

    def __init__(
        self,
        url_base: str,
        api_endpoint: str,
        token: str,
    ) -> None:
        self._auth = AuthenticationManager(url_base, api_endpoint)
        self._auth.authenticate_with_token(token)
        self._url = self._auth.api_client.get_api_url()
        self._token = self._auth.current_token

        self._dm = data_manager.NMRDataManager()

        self._data_ui_out = widgets.Output()

        self._batch_panel = gui_components.BatchPanel(
            self._url, self._token, on_load=self._on_batch_load
        )
        self._status_out = self._batch_panel.status_out

        self._demo_btn = widgets.Button(
            description="Load demo data",
            button_style="warning",
            icon="database",
        )
        self._demo_btn.on_click(self._on_demo_load)

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def display(self) -> None:
        ipydisplay(
            widgets.VBox(
                [
                    self._demo_btn,
                    self._batch_panel.widget,
                    self._data_ui_out,
                ]
            )
        )

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _on_demo_load(self, _b) -> None:
        logger.info("Loading NMR demo data from fixture...")
        self._status_out.clear_output()
        self._data_ui_out.clear_output()
        success = self._dm.load_offline(DEMO_FIXTURE_PATH)
        self._status_out.clear_output()
        if not success:
            with self._status_out:
                ErrorHandler.log_error(
                    "Demo fixture contained no valid NMR measurements.",
                    output_widget=self._status_out,
                )
            return
        with self._status_out:
            ErrorHandler.log_success(
                "Loaded %d demo NMR spectra." % len(self._dm.sample_ids), self._status_out
            )
        self._build_data_ui()

    def _on_batch_load(self, batch_ids_selector: widgets.SelectMultiple) -> None:
        self._status_out.clear_output()
        self._data_ui_out.clear_output()

        with self._status_out:
            ErrorHandler.log_info("Loading NMR data...", self._status_out)

        try:
            success = self._dm.load(self._url, self._token, batch_ids=batch_ids_selector.value)
        except Exception as exc:  # noqa: BLE001
            self._status_out.clear_output()
            ErrorHandler.log_error(
                "Failed to load data", exc, self._status_out, show_traceback=True
            )
            return

        self._status_out.clear_output()

        if not success:
            with self._status_out:
                ErrorHandler.log_error(
                    "The selected batches contain no NMR measurements.",
                    output_widget=self._status_out,
                )
            return

        with self._status_out:
            ErrorHandler.log_success(
                "Loaded %d NMR spectra." % len(self._dm.sample_ids), self._status_out
            )

        self._build_data_ui()

    def _build_data_ui(self) -> None:
        overlay_panel = gui_components.OverlayPlotPanel(self._dm)
        single_panel = gui_components.SingleSpectrumPanel(self._dm)

        with self._data_ui_out:
            self._data_ui_out.clear_output(wait=True)
            ipydisplay(widgets.VBox([overlay_panel.widget, single_panel.widget]))
