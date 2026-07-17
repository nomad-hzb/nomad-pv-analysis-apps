"""
TRPL Plot Manager
=================
Plotly only – no widget imports.  All methods are static and return go.Figure.
"""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

logger = logging.getLogger(__name__)


class TRPLPlotManager:
    """Static plot factory for TRPL analysis."""

    # ------------------------------------------------------------------
    # Raw / denoised TRPL traces
    # ------------------------------------------------------------------
    @staticmethod
    def trpl_traces(
        data: pd.DataFrame,
        y_col: str = "counts",
        normalize: bool = False,
        log_y: bool = True,
    ) -> go.Figure:
        """
        Overlay TRPL traces for every row in *data*.

        Parameters
        ----------
        data      : DataFrame with 'time' and *y_col* list columns, plus 'sample_id'.
        y_col     : Column to plot on the y-axis (e.g. 'counts', 'counts_no_noise').
        normalize : If True, each trace is divided by its maximum.
        log_y     : Use a log scale on the y-axis.
        """
        fig = go.Figure()
        for _, row in data.iterrows():
            t = np.array(row["time"]) * 1e9  # convert s -> ns
            y = np.array(row[y_col])
            if normalize and np.nanmax(y) > 0:
                y = y / np.nanmax(y)
            label = f"{row['sample_id']} – {row.get('data_file', '')}"
            fig.add_trace(
                go.Scatter(
                    x=t,
                    y=y,
                    mode="markers",
                    name=label,
                    marker=dict(size=3),
                )
            )
            # Noise level line when noise column is populated
            if "noise" in row.index and row["noise"] is not None:
                fig.add_hline(
                    y=row["noise"],
                    line_dash="dash",
                    opacity=0.5,
                    annotation_text=f"noise ({row['sample_id']})",
                )

        fig.update_layout(
            xaxis_title="Time [ns]",
            yaxis_title="PL counts [a.u.]" if normalize else "PL counts [#]",
            yaxis_type="log" if log_y else "linear",
            legend_title="Sample",
            template="plotly_white",
        )
        return fig

    # ------------------------------------------------------------------
    # Differential lifetime vs time
    # ------------------------------------------------------------------
    @staticmethod
    def differential_lifetime_time(
        tau_diff_list: list[np.ndarray],
        time_list: list[np.ndarray],
        labels: list[str],
    ) -> go.Figure:
        """Plot tau_diff vs time for each sample."""
        fig = go.Figure()
        for tau, t, lbl in zip(tau_diff_list, time_list, labels):
            fig.add_trace(
                go.Scatter(
                    x=t[: len(tau)] * 1e9,
                    y=tau,
                    mode="lines",
                    name=lbl,
                )
            )
        fig.update_layout(
            xaxis_title="Time [ns]",
            yaxis_title="Differential lifetime [s]",
            template="plotly_white",
        )
        return fig

    # ------------------------------------------------------------------
    # Differential lifetime vs carrier density
    # ------------------------------------------------------------------
    @staticmethod
    def differential_lifetime_density(
        tau_diff_list: list[np.ndarray],
        density_list: list[np.ndarray],
        labels: list[str],
    ) -> go.Figure:
        """Plot tau_diff vs carrier density (both log axes)."""
        fig = go.Figure()
        for tau, n, lbl in zip(tau_diff_list, density_list, labels):
            fig.add_trace(
                go.Scatter(
                    x=n[1:],
                    y=tau,
                    mode="lines",
                    name=lbl,
                )
            )
        fig.update_layout(
            xaxis_title="Carrier Concentration [cm⁻³]",
            yaxis_title="Differential lifetime [s]",
            xaxis_type="log",
            yaxis_type="log",
            template="plotly_white",
        )
        return fig

    # ------------------------------------------------------------------
    # Scatter (scalar columns)
    # ------------------------------------------------------------------
    @staticmethod
    def scatter(
        data: pd.DataFrame,
        x_col: str,
        y_col: str,
        color_col: str = "variation",
    ) -> go.Figure:
        fig = px.scatter(
            data,
            x=x_col,
            y=y_col,
            color=color_col,
            hover_data=["sample_id", "data_file"],
            template="plotly_white",
        )
        return fig

    # ------------------------------------------------------------------
    # Box (scalar columns)
    # ------------------------------------------------------------------
    @staticmethod
    def box(
        data: pd.DataFrame,
        y_col: str,
        x_col: str = "variation",
    ) -> go.Figure:
        fig = px.box(
            data,
            x=x_col,
            y=y_col,
            points="all",
            template="plotly_white",
        )
        return fig
