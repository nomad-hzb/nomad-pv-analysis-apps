"""
TRPL Dashboard App
==================
Thin assembly layer.  Import and call app.display() from the notebook.
"""

from __future__ import annotations

import logging
from pathlib import Path

import data_manager as dm_module
import gui_components as gui
import ipywidgets as widgets
from hysprint_utils.auth_manager import AuthenticationManager
from hysprint_utils.error_handler import ErrorHandler
from IPython.display import display as ipydisplay

logger = logging.getLogger(__name__)

_TESTS_ROOT = Path(__file__).parent.parent.parent / "tests"
DEMO_FIXTURE_PATH = _TESTS_ROOT / "TRPL_Analysis" / "fixtures" / "api_responses.json"


class TRPLApp:
    """Top-level app: authentication -> batch selection -> analysis UI."""

    def __init__(
        self,
        url_base: str,
        api_endpoint: str,
        token: str,
        manual_file: str | None = None,
    ) -> None:
        self._auth = AuthenticationManager(url_base, api_endpoint)
        self._auth.authenticate_with_token(token)
        self._url = self._auth.api_client.get_api_url()
        self._token = self._auth.current_token

        self._data_manager = dm_module.TRPLDataManager(
            url=self._url,
            token=self._token,
        )

        self._load_out = widgets.Output()
        self._data_ui_out = widgets.Output()
        self._container = widgets.VBox([self._load_out, self._data_ui_out])

        self._batch_panel = gui.BatchFilterPanel(
            url=self._url,
            token=self._token,
            on_load=self._on_batch_load,
        )

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
        ipydisplay(self._demo_btn)
        ipydisplay(self._batch_panel.widget)
        ipydisplay(self._container)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------
    def _on_demo_load(self, _b) -> None:
        logger.info("Loading TRPL demo data from fixture...")
        with self._load_out:
            self._load_out.clear_output()
        self._data_ui_out.clear_output()

        success = self._data_manager.load_offline(DEMO_FIXTURE_PATH)

        with self._load_out:
            self._load_out.clear_output()
            if not success:
                ErrorHandler.log_error(
                    "Demo fixture contained no valid TRPL measurements.",
                    output_widget=self._load_out,
                )
                return
            ErrorHandler.log_success(
                "Loaded %d demo measurements." % len(self._data_manager.data),
                output_widget=self._load_out,
            )

        self._build_data_ui()

    def _on_batch_load(self, batch_selector: widgets.SelectMultiple) -> None:
        logger.info("Loading TRPL data...")
        with self._load_out:
            self._load_out.clear_output()

        self._data_ui_out.clear_output()

        success = self._data_manager.load(list(batch_selector.value))

        with self._load_out:
            self._load_out.clear_output()
            if not success:
                ErrorHandler.log_error(
                    "No TRPL measurements found in the selected batches.",
                    output_widget=self._load_out,
                )
                return
            ErrorHandler.log_success(
                "Loaded %d measurements." % len(self._data_manager.data),
                output_widget=self._load_out,
            )

        self._build_data_ui()

    def _build_data_ui(self) -> None:
        with self._data_ui_out:
            self._data_ui_out.clear_output()
            data_ui = gui.DataUI(self._data_manager)
            ipydisplay(data_ui.widget)
