"""
Sample Data Explorer - Main Application Module

This module provides the main interactive data analysis interface for exploring
sample measurement data from NOMAD OASIS. It combines GUI components, data
management, and plotting capabilities into a cohesive Jupyter-based application.

Key Features:
    - Interactive batch and sample selection
    - Multi-axis data visualization (X, Y, Color)
    - Material and layer type filtering
    - Process step parameter exploration
    - Real-time plot generation with Plotly

Classes:
    SampleDataExplorer: Main application controller coordinating all components

Usage:
    from app import SampleDataExplorer

    analyzer = SampleDataExplorer(url, token)
    analyzer.display()

Author: HySprint Team
"""

import logging
import traceback
from typing import List, Optional

import config
import ml_analysis as ml
import pandas as pd
from analysis_data_handlers import AnalysisDataHandlersMixin
from analysis_handlers import AnalysisHandlersMixin
from data_loader import HySprintDataLoader
from data_manager import (
    DataManager,
    get_categorical_columns,
    get_layer_type_options,
    merge_results_per_sample,
    merged_result_column_names,
    process_type_label,
    samples_with_several_rows,
    select_layer_row_per_sample,
    uploaded_numeric_columns,
)
from gui_components import GUIManager
from IPython.display import Markdown, clear_output
from IPython.display import display as ipy_display
from natsort import natsorted
from plot_manager import PlotManager
from utils import ParameterManager, ProcessStepManager, trigger_csv_download

from hysprint_utils.api_calls import (
    get_all_eqe,
    get_batch_ids,
    get_ids_in_batch,
    get_processing_steps,
    get_sample_description,
    get_sample_entry_links,
)

logger = logging.getLogger(__name__)


class SampleDataExplorer(AnalysisDataHandlersMixin, AnalysisHandlersMixin):
    """Main analyzer class that coordinates all modules."""

    def __init__(self, url: str, token: str):
        """
        Initialize the analyzer.

        Args:
            url: API base URL
            token: Authentication token
        """
        self.url = url
        self.token = token

        # Initialize managers
        self.gui = GUIManager()

        # Setup batch selection using batch_selection.py
        self.gui.setup_batch_selection(url, token, self._on_load_batches)

        self.param_manager = ParameterManager()
        self.process_manager = ProcessStepManager()
        self.data_loader = HySprintDataLoader(url, token, get_all_eqe)
        self.data_manager = DataManager(self.data_loader, self.param_manager)
        self.plot_manager = PlotManager(
            self.gui.plot_widget,
            self.gui.stats_output,
            self.gui.correlation_widget,
            self.gui.rf_widget,
            self.gui.bo_widget,
            self.gui.correlation_scatter_output,
            self.gui.experimental_pca_widget,
            self.gui.experimental_pareto_widget,
            self.gui.experimental_outlier_widget,
            self.gui.experimental_drift_widget,
            self.gui.experimental_anova_widget,
            bo_loo_widget=self.gui.bo_loo_widget,
            rf_pdp_output=self.gui.rf_pdp_output,
        )
        self.plot_manager.column_resolver = self.data_manager.resolve_result_column

        # Application state
        self.current_batches = []
        self.current_sample_ids = []
        self.current_variation = {}
        self.processing_steps = []
        self.process_display_to_id = {}

        # Shared analysis dataset (Analysis Data / Correlations / RF / BO tabs).
        # full_analysis_df is the complete merged dataset; analysis_df is the
        # view every downstream tab actually reads, after row_filters are
        # applied - keeping both means a filter can be removed without
        # re-fetching or re-merging anything.
        self.full_analysis_df = None
        self.analysis_df = None
        self.analysis_metadata_cols = []
        self.analysis_results_cols = []
        # {column in the merged results table: result schema label, e.g. "JV"};
        # drives the grouped Results tree in the Analysis Data tab.
        self.analysis_results_groups: dict = {}
        # Same for process metadata columns ("Spin Coating", ...).
        self.analysis_metadata_groups: dict = {}
        # row_filters is what the Filters tab shows (staged); the applied copies are what
        # every tab reads, and only change when the user clicks Confirm filters.
        self.row_filters: list = []  # [{"id", "column", "op", "value"}, ...]
        self._applied_filters: list = []
        self._applied_excluded: set = set()
        self._next_filter_id = 1
        self._last_correlation_result = None
        self._last_rf_result = None
        self._last_bo_result = None
        self._collapsed_result_types = []
        self.analysis_categorical_cols = []
        # A user-uploaded CSV (issue #40) replaces the NOMAD-built dataset until
        # the next batch load; kept separately so Recalculate re-applies it
        # instead of rebuilding from (possibly empty) NOMAD data.
        self._uploaded_df = None
        self._updating_upload_roles = False

        # Connect callbacks
        self._connect_callbacks()

    def _connect_callbacks(self):
        """Connect GUI callbacks to handler methods."""
        self.gui.connect_callbacks(
            {
                "x_data_source": self._on_x_data_source_selected,
                "y_data_source": self._on_y_data_source_selected,
                "color_data_source": self._on_color_data_source_selected,
                "x_material": self._on_x_material_selected,
                "y_material": self._on_y_material_selected,
                "color_material": self._on_color_material_selected,
                "create_plot": self._on_create_plot,
                "toggle_varying": self._on_toggle_varying_only,
                "download": self._on_download_data,
                "find_correlations": self._on_find_correlations,
                "run_random_forest": self._on_run_random_forest,
                "suggest_experiments": self._on_suggest_experiments,
                "recalculate_analysis_data": self._on_recalculate_analysis_data,
                "upload_analysis_csv": self._on_upload_analysis_csv,
                "upload_results_columns_changed": self._on_upload_results_columns_changed,
                "add_row_filter": self._on_add_row_filter,
                "confirm_filters": self._on_confirm_filters,
                "download_analysis_data_preview": self._on_download_analysis_data_preview,
                "download_correlations": self._on_download_correlations,
                "download_rf_results": self._on_download_rf_results,
                "download_bo_suggestions": self._on_download_bo_suggestions,
                "run_pca": self._on_run_pca,
                "find_pareto_front": self._on_find_pareto_front,
                "detect_outliers": self._on_detect_outliers,
                "compute_process_drift": self._on_compute_process_drift,
                "run_anova": self._on_run_anova,
            }
        )
        self.gui.connect_preset_callbacks(self._apply_preset)

    def _update_status(self, message: str):
        """Update status message."""
        with self.gui.status_output:
            clear_output()
            print(message)

    def _refresh_parameter_summary(self):
        """Rebuild and re-render the Parameter Summary tab as Markdown.

        Always clears first - this is called once explicitly after a batch load and
        again from every data-source/material selection change (each of which can
        itself trigger more than one of these calls via ipywidgets' auto-select-first-
        option behavior), so without clearing the summary would render 2-3x in a row.
        """
        markdown_text = self.data_manager.build_parameter_summary_markdown()
        with self.gui.param_summary_output:
            clear_output(wait=True)
            ipy_display(Markdown(markdown_text))

    def _refresh_ml_target_options(self):
        """Keep the Random Forest / Bayesian Optimization target dropdowns in sync
        with the checked Results columns from the Analysis Data tab, preferring an
        efficiency-like column as the default target.

        Targets are always drawn from analysis_results_cols (measurement results),
        never analysis_metadata_cols (process metadata) - enforces "targets are
        always results" at the UI level. Restricted to the currently checked
        subset so unchecking a result column there also removes it as a target
        option.
        """
        checked_results = set(self.gui.get_checked_results_columns())
        numeric_cols = sorted(col for col in self.analysis_results_cols if col in checked_results)

        for selector in (self.gui.rf_target_selector, self.gui.bo_target_selector):
            previous_value = selector.value
            selector.options = numeric_cols
            selector.disabled = not numeric_cols
            if not numeric_cols:
                continue
            if previous_value in numeric_cols:
                selector.value = previous_value
            else:
                default = next((c for c in numeric_cols if "efficiency" in c.lower()), None)
                selector.value = default if default else numeric_cols[0]

        other_selectors = [self.gui.bo_pareto_target] + [
            column for _, column, _, _ in self.gui.bo_constraint_rows
        ]
        for selector in other_selectors:
            previous_value = selector.value
            selector.options = numeric_cols
            if previous_value in numeric_cols:
                selector.value = previous_value

        self._refresh_bo_search_space()

    def _refresh_bo_search_space(self):
        """Rebuild the BO tab's search-space rows for the checked Process
        Metadata columns, defaulting each to its observed range and to integer
        when every measured value is a whole number. Columns listed in
        config.MEASURED_PARAMETERS (logged conditions, not settings) start
        fixed at their median."""
        if self.analysis_df is None or self.analysis_df.empty:
            self.gui.set_bo_search_space([])
            return
        checked_metadata = set(self.gui.get_checked_metadata_columns())
        cols = [
            c
            for c in self.analysis_metadata_cols
            if c in checked_metadata and c in self.analysis_df.columns
        ]
        integer_cols = set(ml.detect_integer_columns(self.analysis_df, cols))
        defaults = []
        for col in cols:
            values = pd.to_numeric(self.analysis_df[col], errors="coerce").dropna()
            if values.empty:
                continue
            defaults.append(
                {
                    "col": col,
                    "min": float(values.min()),
                    "max": float(values.max()),
                    "integer": col in integer_cols,
                    "measured": ml.is_measured_parameter(col, config.MEASURED_PARAMETERS),
                    "median": float(values.median()),
                }
            )
        for col in self.gui.get_checked_categorical_columns():
            if col == "batch" or col not in self.analysis_df.columns:
                continue
            levels = sorted(self.analysis_df[col].dropna().astype(str).unique())
            if len(levels) > 1:
                defaults.append({"col": col, "levels": levels})
        self.gui.set_bo_search_space(defaults)

    def _build_process_dataframe(self) -> Optional[pd.DataFrame]:
        """Outer-merge every process/preparation metadata type currently loaded
        (data_manager.current_metadata) into one row-per-sample_id dataframe.

        A source that logs one row per fabrication layer per sample (Spin
        Coating: ETL, Active Layer, HTL, ...) is first cut down to the single
        layer_type the user picked in the Analysis Data tab's Layer Selection
        controls - otherwise a sample's one result would get joined against
        every one of its layers' rows, duplicating it under unrelated layers'
        parameters (issue #34 follow-up).

        Deliberately independent of data_manager.merged_data / the Plotting tab's
        X/Y/Color selections - a common plotting workflow (e.g. Voc vs efficiency,
        both "Results") never selects a metadata data source for any axis, which
        would leave merged_data with zero process parameters even though
        current_metadata is already fully loaded. Shared by
        _rebuild_full_analysis_dataframe, which feeds the Analysis Data /
        Correlations / Random Forest / Bayesian Optimization tabs.
        """
        if not self.data_manager.current_metadata:
            return None

        layer_selections = self.gui.get_layer_selections()
        process_df = None
        self.analysis_metadata_groups = {}
        for metadata_type, metadata_df in self.data_manager.current_metadata.items():
            if metadata_df is None or metadata_df.empty or "sample_id" not in metadata_df.columns:
                continue
            metadata_df = select_layer_row_per_sample(
                metadata_df, layer_selections.get(metadata_type)
            )
            if metadata_df.empty:
                continue
            if process_df is None:
                renamed = {c: c for c in metadata_df.columns if c != "sample_id"}
                process_df = metadata_df.copy()
            else:
                renamed = merged_result_column_names(
                    process_df.columns, metadata_df.columns, metadata_type
                )
                # Suffix by process type (not a generic "_dup") - the same column name
                # (e.g. layer_material_name) means something different per process
                # type (ETL vs HTL material), so it must survive as a distinct feature,
                # matching the suffixing DataManager.rebuild_merged_data already uses.
                process_df = pd.merge(
                    process_df,
                    metadata_df,
                    on="sample_id",
                    how="outer",
                    suffixes=("", f"_{metadata_type}"),
                )
            for merged_name in renamed.values():
                self.analysis_metadata_groups[merged_name] = process_type_label(metadata_type)

        return process_df

    def _build_results_dataframe(self) -> Optional[pd.DataFrame]:
        """Outer-merge every measurement result type currently loaded
        (data_manager.current_results) into one row-per-sample_id dataframe,
        analogous to _build_process_dataframe but for results. Multiple rows per
        sample_id within a single result type (e.g. multiple JV pixels) are
        collapsed to one via the Analysis Data tab's chosen aggregation method
        (Mean/Median/Max) - unlike the process-metadata side, these really are
        repeated measurements of the same thing, so aggregating (not selecting
        one) is the right operation. With "All Points", only one result type
        keeps its individual rows (see merge_results_per_sample).

        Also carries the first non-null 'datetime' per sample_id through
        (dropped by the numeric-only aggregation otherwise) - measurement
        results commonly have a timestamp (see the "top_level_fields" list
        results are loaded with), and it's the Experimental tab's Process
        Drift tool's only source for one, since not every process-metadata
        loader captures it.
        """
        self._collapsed_result_types = []
        if not self.data_manager.current_results:
            return None

        self.analysis_results_groups = {}
        results_df, self._collapsed_result_types = merge_results_per_sample(
            self.data_manager.current_results,
            self.gui.results_aggregation_selector.value,
            column_groups=self.analysis_results_groups,
        )
        return results_df

    def _rebuild_full_analysis_dataframe(self):
        """Build the shared dataset behind the Analysis Data / Correlations / RF /
        BO tabs: an inner join of every process/preparation parameter with every
        measurement result, on sample_id. Populates self.analysis_df and the
        checked-by-default Results/Process Metadata column lists shown in the
        Analysis Data tab's checkboxes, and refreshes the variation-count warning.
        An uploaded CSV, while active, is re-applied instead.
        """
        if self._uploaded_df is not None:
            self._apply_uploaded_dataset()
            return

        self.gui.set_layer_selectors(get_layer_type_options(self.data_manager.current_metadata))

        process_df = self._build_process_dataframe()
        self._multi_row_samples = samples_with_several_rows(process_df)
        results_df = self._build_results_dataframe()

        if process_df is None or results_df is None:
            self.full_analysis_df = None
            self.analysis_metadata_cols = []
            self.analysis_results_cols = []
            self.analysis_results_groups = {}
            self.analysis_metadata_groups = {}
            self.analysis_categorical_cols = []
        else:
            combined = pd.merge(
                process_df, results_df, on="sample_id", how="inner", suffixes=("", "_result")
            )
            metadata_numeric = set(process_df.select_dtypes(include="number").columns)
            results_numeric = set(results_df.select_dtypes(include="number").columns)

            self.full_analysis_df = combined
            self.analysis_metadata_cols = [
                col
                for col in combined.select_dtypes(include="number").columns
                if col in metadata_numeric and combined[col].dropna().nunique() > 1
            ]
            self.analysis_results_cols = [
                col
                for col in combined.select_dtypes(include="number").columns
                if col in results_numeric and combined[col].dropna().nunique() > 1
            ]
            # Text-valued process parameters (material, solvent, batch, ...).
            process_text = set(process_df.select_dtypes(include="object").columns)
            self.analysis_categorical_cols = [
                c for c in get_categorical_columns(combined) if c in process_text
            ]

        self.gui.set_analysis_columns(
            self.analysis_results_cols,
            self.analysis_metadata_cols,
            results_groups=self.analysis_results_groups,
            metadata_groups=self.analysis_metadata_groups,
            categorical_cols=self.analysis_categorical_cols,
        )
        sample_ids = (
            sorted(self.full_analysis_df["sample_id"].unique())
            if self.full_analysis_df is not None
            else []
        )
        self.gui.set_sample_exclusion_checklist(sample_ids, self._on_sample_exclusion_toggled)
        self._applied_excluded = set()  # a rebuilt checklist starts with every sample included
        self._apply_filters()
        self._refresh_variation_warning()

    def _apply_uploaded_dataset(self):
        """Make the uploaded CSV the shared analysis dataset: the columns picked
        in the Result columns selector become Results, every other usable
        numeric column becomes Process Metadata (never both, so a column can't
        end up predicting itself or appear twice in the scatter matrix)."""
        df = self._uploaded_df
        numeric_cols = uploaded_numeric_columns(df)
        results = set(self.gui.analysis_data_upload_results_selector.value)

        self.full_analysis_df = df
        self.analysis_results_cols = [c for c in numeric_cols if c in results]
        self.analysis_metadata_cols = [c for c in numeric_cols if c not in results]
        self.analysis_results_groups = {}
        self.analysis_metadata_groups = {}
        self.analysis_categorical_cols = get_categorical_columns(df)
        self.gui.set_layer_selectors({})
        self.gui.set_analysis_columns(
            self.analysis_results_cols,
            self.analysis_metadata_cols,
            categorical_cols=self.analysis_categorical_cols,
        )
        sample_ids = sorted(df["sample_id"].unique())
        self.gui.set_sample_exclusion_checklist(sample_ids, self._on_sample_exclusion_toggled)
        self._apply_filters()
        self._refresh_variation_warning()

    def _rerun_active_analyses(self):
        """Re-run whichever of Correlations/RF/BO already produced a result, so
        Recalculate and row-filter changes visibly update whatever the user
        has open without requiring a trip back through each tab's own button."""
        if getattr(self, "_plot_created", False):
            self._on_create_plot(None)
        if self._last_correlation_result is not None:
            self._on_find_correlations(None)
        if self._last_rf_result is not None:
            self._on_run_random_forest(None)
        if self._last_bo_result is not None:
            self._on_suggest_experiments(None)

    def _initialize_batch_options(self):
        """Initialize batch options from API."""
        try:
            all_batch_ids = get_batch_ids(self.url, self.token)
            self.gui.batch_selector.options = natsorted(all_batch_ids)
            self._update_status("✓ Batch options loaded. Select batches to continue.")
        except Exception as e:
            self._update_status(f"❌ Error loading batches: {str(e)}")

    def _filter_batches(self, change):
        """Filter batches based on search term."""
        search_term = change["new"].lower()
        try:
            all_batch_ids = get_batch_ids(self.url, self.token)
            if search_term:
                filtered = [b for b in all_batch_ids if search_term in b.lower()]
            else:
                filtered = all_batch_ids
            self.gui.batch_selector.options = natsorted(filtered)
        except Exception as e:
            self._update_status(f"❌ Error filtering batches: {str(e)}")

    def _on_load_batches(self, button):
        """Handle batch loading."""
        if not self.gui.batch_selector.value:
            self._update_status("⚠️ Please select at least one batch.")
            return

        # Clear old data (including an uploaded CSV, which a batch load replaces)
        self.data_manager.current_results = {}
        self.data_manager.current_metadata = {}
        self._uploaded_df = None
        self.gui.analysis_data_upload_roles_box.layout.display = "none"
        with self.gui.analysis_data_upload_output:
            clear_output()

        self.gui.plot_widget.data = []
        self.gui.plot_widget.update_layout(title='Select data and click "Create Plot"')
        for sel in [
            self.gui.x_param_selector,
            self.gui.y_param_selector,
            self.gui.color_param_selector,
        ]:
            sel.options = []
            sel.disabled = True
        for sel in [
            self.gui.x_material_selector,
            self.gui.y_material_selector,
            self.gui.color_material_selector,
        ]:
            sel.options = ["All"]
            sel.disabled = True

        self._update_status(f"⏳ Loading {len(self.gui.batch_selector.value)} batches...")

        try:
            # Get batch data
            self.current_batches = list(self.gui.batch_selector.value)
            self.current_sample_ids = get_ids_in_batch(self.url, self.token, self.current_batches)
            # the "batch" column is the batch each sample was selected from
            self.data_manager.sample_batch = {}
            for batch_id in self.current_batches:
                for sample_id in get_ids_in_batch(self.url, self.token, [batch_id]):
                    self.data_manager.sample_batch.setdefault(sample_id, batch_id)

            if not self.current_sample_ids:
                self._update_status("❌ No samples found in selected batches.")
                return

            self.current_variation = get_sample_description(
                self.url, self.token, self.current_sample_ids
            )
            self.processing_steps = get_processing_steps(
                self.url, self.token, self.current_sample_ids
            )

            self.data_manager.sample_entry_links = get_sample_entry_links(
                self.url, self.token, self.current_sample_ids
            )

            # Extract process types
            process_types = self.process_manager.extract_process_types(self.processing_steps)

            self.process_display_to_id = {display: original for display, original in process_types}
            display_names = [display for display, _ in process_types]

            # Update data source selectors
            all_options = ["Results"] + sorted(display_names)

            self.gui.x_data_source_selector.options = all_options
            self.gui.x_data_source_selector.disabled = False

            self.gui.y_data_source_selector.options = all_options
            self.gui.y_data_source_selector.disabled = False
            # NOTE: do NOT set .value = 'Results' here — data not loaded yet

            self.gui.color_data_source_selector.options = ["None"] + all_options
            self.gui.color_data_source_selector.disabled = False
            self.gui.color_data_source_selector.value = "None"

            # Load all data for summary FIRST
            self._update_status("⏳ Loading all data for summary...")
            self.data_manager.load_all_data_for_summary(
                self.current_sample_ids, self.current_variation
            )

            # Now set default Y to Results — current_results is populated
            self.gui.y_data_source_selector.value = "Results"

            # Generate parameter summary
            self._refresh_parameter_summary()
            self._rebuild_full_analysis_dataframe()
            self._refresh_ml_target_options()
            self._refresh_experimental_options()

            self._update_status(
                f"✓ Loaded {len(self.current_sample_ids)} samples with "
                f"{len(display_names)} process types. Select data sources."
            )

            # Collapse Step 1 now that batches are loaded, to free up space.
            self.gui.step1_accordion.selected_index = None

        except Exception as e:
            self._update_status(f"❌ Error loading batches: {str(e)}")
            logger.exception("Error loading batches")

    def _on_x_data_source_selected(self, change):
        """Handle X data source selection."""
        if not change["new"]:
            return
        self._load_data_for_source(change["new"], "x")

    def _on_y_data_source_selected(self, change):
        """Handle Y data source selection."""
        if not change["new"]:
            return
        self._load_data_for_source(change["new"], "y")

    def _on_color_data_source_selected(self, change):
        """Handle Color data source selection."""
        if not change["new"] or change["new"] == "None":
            return
        self._load_data_for_source(change["new"], "color")

    def _load_data_for_source(self, data_source: str, param_type: str):
        """Load data for a selected data source."""
        logger.debug(
            "_load_data_for_source: data_source=%s, param_type=%s", data_source, param_type
        )
        self._update_status(f"⏳ Loading data for {param_type.upper()} from: {data_source}...")

        try:
            if data_source == "Results":
                # Load results if not already loaded. Always goes through
                # DataManager.load_all_data_for_summary (the one place this
                # extraction logic lives - it validates rows via MeasurementRow
                # and expands multi-row measurements, e.g. multiple JV scan
                # directions/pixels) rather than duplicating that logic here.
                # This matters because the X/Y data-source dropdowns default
                # to "Results" as soon as their options are assigned (an
                # ipywidgets Dropdown auto-selects the first option when it
                # had none before), which fires this method *before*
                # _on_load_batches gets a chance to call
                # load_all_data_for_summary itself - a second, independent
                # results-loading implementation here previously won that
                # race every time, so the more thorough loader never ran.
                if not self.data_manager.current_results:
                    self.data_manager.load_all_data_for_summary(
                        self.current_sample_ids, self.current_variation
                    )
                else:
                    logger.debug(
                        "Results already loaded: %d measurement types",
                        len(self.data_manager.current_results),
                    )

                # Show measurement types in material selector
                measurement_types_list = list(self.data_manager.current_results.keys())
                logger.debug("Available measurement types: %s", measurement_types_list)

                measurement_display_names = []
                for mt in measurement_types_list:
                    if mt == "jv_measurement":
                        measurement_display_names.append("JV")
                    elif mt == "eqe_measurement":
                        measurement_display_names.append("EQE")
                    elif mt == "mpp_tracking":
                        measurement_display_names.append("MPP")
                    elif mt == "simple_mpp_tracking":
                        measurement_display_names.append("Simple MPP")
                    elif mt == "pl_measurement":
                        measurement_display_names.append("PL")
                    elif mt == "trpl_measurement":
                        measurement_display_names.append("TRPL")
                    elif mt == "abspl_measurement":
                        measurement_display_names.append("AbsPL")
                    elif mt == "pl_imaging":
                        measurement_display_names.append("PL Imaging")
                    elif mt == "sem":
                        measurement_display_names.append("SEM")
                    elif mt == "uvvis_measurement":
                        measurement_display_names.append("UV-Vis")
                    elif mt == "pes":
                        measurement_display_names.append("PES")
                    elif mt == "cyclic_voltammetry":
                        measurement_display_names.append("CV")
                    elif mt == "eis":
                        measurement_display_names.append("EIS")
                    elif mt == "trspv_measurement":
                        measurement_display_names.append("trSPV")
                    elif mt == "nmr":
                        measurement_display_names.append("NMR")
                    elif mt == "xrd":
                        measurement_display_names.append("XRD")
                    else:
                        measurement_display_names.append(mt.replace("_", " ").title())

                logger.debug("Display names: %s", measurement_display_names)
                self._set_material_selector_options(
                    param_type, sorted(measurement_display_names), data_source
                )

                if sorted(measurement_display_names):
                    first_measurement = sorted(measurement_display_names)[0]
                    logger.debug("Auto-selecting first measurement type: %s", first_measurement)
                    if param_type == "x":
                        self.gui.x_material_selector.value = first_measurement
                    elif param_type == "y":
                        self.gui.y_material_selector.value = first_measurement
                    else:
                        self.gui.color_material_selector.value = first_measurement
                else:
                    # Fallback: show all parameters
                    params = self.data_manager.get_parameter_options(
                        self.data_manager.current_results,
                        f"{param_type}_parameters",
                        is_results=True,
                    )
                    self._update_parameter_selector(param_type, params, is_results=True)

            else:
                # Process step data source
                logger.debug("Process step branch: %s", data_source)

                metadata_df = self.data_manager.load_data_for_source(
                    data_source,
                    self.current_sample_ids,
                    self.current_variation,
                    self.process_manager,
                )
                logger.debug(
                    "Metadata loaded, shape: %s",
                    metadata_df.shape if metadata_df is not None else None,
                )

                # Extract materials
                materials = self.data_manager.extract_materials(metadata_df, data_source)
                logger.debug("Materials extracted: %s", materials)
                self._set_material_selector_options(param_type, materials, data_source)

                # Update parameter options
                params = self.data_manager.get_parameter_options(
                    {data_source: metadata_df}, f"{param_type}_parameters", is_results=False
                )
                logger.debug("Got %d parameters: %s", len(params), params[:5] if params else [])
                self._update_parameter_selector(param_type, params, is_results=False)

            # Rebuild merged data
            self._rebuild_merged_data()

        except Exception as e:
            self._update_status(f"❌ Error loading data: {str(e)}")
            logger.exception("Error loading data")

    def _set_material_selector_options(self, param_type: str, materials: list, data_source: str):
        """Set material selector options and immediately populate parameters."""
        logger.debug(
            "_set_material_selector_options: param_type=%s, data_source=%s, materials=%s",
            param_type,
            data_source,
            materials,
        )

        if param_type == "x":
            selector = self.gui.x_material_selector
        elif param_type == "y":
            selector = self.gui.y_material_selector
        else:
            selector = self.gui.color_material_selector

        if materials:
            if data_source == "Results":
                # For Results: materials list = measurement display names (JV, EQE, etc.)
                selector.options = materials
                selector.value = materials[0]
                selector.disabled = False
                if param_type == "x":
                    self.data_manager._x_material_is_all = False
                elif param_type == "y":
                    self.data_manager._y_material_is_all = False
                else:
                    self.data_manager._color_material_is_all = False

                # Directly populate parameters — do NOT rely on observer firing,
                # because value may already equal materials[0] from a previous run.
                self._filter_results_parameters(param_type, materials[0])

            else:
                # For process steps: add 'All' option
                selector.options = ["All"] + materials
                selector.value = "All"
                selector.disabled = False
                if param_type == "x":
                    self.data_manager._x_material_is_all = True
                elif param_type == "y":
                    self.data_manager._y_material_is_all = True
                else:
                    self.data_manager._color_material_is_all = True

                # Populate parameters with 'All' selected (includes Material Type option)
                pm = ProcessStepManager()
                measurement_type = pm.map_display_to_measurement_type(data_source)
                if measurement_type and measurement_type in self.data_manager.current_metadata:
                    metadata_df = self.data_manager.current_metadata[measurement_type]
                    params = self.data_manager.get_parameter_options(
                        {data_source: metadata_df}, f"{param_type}_parameters", is_results=False
                    )
                    self._update_parameter_selector(param_type, params, is_results=False)
        else:
            selector.options = ["All"]
            selector.value = "All"
            selector.disabled = True
            if param_type == "x":
                self.data_manager._x_material_is_all = True
            elif param_type == "y":
                self.data_manager._y_material_is_all = True
            else:
                self.data_manager._color_material_is_all = True

        logger.debug(
            "_set_material_selector_options end: disabled=%s, options=%s",
            selector.disabled,
            list(selector.options)[:5],
        )

    def _update_parameter_selector(self, param_type: str, params: List[str], is_results: bool):
        """Update parameter selector with available parameters."""
        logger.debug(
            "_update_parameter_selector: param_type=%s, count=%d, is_results=%s",
            param_type,
            len(params),
            is_results,
        )

        if param_type == "x":
            selector = self.gui.x_param_selector
        elif param_type == "y":
            selector = self.gui.y_param_selector
        else:
            selector = self.gui.color_param_selector

        selector.options = params if param_type != "color" else ["None"] + params
        selector.disabled = False

        if params:
            if param_type == "x":
                selector.value = params[0]
            elif param_type == "y":
                eff = next((p for p in params if "efficiency" in p.lower()), None)
                selector.value = eff if eff else params[0]
            else:  # color
                selector.value = "None"

    def _on_x_material_selected(self, change):
        """Handle X material selection."""
        logger.debug(
            "_on_x_material_selected: new=%s, source=%s",
            change["new"],
            self.gui.x_data_source_selector.value,
        )

        if not change["new"]:
            return

        # Set flag for "All" selection
        self.data_manager._x_material_is_all = change["new"] == "All"

        # If Results data source, filter parameters by selected measurement type
        if self.gui.x_data_source_selector.value == "Results":
            self._filter_results_parameters("x", change["new"])

        self._rebuild_merged_data()

    def _on_y_material_selected(self, change):
        """Handle Y material selection."""
        logger.debug(
            "_on_y_material_selected: new=%s, source=%s",
            change["new"],
            self.gui.y_data_source_selector.value,
        )

        if not change["new"]:
            return

        # Set flag for "All" selection
        self.data_manager._y_material_is_all = change["new"] == "All"

        # If Results data source, filter parameters by selected measurement type
        if self.gui.y_data_source_selector.value == "Results":
            self._filter_results_parameters("y", change["new"])

        self._rebuild_merged_data()

    def _on_color_material_selected(self, change):
        """Handle Color material selection."""
        logger.debug(
            "_on_color_material_selected: new=%s, source=%s",
            change["new"],
            self.gui.color_data_source_selector.value,
        )

        if not change["new"]:
            return

        # Set flag for "All" selection
        self.data_manager._color_material_is_all = change["new"] == "All"

        # If Results data source, filter parameters by selected measurement type
        if self.gui.color_data_source_selector.value == "Results":
            self._filter_results_parameters("color", change["new"])

        self._rebuild_merged_data()

    def _filter_results_parameters(self, param_type: str, measurement_display_name: str):
        """Filter parameters to show only those from the selected measurement type."""
        logger.debug(
            "_filter_results_parameters: param_type=%s, measurement=%s, keys=%s",
            param_type,
            measurement_display_name,
            list(self.data_manager.current_results.keys()),
        )

        display_to_key = {
            "JV": "jv_measurement",
            "EQE": "eqe_measurement",
            "MPP": "mpp_tracking",
            "Simple MPP": "simple_mpp_tracking",
            "PL": "pl_measurement",
            "TRPL": "trpl_measurement",
            "AbsPL": "abspl_measurement",
            "PL Imaging": "pl_imaging",
            "SEM": "sem",
            "UV-Vis": "uvvis_measurement",
            "PES": "pes",
            "CV": "cyclic_voltammetry",
            "EIS": "eis",
            "trSPV": "trspv_measurement",
            "NMR": "nmr",
            "XRD": "xrd",
        }

        measurement_key = display_to_key.get(measurement_display_name)
        logger.debug("measurement_key resolved to: %s", measurement_key)

        if measurement_key and measurement_key in self.data_manager.current_results:
            df = self.data_manager.current_results[measurement_key]
            single_measurement = {measurement_key: df}
            params = self.data_manager.get_parameter_options(
                single_measurement, f"{param_type}_parameters", is_results=True
            )
        else:
            logger.debug("Measurement key not found in current_results — showing all")
            params = self.data_manager.get_parameter_options(
                self.data_manager.current_results, f"{param_type}_parameters", is_results=True
            )

        logger.debug("Final params count: %d", len(params))
        self._update_parameter_selector(param_type, params, is_results=True)

    def _rebuild_merged_data(self):
        """Rebuild merged data with current selections."""
        invalid_samples = self.data_manager.rebuild_merged_data(
            self.gui.x_data_source_selector.value,
            self.gui.y_data_source_selector.value,
            self.gui.color_data_source_selector.value,
            self.gui.x_material_selector.value,
            self.gui.y_material_selector.value,
            self.gui.color_material_selector.value,
            group_by_subbatch=self.gui.group_by_subbatch.value,
        )

        # Show warning if invalid sample IDs were found
        if invalid_samples:
            with self.gui.status_output:
                print(f"⚠️  {len(invalid_samples)} samples excluded (non-standard ID pattern)")

        # Update parameter summary
        self._refresh_parameter_summary()
        self._refresh_ml_target_options()
        self._refresh_experimental_options()

    def _on_toggle_varying_only(self, change):
        """Handle toggle for showing only varying parameters."""
        if self.data_manager.merged_data is None:
            return

        if change["new"]:
            self._apply_varying_filter()
            self.gui.show_varying_only.button_style = "success"
            self.gui.show_varying_only.icon = "check"
        else:
            # Reload full parameter lists
            self._reload_all_parameters()
            self.gui.show_varying_only.button_style = ""
            self.gui.show_varying_only.icon = ""

    def _apply_varying_filter(self):
        """Filter to show only varying parameters."""
        if self.data_manager.merged_data is None:
            return

        current_x = list(self.gui.x_param_selector.options)
        current_y = list(self.gui.y_param_selector.options)
        current_color = [c for c in self.gui.color_param_selector.options if c != "None"]

        varying_x = self.param_manager.filter_to_varying_only(
            current_x, self.data_manager.merged_data
        )
        varying_y = self.param_manager.filter_to_varying_only(
            current_y, self.data_manager.merged_data
        )
        varying_color = self.param_manager.filter_to_varying_only(
            current_color, self.data_manager.merged_data
        )

        self.gui.x_param_selector.options = varying_x
        self.gui.y_param_selector.options = varying_y
        self.gui.color_param_selector.options = ["None"] + varying_color

        # Update values if needed
        if self.gui.x_param_selector.value not in varying_x and varying_x:
            self.gui.x_param_selector.value = varying_x[0]
        if self.gui.y_param_selector.value not in varying_y and varying_y:
            self.gui.y_param_selector.value = varying_y[0]
        if self.gui.color_param_selector.value not in ["None"] + varying_color:
            self.gui.color_param_selector.value = "None"

    def _reload_all_parameters(self):
        """Reload full parameter lists (undo varying filter)."""
        # Trigger reload by re-selecting current data sources
        if self.gui.x_data_source_selector.value:
            self._load_data_for_source(self.gui.x_data_source_selector.value, "x")
        if self.gui.y_data_source_selector.value:
            self._load_data_for_source(self.gui.y_data_source_selector.value, "y")
        if (
            self.gui.color_data_source_selector.value
            and self.gui.color_data_source_selector.value != "None"
        ):
            self._load_data_for_source(self.gui.color_data_source_selector.value, "color")

    def _apply_preset(self, preset: dict):
        """Apply a config.PRESET_PLOTS entry by driving the same selectors/methods
        the manual dropdown flow uses, then creating the plot.

        Sets each selector's .value directly rather than relying on ipywidgets'
        change-event firing (a preset may set a dropdown to the value it already
        holds, which does not fire an observer), so every axis is force-refreshed
        via the same internal methods the observers call.

        A "source" of "any_metadata" (used for e.g. batch/Material Type, which
        don't depend on which specific process type they're read from) resolves
        to whichever process-metadata data source happens to be loaded for this
        batch - the actual process types available vary per NOMAD upload.
        Values not actually present in a selector's options (e.g. a metadata
        parameter this dataset doesn't have) are skipped with a warning rather
        than raising, since presets are meant to work across differently-shaped
        datasets on a best-effort basis.
        """
        if not self.current_sample_ids:
            self._update_status("⚠️ Load batches before applying a preset plot.")
            return

        skipped = []
        for axis in ("x", "y", "color"):
            axis_cfg = preset.get(axis)
            data_source_sel = getattr(self.gui, f"{axis}_data_source_selector")
            material_sel = getattr(self.gui, f"{axis}_material_selector")
            param_sel = getattr(self.gui, f"{axis}_param_selector")

            if axis_cfg is None:
                if axis == "color" and "None" in data_source_sel.options:
                    data_source_sel.value = "None"
                    # _on_create_plot keys off color_param_selector.value, not
                    # the data source - reset it too, or a "no color" preset
                    # can silently inherit whatever was last selected.
                    if "None" in param_sel.options:
                        param_sel.value = "None"
                continue

            source = axis_cfg["source"]
            if source == "any_metadata":
                metadata_options = [
                    opt for opt in data_source_sel.options if opt not in ("None", "Results")
                ]
                if not metadata_options:
                    skipped.append(
                        f"{axis.upper()} ({axis_cfg['param']} - no process metadata loaded)"
                    )
                    continue
                source = metadata_options[0]

            if source not in data_source_sel.options:
                skipped.append(f"{axis.upper()} ({source} not available)")
                continue

            data_source_sel.value = source
            self._load_data_for_source(source, axis)

            if axis_cfg["material"] in material_sel.options:
                material_sel.value = axis_cfg["material"]
            if source == "Results":
                self._filter_results_parameters(axis, material_sel.value)

            if axis_cfg["param"] in param_sel.options:
                param_sel.value = axis_cfg["param"]
            else:
                skipped.append(f"{axis.upper()} ({axis_cfg['param']} not available)")

        self.gui.plot_type_selector.value = preset.get("plot_type", "Scatter")
        self.gui.jv_aggregation_selector.value = preset.get("aggregation", "All Points")

        self._rebuild_merged_data()
        self._on_create_plot(None)

        if skipped:
            self._update_status("⚠️ Preset applied, but skipped: " + "; ".join(skipped))

    def _on_create_plot(self, button):
        """Handle plot creation."""
        merged = self.data_manager.merged_data
        if merged is None or merged.empty:
            self._update_status("❌ No data available for plotting.")
            return
        source_df = self._plot_source_df()
        if source_df.empty:
            self._update_status("❌ No rows left after the Filters tab's filters.")
            return

        x_param = self.gui.x_param_selector.value
        y_param = self.gui.y_param_selector.value
        color_param = self.gui.color_param_selector.value
        aggregation = self.gui.jv_aggregation_selector.value

        if not x_param or not y_param:
            self._update_status("⚠️ Please select both X and Y parameters.")
            return

        try:
            # Prepare plot data
            plot_type = self.gui.plot_type_selector.value
            plot_df, x_col, y_col, color_col = self.plot_manager.prepare_plot_data(
                source_df,
                x_param,
                y_param,
                color_param,
                aggregation,
                plot_type=plot_type,
                color_data_source=self.gui.color_data_source_selector.value,
                source_material_columns=getattr(self.data_manager, "_source_material_columns", {}),
            )

            if plot_df.empty:
                self._update_status("❌ No valid data points for selected parameters.")
                return

            # Create plot
            color_col = None
            if color_param and color_param != "None":
                # Handle "Material Type" for color
                if color_param == "Material Type":
                    if "layer_material_name" in plot_df.columns:
                        color_col = "layer_material_name"
                    elif "layer_material" in plot_df.columns:
                        color_col = "layer_material"
                    else:
                        material_cols = [
                            col
                            for col in plot_df.columns
                            if "material" in col.lower() and "layer" in col.lower()
                        ]
                        if material_cols:
                            color_col = material_cols[0]
                else:
                    color_col = self.plot_manager.extract_column_name(color_param)

            plot_type = self.gui.plot_type_selector.value
            colorscale = self.gui.colorscale_selector.value

            boxplot_warning = ""
            numeric_x_boxplot = plot_type == "Boxplot" and pd.api.types.is_numeric_dtype(
                plot_df[x_col]
            )
            if numeric_x_boxplot and not self.gui.boxplot_bin_toggle.value:
                boxplot_warning = (
                    f"\n⚠️  Boxplot requires a categorical X axis.\n"
                    f"   '{x_param}' is numeric — falling back to Scatter.\n"
                    f"   Suggestion: use 'Material Type' or a categorical process\n"
                    f"   parameter as X for a meaningful boxplot, or tick\n"
                    f"   'Bin numeric X into groups' to bin it automatically."
                )
                self.plot_manager.create_scatter_plot(
                    plot_df, x_col, y_col, color_col, x_param, y_param, colorscale
                )
                self.plot_manager.register_click_handler(
                    self.data_manager.sample_entry_links, self.gui.click_output
                )
            elif plot_type == "Boxplot":
                bin_count = self.gui.boxplot_bin_count.value if numeric_x_boxplot else None
                self.plot_manager.create_box_plot(
                    plot_df, x_col, y_col, color_col, x_param, y_param, colorscale, bin_count
                )
                self.plot_manager.register_click_handler(
                    self.data_manager.sample_entry_links, self.gui.click_output
                )
            else:
                self.plot_manager.create_scatter_plot(
                    plot_df, x_col, y_col, color_col, x_param, y_param, colorscale
                )
                self.plot_manager.register_click_handler(
                    self.data_manager.sample_entry_links, self.gui.click_output
                )

            # Display statistics
            self.plot_manager.display_statistics(plot_df, x_col, y_col, x_param, y_param)

            # Add subbatch grouping info to status
            status_msg = f"✓ Plot created with {len(plot_df)} data points!"
            if self.gui.group_by_subbatch.value:
                status_msg += " (grouped by subbatch)"
            if self._plot_filter_note:
                status_msg += f" ({self._plot_filter_note})"
            self._plot_created = True

            # Debug output
            if self.gui.debug_checkbox.value:
                with self.gui.status_output:
                    clear_output()
                    print(f"✓ Plot created successfully!{boxplot_warning}\n\nDEBUG INFO:\n...")
                    print("\nDEBUG INFO:")
                    print(f"Data shape: {plot_df.shape}")
                    print(f"X: {x_col}, Y: {y_col}")
                    print(plot_df.head())
            else:
                self._update_status(status_msg)  # Instead of the hardcoded message

        except Exception as e:
            self._update_status(f"❌ Error creating plot: {str(e)}")
            logger.exception("Error creating plot")

    def _on_download_data(self, button):
        """Download the currently plotted data as CSV via browser."""
        with self.gui.download_output:
            clear_output()

            source_df = self._plot_source_df()
            if source_df is None or source_df.empty:
                print("⚠️ No data loaded to download.")
                return

            x_param = self.gui.x_param_selector.value
            y_param = self.gui.y_param_selector.value
            color_param = self.gui.color_param_selector.value
            aggregation = self.gui.jv_aggregation_selector.value

            if not x_param or not y_param:
                print("⚠️ Please select X and Y parameters first.")
                return

            try:
                plot_df, x_col, y_col, _ = self.plot_manager.prepare_plot_data(
                    source_df,
                    x_param,
                    y_param,
                    color_param,
                    aggregation,
                    plot_type=self.gui.plot_type_selector.value,
                )

                filename = trigger_csv_download(plot_df, "plot_data")
                print(
                    f"✓ Downloading {filename} ({len(plot_df)} rows, {len(plot_df.columns)} columns)..."
                )

            except Exception as e:
                print(f"❌ Download error: {e}")
                traceback.print_exc()

    def create_interface(self):
        """Create and return the complete interface."""
        return self.gui.create_layout()

    def display(self):
        """Display the complete interface in Jupyter notebook."""
        from IPython.display import display

        interface = self.create_interface()
        display(interface)
