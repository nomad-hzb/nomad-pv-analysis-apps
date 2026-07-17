"""
plot_manager.py
All plot creation logic. Returns plotly Figure objects.
No widget dependencies -- compatible with ipywidgets, Panel, or any other frontend.
"""

import logging

import plotly.express as px
import plotly.graph_objects as go

logger = logging.getLogger(__name__)


class AbsPlPlotManager:
    """Creates plotly figures for AbsPL data."""

    @staticmethod
    def scatter(
        data,
        x_col: str,
        y_col: str,
        color_col: str | None = None,
    ) -> go.Figure:
        fig = px.scatter(
            data,
            x=x_col,
            y=y_col,
            color=color_col,
            hover_data=["name", "sample_id"],
            title=f"Scatter Plot: {y_col} vs {x_col}",
        )
        fig.update_layout(height=600, width=800)
        return fig

    @staticmethod
    def box(
        data,
        y_col: str,
        x_col: str | None = None,
    ) -> go.Figure:
        if x_col:
            fig = px.box(data, x=x_col, y=y_col, title=f"Box Plot of {y_col} by {x_col}")
        else:
            fig = px.box(data, y=y_col, title=f"Box Plot of {y_col}")
        fig.update_layout(height=600, width=800)
        return fig

    @staticmethod
    def spectral(
        data,
        selected_variations: list[str],
        y_col: str,
        scale: str = "linear",
        normalize: bool = False,
    ) -> go.Figure:
        colorscale = px.colors.qualitative.Plotly
        variation_colors = {
            var: colorscale[i % len(colorscale)] for i, var in enumerate(selected_variations)
        }

        fig = go.Figure()
        filtered = data[data["variation"].isin(selected_variations)]

        for variation in selected_variations:
            vdata = filtered[filtered["variation"] == variation]
            color = variation_colors[variation]

            for i, row in vdata.iterrows():
                wavelengths = row["wavelength"]
                luminescence = row[y_col]
                if luminescence is None:
                    continue
                if normalize and max(luminescence) > 0:
                    luminescence = [v / max(luminescence) for v in luminescence]

                name = f"{variation} - {row['name']}" if row["name"] else f"{variation} {i}"
                fig.add_trace(
                    go.Scatter(
                        x=wavelengths,
                        y=luminescence,
                        mode="lines",
                        name=name,
                        line=dict(width=2, color=color),
                        hovertemplate=(
                            "Wavelength: %{x:.2f} nm<br>"
                            "Luminescence: %{y:.4e}"
                            "<extra>%{fullData.name}</extra>"
                        ),
                    )
                )

        y_title = "Normalized Luminescence" if normalize else "Luminescence Flux Density"
        fig.update_layout(
            title="Wavelength vs. Luminescence Flux Density",
            xaxis_title="Wavelength (nm)",
            yaxis_title=y_title,
            yaxis_type=scale,
            height=600,
            width=900,
            template="plotly_white",
            legend_title_text="Sample",
            hovermode="closest",
            xaxis=dict(rangeslider=dict(visible=True), type="linear"),
        )
        return fig

    @staticmethod
    def statistics_box(
        data,
        col: str,
        groupby: str | None = None,
    ) -> go.Figure:
        if groupby and groupby != "None":
            fig = px.box(data, x=groupby, y=col, title=f"Comparison of {col} by {groupby}")
        else:
            fig = px.box(data, y=col, title=f"Distribution of {col}")
        fig.update_layout(height=500, width=700)
        return fig
