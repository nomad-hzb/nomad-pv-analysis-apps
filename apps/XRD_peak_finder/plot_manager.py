"""
plot_manager.py — XY Visualizer
Plotly only. Static methods that accept data dicts and return go.Figure objects.
"""

from __future__ import annotations

import logging
import math

import numpy as np
import plotly.graph_objects as go
from scipy.signal import find_peaks, peak_widths

logger = logging.getLogger(__name__)


class XRDPlotManager:
    """All plot factories for the XRD/XY visualizer."""

    # -----------------------------------------------------------------------
    # Peak detection (pure computation, no side-effects)
    # -----------------------------------------------------------------------

    @staticmethod
    def detect_peaks(
        x_data: list[float],
        y_data: list[float],
        height_threshold: float | None = None,
        prominence: float | None = None,
    ) -> tuple[list[float], list[float], list[float], list[tuple]]:
        """Return (positions, intensities, areas, segments).

        segments is a list of (x_seg, y_seg, baseline) numpy arrays — one per peak —
        used to draw filled area traces in the plot.
        """
        y_arr = np.array(y_data)
        x_arr = np.array(x_data)

        if height_threshold is None:
            height_threshold = float(np.max(y_arr)) * 0.1
        if prominence is None:
            prominence = float(np.max(y_arr)) * 0.05

        peaks, _ = find_peaks(y_arr, height=height_threshold, prominence=prominence, distance=5)

        areas: list[float] = []
        segments: list[tuple] = []
        if len(peaks) > 0:
            _, _, left_ips, right_ips = peak_widths(y_arr, peaks, rel_height=0.99)
            for j in range(len(peaks)):
                li = max(0, int(np.floor(left_ips[j])))
                ri = min(len(x_arr) - 1, int(np.ceil(right_ips[j])))
                x_seg = x_arr[li : ri + 1]
                y_seg = y_arr[li : ri + 1]
                baseline = np.linspace(float(y_arr[li]), float(y_arr[ri]), len(x_seg))
                areas.append(max(0.0, float(np.trapz(y_seg - baseline, x_seg))))
                segments.append((x_seg, y_seg, baseline))

        return x_arr[peaks].tolist(), y_arr[peaks].tolist(), areas, segments

    # -----------------------------------------------------------------------
    # Individual sample plot
    # -----------------------------------------------------------------------

    @staticmethod
    def individual(
        entry: dict,
        key: str,
        peak_positions: list[float] | None = None,
        peak_intensities: list[float] | None = None,
        peak_segments: list[tuple] | None = None,
    ) -> go.Figure:
        """Return a single-sample XRD figure, optionally with peak markers."""
        x_data = entry.get("angle", [])
        y_data = entry.get("intensity", [])

        fig = go.Figure()
        fig.add_trace(
            go.Scatter(
                x=x_data,
                y=y_data,
                mode="lines",
                name="Data",
                line=dict(width=2, color="blue"),
            )
        )

        if peak_positions:
            fig.add_trace(
                go.Scatter(
                    x=peak_positions,
                    y=peak_intensities,
                    mode="markers",
                    name="Peaks",
                    marker=dict(color="red", size=8, symbol="triangle-up"),
                    hovertemplate="Peak at 2θ: %{x:.2f}°<br>Intensity: %{y:.1f}<extra></extra>",
                )
            )

        if peak_segments:
            x_areas: list = []
            y_areas: list = []
            for x_seg, y_seg, baseline in peak_segments:
                # Polygon: up the data curve, back along the baseline
                x_poly = list(x_seg) + list(x_seg[::-1])
                y_poly = list(y_seg) + list(baseline[::-1])
                x_areas.extend(x_poly + [None])
                y_areas.extend(y_poly + [None])
            fig.add_trace(
                go.Scatter(
                    x=x_areas,
                    y=y_areas,
                    fill="toself",
                    mode="none",
                    name="Peak areas",
                    fillcolor="rgba(255, 165, 0, 0.3)",
                    hoverinfo="skip",
                )
            )

        # Build title
        if entry.get("file_metadata") is not None:
            meta = entry["file_metadata"]
            title_parts = [f"File: {key}"]
            if "Id" in meta:
                title_parts.append(f"ID: {meta['Id']}")
            if "Operator" in meta:
                title_parts.append(f"Operator: {meta['Operator']}")
            title = "<br>".join(title_parts)
        else:
            title = (
                f"Sample: {key}<br>"
                f"Variation: {entry.get('variation', '')}<br>"
                f"Name: {entry.get('name', '')}"
            )

        x_range = [min(x_data), max(x_data)] if x_data else None
        fig.update_layout(
            title=title,
            xaxis_title="2θ (degrees)",
            yaxis_title="Intensity",
            width=700,
            height=450,
            showlegend=True,
            xaxis=dict(dtick=5, range=x_range),
        )
        return fig

    # -----------------------------------------------------------------------
    # Overlay / stagger plot
    # -----------------------------------------------------------------------

    COLORS = [
        "blue",
        "red",
        "green",
        "orange",
        "purple",
        "brown",
        "pink",
        "gray",
        "olive",
        "cyan",
    ]

    @staticmethod
    def overlay(
        entries: dict[str, dict],
        selected_keys: list[str],
        stagger_offset: float = 0.0,
    ) -> go.Figure:
        """Return a stacked overlay figure for the selected keys."""
        fig = go.Figure()

        for i, key in enumerate(selected_keys):
            entry = entries[key]
            x_data = entry.get("angle", [])
            y_data = entry.get("intensity", [])
            staggered_y = [y + i * stagger_offset for y in y_data]
            color = XRDPlotManager.COLORS[i % len(XRDPlotManager.COLORS)]

            display_name = key
            if stagger_offset > 0:
                display_name = f"{key} (+{i * stagger_offset:.0f})"

            fig.add_trace(
                go.Scatter(
                    x=x_data,
                    y=staggered_y,
                    mode="lines",
                    name=display_name,
                    line=dict(color=color, width=2),
                )
            )

        title = "Overlay Plot — Selected Samples"
        if stagger_offset > 0:
            title += f" (stagger: {stagger_offset})"

        fig.update_layout(
            title=title,
            xaxis_title="2θ (degrees)",
            yaxis_title="Intensity",
            width=900,
            height=600,
            showlegend=True,
            xaxis=dict(dtick=5),
            legend=dict(yanchor="top", y=0.99, xanchor="left", x=1.01),
        )
        return fig

    # -----------------------------------------------------------------------
    # Stagger slider range helper (pure maths, no side-effects)
    # -----------------------------------------------------------------------

    @staticmethod
    def suggested_stagger_range(entries: dict[str, dict]) -> tuple[float, float, float]:
        """Return (slider_max, default_value, step) based on the loaded data."""
        max_intensity = 1.0
        for entry in entries.values():
            y = entry.get("intensity") or []
            if y:
                max_intensity = max(max_intensity, float(np.max(y)))

        slider_max = 10 ** math.ceil(math.log10(max_intensity)) if max_intensity > 0 else 1.0
        default_val = slider_max * 0.1
        step = max(1.0, slider_max / 100)
        return slider_max, default_val, step
