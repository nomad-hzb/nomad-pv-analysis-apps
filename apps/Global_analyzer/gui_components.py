"""
GUI Components for HySprint Data Analysis Tool
Creates and manages all user interface widgets
"""

import ipywidgets as widgets
import plotly.graph_objects as go
from natsort import natsorted

from hysprint_utils.api_calls import get_batch_ids_with_authors
from hysprint_utils.plotting_utils import WidgetFactory


class GUIManager:
    """Manages all GUI widgets for the application."""

    def __init__(self):
        """Initialize all widgets."""
        self._create_widgets()

    def _create_widgets(self):
        """Create all GUI widgets."""
        # ====================================================================
        # BATCH SELECTION WIDGETS (Step 1)
        # ====================================================================
        # Populated by setup_batch_selection() once url/token are available.
        self._batch_records = []  # [{"lab_id": ..., "author_name": ...}, ...]
        self.author_filter = None
        self.search_box = None
        self.batch_selector = None
        self.load_batches_button = None
        self.step1_accordion = None

        # ====================================================================
        # DATA SOURCE SELECTORS
        # ====================================================================
        # Subbatch grouping checkbox
        self.group_by_subbatch = widgets.Checkbox(
            value=True,
            description="Group by subbatch (e.g., HZB_User_1_3 groups _C-1, _C-2, _C-3)",
            style={"description_width": "initial"},
            layout=widgets.Layout(width="95%", margin="10px 0px"),
        )

        self.x_data_source_selector = widgets.Dropdown(
            description="X Data Source:",
            style={"description_width": "120px"},
            layout={"width": "400px"},
            disabled=True,
        )

        self.y_data_source_selector = widgets.Dropdown(
            description="Y Data Source:",
            style={"description_width": "120px"},
            layout={"width": "400px"},
            disabled=True,
        )

        self.color_data_source_selector = widgets.Dropdown(
            description="Color Data Source:",
            style={"description_width": "120px"},
            layout={"width": "400px"},
            disabled=True,
        )

        # ====================================================================
        # MATERIAL/LAYER SELECTORS
        # ====================================================================
        self.x_material_selector = widgets.Dropdown(
            description="X Material:",
            options=["All"],
            value="All",
            style={"description_width": "120px"},
            layout={"width": "400px"},
            disabled=True,
        )

        self.y_material_selector = widgets.Dropdown(
            description="Y Material:",
            options=["All"],
            value="All",
            style={"description_width": "120px"},
            layout={"width": "400px"},
            disabled=True,
        )

        self.color_material_selector = widgets.Dropdown(
            description="Color Material:",
            options=["All"],
            value="All",
            style={"description_width": "120px"},
            layout={"width": "400px"},
            disabled=True,
        )

        # ====================================================================
        # PARAMETER SELECTORS
        # ====================================================================
        self.x_param_selector = widgets.Dropdown(
            description="X Parameter:",
            style={"description_width": "120px"},
            layout={"width": "400px"},
            disabled=True,
        )

        self.y_param_selector = widgets.Dropdown(
            description="Y Parameter:",
            style={"description_width": "120px"},
            layout={"width": "400px"},
            disabled=True,
        )

        self.color_param_selector = widgets.Dropdown(
            description="Color By:",
            style={"description_width": "120px"},
            layout={"width": "400px"},
            disabled=True,
        )

        # ====================================================================
        # PLOT CONFIGURATION
        # ====================================================================
        self.jv_aggregation_selector = widgets.Dropdown(
            options=["All Points", "Mean", "Max", "Min", "Median"],
            value="All Points",
            description="Data Display:",
            style={"description_width": "120px"},
            layout={"width": "400px"},
        )

        self.plot_type_selector = widgets.Dropdown(
            options=["Scatter", "Boxplot"],
            value="Scatter",
            description="Plot Type:",
            style={"description_width": "120px"},
            layout={"width": "400px"},
        )

        self.colorscale_selector = widgets.Dropdown(
            options=[
                # ── Colorscales ──
                "Viridis",
                "Plasma",
                "Inferno",
                "Magma",
                "Cividis",
                "Turbo",
                "RdBu",
                "Spectral",
                "Blues",
                "Reds",
                "YlOrRd",
                # ── Single colors ──
                "Blue",
                "Red",
                "Green",
                "Purple",
                "Orange",
                "Gray",
            ],
            value="Viridis",
            description="Color Scale:",
            style={"description_width": "120px"},
            layout={"width": "400px"},
        )

        self.show_varying_only = widgets.ToggleButton(
            value=False,
            description="Show Only Varying Parameters",
            tooltip="Filter to show only parameters that vary across samples",
        )

        self.create_plot_button = widgets.Button(
            description="Create Plot",
            button_style="success",
            icon="chart-line",
            layout={"width": "150px"},
        )

        self.debug_checkbox = widgets.Checkbox(
            value=False,
            description="Show plot data for debugging",
            style={"description_width": "initial"},
        )

        self.download_button = widgets.Button(
            description="Download CSV",
            button_style="info",
            icon="download",
            layout={"width": "150px"},
        )

        self.download_output = widgets.Output()

        self.click_output = widgets.Output(
            layout={
                "border": "1px solid #ddd",
                "padding": "4px",
                "min_height": "30px",
                "margin_top": "4px",
            }
        )

        # ====================================================================
        # OUTPUT WIDGETS
        # ====================================================================
        self.status_output = widgets.Output(
            layout={"border": "1px solid #ddd", "padding": "10px", "height": "150px"}
        )

        self.stats_output = widgets.Output(
            layout={"border": "1px solid #ddd", "padding": "10px", "height": "200px"}
        )

        self.param_summary_output = widgets.Output()

        # ====================================================================
        # CORRELATION MATRIX
        # ====================================================================
        self.correlation_min_unique = widgets.IntText(
            value=5,
            description="Min unique values:",
            tooltip="Only include numeric parameters with more than this many distinct values",
            style={"description_width": "140px"},
            layout={"width": "260px"},
        )

        self.find_correlations_button = widgets.Button(
            description="Find Correlations",
            button_style="success",
            icon="table",
            layout={"width": "180px"},
        )

        self.correlation_status_output = widgets.Output()

        self.correlation_widget = go.FigureWidget()
        self.correlation_widget.update_layout(
            height=600,
            template="plotly_white",
            title='Select data sources, then click "Find Correlations"',
        )

        # ====================================================================
        # RANDOM FOREST / BAYESIAN OPTIMIZATION PLACEHOLDER TABS
        # ====================================================================
        # No analysis logic lives here yet - these Output widgets are the hook
        # point for that future code, which should read from
        # self.data_manager.merged_data (the same dataset the Plotting tab uses).
        self.rf_output = widgets.Output()
        self.bo_output = widgets.Output()

        # ====================================================================
        # PLOT WIDGET
        # ====================================================================
        self.plot_widget = go.FigureWidget()
        self.plot_widget.update_layout(
            height=600, template="plotly_white", title='Select data and click "Create Plot"'
        )

    def connect_callbacks(self, callbacks: dict):
        """
        Connect widget callbacks to handler functions.

        Args:
            callbacks: Dictionary mapping widget names to callback functions
        """
        # Batch selection
        if "search_box" in callbacks:
            self.search_box.observe(callbacks["search_box"], names="value")
        if "author_filter" in callbacks:
            self.author_filter.observe(callbacks["author_filter"], names="value")
        if "load_batches" in callbacks:
            self.load_batches_button.on_click(callbacks["load_batches"])

        # Data sources
        if "x_data_source" in callbacks:
            self.x_data_source_selector.observe(callbacks["x_data_source"], names="value")
        if "y_data_source" in callbacks:
            self.y_data_source_selector.observe(callbacks["y_data_source"], names="value")
        if "color_data_source" in callbacks:
            self.color_data_source_selector.observe(callbacks["color_data_source"], names="value")

        # Materials
        if "x_material" in callbacks:
            self.x_material_selector.observe(callbacks["x_material"], names="value")
        if "y_material" in callbacks:
            self.y_material_selector.observe(callbacks["y_material"], names="value")
        if "color_material" in callbacks:
            self.color_material_selector.observe(callbacks["color_material"], names="value")

        # Plot controls
        if "create_plot" in callbacks:
            self.create_plot_button.on_click(callbacks["create_plot"])
        if "toggle_varying" in callbacks:
            self.show_varying_only.observe(callbacks["toggle_varying"], names="value")

        if "download" in callbacks:
            self.download_button.on_click(callbacks["download"])

        if "find_correlations" in callbacks:
            self.find_correlations_button.on_click(callbacks["find_correlations"])

    def setup_batch_selection(self, url, token, load_data_function):
        """
        Build the Step 1 batch-selection widgets: a "Filter by user" dropdown, a search
        box, the batch multi-select, and the load button.

        Not using hysprint_utils.batch_selection.create_batch_selection here (as most
        other apps do) because that shared helper has no concept of author filtering -
        adding it there would be a cross-cutting change to 12+ apps for a feature only
        this app needs. get_batch_ids_with_authors (also new) is additive to
        hysprint_utils and safe to share.
        """
        self._batch_records = get_batch_ids_with_authors(url, token)

        # Collapse subbatch duplicates the same way batch_selection.create_batch_selection
        # does: drop a record whose lab_id is exactly another record's lab_id minus its
        # trailing "_..." segment (i.e. keep only the top-level batch id).
        all_lab_ids = [r["lab_id"] for r in self._batch_records]
        records_by_lab_id = {}
        for record in self._batch_records:
            lab_id = record["lab_id"]
            if "_".join(lab_id.split("_")[:-1]) in all_lab_ids:
                continue
            records_by_lab_id[lab_id] = record

        self._batch_records = [records_by_lab_id[lab_id] for lab_id in natsorted(records_by_lab_id)]
        self._batch_ids_all = [r["lab_id"] for r in self._batch_records]

        author_names = sorted({r["author_name"] for r in self._batch_records})

        self.author_filter = widgets.Dropdown(
            options=["All"] + author_names,
            value="All",
            description="Filter by user:",
            style={"description_width": "initial"},
            layout=widgets.Layout(width="300px"),
        )

        self.search_box = widgets.Text(description="Search Batch")

        self.batch_selector = widgets.SelectMultiple(
            options=self._batch_ids_all,
            description="Batches",
            layout=widgets.Layout(width="400px", height="300px"),
        )

        self.load_batches_button = WidgetFactory.create_button(
            description="Load Data", button_style="primary"
        )

        def _apply_filters(*_args):
            search_term = self.search_box.value.strip().lower()
            author = self.author_filter.value
            filtered = [
                r["lab_id"]
                for r in self._batch_records
                if (author == "All" or r["author_name"] == author)
                and (not search_term or search_term in r["lab_id"].lower())
            ]
            self.batch_selector.options = natsorted(filtered)

        self.search_box.observe(_apply_filters, names="value")
        self.author_filter.observe(_apply_filters, names="value")
        self.load_batches_button.on_click(lambda b: load_data_function(self.batch_selector))

        return widgets.VBox(
            [self.author_filter, self.search_box, self.batch_selector, self.load_batches_button]
        )

    def create_layout(self) -> widgets.Widget:
        """Create the complete interface layout."""
        # Title
        title = widgets.HTML(
            "<h1 style='text-align: center; color: #2E86AB;'>HySprint Data Analysis Tool</h1>"
        )

        # Step 1: Batch Selection - full-width, collapsible (open by default)
        batch_selection_body = widgets.VBox(
            [self.author_filter, self.search_box, self.batch_selector, self.load_batches_button]
        )
        self.step1_accordion = widgets.Accordion(
            children=[batch_selection_body],
            titles=("Step 1: Select Batches",),
            layout={"width": "100%"},
        )
        self.step1_accordion.selected_index = 0  # Start open

        # Step 2: Data Sources
        step2 = widgets.VBox(
            [
                widgets.HTML("<h3 style='color: #A23B72;'>Step 2: Select Data Sources</h3>"),
                widgets.HTML("<h4 style='color: #666;'>X-Axis Data:</h4>"),
                self.group_by_subbatch,
                self.x_data_source_selector,
                self.x_material_selector,
                self.x_param_selector,
                widgets.HTML("<h4 style='color: #666;'>Y-Axis Data:</h4>"),
                self.y_data_source_selector,
                self.y_material_selector,
                self.y_param_selector,
                widgets.HTML("<h4 style='color: #666;'>Color Data:</h4>"),
                self.color_data_source_selector,
                self.color_material_selector,
                self.color_param_selector,
            ],
            layout={"width": "500px", "padding": "0px 20px 0px 0px"},
        )

        # Step 3: Plot Configuration
        step3 = widgets.VBox(
            [
                widgets.HTML("<h3 style='color: #A23B72;'>Step 3: Configure Plot</h3>"),
                self.plot_type_selector,
                self.jv_aggregation_selector,
                self.colorscale_selector,
                self.show_varying_only,
                self.debug_checkbox,
                widgets.HBox([self.create_plot_button, self.download_button]),
                self.download_output,
            ],
            layout={"width": "500px", "padding": "0px"},
        )

        # Steps 2 & 3 side by side ("x-layout")
        steps_2_and_3 = widgets.HBox([step2, step3])

        plotting_tab = widgets.VBox(
            [
                steps_2_and_3,
                widgets.HTML("<h3 style='color: #A23B72;'>Visualization</h3>"),
                self.plot_widget,
                self.click_output,
                widgets.HTML("<h3 style='color: #A23B72;'>Statistics</h3>"),
                self.stats_output,
            ],
            layout={"padding": "20px"},
        )

        parameter_summary_tab = widgets.VBox(
            [self.param_summary_output], layout={"padding": "20px"}
        )

        correlations_tab = widgets.VBox(
            [
                widgets.HTML(
                    "<p style='color:#666;'>Correlation matrix over every numeric parameter "
                    "in the currently loaded dataset (same data as the Plotting tab). "
                    "Parameters with too few distinct values (e.g. flags/constants) are "
                    "excluded via the threshold below.</p>"
                ),
                widgets.HBox([self.correlation_min_unique, self.find_correlations_button]),
                self.correlation_status_output,
                self.correlation_widget,
            ],
            layout={"padding": "20px"},
        )

        random_forest_tab = widgets.VBox(
            [
                widgets.HTML(
                    "<p style='color:#666;'><i>Random Forest analysis is not wired up yet. "
                    "It will read from the same dataset loaded in Step 1/2 "
                    "(<code>data_manager.merged_data</code>).</i></p>"
                ),
                self.rf_output,
            ],
            layout={"padding": "20px"},
        )

        bayesian_optimization_tab = widgets.VBox(
            [
                widgets.HTML(
                    "<p style='color:#666;'><i>Bayesian Optimization is not wired up yet. "
                    "It will read from the same dataset loaded in Step 1/2 "
                    "(<code>data_manager.merged_data</code>).</i></p>"
                ),
                self.bo_output,
            ],
            layout={"padding": "20px"},
        )

        self.main_tabs = widgets.Tab(
            children=[
                parameter_summary_tab,
                plotting_tab,
                correlations_tab,
                random_forest_tab,
                bayesian_optimization_tab,
            ]
        )
        self.main_tabs.set_title(0, "Parameter Summary")
        self.main_tabs.set_title(1, "Plotting")
        self.main_tabs.set_title(2, "Correlations")
        self.main_tabs.set_title(3, "Random Forest")
        self.main_tabs.set_title(4, "Bayesian Optimization")

        return widgets.VBox(
            [
                title,
                self.step1_accordion,
                widgets.HTML("<h3 style='color: #A23B72;'>Status</h3>"),
                self.status_output,
                self.main_tabs,
            ]
        )
