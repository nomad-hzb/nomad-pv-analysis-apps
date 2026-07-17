"""
plot_manager.py – NMR Plotter
Plotly only. Zero widget imports.
"""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from scipy.signal import find_peaks

logger = logging.getLogger(__name__)

_DEFAULT_COLORS = [
    "#1f77b4",
    "#ff7f0e",
    "#2ca02c",
    "#d62728",
    "#9467bd",
    "#8c564b",
    "#e377c2",
    "#7f7f7f",
    "#bcbd22",
    "#17becf",
]


def default_color(index: int) -> str:
    return _DEFAULT_COLORS[index % len(_DEFAULT_COLORS)]


class NMRPlotManager:
    @staticmethod
    def plot_overlay(
        df: pd.DataFrame,
        colors: dict[str, str],
        offset: float = 0.0,
    ) -> go.Figure:
        """
        Overlay all NMR spectra.

        Parameters
        ----------
        df:
            Full data DataFrame from NMRDataManager.
        colors:
            Mapping of sample_id -> hex color string.
        offset:
            Vertical offset applied cumulatively across spectra.
        """
        fig = go.Figure()

        unique_samples = df["sample_id"].unique()

        for i, sample_id in enumerate(unique_samples):
            sample_row = df[df["sample_id"] == sample_id].iloc[0]
            variation = sample_row["variation"]
            label = variation if variation else sample_id

            x = np.array(sample_row["chemical_shift"])
            y = np.array(sample_row["intensity"])

            # Noise filter: keep only points above 20x the median intensity
            mask = y >= np.median(y) * 20
            x_filt = x[mask]
            y_filt = y[mask] + i * offset

            color = colors.get(sample_id, default_color(i))

            fig.add_trace(
                go.Scatter(
                    x=x_filt,
                    y=y_filt,
                    mode="lines",
                    name=label,
                    line=dict(width=2, color=color),
                    hovertemplate=(
                        "<b>%{fullData.name}</b><br>"
                        "Chemical Shift: %{x:.2f} ppm<br>"
                        "Intensity: %{y:.2f}<br>"
                        f"Offset: {i * offset:.2f}<br>"
                        "<extra></extra>"
                    ),
                )
            )

        fig.update_layout(
            title="NMR Spectra",
            xaxis_title="Chemical Shift (ppm)",
            yaxis_title="Intensity",
            xaxis=dict(autorange="reversed"),
            hovermode="closest",
            legend=dict(orientation="v", yanchor="top", y=1, xanchor="left", x=1.02),
            height=600,
        )
        return fig

    @staticmethod
    def plot_single(
        chemical_shift: list[float],
        intensity: list[float],
        label: str,
        color: str = "#1f77b4",
        height_threshold: float = 0.1,
        range_start: float | None = None,
        range_end: float | None = None,
    ) -> tuple[go.Figure, pd.DataFrame]:
        """
        Plot one NMR spectrum with peak detection and optional integration shading.

        Returns the figure and a DataFrame of detected peaks.
        """
        x = np.array(chemical_shift)
        y = np.array(intensity)

        # Normalize for peak detection
        y_norm = (y - y.min()) / (y.max() - y.min()) if y.max() != y.min() else y

        peaks, _ = find_peaks(y_norm, height=height_threshold)

        fig = go.Figure()

        # Spectrum trace
        fig.add_trace(
            go.Scatter(
                x=x,
                y=y,
                mode="lines",
                name=label,
                line=dict(width=2, color=color),
                hovertemplate=(
                    "<b>%{fullData.name}</b><br>"
                    "Chemical Shift: %{x:.2f} ppm<br>"
                    "Intensity: %{y:.2f}<br>"
                    "<extra></extra>"
                ),
            )
        )

        # Peak markers
        if len(peaks) > 0:
            fig.add_trace(
                go.Scatter(
                    x=x[peaks],
                    y=y[peaks],
                    mode="markers",
                    name=f"Peaks ({len(peaks)} found)",
                    marker=dict(symbol="x", size=8, color="red"),
                    hovertemplate=(
                        "<b>Peak</b><br>"
                        "Chemical Shift: %{x:.2f} ppm<br>"
                        "Intensity: %{y:.2f}<br>"
                        "<extra></extra>"
                    ),
                )
            )

        # Integration range shading
        if range_start is not None and range_end is not None and range_start != range_end:
            lo, hi = min(range_start, range_end), max(range_start, range_end)
            mask = (x >= lo) & (x <= hi)
            if mask.any():
                x_r, y_r = x[mask], y[mask]
                fig.add_trace(
                    go.Scatter(
                        x=np.concatenate([x_r, x_r[::-1]]),
                        y=np.concatenate([y_r, np.zeros_like(y_r)]),
                        fill="toself",
                        fillcolor="rgba(255,255,0,0.3)",
                        line=dict(color="rgba(255,255,0,0)"),
                        name="Integration Range",
                        hoverinfo="skip",
                    )
                )

        fig.update_layout(
            title=f"Single Spectrum: {label}",
            xaxis_title="Chemical Shift (ppm)",
            yaxis_title="Intensity",
            xaxis=dict(autorange="reversed"),
            hovermode="closest",
            legend=dict(orientation="v", yanchor="top", y=1, xanchor="left", x=1.02),
            height=600,
        )

        # Build peak table
        if len(peaks) > 0:
            peak_df = pd.DataFrame(
                {
                    "Peak #": range(1, len(peaks) + 1),
                    "Chemical Shift (ppm)": [f"{v:.2f}" for v in x[peaks]],
                    "Intensity": [f"{v:.2f}" for v in y[peaks]],
                }
            )
        else:
            peak_df = pd.DataFrame(columns=["Peak #", "Chemical Shift (ppm)", "Intensity"])

        return fig, peak_df

    @staticmethod
    def compute_integral(
        chemical_shift: list[float],
        intensity: list[float],
        range_start: float,
        range_end: float,
    ) -> dict | None:
        """
        Compute the trapezoidal integral over [range_start, range_end].
        Returns a dict with keys: start, end, integral, avg_intensity, or None if no
        data points fall in the range.
        """
        x = np.array(chemical_shift)
        y = np.array(intensity)
        lo, hi = min(range_start, range_end), max(range_start, range_end)
        mask = (x >= lo) & (x <= hi)
        if not mask.any():
            return None
        x_r, y_r = x[mask], y[mask]
        integral = float(-1 * np.trapz(y_r, x_r))
        return {
            "start": lo,
            "end": hi,
            "integral": integral,
            "avg_intensity": float(np.mean(y_r)),
        }
