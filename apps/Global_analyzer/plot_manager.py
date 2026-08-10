"""
Plot Manager Module

Manages all plotting operations using Plotly for the Sample Data Explorer.
Handles data preparation, aggregation, and visualization generation.

Key Responsibilities:
    - Prepare data for plotting (handle Material Type, aggregation)
    - Create scatter plots with categorical/continuous coloring
    - Extract parameter names from display strings
    - Position legends and format plots

Classes:
    PlotManager: Plotting operations controller

Author: HySprint Team
"""

import logging
from typing import Optional, Tuple

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from IPython.display import HTML, clear_output
from IPython.display import display as ipy_display
from plotly.subplots import make_subplots
from utils import get_material_column as _get_material_column

logger = logging.getLogger(__name__)


def bin_numeric_column(series: pd.Series, n_bins: int) -> pd.Series:
    """Bin a numeric series into n_bins equal-width ranges, for boxplot grouping.

    Returns an ordered pandas Categorical of human-readable range labels (e.g.
    "12.3 to 45.6" - " to " rather than "-" as separator so negative bin edges,
    which pd.cut can produce when it slightly expands the outermost bin, stay
    unambiguous). The categories are ordered by the underlying numeric range, not
    by the label string - a plain string sort would put "100 to 110" before
    "20 to 30".
    """
    binned = pd.cut(series, bins=n_bins)
    labels = [f"{interval.left:.3g} to {interval.right:.3g}" for interval in binned.cat.categories]
    return binned.cat.rename_categories(labels)


def _ordered_unique_values(series: pd.Series) -> list:
    """Return the series' unique non-null values in their natural order.

    Respects an ordered Categorical's category order (e.g. bin_numeric_column's
    output) instead of falling back to a plain alphabetical sort, which would
    misorder range labels like "100 to 110" before "20 to 30".
    """
    if isinstance(series.dtype, pd.CategoricalDtype) and series.dtype.ordered:
        present = set(series.dropna().unique())
        return [category for category in series.cat.categories if category in present]
    return sorted(series.dropna().unique())


class PlotManager:
    """Manages plot creation and data preparation."""

    def __init__(
        self,
        plot_widget: go.FigureWidget,
        stats_output,
        correlation_widget=None,
        rf_widget=None,
        bo_widget=None,
        correlation_scatter_output=None,
        pca_widget=None,
        pareto_widget=None,
        outlier_widget=None,
        drift_widget=None,
        anova_widget=None,
    ):
        """
        Initialize plot manager.

        Args:
            plot_widget: Plotly FigureWidget for rendering plots
            stats_output: Output widget for statistics display
            correlation_widget: Plotly FigureWidget for the correlation matrix heatmap
            rf_widget: Plotly FigureWidget for the Random Forest feature-importance chart
            bo_widget: Plotly FigureWidget for the Bayesian Optimization suggestions chart
            correlation_scatter_output: Output widget for the correlation scatter-matrix
                view (a second FigureWidget doesn't work here - its subplot grid size
                changes with how many parameters pass the min_unique filter, and a
                FigureWidget's axis layout doesn't cleanly reset between calls with a
                different grid size, so this view is rendered fresh into an Output
                each time instead)
            pca_widget: Plotly FigureWidget for the Experimental tab's PCA scatter
            pareto_widget: Plotly FigureWidget for the Experimental tab's Pareto front
            outlier_widget: Plotly FigureWidget for the Experimental tab's outlier plot
            drift_widget: Plotly FigureWidget for the Experimental tab's process-drift plot
            anova_widget: Plotly FigureWidget for the Experimental tab's ANOVA boxplot -
                separate from plot_widget so it doesn't overwrite whatever the user has
                open on the main Plotting tab
        """
        self.plot_widget = plot_widget
        self.stats_output = stats_output
        self.correlation_widget = correlation_widget
        self.rf_widget = rf_widget
        self.bo_widget = bo_widget
        self.correlation_scatter_output = correlation_scatter_output
        self.pca_widget = pca_widget
        self.pareto_widget = pareto_widget
        self.outlier_widget = outlier_widget
        self.drift_widget = drift_widget
        self.anova_widget = anova_widget

    def get_material_column(self, df: pd.DataFrame) -> Optional[str]:
        """Get the material column name from dataframe."""
        return _get_material_column(df)

    def extract_column_name(self, param: str) -> str:
        """
        Extract the raw DataFrame column name from a display parameter name.
        Strips measurement suffixes like ' (JV)', ' (AbsPL)', and reverses
        display aliases like 'Notes' → 'description'.
        """
        if "(" in param:
            base = param[: param.rfind("(")].strip()
        else:
            base = param

        # Reverse display aliases
        aliases = {
            "Notes": "description",
        }
        return aliases.get(base, base)

    def prepare_plot_data(
        self,
        df: pd.DataFrame,
        x_param: str,
        y_param: str,
        color_param: Optional[str],
        aggregation: str,
        plot_type: str = "Scatter",
        color_data_source: Optional[str] = None,
        source_material_columns: Optional[dict] = None,
    ) -> Tuple[pd.DataFrame, str, str]:
        """Prepare data for plotting, preserving sample_id and color column."""
        if x_param == "Material Type":
            x_col = self.get_material_column(df)
            if x_col is None:
                raise ValueError("No material column found in dataframe")
        else:
            x_col = self.extract_column_name(x_param)

        if y_param == "Material Type":
            y_col = self.get_material_column(df)
            if y_col is None:
                raise ValueError("No material column found in dataframe")
        else:
            y_col = self.extract_column_name(y_param)

        if x_col not in df.columns or y_col not in df.columns:
            raise ValueError(f"Parameters not found in data: {x_col}, {y_col}")

        # Always include sample_id for hover tooltips
        cols_to_include = []
        if "sample_id" in df.columns:
            cols_to_include.append("sample_id")
        cols_to_include.extend([x_col, y_col])

        # Resolve color column
        color_col_resolved = None
        if color_param and color_param != "None":
            if color_param == "Material Type":
                # Use source-specific material column if available
                if color_data_source and source_material_columns:
                    color_col_resolved = source_material_columns.get(color_data_source)
                    logger.debug(
                        "Material Type color: source='%s' -> col='%s'",
                        color_data_source,
                        color_col_resolved,
                    )
                    logger.debug("Available source->col map: %s", source_material_columns)
                if not color_col_resolved:
                    color_col_resolved = self.get_material_column(df)
                    logger.debug(
                        "Material Type color: fallback to first material col='%s'",
                        color_col_resolved,
                    )
            else:
                candidate = self.extract_column_name(color_param)
                if candidate in df.columns:
                    color_col_resolved = candidate
                else:
                    # Try suffix variants from merge (e.g. 'efficiency_jv_measurement')
                    for col in df.columns:
                        if col.startswith(candidate + "_"):
                            color_col_resolved = col
                            logger.debug(
                                "Color column '%s' not found directly, using '%s'", candidate, col
                            )
                            break
                    if not color_col_resolved:
                        logger.warning(
                            "color column '%s' not found in merged data. Available columns: %s",
                            candidate,
                            list(df.columns),
                        )

            if color_col_resolved and color_col_resolved not in cols_to_include:
                cols_to_include.append(color_col_resolved)

        # Remove duplicates preserving order
        seen = set()
        cols_unique = [c for c in cols_to_include if not (c in seen or seen.add(c))]

        plot_df = df[cols_unique].copy()

        # Handle list-valued cells (multiple pixels per measurement)
        plot_df = self._handle_list_values(plot_df, x_col, y_col, aggregation)

        # Aggregate multiple rows per sample_id (Option A: one point per sample)
        # Skip for Boxplot — boxplot needs raw spread, and skip for 'All Points'
        if (
            aggregation != "All Points"
            and plot_type == "Scatter"
            and "sample_id" in plot_df.columns
        ):
            plot_df = self._aggregate_by_sample(
                plot_df, x_col, y_col, color_col_resolved, aggregation
            )

        # Drop rows with NaN in x or y
        rows_before = len(plot_df)
        color_vals_before = (
            set(plot_df[color_col_resolved].dropna().unique())
            if color_col_resolved and color_col_resolved in plot_df.columns
            else set()
        )

        plot_df = plot_df.dropna(subset=[x_col, y_col])
        rows_after = len(plot_df)

        color_vals_after = (
            set(plot_df[color_col_resolved].dropna().unique())
            if color_col_resolved and color_col_resolved in plot_df.columns
            else set()
        )

        dropped_rows = rows_before - rows_after
        dropped_color_vals = color_vals_before - color_vals_after
        logger.debug("dropna: %d -> %d rows (%d dropped)", rows_before, rows_after, dropped_rows)
        if dropped_color_vals:
            logger.debug("Color values lost (no %s data): %s", y_col, sorted(dropped_color_vals))

        logger.debug(
            "prepare_plot_data: shape=%s, x=%s, y=%s, color_col=%s, cols=%s",
            plot_df.shape,
            x_col,
            y_col,
            color_col_resolved,
            list(plot_df.columns),
        )

        return plot_df, x_col, y_col, color_col_resolved

    def _handle_list_values(
        self, df: pd.DataFrame, x_col: str, y_col: str, aggregation: str
    ) -> pd.DataFrame:
        """Handle columns with list values by applying aggregation."""

        def aggregate_value(val, method: str):
            if not isinstance(val, list):
                return val
            if not val:
                return np.nan

            clean_vals = [v for v in val if pd.notna(v)]
            if not clean_vals:
                return np.nan

            if method == "Mean":
                return np.mean(clean_vals)
            elif method == "Max":
                return np.max(clean_vals)
            elif method == "Min":
                return np.min(clean_vals)
            elif method == "Median":
                return np.median(clean_vals)
            elif method == "All Points":
                return clean_vals
            return np.mean(clean_vals)

        if aggregation == "All Points":
            # Expand rows with list values
            expanded_rows = []
            for idx, row in df.iterrows():
                x_val = row[x_col]
                y_val = row[y_col]

                x_list = x_val if isinstance(x_val, list) else [x_val]
                y_list = y_val if isinstance(y_val, list) else [y_val]

                max_len = max(len(x_list), len(y_list))
                for i in range(max_len):
                    new_row = row.copy()
                    new_row[x_col] = x_list[min(i, len(x_list) - 1)]
                    new_row[y_col] = y_list[min(i, len(y_list) - 1)]
                    expanded_rows.append(new_row)

            if expanded_rows:
                return pd.DataFrame(expanded_rows)

        # Apply aggregation to list columns
        for col in df.columns:
            df[col] = df[col].apply(lambda x: aggregate_value(x, aggregation))

        return df

    def register_click_handler(self, sample_entry_links: dict, output_widget):
        """
        Attach a click handler to the FigureWidget.
        Clicking a point displays a clickable NOMAD link in output_widget.
        Requires customdata[0] = sample_id (set in create_scatter_plot / create_box_plot).
        """

        def on_click(trace, points, state):
            if not points.point_inds:
                return
            idx = points.point_inds[0]
            try:
                sample_id = trace.customdata[idx][0]
            except (IndexError, TypeError):
                return

            url = sample_entry_links.get(sample_id)

            with output_widget:
                clear_output(wait=True)
                if url:
                    ipy_display(
                        HTML(
                            f"<b>Selected:</b> {sample_id} &nbsp;"
                            f'<a href="{url}" target="_blank" '
                            f'style="color:#1a73e8;font-weight:bold;">'
                            f"\U0001f517 Open in NOMAD</a>"
                        )
                    )
                else:
                    ipy_display(
                        HTML(
                            f"<b>Selected:</b> {sample_id} "
                            f'<span style="color:gray;">(no NOMAD link available)</span>'
                        )
                    )

        # Attach to all current traces
        for trace in self.plot_widget.data:
            trace.on_click(on_click)

        # Store so we can re-attach after plot updates
        self._click_handler = on_click

    def _aggregate_by_sample(
        self, df: pd.DataFrame, x_col: str, y_col: str, color_col: Optional[str], aggregation: str
    ) -> pd.DataFrame:
        """
        Aggregate multiple rows per sample_id into one row per sample.
        Numeric columns use the chosen method; non-numeric take the first value.
        """
        agg_func_map = {"Mean": "mean", "Max": "max", "Min": "min", "Median": "median"}
        agg_func = agg_func_map.get(aggregation, "mean")

        cols = list(df.columns)
        agg_dict = {}
        for c in cols:
            if c == "sample_id":
                continue
            if pd.api.types.is_numeric_dtype(df[c]):
                agg_dict[c] = agg_func
            else:
                agg_dict[c] = "first"

        if not agg_dict:
            return df

        result = df.groupby("sample_id", as_index=False).agg(agg_dict)
        logger.debug(
            "_aggregate_by_sample: %d rows -> %d rows (method=%s)",
            len(df),
            len(result),
            aggregation,
        )
        return result

    # Single-color lookup table
    _SINGLE_COLORS = {
        "Blue": "#2E86AB",
        "Red": "#E84855",
        "Green": "#3BB273",
        "Purple": "#7B2D8B",
        "Orange": "#F18F01",
        "Gray": "#6B6B6B",
    }

    def _get_trace_colors(self, colorscale_or_color: str, n: int) -> list:
        """
        Return a list of n colors.
        If colorscale_or_color is a known single color name, returns n copies of that color.
        Otherwise samples n evenly-spaced colors from the named Plotly colorscale.
        """
        if colorscale_or_color in self._SINGLE_COLORS:
            return [self._SINGLE_COLORS[colorscale_or_color]] * n

        try:
            import plotly.colors as pc

            fractions = [0.5] if n == 1 else [i / (n - 1) for i in range(n)]
            return pc.sample_colorscale(colorscale_or_color, fractions)
        except Exception as e:
            logger.debug("_get_trace_colors fallback: %s", e)
            return ["#2E86AB"] * n

    def create_scatter_plot(
        self,
        df: pd.DataFrame,
        x_col: str,
        y_col: str,
        color_col: Optional[str],
        x_label: str,
        y_label: str,
        colorscale: str = "Viridis",
    ):
        """Create a scatter plot with sample ID and color value in hover tooltip."""
        self.plot_widget.data = []

        has_sample_id = "sample_id" in df.columns

        def build_customdata(subset, extra_col=None):
            """Build customdata array: [[sample_id, extra_val], ...]"""
            if has_sample_id and extra_col and extra_col in subset.columns:
                return subset[["sample_id", extra_col]].values
            elif has_sample_id:
                return subset[["sample_id"]].values
            return None

        def hover_template(extra_label=None, is_categorical_color=False, category_name=None):
            parts = [f"{x_label}: %{{x}}", f"{y_label}: %{{y}}"]
            if has_sample_id:
                parts.append("Sample: %{customdata[0]}")
            if is_categorical_color and category_name is not None:
                parts.append(f"Color ({extra_label}): {category_name}")
            elif extra_label and not is_categorical_color:
                parts.append(f"{extra_label}: %{{customdata[1]}}")
            return "<br>".join(parts) + "<extra></extra>"

        if color_col and color_col in df.columns:
            color_data = df[color_col]
            logger.debug(
                "Applying color column '%s', dtype=%s, nunique=%d, sample values=%s",
                color_col,
                color_data.dtype,
                color_data.nunique(),
                color_data.dropna().unique()[:5].tolist(),
            )

            if pd.api.types.is_numeric_dtype(color_data):
                customdata = build_customdata(df, color_col)
                trace = go.Scatter(
                    x=df[x_col],
                    y=df[y_col],
                    mode="markers",
                    customdata=customdata,
                    marker=dict(
                        color=color_data,
                        colorscale=colorscale,
                        showscale=True,
                        colorbar=dict(title=color_col),
                        size=10,
                    ),
                    hovertemplate=hover_template(extra_label=color_col),
                )
                self.plot_widget.add_trace(trace)
            else:
                # Categorical colors - one trace per category, colored by colorscale
                categories = sorted(color_data.dropna().unique())
                cat_colors = self._get_trace_colors(colorscale, len(categories))
                for category, cat_color in zip(categories, cat_colors):
                    mask = color_data == category
                    subset = df[mask]
                    customdata = build_customdata(subset)
                    self.plot_widget.add_trace(
                        go.Scatter(
                            x=subset[x_col],
                            y=subset[y_col],
                            mode="markers",
                            name=str(category),
                            customdata=customdata,
                            marker=dict(size=10, color=cat_color),
                            hovertemplate=hover_template(
                                extra_label=color_col,
                                is_categorical_color=True,
                                category_name=str(category),
                            ),
                        )
                    )
        else:
            if color_col:
                logger.debug(
                    "color_col '%s' not in plot_df columns: %s", color_col, list(df.columns)
                )
            customdata = build_customdata(df)
            trace = go.Scatter(
                x=df[x_col],
                y=df[y_col],
                mode="markers",
                customdata=customdata,
                marker=dict(color="#2E86AB", size=10),
                hovertemplate=hover_template(),
            )
            self.plot_widget.add_trace(trace)

        self.plot_widget.update_layout(
            title=f"{y_label} vs {x_label}",
            # type="-" forces Plotly to re-detect the axis type (date/linear/
            # category) from this call's data instead of keeping whatever
            # type a previous plot left behind - a FigureWidget's layout
            # persists across calls (only .data is cleared above), so e.g. a
            # datetime x-axis would otherwise "stick" the next time X is a
            # numeric parameter.
            xaxis=dict(title=x_label, type="-"),
            yaxis=dict(title=y_label, type="-"),
            legend=dict(
                orientation="v",
                yanchor="top",
                y=1,
                xanchor="left",
                x=1.02,
                bgcolor="rgba(255, 255, 255, 0.8)",
                bordercolor="rgba(0, 0, 0, 0.2)",
                borderwidth=1,
            ),
            margin=dict(r=200),
        )

    def create_correlation_heatmap(self, df: pd.DataFrame, min_unique: int = 5) -> list:
        """
        Compute and render a correlation matrix heatmap over every numeric column with
        more than `min_unique` distinct values - filters out near-constant/binary flag
        columns that would otherwise clutter the matrix without saying anything useful.

        Returns the list of columns actually included, so the caller can report it.
        """
        if self.correlation_widget is None:
            raise ValueError("PlotManager has no correlation_widget configured")

        numeric_df = df.select_dtypes(include="number")
        varying_cols = [
            col for col in numeric_df.columns if numeric_df[col].dropna().nunique() > min_unique
        ]

        self.correlation_widget.data = []

        if len(varying_cols) < 2:
            self.correlation_widget.update_layout(
                title="Not enough varying numeric parameters for a correlation matrix"
            )
            return varying_cols

        corr = numeric_df[varying_cols].corr()

        self.correlation_widget.add_trace(
            go.Heatmap(
                z=corr.values,
                x=list(corr.columns),
                y=list(corr.index),
                colorscale="RdBu",
                zmid=0,
                zmin=-1,
                zmax=1,
                colorbar=dict(title="Pearson r"),
                text=[[f"{v:.2f}" for v in row] for row in corr.values],
                texttemplate="%{text}",
                hovertemplate="%{x} vs %{y}: %{z:.3f}<extra></extra>",
            )
        )
        self.correlation_widget.update_layout(
            title=f"Correlation matrix ({len(varying_cols)} parameters, >{min_unique} unique values)",
            height=max(500, 30 * len(varying_cols)),
            template="plotly_white",
            xaxis=dict(tickangle=-45),
            margin=dict(l=150, b=150),
        )
        return varying_cols

    def create_metadata_results_heatmap(
        self,
        df: pd.DataFrame,
        results_cols: list,
        metadata_cols: list,
        min_unique: int = 5,
    ) -> Tuple[list, list]:
        """
        Cross-correlation heatmap: measurement results on the x-axis, process
        metadata on the y-axis - unlike create_correlation_heatmap's full NxN
        matrix, this never correlates two results or two metadata columns against
        each other, only results against metadata. Both axes are filtered to
        columns with more than `min_unique` distinct values, same as
        create_correlation_heatmap.

        Returns (results_used, metadata_used) so the caller can report them.
        """
        if self.correlation_widget is None:
            raise ValueError("PlotManager has no correlation_widget configured")

        numeric_df = df.select_dtypes(include="number")
        results_used = [
            col
            for col in results_cols
            if col in numeric_df.columns and numeric_df[col].dropna().nunique() > min_unique
        ]
        metadata_used = [
            col
            for col in metadata_cols
            if col in numeric_df.columns and numeric_df[col].dropna().nunique() > min_unique
        ]

        self.correlation_widget.data = []

        if not results_used or not metadata_used:
            self.correlation_widget.update_layout(
                title="Not enough varying parameters on both axes for a heatmap"
            )
            return results_used, metadata_used

        corr = pd.DataFrame(
            {
                result_col: numeric_df[metadata_used].corrwith(numeric_df[result_col])
                for result_col in results_used
            }
        )

        self.correlation_widget.add_trace(
            go.Heatmap(
                z=corr.values,
                x=list(corr.columns),
                y=list(corr.index),
                colorscale="RdBu",
                zmid=0,
                zmin=-1,
                zmax=1,
                colorbar=dict(title="Pearson r"),
                text=[[f"{v:.2f}" for v in row] for row in corr.values],
                texttemplate="%{text}",
                hovertemplate="%{x} vs %{y}: %{z:.3f}<extra></extra>",
            )
        )
        self.correlation_widget.update_layout(
            title=(
                f"Results vs Process Metadata ({len(results_used)} x {len(metadata_used)}, "
                f">{min_unique} unique values)"
            ),
            height=max(500, 30 * len(metadata_used)),
            template="plotly_white",
            xaxis=dict(tickangle=-45),
            margin=dict(l=150, b=150),
        )
        return results_used, metadata_used

    def create_correlation_scatter_matrix(
        self, df: pd.DataFrame, min_unique: int = 5, max_params: int = 12
    ) -> tuple:
        """
        Render the second correlation view (matching JV-Analysis's Heatmap/Scatter
        Matrix pair): diagonal histograms, lower-triangle scatter, upper-triangle
        Pearson r as colored text. Capped at max_params columns - an NxN subplot grid
        gets unusably large/slow well before then.

        Renders into self.correlation_scatter_output (a plain Output, not a
        FigureWidget - see __init__'s docstring for why) rather than
        self.correlation_widget. Returns (columns_used, truncated).
        """
        if self.correlation_scatter_output is None:
            raise ValueError("PlotManager has no correlation_scatter_output configured")

        numeric_df = df.select_dtypes(include="number")
        varying_cols = [
            col for col in numeric_df.columns if numeric_df[col].dropna().nunique() > min_unique
        ]
        truncated = len(varying_cols) > max_params
        varying_cols = varying_cols[:max_params]

        with self.correlation_scatter_output:
            clear_output(wait=True)

            if len(varying_cols) < 2:
                return varying_cols, truncated

            subset = numeric_df[varying_cols]
            corr = subset.corr()
            n = len(varying_cols)

            scatter_color = "rgba(93, 164, 214, 0.5)"
            hist_color = "rgba(93, 164, 214, 0.7)"

            fig = make_subplots(
                rows=n,
                cols=n,
                shared_xaxes=False,
                shared_yaxes=False,
                horizontal_spacing=0.04,
                vertical_spacing=0.04,
            )

            for row_idx, label_y in enumerate(varying_cols):
                for col_idx, label_x in enumerate(varying_cols):
                    r, c = row_idx + 1, col_idx + 1

                    if col_idx > row_idx:
                        # Upper triangle: Pearson r as colored text (red=positive, blue=negative)
                        r_val = corr.loc[label_y, label_x]
                        abs_r = abs(r_val)
                        text_color = (
                            f"rgba(215, 48, 39, {0.4 + 0.6 * abs_r:.2f})"
                            if r_val > 0
                            else f"rgba(69, 117, 180, {0.4 + 0.6 * abs_r:.2f})"
                        )
                        font_size = int(9 + 9 * abs_r)
                        fig.add_trace(
                            go.Scatter(
                                x=[0.5],
                                y=[0.5],
                                mode="text",
                                text=[f"<b>{r_val:.2f}</b>"],
                                textfont=dict(size=font_size, color=text_color),
                                showlegend=False,
                                hovertemplate=(
                                    f"<b>{label_x} vs {label_y}</b><br>"
                                    f"Pearson r = {r_val:.3f}<extra></extra>"
                                ),
                            ),
                            row=r,
                            col=c,
                        )
                        fig.update_xaxes(
                            range=[0, 1],
                            showticklabels=False,
                            showgrid=False,
                            zeroline=False,
                            row=r,
                            col=c,
                        )
                        fig.update_yaxes(
                            range=[0, 1],
                            showticklabels=False,
                            showgrid=False,
                            zeroline=False,
                            row=r,
                            col=c,
                        )
                        continue
                    elif col_idx == row_idx:
                        # Diagonal: histogram of the variable
                        vals = subset[label_x].dropna()
                        fig.add_trace(
                            go.Histogram(
                                x=vals,
                                marker_color=hist_color,
                                showlegend=False,
                                hovertemplate=(
                                    f"<b>{label_x}</b><br>Value: %{{x:.3f}}<br>"
                                    "Count: %{y}<extra></extra>"
                                ),
                            ),
                            row=r,
                            col=c,
                        )
                    else:
                        # Lower triangle: scatter
                        common_idx = subset[[label_x, label_y]].dropna().index
                        fig.add_trace(
                            go.Scatter(
                                x=subset.loc[common_idx, label_x],
                                y=subset.loc[common_idx, label_y],
                                mode="markers",
                                marker=dict(size=3, color=scatter_color, opacity=0.7),
                                showlegend=False,
                                hovertemplate=(
                                    f"<b>{label_x} vs {label_y}</b><br>"
                                    f"{label_x}: %{{x:.3f}}<br>"
                                    f"{label_y}: %{{y:.3f}}<extra></extra>"
                                ),
                            ),
                            row=r,
                            col=c,
                        )

            for i, label in enumerate(varying_cols):
                fig.update_xaxes(title_text=label, title_font=dict(size=9), row=n, col=i + 1)
                if i > 0:
                    fig.update_yaxes(title_text=label, title_font=dict(size=9), row=i + 1, col=1)

            cell_size = max(90, min(150, 900 // n))
            title = f"Scatter matrix ({n} parameters, >{min_unique} unique values)"
            if truncated:
                title += f" - showing first {max_params}"
            fig.update_layout(
                title=title,
                height=cell_size * n + 80,
                template="plotly_white",
                margin=dict(l=80, r=40, t=80, b=80),
                showlegend=False,
            )

            ipy_display(fig)

        return varying_cols, truncated

    def create_feature_importance_plot(self, importances: list, target: str):
        """Render Random Forest feature importances as a horizontal bar chart, most
        important parameter on top. Caps at the top 15 for readability."""
        if self.rf_widget is None:
            raise ValueError("PlotManager has no rf_widget configured")

        top = importances[:15]
        names = [name for name, _ in top][::-1]
        values = [value for _, value in top][::-1]

        self.rf_widget.data = []
        self.rf_widget.add_trace(
            go.Bar(x=values, y=names, orientation="h", marker=dict(color="#2E86AB"))
        )
        self.rf_widget.update_layout(
            title=f"Feature importance for {target}",
            xaxis_title="Importance",
            template="plotly_white",
            height=max(400, 30 * len(top)),
            margin=dict(l=200),
        )

    def create_bo_suggestions_plot(self, suggestions: pd.DataFrame, target_col: str):
        """Render suggested next-experiment predictions (mean ± std) as a bar chart,
        ranked left-to-right by expected improvement (the suggestions DataFrame's own
        row order, set by the caller)."""
        if self.bo_widget is None:
            raise ValueError("PlotManager has no bo_widget configured")

        pred_col = f"predicted_{target_col}"
        labels = [f"#{i + 1}" for i in range(len(suggestions))]

        self.bo_widget.data = []
        self.bo_widget.add_trace(
            go.Bar(
                x=labels,
                y=suggestions[pred_col],
                error_y=dict(type="data", array=suggestions["predicted_std"]),
                marker=dict(color="#7B2D8B"),
            )
        )
        self.bo_widget.update_layout(
            title=f"Predicted {target_col} for suggested next experiments",
            xaxis_title="Suggestion (ranked by expected improvement)",
            yaxis_title=target_col,
            template="plotly_white",
            height=450,
        )

    def create_pca_scatter_plot(
        self,
        scores_df: pd.DataFrame,
        explained_variance_ratio: list,
        color_col: Optional[str] = None,
    ):
        """Render PC1 vs PC2 from experimental_analysis.run_pca's scores_df, axis
        titles annotated with % variance explained. Colors by color_col if given
        and present (categorical: one trace per category; numeric: a single
        trace with a continuous colorscale)."""
        if self.pca_widget is None:
            raise ValueError("PlotManager has no pca_widget configured")

        self.pca_widget.data = []
        pc1_pct = explained_variance_ratio[0] * 100
        pc2_pct = explained_variance_ratio[1] * 100 if len(explained_variance_ratio) > 1 else 0.0

        if color_col and color_col in scores_df.columns:
            if pd.api.types.is_numeric_dtype(scores_df[color_col]):
                self.pca_widget.add_trace(
                    go.Scatter(
                        x=scores_df["PC1"],
                        y=scores_df["PC2"],
                        mode="markers",
                        marker=dict(
                            color=scores_df[color_col], colorscale="Viridis", showscale=True
                        ),
                        text=scores_df.get("sample_id"),
                        hovertemplate="PC1: %{x:.3g}<br>PC2: %{y:.3g}<br>Sample: %{text}<extra></extra>",
                    )
                )
            else:
                categories = sorted(scores_df[color_col].dropna().unique())
                colors = self._get_trace_colors("Viridis", len(categories))
                for category, color in zip(categories, colors):
                    subset = scores_df[scores_df[color_col] == category]
                    self.pca_widget.add_trace(
                        go.Scatter(
                            x=subset["PC1"],
                            y=subset["PC2"],
                            mode="markers",
                            name=str(category),
                            marker=dict(color=color),
                            text=subset.get("sample_id"),
                            hovertemplate=(
                                "PC1: %{x:.3g}<br>PC2: %{y:.3g}<br>Sample: %{text}"
                                f"<extra>{category}</extra>"
                            ),
                        )
                    )
        else:
            self.pca_widget.add_trace(
                go.Scatter(
                    x=scores_df["PC1"],
                    y=scores_df["PC2"],
                    mode="markers",
                    marker=dict(color="#2E86AB"),
                    text=scores_df.get("sample_id"),
                    hovertemplate="PC1: %{x:.3g}<br>PC2: %{y:.3g}<br>Sample: %{text}<extra></extra>",
                )
            )

        self.pca_widget.update_layout(
            title="PCA of checked Process Metadata parameters",
            xaxis_title=f"PC1 ({pc1_pct:.1f}% variance)",
            yaxis_title=f"PC2 ({pc2_pct:.1f}% variance)",
            template="plotly_white",
            height=500,
        )

    def create_pareto_front_plot(
        self,
        result_df: pd.DataFrame,
        target_a: str,
        target_b: str,
        is_pareto_col: str = "is_pareto_optimal",
    ):
        """Render the Pareto-front scatter: dominated points in gray, the front
        itself highlighted and connected by a line in target_a order."""
        if self.pareto_widget is None:
            raise ValueError("PlotManager has no pareto_widget configured")

        self.pareto_widget.data = []
        dominated = result_df[~result_df[is_pareto_col]]
        front = result_df[result_df[is_pareto_col]].sort_values(target_a)

        self.pareto_widget.add_trace(
            go.Scatter(
                x=dominated[target_a],
                y=dominated[target_b],
                mode="markers",
                name="Dominated",
                marker=dict(color="lightgray", size=7),
                text=dominated.get("sample_id"),
                hovertemplate=f"{target_a}: %{{x:.3g}}<br>{target_b}: %{{y:.3g}}<br>Sample: %{{text}}<extra></extra>",
            )
        )
        self.pareto_widget.add_trace(
            go.Scatter(
                x=front[target_a],
                y=front[target_b],
                mode="markers+lines",
                name="Pareto front",
                marker=dict(color="#D7301F", size=9),
                line=dict(color="#D7301F", dash="dot"),
                text=front.get("sample_id"),
                hovertemplate=f"{target_a}: %{{x:.3g}}<br>{target_b}: %{{y:.3g}}<br>Sample: %{{text}}<extra></extra>",
            )
        )
        self.pareto_widget.update_layout(
            title=f"Pareto front: {target_a} vs {target_b}",
            xaxis_title=target_a,
            yaxis_title=target_b,
            template="plotly_white",
            height=500,
        )

    def create_outlier_plot(self, pca_scores_df: pd.DataFrame, is_outlier: pd.Series):
        """Render outlier flags positioned via a 2-component PCA of the checked
        features (computed by the caller, purely for visualization - this method
        only plots, it doesn't refit anything)."""
        if self.outlier_widget is None:
            raise ValueError("PlotManager has no outlier_widget configured")

        self.outlier_widget.data = []
        normal = pca_scores_df[~is_outlier.to_numpy()]
        outliers = pca_scores_df[is_outlier.to_numpy()]

        self.outlier_widget.add_trace(
            go.Scatter(
                x=normal["PC1"],
                y=normal["PC2"],
                mode="markers",
                name="Normal",
                marker=dict(color="#2E86AB", size=7),
                text=normal.get("sample_id"),
                hovertemplate="PC1: %{x:.3g}<br>PC2: %{y:.3g}<br>Sample: %{text}<extra></extra>",
            )
        )
        self.outlier_widget.add_trace(
            go.Scatter(
                x=outliers["PC1"],
                y=outliers["PC2"],
                mode="markers",
                name="Outlier",
                marker=dict(color="#D7301F", size=10, symbol="x"),
                text=outliers.get("sample_id"),
                hovertemplate="PC1: %{x:.3g}<br>PC2: %{y:.3g}<br>Sample: %{text}<extra></extra>",
            )
        )
        self.outlier_widget.update_layout(
            title="Outlier detection (positioned via PCA of checked parameters)",
            xaxis_title="PC1",
            yaxis_title="PC2",
            template="plotly_white",
            height=500,
        )

    def create_process_drift_plot(
        self,
        trend_df: pd.DataFrame,
        param_col: str,
        datetime_col: str,
        slope: float,
        p_value: float,
    ):
        """Render param_col vs datetime_col with a fitted linear trend line
        overlaid, slope/p-value in the title."""
        if self.drift_widget is None:
            raise ValueError("PlotManager has no drift_widget configured")

        self.drift_widget.data = []
        self.drift_widget.add_trace(
            go.Scatter(
                x=trend_df[datetime_col],
                y=trend_df[param_col],
                mode="markers",
                name="Measured",
                marker=dict(color="#2E86AB"),
                text=trend_df.get("sample_id"),
                hovertemplate="%{x}<br>"
                + f"{param_col}: %{{y:.3g}}<br>Sample: %{{text}}<extra></extra>",
            )
        )

        time_ordinal = np.arange(len(trend_df))
        intercept = trend_df[param_col].mean() - slope * time_ordinal.mean()
        fitted = slope * time_ordinal + intercept
        self.drift_widget.add_trace(
            go.Scatter(
                x=trend_df[datetime_col],
                y=fitted,
                mode="lines",
                name="Trend",
                line=dict(color="#D7301F", dash="dash"),
            )
        )

        self.drift_widget.update_layout(
            title=f"{param_col} over time (slope={slope:.3g}, p={p_value:.3g})",
            xaxis_title=datetime_col,
            yaxis_title=param_col,
            template="plotly_white",
            height=450,
        )

    def display_statistics(
        self, df: pd.DataFrame, x_col: str, y_col: str, x_label: str, y_label: str
    ):
        """Display plot statistics in the stats output widget.

        Note: caller is responsible for clearing stats_output before calling this.
        """
        with self.stats_output:
            print(f"Number of points: {len(df)}")

            if pd.api.types.is_numeric_dtype(df[y_col]):
                print(f"\nY ({y_label}):")
                print(f"  Mean: {df[y_col].mean():.3f}")
                print(f"  Std:  {df[y_col].std():.3f}")
                print(f"  Min:  {df[y_col].min():.3f}")
                print(f"  Max:  {df[y_col].max():.3f}")

            if pd.api.types.is_numeric_dtype(df[x_col]) and pd.api.types.is_numeric_dtype(
                df[y_col]
            ):
                try:
                    corr = df[x_col].corr(df[y_col])
                    print(f"\nCorrelation: {corr:.3f}")
                except Exception:
                    pass

    def create_box_plot(
        self,
        df: pd.DataFrame,
        x_col: str,
        y_col: str,
        color_col: Optional[str],
        x_label: str,
        y_label: str,
        colorscale: str = "Viridis",
        bin_count: Optional[int] = None,
        target_widget: Optional[go.FigureWidget] = None,
    ):
        """
        Create a boxplot. Caller is responsible for ensuring x is categorical,
        unless bin_count is given - numeric x is then binned into bin_count
        equal-width groups via bin_numeric_column. Renders into target_widget if
        given (e.g. the Experimental tab's ANOVA view), otherwise self.plot_widget
        (the main Plotting tab), so ANOVA doesn't overwrite what the user has open
        there.
        """
        widget = target_widget if target_widget is not None else self.plot_widget
        widget.data = []
        has_sample_id = "sample_id" in df.columns

        # Guard: numeric x makes meaningless boxes (1-2 points per unique value),
        # unless the caller asked for it to be binned into groups.
        if pd.api.types.is_numeric_dtype(df[x_col]):
            if not bin_count:
                logger.warning(
                    "Boxplot requires a categorical X axis. '%s' is numeric — switch to Scatter.",
                    x_label,
                )
                # Render a scatter instead so the user still sees their data
                self.create_scatter_plot(df, x_col, y_col, color_col, x_label, y_label, colorscale)
                return
            df = df.copy()
            df[x_col] = bin_numeric_column(df[x_col], bin_count)

        if (
            color_col
            and color_col in df.columns
            and not pd.api.types.is_numeric_dtype(df[color_col])
        ):
            # Categorical color_col — one trace per category, grouped boxes
            categories = sorted(df[color_col].dropna().unique())
            cat_colors = self._get_trace_colors(colorscale, len(categories))

            for category, color in zip(categories, cat_colors):
                mask = df[color_col] == category
                subset = df[mask]
                text = subset["sample_id"].tolist() if has_sample_id else None
                widget.add_trace(
                    go.Box(
                        x=subset[x_col],
                        y=subset[y_col],
                        name=str(category),
                        text=text,
                        hovertemplate=(
                            f"{x_label}: %{{x}}<br>"
                            f"{y_label}: %{{y}}<br>"
                            f"Sample: %{{text}}"
                            f"<extra>{category}</extra>"
                        ),
                        boxpoints="all",
                        jitter=0.4,
                        pointpos=0,
                        marker=dict(color=color, size=6),
                        line=dict(color=color),
                    )
                )
        else:
            # No categorical color — one trace per unique x-group, each gets a colorscale color
            x_groups = _ordered_unique_values(df[x_col])
            group_colors = self._get_trace_colors(colorscale, len(x_groups))

            for x_val, color in zip(x_groups, group_colors):
                mask = df[x_col] == x_val
                subset = df[mask]
                text = subset["sample_id"].tolist() if has_sample_id else None
                widget.add_trace(
                    go.Box(
                        x=subset[x_col],
                        y=subset[y_col],
                        name=str(x_val),
                        text=text,
                        hovertemplate=(
                            f"{x_label}: %{{x}}<br>"
                            f"{y_label}: %{{y}}<br>"
                            f"Sample: %{{text}}"
                            f"<extra>{x_val}</extra>"
                        ),
                        boxpoints="all",
                        jitter=0.4,
                        pointpos=0,
                        marker=dict(color=color, size=6),
                        line=dict(color=color),
                    )
                )

        widget.update_layout(
            title=f"Distribution of {y_label} grouped by {x_label}",
            # type="-" re-detects the axis type fresh each call - see the
            # matching comment in create_scatter_plot for why that matters.
            xaxis=dict(title=x_label, type="-"),
            yaxis=dict(title=y_label, type="-"),
            boxmode="group",
            legend=dict(
                orientation="v",
                yanchor="top",
                y=1,
                xanchor="left",
                x=1.02,
                bgcolor="rgba(255,255,255,0.8)",
                bordercolor="rgba(0,0,0,0.2)",
                borderwidth=1,
            ),
            margin=dict(r=200),
        )

        if isinstance(df[x_col].dtype, pd.CategoricalDtype) and df[x_col].dtype.ordered:
            # Force the axis to follow the (possibly binned) category order rather
            # than Plotly's default "trace" order, which follows row order and can
            # scramble numeric bin ranges when a categorical color_col is also set.
            widget.update_layout(
                xaxis=dict(categoryorder="array", categoryarray=_ordered_unique_values(df[x_col]))
            )
