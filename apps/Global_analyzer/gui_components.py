"""
GUI Components for HySprint Data Analysis Tool
Creates and manages all user interface widgets
"""

import config
import ipywidgets as widgets
import plotly.graph_objects as go
import utils
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

        self.boxplot_bin_toggle = widgets.Checkbox(
            value=False,
            description="Bin numeric X into groups (Boxplot only)",
            style={"description_width": "initial"},
        )

        self.boxplot_bin_count = widgets.BoundedIntText(
            value=5,
            min=2,
            max=20,
            description="Bins:",
            style={"description_width": "50px"},
            layout={"width": "150px"},
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

        # ====================================================================
        # PLOT PRESETS
        # ====================================================================
        self.preset_buttons: dict = {}
        self.preset_accordion = self._create_preset_widgets()

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
        # ANALYSIS DATA (shared by Correlations / Random Forest / Bayesian Optimization)
        # ====================================================================
        self.results_checklist_box = widgets.VBox(
            layout={
                "max_height": "220px",
                "overflow_y": "auto",
                "border": "1px solid #ddd",
                "padding": "4px",
            }
        )
        self.metadata_checklist_box = widgets.VBox(
            layout={
                "max_height": "220px",
                "overflow_y": "auto",
                "border": "1px solid #ddd",
                "padding": "4px",
            }
        )
        self.recalculate_button = widgets.Button(
            description="Recalculate",
            button_style="success",
            icon="refresh",
            layout={"width": "160px"},
        )
        self.variation_warning_output = widgets.Output()
        self.analysis_data_status_output = widgets.Output()

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

        self.correlation_plot_type = widgets.Dropdown(
            options=["Heatmap", "Scatter Matrix"],
            value="Heatmap",
            description="Format:",
            style={"description_width": "70px"},
            layout={"width": "220px"},
        )

        self.find_correlations_button = widgets.Button(
            description="Find Correlations",
            button_style="success",
            icon="table",
            layout={"width": "180px"},
        )

        self.correlation_download_button = widgets.Button(
            description="Download CSV",
            button_style="info",
            icon="download",
            layout={"width": "150px"},
        )

        self.correlation_status_output = widgets.Output()

        self.correlation_widget = go.FigureWidget()
        self.correlation_widget.update_layout(
            height=600,
            template="plotly_white",
            title='Select data sources, then click "Find Correlations"',
        )

        self.correlation_scatter_output = widgets.Output()

        # ====================================================================
        # RANDOM FOREST
        # ====================================================================
        self.rf_target_selector = widgets.Dropdown(
            description="Target:",
            style={"description_width": "100px"},
            layout={"width": "350px"},
            disabled=True,
        )

        self.run_rf_button = widgets.Button(
            description="Run Random Forest",
            button_style="success",
            icon="tree",
            layout={"width": "200px"},
        )

        self.rf_download_button = widgets.Button(
            description="Download CSV",
            button_style="info",
            icon="download",
            layout={"width": "150px"},
        )

        self.rf_output = widgets.Output()

        self.rf_widget = go.FigureWidget()
        self.rf_widget.update_layout(
            height=450,
            template="plotly_white",
            title='Pick a target and click "Run Random Forest"',
        )

        # ====================================================================
        # BAYESIAN OPTIMIZATION
        # ====================================================================
        self.bo_target_selector = widgets.Dropdown(
            description="Target:",
            style={"description_width": "100px"},
            layout={"width": "350px"},
            disabled=True,
        )

        self.bo_direction_selector = widgets.Dropdown(
            options=["Maximize", "Minimize"],
            value="Maximize",
            description="Goal:",
            style={"description_width": "100px"},
            layout={"width": "200px"},
        )

        self.suggest_experiments_button = widgets.Button(
            description="Suggest Next Experiments",
            button_style="success",
            icon="lightbulb-o",
            layout={"width": "220px"},
        )

        self.bo_download_button = widgets.Button(
            description="Download CSV",
            button_style="info",
            icon="download",
            layout={"width": "150px"},
        )

        self.bo_output = widgets.Output()

        self.bo_widget = go.FigureWidget()
        self.bo_widget.update_layout(
            height=450,
            template="plotly_white",
            title='Pick a target and click "Suggest Next Experiments"',
        )

        # ====================================================================
        # EXPERIMENTAL: PCA
        # ====================================================================
        self.experimental_pca_color_selector = widgets.Dropdown(
            description="Color by:",
            style={"description_width": "100px"},
            layout={"width": "350px"},
        )

        self.experimental_pca_run_button = widgets.Button(
            description="Run PCA",
            button_style="success",
            icon="compress",
            layout={"width": "160px"},
        )

        self.experimental_pca_output = widgets.Output()

        self.experimental_pca_widget = go.FigureWidget()
        self.experimental_pca_widget.update_layout(
            height=500, template="plotly_white", title='Click "Run PCA"'
        )

        # ====================================================================
        # EXPERIMENTAL: PARETO FRONT
        # ====================================================================
        self.experimental_pareto_target_a_selector = widgets.Dropdown(
            description="Target A:",
            style={"description_width": "100px"},
            layout={"width": "300px"},
            disabled=True,
        )
        self.experimental_pareto_direction_a_selector = widgets.Dropdown(
            options=["Maximize", "Minimize"],
            value="Maximize",
            description="Goal A:",
            style={"description_width": "80px"},
            layout={"width": "180px"},
        )
        self.experimental_pareto_target_b_selector = widgets.Dropdown(
            description="Target B:",
            style={"description_width": "100px"},
            layout={"width": "300px"},
            disabled=True,
        )
        self.experimental_pareto_direction_b_selector = widgets.Dropdown(
            options=["Maximize", "Minimize"],
            value="Maximize",
            description="Goal B:",
            style={"description_width": "80px"},
            layout={"width": "180px"},
        )

        self.experimental_pareto_run_button = widgets.Button(
            description="Find Pareto Front",
            button_style="success",
            icon="balance-scale",
            layout={"width": "180px"},
        )

        self.experimental_pareto_output = widgets.Output()

        self.experimental_pareto_widget = go.FigureWidget()
        self.experimental_pareto_widget.update_layout(
            height=500,
            template="plotly_white",
            title='Pick two targets and click "Find Pareto Front"',
        )

        # ====================================================================
        # EXPERIMENTAL: OUTLIER DETECTION
        # ====================================================================
        self.experimental_outlier_contamination_selector = widgets.BoundedFloatText(
            value=0.05,
            min=0.01,
            max=0.5,
            step=0.01,
            description="Contamination:",
            style={"description_width": "110px"},
            layout={"width": "220px"},
        )

        self.experimental_outlier_run_button = widgets.Button(
            description="Detect Outliers",
            button_style="success",
            icon="search",
            layout={"width": "180px"},
        )

        self.experimental_outlier_output = widgets.Output()

        self.experimental_outlier_widget = go.FigureWidget()
        self.experimental_outlier_widget.update_layout(
            height=500, template="plotly_white", title='Click "Detect Outliers"'
        )

        # ====================================================================
        # EXPERIMENTAL: PROCESS DRIFT
        # ====================================================================
        self.experimental_drift_param_selector = widgets.Dropdown(
            description="Parameter:",
            style={"description_width": "100px"},
            layout={"width": "350px"},
            disabled=True,
        )

        self.experimental_drift_run_button = widgets.Button(
            description="Check Drift",
            button_style="success",
            icon="line-chart",
            layout={"width": "160px"},
        )

        self.experimental_drift_output = widgets.Output()

        self.experimental_drift_widget = go.FigureWidget()
        self.experimental_drift_widget.update_layout(
            height=450, template="plotly_white", title='Pick a parameter and click "Check Drift"'
        )

        # ====================================================================
        # EXPERIMENTAL: ANOVA
        # ====================================================================
        self.experimental_anova_group_selector = widgets.Dropdown(
            description="Group by:",
            style={"description_width": "100px"},
            layout={"width": "350px"},
            disabled=True,
        )
        self.experimental_anova_value_selector = widgets.Dropdown(
            description="Measure:",
            style={"description_width": "100px"},
            layout={"width": "350px"},
            disabled=True,
        )

        self.experimental_anova_run_button = widgets.Button(
            description="Run ANOVA",
            button_style="success",
            icon="calculator",
            layout={"width": "160px"},
        )

        self.experimental_anova_output = widgets.Output()

        self.experimental_anova_widget = go.FigureWidget()
        self.experimental_anova_widget.update_layout(
            height=450,
            template="plotly_white",
            title='Pick a group and measure, then click "Run ANOVA"',
        )

        # ====================================================================
        # PLOT WIDGET
        # ====================================================================
        self.plot_widget = go.FigureWidget()
        self.plot_widget.update_layout(
            height=600, template="plotly_white", title='Select data and click "Create Plot"'
        )

    def _create_preset_widgets(self) -> widgets.Accordion:
        """Build one button per config.PRESET_PLOTS entry, in a collapsible
        Accordion that starts open (a discovery aid, not something to hide once used).
        """
        buttons = []
        for preset in config.PRESET_PLOTS:
            button = widgets.Button(
                description=preset["label"],
                button_style="info",
                icon="bolt",
                layout={"width": "auto"},
            )
            self.preset_buttons[preset["id"]] = button
            buttons.append(button)

        # flex_flow "row wrap" + align_items "flex-start" - without these a
        # Box's children stretch to the full container width by default, which
        # turns short preset buttons into full-width bars.
        button_row = widgets.HBox(
            buttons, layout={"flex_flow": "row wrap", "align_items": "flex-start", "gap": "8px"}
        )
        accordion = widgets.Accordion(
            children=[button_row],
            titles=("Plot Presets",),
        )
        accordion.selected_index = 0  # Start open
        return accordion

    def connect_preset_callbacks(self, handler):
        """Wire each preset button to `handler(preset_dict)`."""
        presets_by_id = {preset["id"]: preset for preset in config.PRESET_PLOTS}
        for preset_id, button in self.preset_buttons.items():
            preset = presets_by_id[preset_id]
            button.on_click(lambda _button, preset=preset: handler(preset))

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

        if "run_random_forest" in callbacks:
            self.run_rf_button.on_click(callbacks["run_random_forest"])
        if "suggest_experiments" in callbacks:
            self.suggest_experiments_button.on_click(callbacks["suggest_experiments"])
        if "recalculate_analysis_data" in callbacks:
            self.recalculate_button.on_click(callbacks["recalculate_analysis_data"])
        if "download_correlations" in callbacks:
            self.correlation_download_button.on_click(callbacks["download_correlations"])
        if "download_rf_results" in callbacks:
            self.rf_download_button.on_click(callbacks["download_rf_results"])
        if "download_bo_suggestions" in callbacks:
            self.bo_download_button.on_click(callbacks["download_bo_suggestions"])

        # Experimental tab
        if "run_pca" in callbacks:
            self.experimental_pca_run_button.on_click(callbacks["run_pca"])
        if "find_pareto_front" in callbacks:
            self.experimental_pareto_run_button.on_click(callbacks["find_pareto_front"])
        if "detect_outliers" in callbacks:
            self.experimental_outlier_run_button.on_click(callbacks["detect_outliers"])
        if "compute_process_drift" in callbacks:
            self.experimental_drift_run_button.on_click(callbacks["compute_process_drift"])
        if "run_anova" in callbacks:
            self.experimental_anova_run_button.on_click(callbacks["run_anova"])

    def set_analysis_columns(self, results_cols: list, metadata_cols: list):
        """(Re)build the Results / Process Metadata checkbox lists on the Analysis
        Data tab, all checked by default. Called whenever the shared analysis
        dataframe is rebuilt (batch load or Recalculate)."""
        self.results_checklist_box.children = [
            widgets.Checkbox(value=True, description=col, indent=False) for col in results_cols
        ]
        self.metadata_checklist_box.children = [
            widgets.Checkbox(value=True, description=col, indent=False) for col in metadata_cols
        ]

    def get_checked_results_columns(self) -> list:
        """Column names currently checked in the Results checklist."""
        return [cb.description for cb in self.results_checklist_box.children if cb.value]

    def get_checked_metadata_columns(self) -> list:
        """Column names currently checked in the Process Metadata checklist."""
        return [cb.description for cb in self.metadata_checklist_box.children if cb.value]

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
                self.show_varying_only,
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
                widgets.HBox([self.boxplot_bin_toggle, self.boxplot_bin_count]),
                self.jv_aggregation_selector,
                self.colorscale_selector,
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
                self.preset_accordion,
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

        analysis_data_tab = widgets.VBox(
            [
                widgets.HTML(
                    "<p style='color:#666;'>This is the full dataset loaded on the Parameter "
                    "Summary/Plotting tabs (independent of what's currently selected there), "
                    "and it feeds Correlations, Random Forest, and Bayesian Optimization. "
                    "<b>Targets are always measurement results; supporting variables are "
                    "always process metadata.</b> Uncheck any column you want excluded from "
                    "all three, then click Recalculate.</p>"
                ),
                widgets.Accordion(
                    children=[
                        widgets.VBox(
                            [
                                widgets.HTML("<h4 style='color: #666;'>Results (targets)</h4>"),
                                self.results_checklist_box,
                                widgets.HTML(
                                    "<h4 style='color: #666;'>Process Metadata (supporting)</h4>"
                                ),
                                self.metadata_checklist_box,
                            ]
                        )
                    ],
                    titles=("Variable Selection",),
                    selected_index=0,
                ),
                self.variation_warning_output,
                self.recalculate_button,
                self.analysis_data_status_output,
            ],
            layout={"padding": "20px"},
        )

        correlations_tab = widgets.VBox(
            [
                widgets.HTML(
                    "<p style='color:#666;'>Cross-correlation between the checked Results "
                    "(x-axis) and checked Process Metadata (y-axis) columns from the "
                    "Analysis Data tab. Parameters with too few distinct values (e.g. "
                    "flags/constants) are excluded via the threshold below.</p>"
                    "<p style='color:#444;'><b>Why it helps:</b> a quick way to spot which "
                    "process settings tend to move together with your results - a strong "
                    "correlation is a hint (not proof) of a relationship worth testing "
                    "deliberately.</p>"
                    "<p style='color:#888; font-size:0.9em;'>Learn more: "
                    '<a href="https://en.wikipedia.org/wiki/Correlation" target="_blank">'
                    "Correlation (Wikipedia)</a></p>"
                ),
                widgets.HBox(
                    [
                        self.correlation_min_unique,
                        self.correlation_plot_type,
                        self.find_correlations_button,
                        self.correlation_download_button,
                    ]
                ),
                self.correlation_status_output,
                self.correlation_widget,
                self.correlation_scatter_output,
                self.download_output,
            ],
            layout={"padding": "20px"},
        )

        doe_user = utils.get_current_user()
        doe_uploads_path = utils.get_uploads_path()
        doe_voila_url = utils.build_doe_voila_url(doe_user, doe_uploads_path)
        doe_full_url = utils.build_doe_full_url(doe_voila_url)

        random_forest_tab = widgets.VBox(
            [
                widgets.HTML(
                    "<p style='color:#666;'>Fits a Random Forest to predict the chosen "
                    "target (a Results column) from the checked Process Metadata columns "
                    "in the Analysis Data tab, and reports which parameters matter most.</p>"
                    "<p style='color:#444;'><b>Why it helps:</b> tells you which process "
                    "parameters matter most for your outcome - useful for deciding what to "
                    "control tightly during fabrication and what to deprioritize.</p>"
                    "<p style='color:#888; font-size:0.9em;'>Learn more: "
                    '<a href="https://en.wikipedia.org/wiki/Random_forest" target="_blank">'
                    "Random forest (Wikipedia)</a></p>"
                ),
                widgets.HTML(
                    f'<p><a href="{doe_voila_url}" target="_blank" title="{doe_full_url}">'
                    "Open Design of Experiments tool</a> to plan the next batch of "
                    "samples based on these results.</p>"
                ),
                widgets.HBox(
                    [self.rf_target_selector, self.run_rf_button, self.rf_download_button]
                ),
                self.rf_output,
                self.rf_widget,
                self.download_output,
            ],
            layout={"padding": "20px"},
        )

        bayesian_optimization_tab = widgets.VBox(
            [
                widgets.HTML(
                    "<p style='color:#666;'>Fits a Gaussian Process surrogate model on "
                    "the checked Process Metadata columns in the Analysis Data tab and "
                    "suggests parameter combinations most likely to improve the chosen "
                    "target (a Results column) next.</p>"
                    "<p style='color:#666;'><b>This is a stateless, single-shot "
                    "suggester, not a closed-loop optimizer</b> - it does not remember "
                    "past suggestions or track which experiments came from which round. "
                    "Re-run it after each new batch of real measurements comes in. If "
                    "you need to track optimization rounds over time, that would need "
                    "e.g. a 'round' sample tag added to the data - not implemented "
                    "here.</p>"
                    "<p style='color:#444;'><b>Why it helps:</b> suggests which parameter "
                    "combination to try next to improve your target, usually reaching a "
                    "good result in far fewer experiments than a full grid search.</p>"
                    "<p style='color:#888; font-size:0.9em;'>Learn more: "
                    '<a href="https://en.wikipedia.org/wiki/Bayesian_optimization" target="_blank">'
                    "Bayesian optimization (Wikipedia)</a></p>"
                ),
                widgets.HBox(
                    [
                        self.bo_target_selector,
                        self.bo_direction_selector,
                        self.suggest_experiments_button,
                        self.bo_download_button,
                    ]
                ),
                self.bo_output,
                self.bo_widget,
                self.download_output,
            ],
            layout={"padding": "20px"},
        )

        experimental_intro = widgets.HTML(
            "<p style='color:#666;'><b>Experimental</b> - first-look tools being "
            "evaluated for usefulness on this data. Not yet promoted to top-level "
            "tabs; behavior/UI here may change or disappear. All read from the "
            "shared Analysis Data tab.</p>"
        )

        experimental_pca_tab = widgets.VBox(
            [
                widgets.HTML(
                    "<p style='color:#666;'>PCA over the checked Process Metadata "
                    "columns - shows which process parameters vary/cluster "
                    "together.</p>"
                    "<p style='color:#444;'><b>Why it helps:</b> spots redundant knobs "
                    "(e.g. two temperatures that always move together) and can reveal "
                    "batches with a similar overall process 'fingerprint' at a glance.</p>"
                    "<p style='color:#888; font-size:0.9em;'>Learn more: "
                    '<a href="https://en.wikipedia.org/wiki/Principal_component_analysis" '
                    'target="_blank">Principal component analysis (Wikipedia)</a></p>'
                ),
                widgets.HBox(
                    [self.experimental_pca_color_selector, self.experimental_pca_run_button]
                ),
                self.experimental_pca_output,
                self.experimental_pca_widget,
            ],
            layout={"padding": "20px"},
        )

        experimental_pareto_tab = widgets.VBox(
            [
                widgets.HTML(
                    "<p style='color:#666;'>Finds the Pareto-optimal trade-off "
                    "between two checked Results columns - points where you can't "
                    "improve one without making the other worse.</p>"
                    "<p style='color:#444;'><b>Why it helps:</b> highlights the best "
                    "trade-off samples between two competing goals (e.g. efficiency vs. "
                    "stability) - the front tells you what's actually achievable "
                    "together, not just what's best for each goal individually.</p>"
                    "<p style='color:#888; font-size:0.9em;'>Learn more: "
                    '<a href="https://en.wikipedia.org/wiki/Pareto_front" target="_blank">'
                    "Pareto front (Wikipedia)</a></p>"
                ),
                widgets.HBox(
                    [
                        self.experimental_pareto_target_a_selector,
                        self.experimental_pareto_direction_a_selector,
                    ]
                ),
                widgets.HBox(
                    [
                        self.experimental_pareto_target_b_selector,
                        self.experimental_pareto_direction_b_selector,
                    ]
                ),
                self.experimental_pareto_run_button,
                self.experimental_pareto_output,
                self.experimental_pareto_widget,
            ],
            layout={"padding": "20px"},
        )

        experimental_outlier_tab = widgets.VBox(
            [
                widgets.HTML(
                    "<p style='color:#666;'>Isolation Forest over the checked "
                    "Process Metadata + Results columns combined - flags samples "
                    "whose overall parameter/result combination looks unusual, "
                    "not just single-column extremes.</p>"
                    "<p style='color:#444;'><b>Why it helps:</b> a fast way to catch "
                    "mismeasured, mislabeled, or genuinely anomalous samples before they "
                    "skew a correlation, Random Forest, or other analysis downstream.</p>"
                    "<p style='color:#888; font-size:0.9em;'>Learn more: "
                    '<a href="https://en.wikipedia.org/wiki/Isolation_forest" target="_blank">'
                    "Isolation forest (Wikipedia)</a></p>"
                ),
                widgets.HBox(
                    [
                        self.experimental_outlier_contamination_selector,
                        self.experimental_outlier_run_button,
                    ]
                ),
                self.experimental_outlier_output,
                self.experimental_outlier_widget,
            ],
            layout={"padding": "20px"},
        )

        experimental_drift_tab = widgets.VBox(
            [
                widgets.HTML(
                    "<p style='color:#666;'>Checks whether a checked Process "
                    "Metadata parameter trends up or down over time (parsed from "
                    "the raw datetime field).</p>"
                    "<p style='color:#444;'><b>Why it helps:</b> catches tool drift, "
                    "calibration issues, or slow environmental changes before they show "
                    "up as an unexplained dip in yield.</p>"
                    "<p style='color:#888; font-size:0.9em;'>Learn more: "
                    '<a href="https://en.wikipedia.org/wiki/Trend_estimation" target="_blank">'
                    "Trend estimation (Wikipedia)</a></p>"
                ),
                widgets.HBox(
                    [self.experimental_drift_param_selector, self.experimental_drift_run_button]
                ),
                self.experimental_drift_output,
                self.experimental_drift_widget,
            ],
            layout={"padding": "20px"},
        )

        experimental_anova_tab = widgets.VBox(
            [
                widgets.HTML(
                    "<p style='color:#666;'>One-way ANOVA: does a checked Results "
                    "column differ significantly across groups of a categorical "
                    "process metadata column (e.g. layer material)?</p>"
                    "<p style='color:#444;'><b>Why it helps:</b> tells you whether a "
                    "categorical choice (e.g. which material or which tool) makes a "
                    "statistically real difference in your results, or whether the "
                    "difference you're seeing is just noise.</p>"
                    "<p style='color:#888; font-size:0.9em;'>Learn more: "
                    '<a href="https://en.wikipedia.org/wiki/Analysis_of_variance" '
                    'target="_blank">Analysis of variance (Wikipedia)</a></p>'
                ),
                widgets.HBox(
                    [self.experimental_anova_group_selector, self.experimental_anova_value_selector]
                ),
                self.experimental_anova_run_button,
                self.experimental_anova_output,
                self.experimental_anova_widget,
            ],
            layout={"padding": "20px"},
        )

        experimental_sub_tabs = widgets.Tab(
            children=[
                experimental_pca_tab,
                experimental_pareto_tab,
                experimental_outlier_tab,
                experimental_drift_tab,
                experimental_anova_tab,
            ]
        )
        experimental_sub_tabs.set_title(0, "PCA")
        experimental_sub_tabs.set_title(1, "Pareto Front")
        experimental_sub_tabs.set_title(2, "Outlier Detection")
        experimental_sub_tabs.set_title(3, "Process Drift")
        experimental_sub_tabs.set_title(4, "ANOVA")

        experimental_tab = widgets.VBox(
            [experimental_intro, experimental_sub_tabs], layout={"padding": "20px"}
        )

        self.main_tabs = widgets.Tab(
            children=[
                parameter_summary_tab,
                plotting_tab,
                analysis_data_tab,
                correlations_tab,
                random_forest_tab,
                bayesian_optimization_tab,
                experimental_tab,
            ]
        )
        self.main_tabs.set_title(0, "Parameter Summary")
        self.main_tabs.set_title(1, "Plotting")
        self.main_tabs.set_title(2, "Analysis Data")
        self.main_tabs.set_title(3, "Correlations")
        self.main_tabs.set_title(4, "Random Forest")
        self.main_tabs.set_title(5, "Bayesian Optimization")
        self.main_tabs.set_title(6, "Experimental")

        return widgets.VBox(
            [
                title,
                self.step1_accordion,
                widgets.HTML("<h3 style='color: #A23B72;'>Status</h3>"),
                self.status_output,
                self.main_tabs,
            ]
        )
