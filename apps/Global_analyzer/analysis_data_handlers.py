"""Handlers of the Filters and Analysis Data tabs of SampleDataExplorer (app.py): staged filters,
sample exclusion, the analysis table, uploaded datasets. A mixin: it relies on the attributes
SampleDataExplorer sets up."""

import logging
from typing import Optional

import pandas as pd
from data_manager import (
    MISSING_VALUE_MODES,
    apply_row_filters,
    exclude_samples,
    fill_missing_with_zero,
    filter_plot_data,
    label_column_roles,
    parse_uploaded_analysis_csv,
    split_column_roles,
    uploaded_numeric_columns,
    variation_warning,
)
from IPython.display import HTML, clear_output
from IPython.display import display as ipy_display
from utils import trigger_csv_download

logger = logging.getLogger(__name__)


class AnalysisDataHandlersMixin:
    def _apply_filters(self):
        """Apply the active Analysis Data row filters and sample exclusions on
        top of the full merged dataset, so self.analysis_df - what every
        downstream tab (Correlations, Random Forest, Bayesian Optimization,
        Experimental) actually reads - only ever contains rows the user has
        chosen to keep. Row filters combine with AND; a filter referencing a
        column no longer present (e.g. after unchecking it) is skipped rather
        than erroring. Missing values are filled with 0 afterwards when the
        Missing values option asks for it, so filters still see the real data."""
        self._n_filled_missing = 0
        if self.full_analysis_df is None:
            self.analysis_df = None
        else:
            filtered = apply_row_filters(self.full_analysis_df, self._applied_filters)
            filtered = exclude_samples(filtered, self._applied_excluded)
            mode = MISSING_VALUE_MODES[self.gui.missing_values_selector.value]
            if mode != "keep":
                columns = list(self.analysis_metadata_cols)
                if mode == "all":
                    columns += self.analysis_results_cols
                filtered, self._n_filled_missing = fill_missing_with_zero(filtered, columns)
            self.analysis_df = filtered

        self.gui.render_active_filters(self.row_filters, self._on_remove_row_filter)
        self._render_analysis_data_preview()
        self._update_filter_summary()
        self._refresh_filters_pending()

    def _refresh_filters_pending(self):
        """Show whether the Filters tab holds edits that are not applied yet."""
        staged = [(f["column"], f["op"], f["value"]) for f in self.row_filters]
        applied = [(f["column"], f["op"], f["value"]) for f in self._applied_filters]
        pending = staged != applied or self.gui.get_excluded_sample_ids() != self._applied_excluded
        self.gui.set_filters_pending(pending)

    def _on_confirm_filters(self, button):
        """Apply the staged row filters and sample exclusions to every tab."""
        self._applied_filters = [dict(f) for f in self.row_filters]
        self._applied_excluded = set(self.gui.get_excluded_sample_ids())
        self._apply_filters()
        self._rerun_active_analyses()

    def _update_filter_summary(self):
        """The Filters tab's one-line summary of what passes (analysis rows and samples)."""
        if self.full_analysis_df is None or self.analysis_df is None:
            self.gui.set_filter_summary("")
            return
        samples_all = self.full_analysis_df["sample_id"].nunique()
        samples_kept = self.analysis_df["sample_id"].nunique()
        self.gui.set_filter_summary(
            f"<b>{samples_kept} of {samples_all} samples</b> and {len(self.analysis_df)} of "
            f"{len(self.full_analysis_df)} analysis rows pass the filters "
            f"({len(self._applied_filters)} row filter(s), "
            f"{len(self._applied_excluded)} excluded sample(s))."
        )

    def _plot_source_df(self) -> Optional[pd.DataFrame]:
        """The Plotting tab's table with the Filters tab's filters and exclusions applied; sets
        self._plot_filter_note to what was kept and which filters did not apply."""
        merged = self.data_manager.merged_data
        self._plot_filter_note = ""
        if merged is None:
            return None
        excluded = self._applied_excluded
        if not self._applied_filters and not excluded:
            return merged
        filtered, skipped = filter_plot_data(merged, self._applied_filters, excluded)
        note = f"filters kept {len(filtered)} of {len(merged)} rows"
        if skipped:
            names = ", ".join(f"{f['column']} {f['op']} {f['value']:g}" for f in skipped)
            note += f"; not applied (column not in this plot's data): {names}"
        self._plot_filter_note = note
        return filtered

    def _get_analysis_data_preview_df(self) -> Optional[pd.DataFrame]:
        """The exact rows/columns currently feeding Correlations/Random Forest/
        Bayesian Optimization/Experimental - shared by the preview table and
        its Download CSV button so both always show exactly the same data.
        None if there's nothing loaded yet."""
        if self.analysis_df is None or self.analysis_df.empty:
            return None

        checked_results_set = set(self.gui.get_checked_results_columns())
        checked_metadata_set = set(self.gui.get_checked_metadata_columns())
        preview_cols = (
            ["sample_id"]
            + [c for c in self.analysis_metadata_cols if c in checked_metadata_set]
            + [c for c in self.analysis_results_cols if c in checked_results_set]
        )
        preview_cols = [c for c in preview_cols if c in self.analysis_df.columns]
        # Role prefixes in the headers, so the table says which column is which and an
        # exported CSV re-uploads with the same results/process split.
        return label_column_roles(
            self.analysis_df[preview_cols], self.analysis_results_cols, self.analysis_metadata_cols
        )

    def _render_analysis_data_preview(self):
        """Render the exact rows/columns currently feeding Correlations/Random
        Forest/Bayesian Optimization/Plotting/Experimental into the Analysis
        Data tab's collapsible preview - so what an analysis actually used is
        visible, not just trusted. Rendered as a fixed-height div with
        overflow:auto (not a bare display(df)) so a wide/tall table scrolls
        in both directions inside its own box instead of stretching the
        whole page, and to_html(max_rows=None) so every row shows regardless
        of pandas' own default display.max_rows truncation."""
        with self.gui.analysis_data_preview_output:
            clear_output(wait=True)
            preview_df = self._get_analysis_data_preview_df()
            if preview_df is None:
                print("No data available yet.")
                return

            n_total = len(self.full_analysis_df) if self.full_analysis_df is not None else 0
            print(
                f"{len(preview_df)} of {n_total} row(s) x {len(preview_df.columns)} column(s) "
                "currently feeding the analysis:"
            )
            if self._n_filled_missing:
                print(f"{self._n_filled_missing} missing value(s) filled with 0.")
            table_html = preview_df.to_html(index=False, max_rows=None, max_cols=None)
            ipy_display(
                HTML(
                    f"<div style='max-height:500px; width:100%; overflow:auto;'>{table_html}</div>"
                )
            )

    def _on_download_analysis_data_preview(self, button):
        """Download exactly what the preview table above is showing, as CSV."""
        with self.gui.analysis_data_preview_download_output:
            clear_output()
            preview_df = self._get_analysis_data_preview_df()
            if preview_df is None:
                print("No data available yet.")
                return
            filename = trigger_csv_download(preview_df, "analysis_data")
            print(f"✓ Downloaded {filename}")

    def _on_add_row_filter(self, button):
        """Add one row filter (column/op/value from the Analysis Data tab's
        filter controls) and immediately re-apply all filters."""
        column = self.gui.filter_column_selector.value
        if not column:
            return
        self.row_filters.append(
            {
                "id": self._next_filter_id,
                "column": column,
                "op": self.gui.filter_operator_selector.value,
                "value": self.gui.filter_value_input.value,
            }
        )
        self._next_filter_id += 1
        self.gui.render_active_filters(self.row_filters, self._on_remove_row_filter)
        self._refresh_filters_pending()

    def _on_remove_row_filter(self, filter_id):
        """Drop one active row filter (by id) and re-apply the rest."""
        self.row_filters = [f for f in self.row_filters if f["id"] != filter_id]
        self.gui.render_active_filters(self.row_filters, self._on_remove_row_filter)
        self._refresh_filters_pending()

    def _on_sample_exclusion_toggled(self, change):
        """A sample's checkbox in "Exclude specific samples" was checked or
        unchecked - staged until Confirm filters; otherwise (before, it re-applied at once) and
        re-run whichever of Correlations/RF/BO is already showing a result."""
        self._refresh_filters_pending()

    def _refresh_variation_warning(self):
        """Show an advisory (never blocking) warning for checked metadata columns
        with too little variation to be useful for correlation/RF/BO."""
        with self.gui.variation_warning_output:
            clear_output()
            if self.analysis_df is None:
                return
            checked_metadata = self.gui.get_checked_metadata_columns()
            low_variation = variation_warning(self.analysis_df, checked_metadata)
            if low_variation:
                print(
                    "⚠️ For better results, use parameters with more variation "
                    f"(aim for 6+ distinct values): {', '.join(low_variation)}"
                )
            if getattr(self, "_multi_row_samples", None) and self._uploaded_df is None:
                shown = ", ".join(self._multi_row_samples[:5])
                more = len(self._multi_row_samples) - 5
                print(
                    f"⚠️ {len(self._multi_row_samples)} sample(s) have more than one entry of "
                    "the same process step (e.g. two spin-coating steps): their rows are "
                    "repeated in this table, once per entry, so the parameters of one step are "
                    "paired with the other's. Choose a layer type or check the entries: "
                    f"{shown}{f' (+{more} more)' if more > 0 else ''}"
                )
            if self._collapsed_result_types and self._uploaded_df is None:
                print(
                    "ℹ️ 'All Points' keeps individual rows for one measurement type only; "
                    "pairing every row of one type with every row of another would "
                    "invent combinations that were never measured. Averaged per sample "
                    f"instead: {', '.join(self._collapsed_result_types)}"
                )

    def _on_recalculate_analysis_data(self, button):
        """Rebuild the shared analysis dataframe and re-run whichever of
        Correlations/RF/BO already produced a result, so Recalculate visibly
        updates whatever the user has open without requiring a trip back through
        each tab's own button."""
        with self.gui.analysis_data_status_output:
            clear_output()
            print("Recalculating...")

        self._rebuild_full_analysis_dataframe()
        self._refresh_ml_target_options()
        self._refresh_experimental_options()

        checked_results = self.gui.get_checked_results_columns()
        checked_metadata = self.gui.get_checked_metadata_columns()
        with self.gui.analysis_data_status_output:
            clear_output()
            print("✓ Analysis data updated.")
            print(
                f"Using {len(checked_results)} results column(s): "
                f"{', '.join(checked_results) if checked_results else '(none checked)'}"
            )
            print(
                f"Using {len(checked_metadata)} process metadata column(s): "
                f"{', '.join(checked_metadata) if checked_metadata else '(none checked)'}"
            )

        self._rerun_active_analyses()

    def _on_upload_analysis_csv(self, change):
        """Replace the shared analysis dataset with a user-uploaded CSV,
        bypassing the NOMAD batch-load pipeline entirely (issue #40) - e.g. for
        a quick offline experiment that has nothing to do with a NOMAD-tracked
        batch. A flat CSV doesn't say which columns are results and which are
        process parameters, so the user picks the results in a selector that
        appears after upload (default: the last numeric column, which is where
        this tab's own "Download CSV" export puts results).
        """
        uploaded = change["new"]
        if not uploaded:
            return

        file_info = uploaded[0]
        with self.gui.analysis_data_upload_output:
            clear_output()
            try:
                df = parse_uploaded_analysis_csv(bytes(file_info["content"]))
                df, labelled_results, _ = split_column_roles(df)
            except Exception as e:
                logger.exception("Failed to parse uploaded analysis CSV")
                print(f"❌ Could not read CSV: {e}")
                return

            numeric_cols = uploaded_numeric_columns(df)
            if len(numeric_cols) < 2:
                print(
                    "❌ Need at least 2 numeric columns with 2+ distinct values each "
                    "(one result and one parameter)."
                )
                return

            self._uploaded_df = df
            self._updating_upload_roles = True
            try:
                selector = self.gui.analysis_data_upload_results_selector
                selector.options = numeric_cols
                # Columns exported as "result: ..." are results; an unlabelled CSV
                # falls back to its last numeric column.
                preselected = [c for c in numeric_cols if c in labelled_results]
                selector.value = tuple(preselected) or (numeric_cols[-1],)
            finally:
                self._updating_upload_roles = False
            self.gui.analysis_data_upload_roles_box.layout.display = None

            self._apply_uploaded_dataset()
            self._refresh_ml_target_options()
            self._refresh_experimental_options()
            print(
                f"✓ Loaded {len(df)} row(s), {len(numeric_cols)} usable numeric column(s) "
                "from the uploaded CSV. Check the result column(s) below."
            )
        # Reset so picking the same (edited) file again still fires a change.
        self.gui.analysis_data_upload.value = ()
        self._rerun_active_analyses()

    def _on_missing_values_changed(self, change):
        """The Missing values option changed: refill and re-run the open analyses."""
        self._apply_filters()
        self._rerun_active_analyses()

    def _on_upload_results_columns_changed(self, change):
        """The user changed which uploaded columns count as results - re-split
        and refresh every tab reading the shared dataset."""
        if self._updating_upload_roles or self._uploaded_df is None:
            return
        self._apply_uploaded_dataset()
        self._refresh_ml_target_options()
        self._refresh_experimental_options()
        self._rerun_active_analyses()
