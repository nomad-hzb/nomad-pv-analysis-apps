"""plot_manager.py -- pure Plotly; zero widget imports."""

from __future__ import annotations

import itertools
import logging
from typing import TYPE_CHECKING, Callable

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import plotly.io as pio

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from data_manager import EQEDataManager

# ---------------------------------------------------------------------------
# Shared template (built once at import time)
# ---------------------------------------------------------------------------

_VIVID = px.colors.qualitative.Vivid


def _build_template() -> go.layout.Template:
    t = pio.templates["plotly_white"]
    t.data.scatter = [go.Scatter(line_color=c) for c in _VIVID]
    return t


_TEMPLATE = _build_template()


# ---------------------------------------------------------------------------
# EQE curve plot
# ---------------------------------------------------------------------------


def plot_eqe_curves(
    dm: "EQEDataManager",
    axis_col: str,  # "photon_energy_array" or "wavelength_array"
    axis_title: str,
    width: int,
    height: int,
    group_by_name: bool,
    use_std: bool,  # True = mean+std; False = median+quartiles
    name_fn: Callable[[str, str], str],
) -> go.Figure:
    """Return a Plotly Figure of EQE curves for all selected cells."""

    color_cycle = itertools.cycle(_VIVID)

    fig = go.Figure(
        layout=go.Layout(
            width=width,
            height=height,
            xaxis={"title": {"text": axis_title}},
            yaxis={"title": {"text": "external quantum efficiency"}},
            template=_TEMPLATE,
        )
    )

    if group_by_name:
        # Collect all selected curves by their display name
        grouped: dict[str, list[pd.DataFrame]] = {}
        for sid in dm.sample_ids:
            sample_name = _sample_display_name(dm, sid)
            filtered = dm.params.loc[sid]
            filtered = filtered[filtered["plot"]]
            for idx in filtered.index:
                label = name_fn(sample_name, filtered.loc[idx, "name"])
                curve_df = dm.curves.loc[(sid, *idx), :]
                grouped.setdefault(label, []).append(curve_df)

        for label, curve_list in grouped.items():
            color = next(color_cycle)
            _add_grouped_traces(fig, curve_list, label, color, axis_col, use_std)

    else:
        for sid in dm.sample_ids:
            sample_name = _sample_display_name(dm, sid)
            filtered = dm.params.loc[sid]
            filtered = filtered[filtered["plot"]]
            for idx in filtered.index:
                curve_df = dm.curves.loc[(sid, *idx), :]
                fig.add_scatter(
                    x=curve_df[axis_col],
                    y=curve_df["eqe_array"],
                    name=name_fn(sample_name, filtered.loc[idx, "name"]),
                )

    return fig


def _add_grouped_traces(
    fig: go.Figure,
    curve_list: list[pd.DataFrame],
    label: str,
    color: str,
    axis_col: str,
    use_std: bool,
) -> None:
    """Interpolate curves onto a common x-grid and add mean/band traces."""

    wavelength_mode = axis_col == "wavelength_array"

    if wavelength_mode:
        # Wavelength arrays are descending (high -> low nm = low -> high eV).
        # Use iloc[::-1] to get ascending order for np.interp.
        max_x = max(c[axis_col].iloc[0] for c in curve_list)
        min_x = min(c[axis_col].iloc[-1] for c in curve_list)
    else:
        max_x = max(c[axis_col].iloc[-1] for c in curve_list)
        min_x = min(c[axis_col].iloc[0] for c in curve_list)

    xgrid = np.linspace(min_x, max_x, 500)

    rows = []
    for c in curve_list:
        if wavelength_mode:
            xvals = c[axis_col].iloc[::-1].values
            yvals = c["eqe_array"].iloc[::-1].values
        else:
            xvals = c[axis_col].values
            yvals = c["eqe_array"].values
        rows.append(np.interp(xgrid, xvals, yvals, left=np.nan, right=np.nan))

    interp = pd.DataFrame(rows)  # shape (n_curves, 500)

    if use_std:
        central = interp.mean()
        spread_hi = central + interp.std()
        spread_lo = central - interp.std()
    else:
        central = interp.median()
        spread_hi = interp.quantile(0.75)
        spread_lo = interp.quantile(0.25)

    # Band (fill area)
    rgba = f"rgba({color[4:-1]},0.2)"  # e.g. "rgb(255,0,0)" -> "rgba(255,0,0,0.2)"
    band_x = np.concatenate([xgrid, xgrid[::-1]])
    band_y = pd.concat([spread_hi, spread_lo.iloc[::-1]])
    fig.add_scatter(
        x=band_x,
        y=band_y,
        line_color="rgba(255,255,255,0)",
        fillcolor=rgba,
        fill="toself",
        legendgroup=label,
        showlegend=False,
        name=label,
    )

    # Central line
    fig.add_scatter(
        x=xgrid,
        y=central,
        name=label,
        line_color=color,
        legendgroup=label,
    )


# ---------------------------------------------------------------------------
# Boxplot
# ---------------------------------------------------------------------------


def plot_boxplot(
    dm: "EQEDataManager",
    column_name: str,
    axis_title: str,
    width: int,
    height: int,
    name_fn: Callable[[str, str], str],
) -> go.Figure:
    """Return a Plotly Figure with one box per display label."""

    fig = go.Figure(
        layout=go.Layout(
            width=width,
            height=height,
            yaxis={"title": {"text": axis_title}},
            template=_TEMPLATE,
        )
    )

    x_vals: list[str] = []
    y_vals: list[float] = []

    for sid in dm.sample_ids:
        sample_name = _sample_display_name(dm, sid)
        filtered = dm.params.loc[sid]
        filtered = filtered[filtered["plot"]]
        for idx in filtered.index:
            x_vals.append(name_fn(sample_name, filtered.loc[idx, "name"]))
            y_vals.append(filtered.loc[idx, column_name])

    fig.add_box(x=x_vals, y=y_vals)
    return fig


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _sample_display_name(dm: "EQEDataManager", sample_id: str) -> str:
    """Return the user-assigned display name, falling back to sample_id."""
    try:
        name = dm.properties.loc[sample_id, "name"]
        return str(name) if name and str(name).strip() else sample_id
    except KeyError:
        return sample_id
