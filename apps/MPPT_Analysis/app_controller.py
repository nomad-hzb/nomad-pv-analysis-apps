"""
Main application controller for MPPT Analysis App
"""

import logging
from pathlib import Path

import ipywidgets as widgets
from app_state import AppState
from data_manager import DataManager
from gui_components import GUIComponents
from IPython.display import display
from plot_manager import PlotManager

from hysprint_utils import plotting_utils

try:
    from hysprint_utils.config import API_ENDPOINT, URL_BASE
except ImportError:
    URL_BASE = "https://nomad-hzb-se.de"
    API_ENDPOINT = "/nomad-oasis/api/v1"
    logging.getLogger(__name__).warning(
        "hysprint_utils.config not found; using hardcoded URL fallback"
    )

logger = logging.getLogger(__name__)

_TESTS_ROOT = Path(__file__).parent.parent.parent / "tests"
DEMO_FIXTURE_PATH = _TESTS_ROOT / "MPPT_Analysis" / "fixtures" / "api_responses.json"


class MPPTAnalysisApp:
    """Main application controller that coordinates all components"""

    def __init__(self, token):
        url = f"{URL_BASE}{API_ENDPOINT}"
        # Initialize core components
        self.app_state = AppState()
        self.app_state.set_api_config(url, token)

        self.data_manager = DataManager(url, token)
        self.plot_manager = PlotManager(self.app_state, self.data_manager)

        # Pass self to GUI components so they can call our methods
        self.gui_components = GUIComponents(
            self.app_state, self.data_manager, self.plot_manager, self
        )  # noqa: E501

        self._demo_btn = widgets.Button(
            description="Load demo data",
            button_style="warning",
            icon="database",
        )
        self._demo_btn.on_click(self._on_demo_load)

        # UI components
        self.tab_widget = None
        self.setup_ui()

    def setup_ui(self):
        """Initialize the main UI with tabs"""
        self.tab_widget = widgets.Tab()

        # Create initial tabs
        batch_tab = self.gui_components.create_batch_tab()
        sample_tab = self.gui_components.create_disabled_tab(
            "Sample Selection",
            "This tab will be enabled after loading MPPT data from the Batch Selection tab.",
        )
        fitting_tab = self.gui_components.create_disabled_tab(
            "Curve Fitting", "This tab will be enabled after confirming sample selection."
        )
        plotting_tab = self.gui_components.create_disabled_tab(
            "Plotting", "This tab will be enabled after completing curve fitting."
        )
        download_tab = self.gui_components.create_disabled_tab(
            "Download Results", "This tab will be enabled after completing curve fitting."
        )

        self.tab_widget.children = [batch_tab, sample_tab, fitting_tab, plotting_tab, download_tab]
        self.tab_widget.titles = (
            "Batch Selection",
            "Sample Selection",
            "Curve Fitting",
            "Plotting",
            "Download Results",
        )  # noqa: E501

        # Lock tabs initially
        for i in [1, 2, 3, 4]:
            self.tab_widget.set_title(i, f"🔒 {self.tab_widget.get_title(i)}")

        # Display the interface
        display(self._demo_btn)
        display(plotting_utils.create_manual("mppt_manual.md"))
        display(self.tab_widget)

    def enable_sample_tab(self):
        """Enable the sample selection tab"""
        if not self.app_state.has_curves_data():
            return

        sample_tab = self.gui_components.create_sample_tab()

        current_children = list(self.tab_widget.children)
        current_children[1] = sample_tab
        self.tab_widget.children = current_children

        self.tab_widget.set_title(1, "Sample Selection")
        self.tab_widget.selected_index = 1

    def enable_fitting_tab(self):
        """Enable the fitting tab"""
        if not self.app_state.has_selected_samples():
            return

        fitting_tab = self.gui_components.create_fitting_tab()

        current_children = list(self.tab_widget.children)
        current_children[2] = fitting_tab
        self.tab_widget.children = current_children

        self.tab_widget.set_title(2, "Curve Fitting")
        self.tab_widget.selected_index = 2

    def enable_plotting_tab(self):
        """Enable the plotting tab"""
        if not self.app_state.has_fit_results():
            return

        plotting_tab = self.gui_components.create_plotting_tab()

        current_children = list(self.tab_widget.children)
        current_children[3] = plotting_tab
        self.tab_widget.children = current_children

        self.tab_widget.set_title(3, "Plotting")
        self.tab_widget.selected_index = 3

        # Also enable download tab
        self.enable_download_tab()

    def enable_download_tab(self):
        """Enable the download tab"""
        if not self.app_state.has_fit_results():
            return

        download_tab = self.gui_components.create_download_tab()

        current_children = list(self.tab_widget.children)
        current_children[4] = download_tab
        self.tab_widget.children = current_children

        self.tab_widget.set_title(4, "Download Results")

    def _on_demo_load(self, _b) -> None:
        success = self.data_manager.load_offline(DEMO_FIXTURE_PATH)
        if not success:
            logger.warning("Demo fixture contained no valid MPPT measurements.")
            return
        self.app_state.load_curves_data(
            self.data_manager.curves,
            self.data_manager.sample_ids,
            self.data_manager.entries,
            self.data_manager.properties,
        )
        logger.info("MPPT demo data loaded. %d sample(s).", len(self.data_manager.sample_ids))
        self.enable_sample_tab()


def create_mppt_app(token):
    """Factory function to create and initialize the MPPT Analysis App"""
    return MPPTAnalysisApp(token)
