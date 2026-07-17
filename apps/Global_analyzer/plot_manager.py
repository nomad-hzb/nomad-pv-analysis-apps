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
from utils import get_material_column as _get_material_column

logger = logging.getLogger(__name__)


class PlotManager:
    """Manages plot creation and data preparation."""

    def __init__(self, plot_widget: go.FigureWidget, stats_output):
        """
        Initialize plot manager.

        Args:
            plot_widget: Plotly FigureWidget for rendering plots
            stats_output: Output widget for statistics display
        """
        self.plot_widget = plot_widget
        self.stats_output = stats_output

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
            xaxis_title=x_label,
            yaxis_title=y_label,
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
    ):
        """
        Create a boxplot. Caller is responsible for ensuring x is categorical.
        """
        self.plot_widget.data = []
        has_sample_id = "sample_id" in df.columns

        # Guard: numeric x makes meaningless boxes (1-2 points per unique value)
        if pd.api.types.is_numeric_dtype(df[x_col]):
            logger.warning(
                "Boxplot requires a categorical X axis. '%s' is numeric — switch to Scatter.",
                x_label,
            )
            # Render a scatter instead so the user still sees their data
            self.create_scatter_plot(df, x_col, y_col, color_col, x_label, y_label, colorscale)
            return

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
                self.plot_widget.add_trace(
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
            x_groups = sorted(df[x_col].dropna().unique())
            group_colors = self._get_trace_colors(colorscale, len(x_groups))

            for x_val, color in zip(x_groups, group_colors):
                mask = df[x_col] == x_val
                subset = df[mask]
                text = subset["sample_id"].tolist() if has_sample_id else None
                self.plot_widget.add_trace(
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

        self.plot_widget.update_layout(
            title=f"Distribution of {y_label} grouped by {x_label}",
            xaxis_title=x_label,
            yaxis_title=y_label,
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
