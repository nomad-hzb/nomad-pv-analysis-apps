"""app.py -- thin assembly layer; no business logic here."""

from __future__ import annotations

import logging
from pathlib import Path

import data_manager as dm_module
import gui_components
import ipywidgets as widgets
from hysprint_utils.auth_manager import AuthenticationManager
from hysprint_utils.error_handler import ErrorHandler
from hysprint_utils.plotting_utils import create_manual
from IPython.display import display as ipydisplay

logger = logging.getLogger(__name__)

_TESTS_ROOT = Path(__file__).parent.parent.parent / "tests"
DEMO_FIXTURE_PATH = _TESTS_ROOT / "EQE_Analysis" / "fixtures" / "api_responses.json"
class EQEApp:
    def __init__(
        self,
        url_base: str,
        api_endpoint: str,
        token: str,
        manual_file: str | None = None,
    ):
        self._auth = AuthenticationManager(url_base, api_endpoint)
        self._auth.authenticate_with_token(token)
        self._url = self._auth.api_client.get_api_url()
        self._token = self._auth.current_token
        self._manual_file = manual_file

        self._dm = dm_module.EQEDataManager()
        self._status_out = widgets.Output()
        self._data_area = widgets.Output()
        self._demo_btn = widgets.Button(
            description="Load demo data",
            button_style="warning",
            icon="database",
        )
        self._demo_btn.on_click(self._on_demo_load)

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def display(self):
        batch_panel = gui_components.BatchPanel(
            url=self._url,
            token=self._token,
            on_load=self._on_load,
            measurement_type=dm_module.MEASUREMENT_TYPE,
        )
        sections = []
        if self._manual_file:
            sections.append(create_manual(self._manual_file))
        sections += [self._demo_btn, batch_panel.widget, self._status_out, self._data_area]
        ipydisplay(widgets.VBox(sections))

    # ------------------------------------------------------------------
    # Internal callbacks
    # ------------------------------------------------------------------

    def _on_demo_load(self, _b) -> None:
        logger.info("Loading EQE demo data from fixture...")
        self._status_out.clear_output()
        self._data_area.clear_output()
        success = self._dm.load_offline(DEMO_FIXTURE_PATH)
        if not success:
            logger.warning("Demo fixture contained no valid EQE measurements.")
            return
        logger.info("EQE demo data loaded.")
        self._build_data_ui()

    def _on_load(self, batch_ids_selector) -> None:
        logger.info("Loading EQE data...")
        self._status_out.clear_output()
        self._data_area.clear_output()

        try:
            success = self._dm.load(self._url, self._token, batch_ids_selector.value)
        except Exception as exc:
            ErrorHandler.log_error("Data load failed", exc, self._status_out, show_traceback=True)
            return

        self._status_out.clear_output()
        if not success:
            logger.warning("The selected batches contain no EQE measurements.")
            return
        logger.info("EQE data loaded.")

        self._build_data_ui()

    def _build_data_ui(self) -> None:
        variables_panel = gui_components.VariablesPanel(self._dm)
        curve_panel = gui_components.CurvePlotPanel(self._dm)
        box_panel = gui_components.BoxPlotPanel(self._dm)
        download_panel = gui_components.DownloadPanel(self._dm)

        tabs = widgets.Tab(
            children=[
                variables_panel.widget,
                curve_panel.widget,
                box_panel.widget,
                download_panel.widget,
            ]
        )
        for i, title in enumerate(["Dataset Names", "EQE Curves", "Boxplot", "Download"]):
            tabs.set_title(i, title)

        def _on_tab_change(change):
            if change["new"] in (1, 2):
                variables_panel.apply()
            if change["new"] == 1:
                curve_panel.refresh()
            elif change["new"] == 2:
                box_panel.refresh()

        tabs.observe(_on_tab_change, names=["selected_index"])

        # Pre-render both plot panels now so their Output widgets are populated
        # before the user first visits those tabs (avoids blank-on-first-visit).
        variables_panel.apply()
        curve_panel.refresh()
        box_panel.refresh()

        with self._data_area:
            self._data_area.clear_output()
            ipydisplay(tabs)
