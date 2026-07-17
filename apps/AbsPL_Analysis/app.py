"""
app.py
Thin assembly layer. Wires auth, data, plots, and GUI panels together.
The notebook only needs to instantiate AbsPlApp and call .display().
"""

import logging
from pathlib import Path

import ipywidgets as widgets
from data_manager import MEASUREMENT_TYPE, AbsPlDataManager
from gui_components import (
    AdvancedPanel,
    BatchPanel,
    FilterPanel,
    PlottingPanel,
    SpectralPanel,
)
from hysprint_utils.auth_manager import AuthenticationManager
from hysprint_utils.plotting_utils import create_manual
from IPython.display import display as ipydisplay
from plot_manager import AbsPlPlotManager

logger = logging.getLogger(__name__)

_TESTS_ROOT = Path(__file__).parent.parent.parent / "tests"
DEMO_FIXTURE_PATH = _TESTS_ROOT / "AbsPL_Analysis" / "fixtures" / "api_responses.json"
class AbsPlApp:
    """
    Top-level application object.

    Usage in notebook:
        app = AbsPlApp(url_base, api_endpoint, token)
        app.display()
    """

    def __init__(
        self,
        url_base: str,
        api_endpoint: str,
        token: str,
        manual_file: str | None = None,
    ):
        self._auth = AuthenticationManager(url_base, api_endpoint)
        self._auth.authenticate_with_token(token)

        api_url = self._auth.api_client.get_api_url()
        self._data_manager = AbsPlDataManager(api_url, token)
        self._plot_manager = AbsPlPlotManager()
        self._manual_file = manual_file

        self._status_out = widgets.Output()
        self._dynamic_out = widgets.Output()
        self._demo_btn = widgets.Button(
            description="Load demo data",
            button_style="warning",
            icon="database",
        )
        self._demo_btn.on_click(self._on_demo_load)

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def display(self):
        """Build and display the full application UI."""
        batch_panel = BatchPanel(
            url=self._auth.api_client.get_api_url(),
            token=self._auth.current_token,
            on_load=self._on_load,
            measurement_type=MEASUREMENT_TYPE,
        )

        sections = []
        if self._manual_file:
            sections.append(create_manual(self._manual_file))
        sections += [self._demo_btn, batch_panel.widget, self._status_out, self._dynamic_out]

        ipydisplay(widgets.VBox(sections))

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _on_demo_load(self, _b) -> None:
        logger.info("Loading AbsPL demo data from fixture...")
        self._status_out.clear_output()
        self._dynamic_out.clear_output()
        success = self._data_manager.load_offline(DEMO_FIXTURE_PATH)
        if not success:
            logger.warning("Demo fixture contained no valid AbsPL measurements.")
            return
        logger.info("AbsPL demo data loaded. %s", self._data_manager.filter_summary)
        self._build_data_ui()

    def _on_load(self, batch_selector):
        """Called by BatchPanel when the user clicks 'Load Data'."""
        logger.info("Loading AbsPL data...")
        self._status_out.clear_output()

        success = self._data_manager.load(batch_selector.value)

        self._dynamic_out.clear_output()
        self._status_out.clear_output()

        if not success:
            logger.warning("No AbsPL measurements found in the selected batches.")
            return

        logger.info("Data loaded. %s", self._data_manager.filter_summary)

        self._build_data_ui()

    def _build_data_ui(self):
        """Assemble and display all data panels after a successful load."""
        dm = self._data_manager
        pm = self._plot_manager

        summary_out = widgets.Output()
        with summary_out:
            ipydisplay(dm.data.describe())

        ui = widgets.VBox(
            [
                widgets.HTML("<h3>Data Summary</h3>"),
                summary_out,
                widgets.HTML("<h3>Data Filtering</h3>"),
                FilterPanel(dm).widget,
                widgets.HTML("<h3>Plotting Tools</h3>"),
                PlottingPanel(dm, pm).widget,
                widgets.HTML("<h3>Spectral Plot</h3>"),
                SpectralPanel(dm, pm).widget,
                widgets.HTML("<h3>Advanced Analysis</h3>"),
                AdvancedPanel(dm, pm).widget,
            ]
        )

        with self._dynamic_out:
            ipydisplay(ui)
