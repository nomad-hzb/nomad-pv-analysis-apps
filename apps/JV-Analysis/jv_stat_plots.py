"""Statistical JV plots, as a mixin of PlotManager (plot_manager.py).

Boxplots, histograms, combination plots and correlation plots of the JV parameters.
"""

import logging

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots

try:
    from utils import save_combined_excel_data
except ImportError:

    def save_combined_excel_data(*args, **kwargs):
        return None


logger = logging.getLogger(__name__)


def _parse_custom_order(order_str):
    """
    Parse a custom order string into an ordered list of display groups.

    Format examples:
        "L1, L2, L3"                        → simple ordered list
        "(L1, l1, 10min), L2, (L3, 30min)"  → aliased groups; first alias is displayed,
                                               all aliases in a group match the same category

    Returns a list of dicts [{'display': str, 'aliases': [str, ...]}, ...],
    or None if the string is empty.
    """
    order_str = order_str.strip()
    if not order_str:
        return None

    # Split by top-level commas (ignore commas inside parentheses)
    tokens = []
    depth = 0
    current = ""
    for char in order_str:
        if char == "(":
            depth += 1
            current += char
        elif char == ")":
            depth -= 1
            current += char
        elif char == "," and depth == 0:
            tokens.append(current.strip())
            current = ""
        else:
            current += char
    if current.strip():
        tokens.append(current.strip())

    groups = []
    for token in tokens:
        token = token.strip()
        if not token:
            continue
        if token.startswith("(") and token.endswith(")"):
            aliases = [a.strip() for a in token[1:-1].split(",") if a.strip()]
            if aliases:
                groups.append({"display": aliases[0], "aliases": aliases})
        else:
            groups.append({"display": token, "aliases": [token]})

    return groups if groups else None


class StatPlotsMixin:
    def create_boxplot(
        self,
        data,
        var_x,
        var_y,
        filtered_info,
        datatype="data",
        wb=None,
        colors=None,
        sort_order="Alphanumeric ↑",
        custom_order="",
        direction_split=False,
    ):
        """Create a boxplot with statistical analysis - ENHANCED with data verification"""
        names_dict = self.PARAM_COLUMNS
        var_name_y = names_dict[var_y]
        trash, filters = filtered_info

        if var_x == "batch" and "batch_for_plotting" in data.columns:
            var_x = "batch_for_plotting"

        # Show what samples are included in this plot
        unique_samples = data["sample"].nunique()  # noqa: F841
        unique_cells = data.groupby("sample")["cell"].nunique().sum()  # noqa: F841

        try:
            data["sample"] = data["sample"].astype(int)
        except ValueError:
            pass

        data = data.copy()  # Don't modify original data

        # Handle MultiIndex if present
        if isinstance(data.columns, pd.MultiIndex):
            data.columns = [
                "_".join(str(col).strip() for col in column if str(col) != "")
                for column in data.columns.values
            ]
        if isinstance(data.index, pd.MultiIndex):
            data = data.reset_index()

        data["Jsc(mA/cm2)"] = data["Jsc(mA/cm2)"].abs()

        # Apply custom order: filter data to only listed categories and relabel aliases
        custom_groups = None
        if sort_order == "Custom" and custom_order:
            custom_groups = _parse_custom_order(custom_order)
            if custom_groups:
                alias_to_display = {}
                for g in custom_groups:
                    for alias in g["aliases"]:
                        alias_to_display[alias] = g["display"]
                data[var_x] = data[var_x].astype(str)
                mask = data[var_x].isin(alias_to_display)
                data = data[mask].copy()
                data[var_x] = data[var_x].map(alias_to_display)
                # Trash counts are no longer meaningful after relabelling
                trash = trash.iloc[0:0]

        # Calculate statistics
        descriptor = data.groupby(var_x)[var_name_y].describe()

        # Get initial ordering
        initial_orderc = descriptor.sort_index()["count"].index

        # Custom ordering to put Reverse before Forward (always overrides sort_order)
        if "direction" in var_x.lower() or (
            len(initial_orderc) == 2 and set(initial_orderc) == {"Forward", "Reverse"}
        ):
            orderc = (
                ["Reverse", "Forward"]
                if set(initial_orderc) == {"Forward", "Reverse"}
                else list(initial_orderc)
            )
        elif sort_order == "Custom" and custom_groups:
            # Preserve the exact order from the parsed groups (already applied to data above)
            present = set(initial_orderc)
            orderc = [g["display"] for g in custom_groups if g["display"] in present]
        elif sort_order == "Alphanumeric ↓":
            orderc = sorted(initial_orderc, reverse=True)
        elif sort_order == "Mean ↑":
            means = data.groupby(var_x)[var_name_y].mean()
            orderc = means.sort_values(ascending=True).index.tolist()
        elif sort_order == "Mean ↓":
            means = data.groupby(var_x)[var_name_y].mean()
            orderc = means.sort_values(ascending=False).index.tolist()
        elif sort_order == "Median ↑":
            medians = data.groupby(var_x)[var_name_y].median()
            orderc = medians.sort_values(ascending=True).index.tolist()
        elif sort_order == "Median ↓":
            medians = data.groupby(var_x)[var_name_y].median()
            orderc = medians.sort_values(ascending=False).index.tolist()
        else:  # "Alphanumeric ↑" (default)
            orderc = list(initial_orderc)  # already sorted by sort_index()

        # Create dictionaries to map categories to their counts
        data_counts = data.groupby(var_x)[var_name_y].count().to_dict()
        trash_counts = trash.groupby(var_x)[var_name_y].count().to_dict() if not trash.empty else {}

        fig = go.Figure()

        # Use provided color scheme or default
        if colors is None:
            colors = [
                "rgba(93, 164, 214, 0.7)",
                "rgba(255, 144, 14, 0.7)",
                "rgba(44, 160, 101, 0.7)",
                "rgba(255, 65, 54, 0.7)",
                "rgba(207, 114, 255, 0.7)",
                "rgba(127, 96, 0, 0.7)",
                "rgba(255, 140, 184, 0.7)",
                "rgba(79, 90, 117, 0.7)",
            ]

        _dir_colors = {
            "Reverse": "rgba(255, 182, 193, 0.8)",
            "Forward": "rgba(173, 216, 230, 0.8)",
        }

        use_direction_split = (
            direction_split and "direction" in data.columns and var_x != "direction"
        )

        if use_direction_split:
            # Two traces (one per direction); x values are the category labels so Plotly
            # automatically groups them side by side under boxmode="group".
            for direction in ["Reverse", "Forward"]:
                dir_data = data[data["direction"] == direction]
                x_vals, y_vals, customdata = [], [], []
                for category in orderc:
                    cat_dir = dir_data[dir_data[var_x] == category]
                    ys = cat_dir[var_name_y].dropna()
                    if not ys.empty:
                        x_vals.extend([str(category)] * len(ys))
                        y_vals.extend(ys.tolist())
                        customdata.extend(cat_dir.loc[ys.index, ["sample", "cell"]].values.tolist())

                if y_vals:
                    fig.add_trace(
                        go.Box(
                            x=x_vals,
                            y=y_vals,
                            name=direction,
                            legendgroup=direction,
                            boxpoints="all",
                            pointpos=0,
                            jitter=0.5,
                            whiskerwidth=0.4,
                            marker=dict(size=5, opacity=0.7, color="rgba(0,0,0,0.7)"),
                            line=dict(width=1.5),
                            fillcolor=_dir_colors.get(direction, colors[0]),
                            boxmean=True,
                            customdata=customdata,
                            hovertemplate=(
                                f"<b>%{{x}} — {direction}</b><br>"
                                + "Value: %{y:.3f}<br>"
                                + "Sample: %{customdata[0]}<br>"
                                + "Cell: %{customdata[1]}"
                            ),
                        )
                    )
            show_legend = True
        else:
            # Original single-color per category
            for i, category in enumerate(orderc):
                category_data = data[data[var_x] == category][var_name_y].dropna()
                if not category_data.empty:
                    data_count = data_counts.get(category, 0)
                    trash_count = trash_counts.get(category, 0)
                    median = category_data.median()
                    mean = category_data.mean()

                    category_name = (
                        f"{category} (n={data_count})"
                        if trash_count == 0
                        else f"{category} ({data_count}/{data_count + trash_count})"
                    )

                    fig.add_trace(
                        go.Box(
                            y=category_data,
                            name=category_name,
                            boxpoints="all",
                            pointpos=0,
                            jitter=0.5,
                            whiskerwidth=0.4,
                            marker=dict(size=5, opacity=0.7, color="rgba(0,0,0,0.7)"),
                            line=dict(width=1.5),
                            fillcolor=colors[i % len(colors)],
                            boxmean=True,
                            width=0.8,
                            customdata=data[data[var_x] == category][["sample", "cell"]].values,
                            hovertemplate=(
                                f"<b>{category}</b><br>"
                                + "Value: %{y:.3f}<br>"
                                + "Sample: %{customdata[0]}<br>"
                                + "Cell: %{customdata[1]}<br>"
                                + f"Median: {median:.3f}<br>"
                                + f"Mean: {mean:.3f}<br>"
                                + f"Count: {data_count}"
                            ),
                        )
                    )
            show_legend = False

        # Create title with data info
        dir_note = " | split by scan direction" if use_direction_split else ""
        title_text = f"Boxplot of {var_y} by {var_x}{dir_note}" + (
            " (filtered out)" if datatype == "junk" else " (filtered data)"
        )
        subtitle = f"Data from {len(data)} measurements across {data[var_x].nunique()} {var_x} categories (after filtering)"  # noqa: E501

        fig.update_layout(
            title=f"{title_text}<br><sup>{subtitle}</sup>",
            xaxis_title=var_x,
            yaxis_title=self.UNIT_LABELS.get(var_name_y, var_name_y),
            boxmode="group",
            boxgap=0.05,
            boxgroupgap=0.1,
            template="plotly_white",
            margin=dict(l=40, r=40, t=100, b=80),
            showlegend=show_legend,
            plot_bgcolor="white",
            paper_bgcolor="white",
        )

        # Rotate x-axis labels if many categories
        if len(orderc) > 4:
            fig.update_layout(xaxis=dict(tickangle=-10, tickfont=dict(size=10)))

        # Save to Excel if workbook provided
        if wb:
            try:
                from utils import save_combined_excel_data

                wb = save_combined_excel_data(
                    self.plot_output_path,
                    wb,
                    data,
                    filtered_info,
                    var_x,
                    var_name_y,
                    var_y,
                    descriptor,
                )
            except ImportError:
                pass  # Skip Excel save if utils not available

        sample_name = (
            f"boxplotj_{var_y}_by_{var_x}.html"
            if datatype == "junk"
            else f"boxplot_{var_y}_by_{var_x}.html"
        )

        return fig, sample_name, wb

    def create_histogram(self, df, var_y, colors=None):
        """Create a histogram with statistics"""
        logger.debug("📊 Creating histogram with %s records for %s", len(df), var_y)

        names_dict = {
            "voc": "Voc(V)",
            "jsc": "Jsc(mA/cm2)",
            "ff": "FF(%)",
            "pce": "PCE(%)",
            "vmpp": "V_mpp(V)",
            "jmpp": "J_mpp(mA/cm2)",
            "pmpp": "P_mpp(mW/cm2)",
            "rser": "R_series(Ohmcm2)",
            "rshu": "R_shunt(Ohmcm2)",
        }

        pl_y = names_dict[var_y]

        # Determine number of bins
        bins = {"voc": 20, "jsc": 30}.get(var_y, 40)

        # Create histogram
        fig = go.Figure()

        primary_color = colors[0] if colors else "rgba(0, 0, 255, 0.6)"
        line_color = (
            colors[0].replace("0.6", "1.0")
            if colors and "rgba" in colors[0]
            else "rgba(0, 0, 255, 1)"
        )

        fig.add_trace(
            go.Histogram(
                x=df[pl_y],
                marker=dict(color=primary_color, line=dict(color=line_color, width=1)),
                hovertemplate=f"{pl_y}: %{{x:.3f}}<br>Count: %{{y}}<extra></extra>",
            )
        )

        # Add KDE if enough data points
        if len(df) > 5:
            try:
                from scipy import stats

                kde_x = np.linspace(df[pl_y].min(), df[pl_y].max(), 100)
                kde = stats.gaussian_kde(df[pl_y].dropna())
                kde_y = kde(kde_x) * len(df) * (df[pl_y].max() - df[pl_y].min()) / bins

                fig.add_trace(
                    go.Scatter(
                        x=kde_x,
                        y=kde_y,
                        mode="lines",
                        line=dict(color="red", width=2),
                        name="KDE",
                        hoverinfo="skip",
                    )
                )
            except ImportError:
                pass  # Skip KDE if scipy not available

        # Calculate statistics
        mean_val = df[pl_y].mean()
        median_val = df[pl_y].median()
        std_val = df[pl_y].std()
        min_val = df[pl_y].min()
        max_val = df[pl_y].max()
        count_val = len(df)

        # Create subplot with statistics table
        fig_with_stats = make_subplots(
            rows=2,
            cols=1,
            row_heights=[0.7, 0.3],  # Main plot takes 75%, stats take 25%
            specs=[[{"type": "histogram"}], [{"type": "table"}]],
            subplot_titles=["", "Statistics"],
            vertical_spacing=0.2,
        )

        # Add the histogram trace to the first subplot
        fig_with_stats.add_trace(
            go.Histogram(
                x=df[pl_y],
                marker=dict(color=primary_color, line=dict(color=line_color, width=1)),
                hovertemplate=f"{pl_y}: %{{x:.3f}}<br>Count: %{{y}}<extra></extra>",
            ),
            row=1,
            col=1,
        )

        # Add KDE if enough data points
        if len(df) > 5:
            try:
                from scipy import stats

                kde_x = np.linspace(df[pl_y].min(), df[pl_y].max(), 100)
                kde = stats.gaussian_kde(df[pl_y].dropna())
                kde_y = kde(kde_x) * len(df) * (df[pl_y].max() - df[pl_y].min()) / bins

                fig_with_stats.add_trace(
                    go.Scatter(
                        x=kde_x,
                        y=kde_y,
                        mode="lines",
                        line=dict(color="red", width=2),
                        name="KDE",
                        hoverinfo="skip",
                    ),
                    row=1,
                    col=1,
                )
            except ImportError:
                pass

        # Add statistics table
        fig_with_stats.add_trace(
            go.Table(
                header=dict(values=["Statistic", "Value"], fill_color="lightgray", align="left"),
                cells=dict(
                    values=[
                        ["Count", "Mean", "Median", "Std Dev", "Min", "Max"],
                        [
                            f"{count_val}",
                            f"{mean_val:.3f}",
                            f"{median_val:.3f}",
                            f"{std_val:.3f}",
                            f"{min_val:.3f}",
                            f"{max_val:.3f}",
                        ],
                    ],
                    fill_color="white",
                    align="left",
                ),
            ),
            row=2,
            col=1,
        )

        # Update layout
        fig_with_stats.update_layout(
            title=f"Histogram of {pl_y} (Filtered Data)",
            template="plotly_white",
            bargap=0.1,
            hovermode="closest",
            height=750,
            showlegend=True,  # Change from False to True
            legend=dict(
                x=1.02,
                y=1,
                bgcolor="rgba(255,255,255,0.9)",
                bordercolor="black",
                borderwidth=1,
                xanchor="left",
                yanchor="top",
            ),
            margin=dict(r=150),  # Add right margin for external legend
        )

        fig_with_stats.update_xaxes(title_text=pl_y, row=1, col=1)
        fig_with_stats.update_yaxes(title_text="Frequency", row=1, col=1)
        fig_with_stats.update_xaxes(showgrid=True, gridwidth=1, gridcolor="lightgray", row=1, col=1)
        fig_with_stats.update_yaxes(showgrid=True, gridwidth=1, gridcolor="lightgray", row=1, col=1)

        # Use the subplot figure instead of the original
        fig = fig_with_stats
        sample_name = f"histogram_{var_y}_filtered.html"

        return fig, sample_name

    def create_combination_plots(self, data, var_y, combination_type, filtered_info, colors=None):
        """Create multiple plots separated by condition/direction/cell and grouped by status/condition"""  # noqa: E501
        logger.debug("📊 Creating combination plots: %s", combination_type)

        names_dict = self.PARAM_COLUMNS
        var_name_y = names_dict[var_y]

        # Filter out dark measurements (D1, D2, etc.) for these combination plots
        data = data[~data["status"].str.startswith("D")].copy()
        logger.debug("   Filtered out dark measurements, %s records remaining", len(data))

        # Define what we separate plots by and what we group within plots
        plot_config = {
            "sg": {
                "primary_var": "condition",
                "primary_label": "Condition",
                "secondary_var": "status",
                "secondary_label": "Status",
            },
            "cg": {
                "primary_var": "condition",
                "primary_label": "Condition",
                "secondary_var": "direction",
                "secondary_label": "Direction",
            },
            "bg": {
                "primary_var": "condition",
                "primary_label": "Condition",
                "secondary_var": "cell",
                "secondary_label": "Cell",
            },
        }

        if combination_type not in plot_config:
            logger.warning("Warning: Unknown combination type %s", combination_type)
            return [], []

        config = plot_config[combination_type]
        primary_var = config["primary_var"]
        primary_label = config["primary_label"]
        secondary_var = config["secondary_var"]
        secondary_label = config["secondary_label"]

        # Check if required columns exist
        missing_cols = []
        for col in [primary_var, secondary_var]:
            if col not in data.columns:
                missing_cols.append(col)

        if missing_cols:
            logger.warning("Warning: Missing columns %s in data", missing_cols)
            return [], []

        # Get unique values for primary variable (what we separate plots by)
        primary_values = sorted(data[primary_var].unique())

        if not primary_values:
            logger.warning("Warning: No data found for primary variable %s", primary_var)
            return [], []

        figures = []
        figure_names = []

        # Create separate plot for each primary variable value
        for primary_val in primary_values:
            primary_data = data[data[primary_var] == primary_val]

            if primary_data.empty:
                continue

            # Custom ordering for direction to put Reverse before Forward
            if secondary_var == "direction":
                secondary_values = (
                    ["Reverse", "Forward"]
                    if set(primary_data[secondary_var].unique()) == {"Forward", "Reverse"}
                    else sorted(primary_data[secondary_var].unique())
                )
            else:
                secondary_values = sorted(primary_data[secondary_var].unique())

            if not secondary_values:
                continue

            fig = go.Figure()

            # Use a pleasing color palette
            if colors is None:
                colors = [
                    "rgba(93, 164, 214, 0.7)",
                    "rgba(255, 144, 14, 0.7)",
                    "rgba(44, 160, 101, 0.7)",
                    "rgba(255, 65, 54, 0.7)",
                    "rgba(207, 114, 255, 0.7)",
                    "rgba(127, 96, 0, 0.7)",
                    "rgba(255, 140, 184, 0.7)",
                    "rgba(79, 90, 117, 0.7)",
                ]

            # Add boxplot for each secondary value within this primary value
            for i, secondary_val in enumerate(secondary_values):
                subset_data = primary_data[primary_data[secondary_var] == secondary_val][
                    var_name_y
                ].dropna()

                if not subset_data.empty:
                    count = len(subset_data)
                    median = subset_data.median()
                    mean = subset_data.mean()

                    fig.add_trace(
                        go.Box(
                            y=subset_data,
                            name=f"{secondary_val} (n={count})",
                            boxpoints="all",
                            pointpos=0,
                            jitter=0.5,
                            whiskerwidth=0.4,
                            marker=dict(size=5, opacity=0.7, color="rgba(0,0,0,0.7)"),
                            line=dict(width=1.5),
                            fillcolor=colors[i % len(colors)],
                            boxmean=True,
                            width=0.8,
                            hovertemplate=(
                                f"<b>{secondary_val}</b><br>"
                                + "Value: %{y:.3f}<br>"
                                + f"Median: {median:.3f}<br>"
                                + f"Mean: {mean:.3f}<br>"
                                + f"Count: {count}"
                            ),
                        )
                    )

            # Update layout
            title_text = f"{var_y} by {secondary_label} ({primary_label}: {primary_val})"
            subtitle = f"Data from {len(primary_data)} measurements (light only)"

            fig.update_layout(
                title=f"{title_text}<br><sup>{subtitle}</sup>",
                xaxis_title=f"{secondary_label}",
                yaxis_title=self.UNIT_LABELS.get(var_name_y, var_name_y),
                boxmode="group",
                boxgap=0.05,
                boxgroupgap=0.1,
                template="plotly_white",
                margin=dict(l=40, r=40, t=100, b=80),
                showlegend=False,
                plot_bgcolor="white",
                paper_bgcolor="white",
            )

            # Rotate x-axis labels if many secondary values
            if len(secondary_values) > 4:
                fig.update_layout(xaxis=dict(tickangle=-10, tickfont=dict(size=10)))

            figures.append(fig)

            # Clean primary_val for filename (remove special characters)
            clean_primary_val = (
                str(primary_val).replace(" ", "_").replace("/", "_").replace("&", "and")
            )
            figure_names.append(
                f"boxplot_{var_y}_by_{secondary_var}_{primary_var}_{clean_primary_val}.html"
            )

        logger.debug("   Created %s combination plots", len(figures))
        return figures, figure_names

    def create_triple_combination_plots(
        self, data, var_y, combination_type, filtered_info, colors=None
    ):
        """Create a single figure with facet subplots per condition, colored by direction."""
        logger.debug("🎨 Creating triple combination plots: %s", combination_type)

        names_dict = self.PARAM_COLUMNS
        var_name_y = names_dict[var_y]

        data = data[~data["status"].str.startswith("D")].copy()
        logger.debug("   Filtered out dark measurements, %s records remaining", len(data))

        required_cols = ["condition", "status", "direction"]
        missing_cols = [col for col in required_cols if col not in data.columns]
        if missing_cols:
            logger.warning("Warning: Missing columns %s in data", missing_cols)
            return [], []

        if data.empty:
            return [], []

        # Order direction so Reverse always comes first
        data["direction"] = pd.Categorical(
            data["direction"], categories=["Reverse", "Forward"], ordered=True
        )
        data = data.sort_values("direction")

        fig = px.box(
            data,
            x="status",
            y=var_name_y,
            color="direction",
            facet_col="condition",
            facet_col_wrap=3,
            points="outliers",
            template="plotly_white",
            color_discrete_map={
                "Reverse": "rgba(255, 182, 193, 0.8)",
                "Forward": "rgba(173, 216, 230, 0.8)",
            },
            labels={var_name_y: self.UNIT_LABELS.get(var_name_y, var_name_y)},
            title=f"{var_y} by Direction and Status per Condition<br><sup>Light measurements only, {len(data)} records</sup>",  # noqa: E501
        )

        fig.update_traces(quartilemethod="linear", jitter=0.4, marker=dict(size=4, opacity=0.6))

        n_conditions = data["condition"].nunique()
        n_rows = int(np.ceil(n_conditions / 3))

        fig.update_layout(
            height=400 * n_rows,
            boxmode="group",
            boxgap=0.01,
            boxgroupgap=0.02,
            margin=dict(l=60, r=160, t=120, b=80),
            legend=dict(
                x=1.01,
                y=1,
                xanchor="left",
                yanchor="top",
                bgcolor="rgba(255,255,255,0.9)",
                bordercolor="black",
                borderwidth=1,
            ),
        )

        # Clean up facet labels (remove "condition=")
        fig.for_each_annotation(lambda a: a.update(text=a.text.split("=")[-1]))

        figure_name = f"boxplot_{var_y}_by_direction_status_all_conditions.html"
        logger.debug("   Created 1 combined facet figure for %s conditions", n_conditions)
        return [fig], [figure_name]

    def create_correlation_plot(self, data, filtered_info, colors=None, all_data=False):
        """Create a correlation heatmap of all JV parameters."""
        logger.debug("📊 Creating correlation plot")

        col_map = {
            "Voc": "Voc(V)",
            "Jsc": "Jsc(mA/cm2)",
            "FF": "FF(%)",
            "PCE": "PCE(%)",
            "Voc x FF": "Voc x FF(V%)",
            "R_ser": "R_series(Ohmcm2)",
            "R_shu": "R_shunt(Ohmcm2)",
            "V_mpp": "V_mpp(V)",
            "J_mpp": "J_mpp(mA/cm2)",
            "P_mpp": "P_mpp(mW/cm2)",
        }
        display_labels = list(col_map.keys())
        actual_cols = [col_map[k] for k in display_labels]

        available = [c for c in actual_cols if c in data.columns]
        available_labels = [display_labels[actual_cols.index(c)] for c in available]

        subset = data[available].copy()
        subset["Jsc(mA/cm2)"] = subset["Jsc(mA/cm2)"].abs()

        corr = subset.corr()
        corr_rounded = corr.round(2)

        fig = go.Figure(
            go.Heatmap(
                z=corr.values,
                x=available_labels,
                y=available_labels,
                colorscale="RdBu",
                zmid=0,
                zmin=-1,
                zmax=1,
                text=corr_rounded.values,
                texttemplate="%{text}",
                hovertemplate="x: %{x}<br>y: %{y}<br>r = %{z:.3f}<extra></extra>",
                colorbar=dict(title="Pearson r"),
            )
        )

        data_label = "all data" if all_data else "filtered data"
        fig.update_layout(
            title=(
                f"Correlation Matrix of JV Parameters<br>"
                f"<sup>{len(data)} measurements ({data_label})</sup>"
            ),
            template="plotly_white",
            autosize=True,
            height=650,
            margin=dict(l=80, r=40, t=100, b=80),
        )

        return fig, "correlation_jv_parameters.html"

    def create_correlation_scatter_matrix(self, data, filtered_info, colors=None, all_data=False):
        """Create a scatter matrix with histograms on the diagonal (lower triangle only)."""
        logger.debug("📊 Creating correlation scatter matrix")

        col_map = {
            "Voc": "Voc(V)",
            "Jsc": "Jsc(mA/cm2)",
            "FF": "FF(%)",
            "PCE": "PCE(%)",
            "Voc x FF": "Voc x FF(V%)",
            "R_ser": "R_series(Ohmcm2)",
            "R_shu": "R_shunt(Ohmcm2)",
            "V_mpp": "V_mpp(V)",
            "J_mpp": "J_mpp(mA/cm2)",
            "P_mpp": "P_mpp(mW/cm2)",
        }
        display_labels = list(col_map.keys())
        actual_cols = [col_map[k] for k in display_labels]

        available = [c for c in actual_cols if c in data.columns]
        available_labels = [display_labels[actual_cols.index(c)] for c in available]

        subset = data[available].copy()
        subset.columns = available_labels
        subset["Jsc"] = subset["Jsc"].abs()

        corr = subset.corr()

        n = len(available_labels)
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

        for row_idx, label_y in enumerate(available_labels):
            for col_idx, label_x in enumerate(available_labels):
                r, c = row_idx + 1, col_idx + 1

                if col_idx > row_idx:
                    # Upper triangle: show Pearson R value
                    r_val = corr.loc[label_y, label_x]
                    abs_r = abs(r_val)
                    # Color: red (positive) / blue (negative), intensity scales with |r|
                    if r_val > 0:
                        text_color = f"rgba(215, 48, 39, {0.4 + 0.6 * abs_r:.2f})"
                    else:
                        text_color = f"rgba(69, 117, 180, {0.4 + 0.6 * abs_r:.2f})"
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
                                f"Pearson R = {r_val:.3f}<extra></extra>"
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
                    # Align indices
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

        # Add axis labels along the edges only
        for i, label in enumerate(available_labels):
            # Bottom row: x-axis titles
            fig.update_xaxes(title_text=label, title_font=dict(size=10), row=n, col=i + 1)
            # Left column: y-axis titles (skip diagonal)
            if i > 0:
                fig.update_yaxes(title_text=label, title_font=dict(size=10), row=i + 1, col=1)

        cell_size = max(110, min(170, 900 // n))
        data_label = "all data" if all_data else "filtered data"
        fig.update_layout(
            title=(
                f"Scatter Matrix of JV Parameters<br>"
                f"<sup>{len(data)} measurements ({data_label}) — "
                f"diagonal: distribution, lower triangle: scatter</sup>"
            ),
            height=cell_size * n + 80,
            autosize=True,
            template="plotly_white",
            margin=dict(l=80, r=40, t=100, b=80),
            showlegend=False,
        )

        return fig, "correlation_scatter_matrix.html"

    def create_voc_jsc_ff_pce_subplots(
        self, data, filtered_info, colors=None, var_x=None, direction_split=False
    ):
        """Create a 2x2 facet figure with Voc, Jsc, FF, PCE boxplots."""
        logger.debug("📊 Creating Voc/Jsc/FF/PCE subplots")

        params = ["Voc(V)", "Jsc(mA/cm2)", "FF(%)", "PCE(%)"]
        param_labels = ["Voc", "Jsc", "FF", "PCE"]

        available = [c for c in params if c in data.columns]
        if not available:
            logger.warning("Warning: none of the expected columns found in data")
            return None, ""

        data = data.copy()
        data["Jsc(mA/cm2)"] = data["Jsc(mA/cm2)"].abs()

        if var_x is None:
            var_x = "batch_for_plotting" if "batch_for_plotting" in data.columns else "sample"
        elif var_x == "batch" and "batch_for_plotting" in data.columns:
            var_x = "batch_for_plotting"

        if var_x not in data.columns:
            var_x = "sample"

        try:
            data[var_x] = data[var_x].astype(int)
        except (ValueError, TypeError):
            pass

        use_direction_color = (
            direction_split and "direction" in data.columns and var_x != "direction"
        )

        if use_direction_color:
            # Order direction so Reverse always comes first
            data["direction"] = pd.Categorical(
                data["direction"], categories=["Reverse", "Forward"], ordered=True
            )
            data = data.sort_values("direction")
            id_vars = [var_x, "direction"]
        else:
            id_vars = [var_x]

        # Melt to long format so px.box can use facet_col
        melt_df = data[id_vars + available].melt(
            id_vars=id_vars, value_vars=available, var_name="parameter", value_name="value"
        )

        # Use short labels for display
        label_map = dict(zip(params, param_labels))
        melt_df["parameter"] = melt_df["parameter"].map(label_map)

        # Fix parameter order
        melt_df["parameter"] = pd.Categorical(
            melt_df["parameter"], categories=param_labels, ordered=True
        )
        melt_df = melt_df.sort_values("parameter")

        if colors is None:
            colors = [
                "rgba(93, 164, 214, 0.7)",
                "rgba(255, 144, 14, 0.7)",
                "rgba(44, 160, 101, 0.7)",
                "rgba(255, 65, 54, 0.7)",
                "rgba(207, 114, 255, 0.7)",
                "rgba(127, 96, 0, 0.7)",
                "rgba(255, 140, 184, 0.7)",
                "rgba(79, 90, 117, 0.7)",
            ]

        dir_note = " | split by scan direction" if use_direction_color else ""
        common_kwargs = dict(
            x=var_x,
            y="value",
            facet_col="parameter",
            facet_col_wrap=2,
            facet_col_spacing=0.08,
            points="all",
            template="plotly_white",
            title=(
                f"The big 4 — Voc, Jsc, FF, PCE by {var_x}{dir_note}<br>"
                f"<sup>{len(data)} measurements (filtered data)</sup>"
            ),
        )
        if use_direction_color:
            px_kwargs = {
                **common_kwargs,
                "color": "direction",
                "color_discrete_map": {
                    "Reverse": "rgba(255, 182, 193, 0.8)",
                    "Forward": "rgba(173, 216, 230, 0.8)",
                },
            }
        else:
            px_kwargs = {
                **common_kwargs,
                "color": var_x,
                "color_discrete_sequence": colors,
            }

        fig = px.box(melt_df, **px_kwargs)

        # px.box never sets fillcolor explicitly -- the per-category/direction color
        # from color_discrete_sequence/color_discrete_map lives entirely in
        # marker.color, and the box fill falls back to it at render time. Snapshot
        # that as an explicit fillcolor before overriding marker.color below, or
        # every box collapses to the same flat marker color.
        for trace in fig.data:
            trace.fillcolor = trace.marker.color

        # Match the single-parameter boxplot's styling (create_boxplot): black,
        # semi-opaque points that read clearly against any fill color, a defined
        # box outline, and an explicit box width so each box keeps real margin
        # from its neighbors and the facet frame, instead of nearly filling the
        # slot boxgap leaves it.
        fig.update_traces(
            quartilemethod="linear",
            jitter=0.5,
            pointpos=0,
            whiskerwidth=0.4,
            width=0.8,
            marker=dict(size=5, opacity=0.7, color="rgba(0,0,0,0.7)"),
            line=dict(width=1.5),
            boxmean=True,
        )

        layout_kwargs = dict(
            height=750,
            # color is tied 1:1 to x here, so there's only ever one box per x
            # position; "group" would reserve an empty slot per legend entry at
            # every position and shrink the boxes. Direction-split genuinely has
            # two groups (Reverse/Forward) sharing each position, so it keeps
            # "group".
            boxmode="group" if use_direction_color else "overlay",
            boxgap=0.05,
            boxgroupgap=0.1,
        )
        if use_direction_color:
            layout_kwargs["margin"] = dict(l=60, r=160, t=120, b=80)
            layout_kwargs["legend"] = dict(
                x=1.01,
                y=1,
                xanchor="left",
                yanchor="top",
                bgcolor="rgba(255,255,255,0.9)",
                bordercolor="black",
                borderwidth=1,
            )
        else:
            layout_kwargs["margin"] = dict(l=60, r=40, t=120, b=80)
            layout_kwargs["showlegend"] = False

        fig.update_layout(**layout_kwargs)

        # Clean up facet labels (remove "parameter=")
        fig.for_each_annotation(lambda a: a.update(text=a.text.split("=")[-1]))

        # Independent y-axes per facet, each labelled with its own units. With
        # facet_col_wrap=2 and this fixed param_labels order (Voc, Jsc, FF, PCE),
        # Plotly Express lays the grid out as Voc|Jsc on top and FF|PCE below, and
        # addresses rows bottom-up (row=1 is the bottom row) -- verified empirically,
        # since that ordering isn't documented.
        fig.update_yaxes(matches=None, showticklabels=True, title="")
        n_facet_cols = 2
        n_facet_rows = -(-len(param_labels) // n_facet_cols)  # ceil division
        for i, (param, label) in enumerate(zip(params, param_labels)):
            fig.update_yaxes(
                title_text=self.UNIT_LABELS.get(param, label),
                row=n_facet_rows - (i // n_facet_cols),
                col=i % n_facet_cols + 1,
            )

        # Solid frame around each of the 4 facet subplots
        fig.update_xaxes(showline=True, linewidth=1.5, linecolor="#999999", mirror=True)
        fig.update_yaxes(showline=True, linewidth=1.5, linecolor="#999999", mirror=True)

        return fig, "boxplot_voc_jsc_ff_pce_2x2.html"
