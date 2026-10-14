"""Handlers of the analysis tabs of SampleDataExplorer (app.py): downloads, correlations,
Random Forest, Bayesian optimization and the experimental tools. A mixin: it relies on the
attributes SampleDataExplorer sets up (gui, data_manager, analysis dataframes)."""

import logging

import experimental_analysis as experimental
import ml_analysis as ml
import pandas as pd
from data_manager import (
    average_rows_per_sample,
    get_categorical_columns,
)
from IPython.display import HTML, Markdown, clear_output
from IPython.display import display as ipy_display
from utils import trigger_csv_download

logger = logging.getLogger(__name__)


def _rows_note(result: dict) -> str:
    """' (N rows: ...)' when the model saw more rows than samples (pixels, repeats)."""
    if result["n_rows"] == result["n_samples"]:
        return ""
    return f" ({result['n_rows']} rows: several measurements per sample)"


def _format_cell(value) -> str:
    """A table cell: numbers to 3 significant digits, anything else as text."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return f"{value:.3g}"
    return str(value)


def _missing_note(result: dict) -> str:
    """A Markdown bullet naming the parameters whose missing values cost rows."""
    missing = result["missing_by_column"]
    if not missing:
        return ""
    dropped = result["n_rows_with_target"] - result["n_rows"]
    worst = ", ".join(f"`{col}` ({n})" for col, n in list(missing.items())[:3])
    return (
        f"- ⚠️ {dropped} of {result['n_rows_with_target']} rows with a target value "
        f"were left out for missing parameter values, mostly: {worst}. Unchecking a "
        "sparse parameter in the Analysis Data tab brings them back.\n"
    )


class AnalysisHandlersMixin:
    def _on_download_correlations(self, button):
        """Download the last-computed correlation matrix as CSV via browser."""
        with self.gui.correlation_download_output:
            clear_output()

            if not self._last_correlation_result:
                print("⚠️ No correlation results yet - click Find Correlations first.")
                return

            corr_df = self._last_correlation_result["dataframe"]
            filename = trigger_csv_download(corr_df, "correlations")
            print(
                f"✓ Downloading {filename} ({len(corr_df)} rows, {len(corr_df.columns)} columns)..."
            )

    def _on_download_rf_results(self, button):
        """Download the last Random Forest feature importances as CSV via browser."""
        with self.gui.rf_download_output:
            clear_output()

            if not self._last_rf_result:
                print("⚠️ No Random Forest results yet - click Run Random Forest first.")
                return

            importances_df = pd.DataFrame(
                self._last_rf_result["importances"],
                columns=["parameter", "importance_r2_drop", "importance_sd"],
            )
            filename = trigger_csv_download(importances_df, "random_forest_importances")
            print(
                f"✓ Downloading {filename} ({len(importances_df)} rows, "
                f"{len(importances_df.columns)} columns)..."
            )

    def _on_download_bo_suggestions(self, button):
        """Download the last Bayesian Optimization suggestions as CSV via browser."""
        with self.gui.bo_download_output:
            clear_output()

            if not self._last_bo_result:
                print("⚠️ No suggestions yet - click Suggest Next Experiments first.")
                return

            suggestions_df = self._last_bo_result["suggestions"]
            filename = trigger_csv_download(suggestions_df, "bo_suggestions")
            print(
                f"✓ Downloading {filename} ({len(suggestions_df)} rows, "
                f"{len(suggestions_df.columns)} columns)..."
            )

    def _on_find_correlations(self, button):
        """Compute and render a correlation view over the shared analysis dataset
        (Analysis Data tab), in whichever of the two formats (Heatmap / Scatter
        Matrix) is currently selected. Heatmap puts results on x, process metadata
        on y; Scatter Matrix keeps its full mixed-column grid, just restricted to
        the checked columns."""
        with self.gui.correlation_status_output:
            clear_output()

            if self.analysis_df is None or self.analysis_df.empty:
                print("⚠️ No data available. Load batches first.")
                self._last_correlation_result = None
                return

            checked_results_set = set(self.gui.get_checked_results_columns())
            checked_metadata_set = set(self.gui.get_checked_metadata_columns())
            checked_results = [c for c in self.analysis_results_cols if c in checked_results_set]
            checked_metadata = [c for c in self.analysis_metadata_cols if c in checked_metadata_set]

            if not checked_results or not checked_metadata:
                print(
                    "⚠️ Check at least one Results column and one Process Metadata "
                    "column in the Analysis Data tab."
                )
                self._last_correlation_result = None
                return

            min_unique = self.gui.correlation_min_unique.value
            plot_type = self.gui.correlation_plot_type.value

            corr_source = self.analysis_df
            if self.gui.correlation_per_sample.value:
                corr_source = average_rows_per_sample(
                    self.analysis_df, checked_results + checked_metadata
                )
                if len(corr_source) < len(self.analysis_df):
                    print(
                        f"ℹ️ Averaged {len(self.analysis_df)} rows into "
                        f"{len(corr_source)} samples (one point per sample)."
                    )

            try:
                if plot_type == "Heatmap":
                    self.gui.correlation_scatter_output.clear_output()
                    results_used, metadata_used = self.plot_manager.create_metadata_results_heatmap(
                        corr_source, checked_results, checked_metadata, min_unique=min_unique
                    )
                    dropped_results = [c for c in checked_results if c not in results_used]
                    dropped_metadata = [c for c in checked_metadata if c not in metadata_used]
                    if not results_used or not metadata_used:
                        print(
                            f"⚠️ Not enough varying parameters (need >{min_unique} unique "
                            "values) on both axes for a heatmap."
                        )
                        if dropped_results:
                            print(
                                f"  Excluded results (too few unique values): {', '.join(dropped_results)}"
                            )
                        if dropped_metadata:
                            print(
                                "  Excluded process metadata (too few unique values): "
                                f"{', '.join(dropped_metadata)}"
                            )
                        self._last_correlation_result = None
                    else:
                        print(
                            f"✓ Correlation heatmap computed: {len(results_used)} result(s) "
                            f"x {len(metadata_used)} metadata parameter(s)."
                        )
                        if dropped_results or dropped_metadata:
                            excluded = dropped_results + dropped_metadata
                            print(
                                f"  Excluded {len(excluded)} checked column(s) with <{min_unique + 1} "
                                f"unique values: {', '.join(excluded)}"
                            )
                        numeric_df = corr_source.select_dtypes(include="number")
                        corr_df = (
                            pd.DataFrame(
                                {
                                    result_col: numeric_df[metadata_used].corrwith(
                                        numeric_df[result_col]
                                    )
                                    for result_col in results_used
                                }
                            )
                            .reset_index()
                            .rename(columns={"index": "metadata_parameter"})
                        )
                        self._last_correlation_result = {
                            "type": "heatmap",
                            "results": results_used,
                            "metadata": metadata_used,
                            "dataframe": corr_df,
                        }
                else:
                    self.gui.correlation_widget.data = []
                    self.gui.correlation_widget.update_layout(
                        title='Switch "Format" to Heatmap to use this view'
                    )
                    combined_df = corr_source[checked_results + checked_metadata]
                    used_cols, truncated = self.plot_manager.create_correlation_scatter_matrix(
                        combined_df, min_unique=min_unique
                    )
                    numeric_combined = combined_df.select_dtypes(include="number")
                    dropped_for_variance = [
                        c
                        for c in checked_results + checked_metadata
                        if c in numeric_combined.columns
                        and numeric_combined[c].dropna().nunique() <= min_unique
                        and c not in used_cols
                    ]
                    if len(used_cols) < 2:
                        print(
                            f"⚠️ Only {len(used_cols)} numeric parameter(s) have more than "
                            f"{min_unique} unique values - need at least 2 for a scatter matrix."
                        )
                        if dropped_for_variance:
                            print(
                                f"  Excluded (too few unique values): {', '.join(dropped_for_variance)}"
                            )
                        self._last_correlation_result = None
                    else:
                        note = " (showing the first 12)" if truncated else ""
                        print(f"✓ Scatter matrix computed for {len(used_cols)} parameters{note}.")
                        if dropped_for_variance:
                            print(
                                f"  Excluded {len(dropped_for_variance)} checked column(s) with "
                                f"<{min_unique + 1} unique values: {', '.join(dropped_for_variance)}"
                            )
                        corr_df = combined_df[used_cols].corr().reset_index()
                        corr_df = corr_df.rename(columns={"index": "parameter"})
                        self._last_correlation_result = {
                            "type": "scatter_matrix",
                            "columns": used_cols,
                            "dataframe": corr_df,
                        }
            except Exception as e:
                print(f"❌ Error computing correlations: {e}")
                logger.exception("Error computing correlations")
                self._last_correlation_result = None

    def _on_run_random_forest(self, button):
        """Fit a Random Forest to predict the chosen target (a Results column) from
        the checked Process Metadata columns in the Analysis Data tab, and report
        which of them matter most."""
        with self.gui.rf_output:
            clear_output(wait=True)

            if self.analysis_df is None or self.analysis_df.empty:
                print("⚠️ No data available. Load batches and select data sources first.")
                self._last_rf_result = None
                return

            target = self.gui.rf_target_selector.value
            if not target:
                print("⚠️ Pick a target parameter first.")
                self._last_rf_result = None
                return

            checked_metadata = set(self.gui.get_checked_metadata_columns())
            feature_cols = [
                col
                for col in self.analysis_metadata_cols
                if col in checked_metadata and col != target
            ]
            categorical_cols = [
                c
                for c in self.gui.get_checked_categorical_columns()
                if c in self.analysis_df.columns
            ]
            if not feature_cols and not categorical_cols:
                print(
                    "⚠️ No Process Metadata or categorical parameters checked. Check at "
                    "least one in the Analysis Data tab."
                )
                self._last_rf_result = None
                return

            print("⏳ Cross-validating the Random Forest...")
            try:
                result = ml.run_random_forest(
                    self.analysis_df,
                    target,
                    feature_cols=feature_cols,
                    categorical_cols=categorical_cols,
                )
            except ValueError as e:
                print(f"⚠️ {e}")
                self._last_rf_result = None
                return
            except Exception as e:
                print(f"❌ Error running Random Forest: {e}")
                logger.exception("Error running Random Forest")
                self._last_rf_result = None
                return

            clear_output(wait=True)
            top_features = "\n".join(
                f"- **{name}**: {mean:.3f} ± {sd:.3f}"
                for name, mean, sd in result["importances"][:10]
            )
            r2_note = (
                " _(no better than predicting the average: the importances below "
                "carry little information)_"
                if result["r2"] <= 0
                else ""
            )
            summary = (
                f"### Random Forest results for `{target}`\n\n"
                f"- Samples used: **{result['n_samples']}**"
                f"{_rows_note(result)}\n"
                f"- Features used: **{result['n_features']}**\n"
                f"- Cross-validated R²: **{result['r2']:.3f} ± {result['r2_sd']:.3f}**"
                f"{r2_note}\n"
                f"- Cross-validated RMSE: **{result['rmse']:.3g} ± {result['rmse_sd']:.2g}**\n"
                f"  _({result['n_folds']}-fold, repeated {result['n_repeats']}x, all rows "
                "of a sample kept in the same fold; ± is the SD over repeats)_\n"
                + _missing_note(result)
                + "".join(f"- ⚠️ {w}\n" for w in result["warnings"])
                + "\n**Top parameters by importance** (drop in cross-validated R² "
                f"when shuffled, ± SD):\n\n{top_features}"
            )
            ipy_display(Markdown(summary))
            self.plot_manager.create_feature_importance_plot(result["importances"], target)
            self.plot_manager.create_partial_dependence_plot(result["partial_dependence"], target)
            self._last_rf_result = result

    def _bo_inputs(self, target: str):
        """Feature, categorical, batch, search-space and constraint arguments for
        the BO calls, from the Analysis Data checklists and the BO tab's controls.
        None if nothing usable is checked (the message is already printed)."""
        checked_metadata = set(self.gui.get_checked_metadata_columns())
        feature_cols = [
            col for col in self.analysis_metadata_cols if col in checked_metadata and col != target
        ]
        checked_categorical = [
            c for c in self.gui.get_checked_categorical_columns() if c in self.analysis_df.columns
        ]
        categorical_cols = [c for c in checked_categorical if c != "batch"]
        if not feature_cols and not categorical_cols:
            print(
                "⚠️ No Process Metadata or categorical parameters checked. Check at "
                "least one in the Analysis Data tab."
            )
            return None

        batch_col = None
        if (
            self.gui.bo_batch_offset.value
            and "batch" in self.analysis_df.columns
            and self.analysis_df["batch"].nunique() > 1
        ):
            batch_col = "batch"

        space = self.gui.get_bo_search_space()
        numeric_space = {c: v for c, v in space.items() if not v.get("categorical")}
        return {
            "feature_cols": feature_cols,
            "categorical_cols": categorical_cols,
            "batch_col": batch_col,
            "bounds": {
                c: (numeric_space[c]["min"], numeric_space[c]["max"])
                for c in feature_cols
                if c in numeric_space
            },
            "integer_cols": [
                c for c in feature_cols if c in numeric_space and numeric_space[c]["integer"]
            ],
            "fixed": {
                c: space[c]["fixed"]
                for c in [*feature_cols, *categorical_cols]
                if c in space and space[c]["fixed"] is not None
            },
            "constraints": [c for c in self.gui.get_bo_constraints() if c["col"] != target],
        }

    def _on_suggest_experiments(self, button):
        """Suggest next parameter combinations most likely to improve the chosen
        target (a Results column), using a Gaussian Process surrogate fit on the
        checked Process Metadata (and categorical) parameters in the Analysis
        Data tab - or, with a second objective, a batch spread along the
        trade-off between the two."""
        with self.gui.bo_output:
            clear_output(wait=True)

            if self.analysis_df is None or self.analysis_df.empty:
                print("⚠️ No data available. Load batches and select data sources first.")
                self._last_bo_result = None
                return

            target = self.gui.bo_target_selector.value
            if not target:
                print("⚠️ Pick a target parameter first.")
                self._last_bo_result = None
                return

            direction = self.gui.bo_direction_selector.value.lower()
            inputs = self._bo_inputs(target)
            if inputs is None:
                self._last_bo_result = None
                return

            second = self.gui.bo_pareto_target.value if self.gui.bo_pareto_enable.value else None
            if second == target:
                print("⚠️ Pick a second objective different from the target.")
                self._last_bo_result = None
                return
            if second:
                inputs["constraints"] = [c for c in inputs["constraints"] if c["col"] != second]

            # Fitting the Gaussian Process can take a while: show a banner that
            # stays until the results replace it (clear_output(wait=True) below).
            self.gui.suggest_experiments_button.disabled = True
            ipy_display(
                HTML(
                    "<div style='padding:12px 16px; margin:8px 0; background:#fff3cd; "
                    "border:2px solid #f0ad4e; border-radius:4px; color:#664d03; "
                    "font-size:1.1em; font-weight:bold;'>"
                    "⏳ Processing... fitting the model and calculating suggestions. "
                    "This can take a moment.</div>"
                )
            )
            try:
                if second:
                    result = ml.suggest_pareto_experiments(
                        self.analysis_df,
                        [(target, direction), (second, self.gui.bo_pareto_direction.value.lower())],
                        n_suggestions=self.gui.bo_n_suggestions.value,
                        **inputs,
                    )
                else:
                    result = ml.suggest_next_experiments(
                        self.analysis_df,
                        target,
                        direction=direction,
                        n_suggestions=self.gui.bo_n_suggestions.value,
                        log_target=self.gui.bo_log_target.value,
                        **inputs,
                    )
            except ValueError as e:
                clear_output(wait=True)
                print(f"⚠️ {e}")
                self._last_bo_result = None
                return
            except Exception as e:
                clear_output(wait=True)
                print(f"❌ Error suggesting experiments: {e}")
                logger.exception("Error suggesting experiments")
                self._last_bo_result = None
                return
            finally:
                self.gui.suggest_experiments_button.disabled = False

            try:
                if second:
                    self._show_pareto_suggestions(result)
                else:
                    self._show_bo_suggestions(result)
            except Exception as e:
                clear_output(wait=True)
                print(f"❌ Error plotting suggestions: {e}")
                logger.exception("Error plotting BO suggestions")
                self._last_bo_result = None
                return
            self._last_bo_result = result

    def _show_pareto_suggestions(self, result: dict):
        """Render suggest_pareto_experiments' output: a table of picks with each
        objective's prediction and weighting, and the trade-off plot."""
        suggestions = result["suggestions"]
        (col_a, dir_a), (col_b, dir_b) = result["objectives"][:2]
        objective_cols = {
            f"predicted_{col_a}",
            f"predicted_{col_b}",
            f"weight_{col_a}",
            f"weight_{col_b}",
        }
        feature_cols = [c for c in suggestions.columns if c not in objective_cols]
        header = [
            *feature_cols,
            f"{col_a} (predicted)",
            f"{col_b} (predicted)",
            f"weight on {col_a}",
        ]
        lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
        for _, row in suggestions.iterrows():
            values = [_format_cell(row[c]) for c in feature_cols]
            lines.append(
                "| "
                + " | ".join(values)
                + f" | {row[f'predicted_{col_a}']:.4g} | {row[f'predicted_{col_b}']:.4g} "
                f"| {row[f'weight_{col_a}']:.2f} |"
            )
        summary = (
            f"### {len(suggestions)} suggestion(s) along the trade-off: {dir_a} `{col_a}`, "
            f"{dir_b} `{col_b}`\n\n"
            f"- Samples used: **{result['n_samples']}**\n"
            "- Each suggestion weighs the two objectives differently, from mostly "
            f"`{col_a}` (weight near 1) to mostly `{col_b}`; predictions are from a model "
            "of each objective on its own.\n"
            + "".join(f"- ⚠️ {w}\n" for w in result["warnings"])
            + "\n"
            + "\n".join(lines)
        )
        measured = average_rows_per_sample(self.analysis_df, [col_a, col_b]).dropna(
            subset=[col_a, col_b]
        )
        self.plot_manager.create_pareto_suggestions_plot(measured, suggestions, col_a, col_b)
        self.gui.bo_loo_widget.data = []
        self.gui.bo_loo_widget.update_layout(title="Model check: not shown for a two-objective run")
        # Swap the Processing banner for the results in one step.
        clear_output(wait=True)
        ipy_display(Markdown(summary))

    def _show_bo_suggestions(self, result: dict):
        """Render suggest_next_experiments' output: summary, table and plots."""
        target = result["target"]
        suggestions = result["suggestions"]
        pred_col = f"predicted_{target}"
        has_constraints = "probability_feasible" in suggestions.columns
        display_feature_cols = [
            c
            for c in suggestions.columns
            if c
            not in (
                pred_col,
                "predicted_low",
                "predicted_high",
                "expected_improvement",
                "probability_feasible",
            )
        ]

        log_target = result["log_target"]
        log_units = " (log10)" if log_target else ""
        header_cols = [
            *display_feature_cols,
            f"{target} (predicted)",
            "range (±1 SD)",
            ("EI x P(feasible)" if has_constraints else "Expected improvement") + log_units,
            *(["P(feasible)"] if has_constraints else []),
        ]
        table_lines = [
            "| " + " | ".join(header_cols) + " |",
            "|" + "---|" * len(header_cols),
        ]
        integer_set = set(result["integer_cols"])
        for _, row in suggestions.iterrows():
            values = [
                f"{int(row[c])}" if c in integer_set else _format_cell(row[c])
                for c in display_feature_cols
            ]
            table_lines.append(
                "| " + " | ".join(values) + f" | {row[pred_col]:.4g} "
                f"| {row['predicted_low']:.3g} to {row['predicted_high']:.3g} "
                f"| {row['expected_improvement']:.3g} |"
                + (f" {row['probability_feasible']:.2f} |" if has_constraints else "")
            )

        steps_estimate = ml.estimate_max_bo_steps(result["n_features"])

        upper = result["length_scale_upper"]
        length_scale_lines = "\n".join(
            f"  - `{col}`: {ls:.2g}"
            + (" (at the upper limit: no detectable effect)" if ls >= upper * 0.99 else "")
            for col, ls in sorted(result["length_scales"].items(), key=lambda kv: kv[1])
        )

        # Once the batch has covered the promising regions, EI for the rest
        # is ~0 and later picks are close to arbitrary - say so.
        ei = suggestions["expected_improvement"].to_numpy()
        low_ei = [i + 1 for i, v in enumerate(ei) if ei[0] > 0 and v < 1e-3 * ei[0]]
        low_ei_note = (
            f"- ⚠️ Suggestion(s) #{low_ei[0]} onward have near-zero expected "
            "improvement: given the earlier picks, the model sees little left to "
            "gain, so these are weakly motivated (with constraints, they may also be "
            "unlikely to meet them: check P(feasible)). Fewer suggestions, or measuring "
            "the first ones before asking again, is usually better.\n"
            if low_ei
            else ""
        )

        if log_target:
            noise_line = (
                f"- Fitted measurement noise: **± {result['noise_sd']:.2g}** in log10 "
                f"units (1 SD), i.e. a single measurement scatters by a factor of "
                f"about {10 ** result['noise_sd']:.2g}\n"
            )
        else:
            noise_line = (
                f"- Fitted measurement noise: **± {result['noise_sd']:.2g}** (1 SD, "
                f"in `{target}` units)\n"
            )
        batch_line = ""
        if result["batch_col"]:
            batch_line = (
                f"- Batch offsets modelled across **{result['n_batches']}** batches: "
                f"batches differ by about **± {result['batch_offset_sd']:.2g}**{log_units} "
                "(1 SD). Predictions are for the process alone, i.e. a new batch "
                "without its own (unknown) offset.\n"
            )
        constraint_line = ""
        if result["constraints"]:
            listed = ", ".join(
                f"`{c['col']}` {c['op']} {c['value']:g}" for c in result["constraints"]
            )
            constraint_line = f"- Constraints: {listed} (each with its own model)\n"
        if result["incumbent"] is None:
            incumbent_text = "none yet (no measured sample is predicted to meet the constraints)"
        else:
            incumbent_text = f"**{result['incumbent']:.4g}**"
        summary = (
            f"### {len(suggestions)} suggested next experiment(s) to "
            f"{result['direction']} `{target}`\n\n"
            f"- Samples used: **{result['n_samples']}**{_rows_note(result)}"
            + (" (target modelled on a log10 scale)" if log_target else "")
            + "\n"
            f"- Best observed so far: **{result['best_observed']:.4g}**; best "
            f"predicted at a measured sample (what EI tries to beat): {incumbent_text}\n"
            + noise_line
            + batch_line
            + constraint_line
            + f"- Leave-one-sample-out R²{log_units}: **{result['loo_r2']:.2f}** "
            "(how well the model predicts a sample it has not seen; see the model "
            "check plot below)\n"
            + _missing_note(result)
            + "".join(f"- ⚠️ {w}\n" for w in result["warnings"])
            + "- Length scales (0-1 scaled; smaller = stronger effect; estimated "
            "from the data, so uncertain with few or noisy samples):\n"
            f"{length_scale_lines}\n"
            f"- {steps_estimate['rationale']}\n"
            + low_ei_note
            + "- Listed in the order they were picked as one batch (see 'How are the "
            "suggestions calculated?' above).\n\n" + "\n".join(table_lines)
        )
        self.plot_manager.create_bo_suggestions_plot(suggestions, target)
        self.plot_manager.create_bo_loo_plot(result["loo_df"], target, result["loo_r2"], log_target)
        # Swap the Processing banner for the results in one step.
        clear_output(wait=True)
        ipy_display(Markdown(summary))

    def _refresh_experimental_options(self):
        """Keep the Experimental tab's dropdowns in sync with the checked columns
        (mirrors _refresh_ml_target_options). ANOVA's grouping selector is the one
        exception: it's populated from analysis_df's categorical columns directly,
        not gated by the numeric-only Analysis Data checkboxes - see the plan's
        "design gap" note on why there's no categorical checkbox to filter by."""
        checked_results = set(self.gui.get_checked_results_columns())
        checked_metadata = set(self.gui.get_checked_metadata_columns())
        results_cols = sorted(c for c in self.analysis_results_cols if c in checked_results)
        metadata_cols = sorted(c for c in self.analysis_metadata_cols if c in checked_metadata)

        color_options = ["None"] + results_cols + metadata_cols
        prev = self.gui.experimental_pca_color_selector.value
        self.gui.experimental_pca_color_selector.options = color_options
        self.gui.experimental_pca_color_selector.value = prev if prev in color_options else "None"

        for selector in (
            self.gui.experimental_pareto_target_a_selector,
            self.gui.experimental_pareto_target_b_selector,
        ):
            prev = selector.value
            selector.options = results_cols
            selector.disabled = not results_cols
            if results_cols:
                selector.value = prev if prev in results_cols else results_cols[0]

        selector = self.gui.experimental_drift_param_selector
        prev = selector.value
        selector.options = metadata_cols
        selector.disabled = not metadata_cols
        if metadata_cols:
            selector.value = prev if prev in metadata_cols else metadata_cols[0]

        categorical_cols = (
            get_categorical_columns(self.analysis_df) if self.analysis_df is not None else []
        )
        selector = self.gui.experimental_anova_group_selector
        prev = selector.value
        selector.options = categorical_cols
        selector.disabled = not categorical_cols
        if categorical_cols:
            selector.value = prev if prev in categorical_cols else categorical_cols[0]

        selector = self.gui.experimental_anova_value_selector
        prev = selector.value
        selector.options = results_cols
        selector.disabled = not results_cols
        if results_cols:
            selector.value = prev if prev in results_cols else results_cols[0]

    def _on_run_pca(self, button):
        """Run PCA over the checked Process Metadata columns and plot PC1 vs PC2."""
        with self.gui.experimental_pca_output:
            clear_output(wait=True)

            if self.analysis_df is None or self.analysis_df.empty:
                print("⚠️ No data available. Load batches first.")
                return

            checked_metadata = set(self.gui.get_checked_metadata_columns())
            feature_cols = [c for c in self.analysis_metadata_cols if c in checked_metadata]

            try:
                result = experimental.run_pca(self.analysis_df, feature_cols=feature_cols)
            except ValueError as e:
                print(f"⚠️ {e}")
                return
            except Exception as e:
                print(f"❌ Error running PCA: {e}")
                logger.exception("Error running PCA")
                return

            color_col = self.gui.experimental_pca_color_selector.value
            color_col = None if not color_col or color_col == "None" else color_col
            scores_df = result["scores_df"]
            if color_col and color_col in self.analysis_df.columns:
                # By row position, not a merge on sample_id: a sample_id repeats
                # under "All Points", and a merge would multiply the points.
                color_values = self.analysis_df.loc[result["source_index"], color_col]
                scores_df = scores_df.assign(**{color_col: color_values.to_numpy()})

            variance_pct = ", ".join(f"{v:.1%}" for v in result["explained_variance_ratio"])
            summary = (
                f"### PCA over {len(result['feature_cols'])} checked Process Metadata parameters\n\n"
                f"- Samples used: **{result['n_samples']}**\n"
                f"- Explained variance (PC1, PC2, ...): **{variance_pct}**\n"
            )
            ipy_display(Markdown(summary))
            self.plot_manager.create_pca_scatter_plot(
                scores_df, result["explained_variance_ratio"], color_col=color_col
            )

    def _on_find_pareto_front(self, button):
        """Find the Pareto-optimal trade-off between two checked Results columns."""
        with self.gui.experimental_pareto_output:
            clear_output(wait=True)

            if self.analysis_df is None or self.analysis_df.empty:
                print("⚠️ No data available. Load batches first.")
                return

            target_a = self.gui.experimental_pareto_target_a_selector.value
            target_b = self.gui.experimental_pareto_target_b_selector.value
            if not target_a or not target_b:
                print("⚠️ Pick two target parameters first.")
                return
            if target_a == target_b:
                print("⚠️ Pick two different target parameters.")
                return

            direction_a = self.gui.experimental_pareto_direction_a_selector.value.lower()
            direction_b = self.gui.experimental_pareto_direction_b_selector.value.lower()

            try:
                result = experimental.find_pareto_front(
                    self.analysis_df, target_a, target_b, direction_a, direction_b
                )
            except ValueError as e:
                print(f"⚠️ {e}")
                return
            except Exception as e:
                print(f"❌ Error finding Pareto front: {e}")
                logger.exception("Error finding Pareto front")
                return

            summary = (
                f"### Pareto front: {direction_a} `{target_a}` vs {direction_b} `{target_b}`\n\n"
                f"- Samples used: **{result['n_samples']}**\n"
                f"- Samples on the front: **{result['n_on_front']}**\n"
            )
            ipy_display(Markdown(summary))
            self.plot_manager.create_pareto_front_plot(result["result_df"], target_a, target_b)

    def _on_detect_outliers(self, button):
        """Run Isolation Forest over the checked Process Metadata + Results columns
        combined, to flag samples whose overall profile looks unusual."""
        with self.gui.experimental_outlier_output:
            clear_output(wait=True)

            if self.analysis_df is None or self.analysis_df.empty:
                print("⚠️ No data available. Load batches first.")
                return

            checked_metadata = set(self.gui.get_checked_metadata_columns())
            checked_results = set(self.gui.get_checked_results_columns())
            feature_cols = [
                c
                for c in (*self.analysis_metadata_cols, *self.analysis_results_cols)
                if c in checked_metadata or c in checked_results
            ]
            if not feature_cols:
                print("⚠️ No columns checked. Check at least one in the Analysis Data tab.")
                return

            contamination = self.gui.experimental_outlier_contamination_selector.value

            try:
                result = experimental.detect_outliers(
                    self.analysis_df, feature_cols=feature_cols, contamination=contamination
                )
            except ValueError as e:
                print(f"⚠️ {e}")
                return
            except Exception as e:
                print(f"❌ Error detecting outliers: {e}")
                logger.exception("Error detecting outliers")
                return

            try:
                pca_result = experimental.run_pca(
                    result["result_df"], feature_cols=result["feature_cols"]
                )
            except ValueError:
                print(
                    f"✓ Found {result['n_outliers']} outlier(s) out of {result['n_samples']} "
                    "samples, but there aren't enough varying parameters to plot a 2D "
                    "PCA view."
                )
                outlier_ids = result["result_df"].loc[
                    result["result_df"]["is_outlier"], "sample_id"
                ]
                ipy_display(Markdown("Outlier sample IDs: " + ", ".join(outlier_ids.astype(str))))
                return

            summary = (
                f"### Outlier detection over {len(result['feature_cols'])} checked parameters\n\n"
                f"- Rows checked: **{result['n_samples']}** (each measurement row on its own)\n"
                f"- Outliers flagged: **{result['n_outliers']}** "
                f"(contamination={contamination:.2f})\n"
            )
            ipy_display(Markdown(summary))
            # By row position: sample_id repeats under "All Points", so a lookup
            # by sample_id would return several flags per point.
            is_outlier = result["result_df"].loc[pca_result["source_index"], "is_outlier"]
            self.plot_manager.create_outlier_plot(
                pca_result["scores_df"], is_outlier.reset_index(drop=True)
            )

    def _on_compute_process_drift(self, button):
        """Check whether a checked Process Metadata parameter trends over time."""
        with self.gui.experimental_drift_output:
            clear_output(wait=True)

            if self.analysis_df is None or self.analysis_df.empty:
                print("⚠️ No data available. Load batches first.")
                return

            param_col = self.gui.experimental_drift_param_selector.value
            if not param_col:
                print("⚠️ Pick a parameter first.")
                return

            try:
                result = experimental.compute_process_drift(self.analysis_df, param_col)
            except ValueError as e:
                print(f"⚠️ {e}")
                return
            except Exception as e:
                print(f"❌ Error checking process drift: {e}")
                logger.exception("Error checking process drift")
                return

            trend_note = (
                "significant trend" if result["p_value"] < 0.05 else "no significant trend detected"
            )
            summary = (
                f"### {param_col} over time\n\n"
                f"- Samples used: **{result['n_samples']}**\n"
                f"- Slope: **{result['slope']:.3g}** per sample, in time order "
                f"(p={result['p_value']:.3g} - {trend_note})\n"
            )
            ipy_display(Markdown(summary))
            self.plot_manager.create_process_drift_plot(
                result["trend_df"],
                param_col,
                result["datetime_col"],
                result["slope"],
                result["p_value"],
            )

    def _on_run_anova(self, button):
        """One-way ANOVA: does a checked Results column differ significantly
        across groups of a categorical process metadata column?"""
        with self.gui.experimental_anova_output:
            clear_output(wait=True)

            if self.analysis_df is None or self.analysis_df.empty:
                print("⚠️ No data available. Load batches first.")
                return

            group_col = self.gui.experimental_anova_group_selector.value
            value_col = self.gui.experimental_anova_value_selector.value
            if not group_col or not value_col:
                print("⚠️ Pick a group-by column and a measure first.")
                return

            try:
                result = experimental.run_anova(self.analysis_df, group_col, value_col)
            except ValueError as e:
                print(f"⚠️ {e}")
                return
            except Exception as e:
                print(f"❌ Error running ANOVA: {e}")
                logger.exception("Error running ANOVA")
                return

            groups_line = ", ".join(f"{name} (n={n})" for name, n in result["groups"].items())
            significance_note = "significant" if result["significant"] else "not significant"
            summary = (
                f"### ANOVA: `{value_col}` across `{group_col}`\n\n"
                f"- Groups (n = samples; pixels of one sample are averaged first): "
                f"{groups_line}\n"
                f"- F-statistic: **{result['f_stat']:.3g}**\n"
                f"- p-value: **{result['p_value']:.3g}** ({significance_note} at p<0.05)\n"
            )
            ipy_display(Markdown(summary))
            self.plot_manager.create_box_plot(
                self.analysis_df,
                group_col,
                value_col,
                None,
                group_col,
                value_col,
                target_widget=self.gui.experimental_anova_widget,
            )
