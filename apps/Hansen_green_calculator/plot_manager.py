"""
plot_manager.py
Pure Plotly figure factories.  No widget imports.
Every function accepts DataFrames / plain values and returns go.Figure.
"""

from __future__ import annotations

import logging
from typing import Optional

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from data_manager import calculate_enclosing_sphere, create_sphere_mesh
from plotly.subplots import make_subplots

logger = logging.getLogger(__name__)
# ---------------------------------------------------------------------------
# Shared axis layout helper
# ---------------------------------------------------------------------------

_SCENE_BASE = dict(
    xaxis_title="Dispersion (δD)",
    yaxis_title="Polar (δP)",
    zaxis_title="Hydrogen Bonding (δH)",
)


def _cube_scene(**kwargs) -> dict:
    s = dict(_SCENE_BASE)
    s["aspectmode"] = "cube"
    s["aspectratio"] = dict(x=1, y=1, z=1)
    s.update(kwargs)
    return s


# ---------------------------------------------------------------------------
# Tab 1 – Solvent 3D Explorer  (db.csv)
# ---------------------------------------------------------------------------


def solvent_3d(
    df: pd.DataFrame,
    color_by: Optional[str] = None,
    highlighted_idx: Optional[list] = None,
) -> go.Figure:
    """3D Hansen scatter with optional highlight and colour coding."""
    fig = go.Figure()

    if highlighted_idx is None:
        highlighted_idx = []

    normal_mask = ~df.index.isin(highlighted_idx)
    highlight_mask = df.index.isin(highlighted_idx)

    def _hover(row):
        t = f"<b>{row.get('Name', '?')}</b><br>D: {row['D']}<br>P: {row['P']}<br>H: {row['H']}"
        if color_by and color_by in df.columns and pd.notna(row.get(color_by)):
            t += f"<br>{color_by}: {row[color_by]}"
        if pd.notna(row.get("CAS")):
            t += f"<br>CAS: {row['CAS']}"
        return t

    hover_all = [_hover(row) for _, row in df.iterrows()]

    color_vals = None
    colorbar_dict = None
    if color_by and color_by in df.columns:
        color_vals = pd.to_numeric(df[color_by], errors="coerce")
        colorbar_dict = dict(title=dict(text=color_by), thickness=15, len=0.8, x=1.02)

    # Normal points
    normal_mask_arr = np.asarray(normal_mask)
    if normal_mask_arr.any():
        normal_df = df[normal_mask]
        normal_hover = [hover_all[i] for i in range(len(df)) if normal_mask_arr[i]]
        marker = dict(
            size=5,
            opacity=0.6 if highlighted_idx else 0.8,
            line=dict(color="rgba(50,50,50,0.2)", width=0.5),
        )
        if color_vals is not None:
            marker["color"] = color_vals[normal_mask]
            marker["colorscale"] = "Viridis"
            marker["colorbar"] = colorbar_dict
        else:
            marker["color"] = "steelblue"
        fig.add_trace(
            go.Scatter3d(
                x=normal_df["D"],
                y=normal_df["P"],
                z=normal_df["H"],
                mode="markers",
                marker=marker,
                text=normal_hover,
                hovertemplate="%{text}<extra></extra>",
                name="All Solvents",
                showlegend=False,
            )
        )

    # Highlighted points
    highlight_mask_arr = np.asarray(highlight_mask)
    if highlight_mask_arr.any():
        hl_df = df[highlight_mask]
        hl_hover = [hover_all[i] for i in range(len(df)) if highlight_mask_arr[i]]
        hl_marker = dict(size=12, opacity=1.0, line=dict(color="red", width=4), symbol="diamond")
        if color_vals is not None:
            hl_marker["color"] = color_vals[highlight_mask]
            hl_marker["colorscale"] = "Viridis"
        else:
            hl_marker["color"] = "orange"
        fig.add_trace(
            go.Scatter3d(
                x=hl_df["D"],
                y=hl_df["P"],
                z=hl_df["H"],
                mode="markers",
                marker=hl_marker,
                text=hl_hover,
                hovertemplate="%{text}<extra></extra>",
                name=f"Highlighted ({len(hl_df)})",
                showlegend=True,
            )
        )

    fig.update_layout(
        scene=_cube_scene(),
        height=650,
        margin=dict(l=0, r=0, b=0, t=40),
    )
    return fig


# ---------------------------------------------------------------------------
# Tab 2 – 2D Scatter / Correlation  (db.csv)
# ---------------------------------------------------------------------------


def scatter_2d(
    df: pd.DataFrame,
    x_col: str,
    y_col: str,
    color_col: Optional[str] = None,
) -> go.Figure:
    cols = [x_col, y_col] + ([color_col] if color_col else [])
    fdf = df.dropna(subset=cols)
    fig = go.Figure()
    marker = dict(size=8)
    if color_col:
        marker["color"] = fdf[color_col]
        marker["colorscale"] = "RdYlBu"
        marker["showscale"] = True
        marker["colorbar"] = dict(title=color_col)
    fig.add_trace(
        go.Scatter(
            x=fdf[x_col],
            y=fdf[y_col],
            mode="markers",
            marker=marker,
            text=fdf.get("Name", pd.Series([""] * len(fdf))),
            hovertemplate="<b>%{text}</b><br>"
            + f"{x_col}: %{{x}}<br>{y_col}: %{{y}}"
            + ("<br>" + color_col + ": %{marker.color}" if color_col else "")
            + "<extra></extra>",
        )
    )
    fig.update_layout(
        title=f"{y_col} vs {x_col}" + (f" – coloured by {color_col}" if color_col else ""),
        xaxis_title=x_col,
        yaxis_title=y_col,
        height=550,
        template="plotly_white",
    )
    return fig


def correlation_matrix(df: pd.DataFrame) -> go.Figure:
    num = df.select_dtypes(include=[np.number])
    n = len(num.columns)
    fig = make_subplots(
        rows=n,
        cols=n,
        horizontal_spacing=0.02,
        vertical_spacing=0.02,
    )
    for i in range(n):
        for j in range(n):
            if i == j:
                fig.add_trace(
                    go.Histogram(
                        x=num.iloc[:, i],
                        showlegend=False,
                        marker=dict(color="lightsteelblue", opacity=0.7),
                    ),
                    row=i + 1,
                    col=j + 1,
                )
            else:
                fig.add_trace(
                    go.Scatter(
                        x=num.iloc[:, j],
                        y=num.iloc[:, i],
                        mode="markers",
                        marker=dict(size=3, opacity=0.5, color="steelblue"),
                        showlegend=False,
                    ),
                    row=i + 1,
                    col=j + 1,
                )
            fig.update_xaxes(title_text=num.columns[j], title_font_size=9, row=i + 1, col=j + 1)
            fig.update_yaxes(title_text=num.columns[i], title_font_size=9, row=i + 1, col=j + 1)
    size = max(700, n * 120)
    fig.update_layout(height=size, width=size, showlegend=False, title="Correlation Matrix")
    return fig


# ---------------------------------------------------------------------------
# Tab 3 – Blend Calculator  (db.csv)
# ---------------------------------------------------------------------------


def blend_3d(
    all_df: pd.DataFrame,
    selected_df: pd.DataFrame,
    target_hsp: list[float],
    blend_hsp: list[float],
    color_by: Optional[str] = None,
) -> go.Figure:
    fig = go.Figure()

    # Background: all solvents (faded)
    fig.add_trace(
        go.Scatter3d(
            x=all_df["D"],
            y=all_df["P"],
            z=all_df["H"],
            mode="markers",
            marker=dict(size=3, color="lightgray", opacity=0.25),
            text=all_df.get("Name", pd.Series([""] * len(all_df))),
            hovertemplate="<b>%{text}</b><br>D: %{x}<br>P: %{y}<br>H: %{z}<extra></extra>",
            name="All Solvents",
        )
    )

    # Selected solvents
    if len(selected_df) > 0:
        marker = dict(size=10, opacity=1.0, line=dict(color="darkblue", width=2), symbol="diamond")
        if color_by and color_by in selected_df.columns:
            cv = pd.to_numeric(selected_df[color_by], errors="coerce")
            if not cv.isna().all():
                marker["color"] = cv
                marker["colorscale"] = "Viridis"
                marker["colorbar"] = dict(title=color_by, thickness=15, len=0.6, x=1.02)
        else:
            marker["color"] = "royalblue"
        fig.add_trace(
            go.Scatter3d(
                x=selected_df["D"],
                y=selected_df["P"],
                z=selected_df["H"],
                mode="markers",
                marker=marker,
                text=selected_df.get("Name", pd.Series([""] * len(selected_df))),
                hovertemplate="<b>SELECTED: %{text}</b><br>D: %{x}<br>P: %{y}<br>H: %{z}<extra></extra>",
                name="Selected",
            )
        )

    # Target HSP (red diamond)
    fig.add_trace(
        go.Scatter3d(
            x=[target_hsp[0]],
            y=[target_hsp[1]],
            z=[target_hsp[2]],
            mode="markers",
            marker=dict(
                size=14, color="red", symbol="diamond", line=dict(color="darkred", width=3)
            ),
            hovertemplate="<b>TARGET</b><br>D: %{x}<br>P: %{y}<br>H: %{z}<extra></extra>",
            name="Target HSP",
        )
    )

    # Blend HSP (green square)
    fig.add_trace(
        go.Scatter3d(
            x=[blend_hsp[0]],
            y=[blend_hsp[1]],
            z=[blend_hsp[2]],
            mode="markers",
            marker=dict(
                size=14, color="limegreen", symbol="square", line=dict(color="darkgreen", width=3)
            ),
            hovertemplate="<b>BLEND</b><br>D: %{x}<br>P: %{y}<br>H: %{z}<extra></extra>",
            name="Calculated Blend",
        )
    )

    fig.update_layout(
        scene=dict(_SCENE_BASE),
        height=600,
        margin=dict(l=0, r=0, b=0, t=50),
        legend=dict(x=0.01, y=0.99),
    )
    return fig


# ---------------------------------------------------------------------------
# Tab 4 – Inks (PlottedInks.xlsx – Inks sheet)
# ---------------------------------------------------------------------------


def inks_3d(
    df: pd.DataFrame,
    show_spheres: bool = True,
) -> go.Figure:
    fig = px.scatter_3d(
        df,
        x="D",
        y="P",
        z="H",
        color="Solutes",
        custom_data=["formatted_solvents"],
        labels={"D": "D", "P": "P", "H": "H"},
    )
    fig.update_traces(
        hovertemplate=(
            "<b>%{fullData.name}</b><br>"
            "D: %{x}<br>P: %{y}<br>H: %{z}<br>"
            "%{customdata[0]}<extra></extra>"
        )
    )

    if show_spheres and "Solutes" in df.columns:
        colors = px.colors.qualitative.Plotly
        for i, (solute_name, group) in enumerate(df.groupby("Solutes")):
            if len(group) < 2:
                continue
            center, radius = calculate_enclosing_sphere(group)
            xs, ys, zs = create_sphere_mesh(center, radius)
            col = colors[i % len(colors)]
            info_lines = [
                f"<b>{solute_name}</b>",
                f"{len(group)} data points",
                f"D: {group['D'].min():.2f} – {group['D'].max():.2f}",
                f"P: {group['P'].min():.2f} – {group['P'].max():.2f}",
                f"H: {group['H'].min():.2f} – {group['H'].max():.2f}",
            ]
            if "Researcher" in group.columns:
                rs = group["Researcher"].dropna().unique()
                if len(rs):
                    info_lines.append("Researchers: " + ", ".join(rs[:3]))
            hover_info = "<br>".join(info_lines)
            fig.add_trace(
                go.Surface(
                    x=xs,
                    y=ys,
                    z=zs,
                    opacity=0.13,
                    colorscale=[[0, col], [1, col]],
                    showscale=False,
                    name=f"{solute_name}_envelope",
                    legendgroup=solute_name,
                    showlegend=False,
                    hovertemplate=hover_info + "<extra></extra>",
                )
            )

    # Equalise grid spacing
    ranges = [
        df["D"].max() - df["D"].min(),
        df["P"].max() - df["P"].min(),
        df["H"].max() - df["H"].min(),
    ]
    step = max(ranges) / 10
    fig.update_layout(
        legend_title_text="Solutes",
        height=680,
        margin=dict(l=0, r=0, b=0, t=30),
        scene=dict(
            xaxis_title="D",
            yaxis_title="P",
            zaxis_title="H",
            aspectmode="cube",
            xaxis=dict(dtick=step),
            yaxis=dict(dtick=step),
            zaxis=dict(dtick=step),
        ),
    )
    return fig


# ---------------------------------------------------------------------------
# Tab 5 – Perovskite Solute/Solvent  (Sheet2 / Sheet3)
# ---------------------------------------------------------------------------

MARKER_MAP = {"Stable": "circle", "Semi-stable": "diamond", "Not stable": "x"}


def _perovskite_hover(row, color_by: str, all_solvents: list[str]) -> str:
    solute = row.get("Solute", "?")
    solvent = row.get("Solvent", "?")
    stability = row.get("Stability", "?")
    val = row.get(color_by)
    t = f"<b>{solute}</b><br><b>Current Sample:</b><br>"
    t += f"• Solvent: {solvent}<br>• Stability: {stability}<br>"
    if pd.notna(val):
        t += f"• {color_by}: {val:.2f}<br><br>"
    if len(all_solvents) > 1:
        t += f"<b>All solvents for {solute} ({len(all_solvents)}):</b><br>"
        for i, s in enumerate(all_solvents, 1):
            marker = " ← current" if s == solvent else ""
            bold = "<b>" if s == solvent else ""
            endbold = "</b>" if s == solvent else ""
            t += f"• {bold}{i}. {s}{marker}{endbold}<br>"
    else:
        t += f"<b>Only sample for {solute}</b>"
    return t


def perovskite_3d(
    df: pd.DataFrame,
    color_by: str = "DN",
    selected_solutes: Optional[list[str]] = None,
) -> go.Figure:
    if selected_solutes:
        plot_df = df[df["Solute"].isin(selected_solutes)].copy()
    else:
        plot_df = df.copy()

    if plot_df.empty:
        return go.Figure().update_layout(title="No data for selected solutes.")

    symbols = [MARKER_MAP.get(s, "circle") for s in plot_df.get("Stability", pd.Series())]
    sizes = [8 if sym == "x" else 12 for sym in symbols]

    # Pre-compute hover text
    hover_texts = []
    for _, row in plot_df.iterrows():
        solute = row.get("Solute")
        all_solvs = df[df["Solute"] == solute]["Solvent"].tolist() if solute else []
        hover_texts.append(_perovskite_hover(row, color_by, all_solvs))

    color_vals = pd.to_numeric(plot_df.get(color_by, pd.Series(dtype=float)), errors="coerce")

    fig = go.Figure()
    fig.add_trace(
        go.Scatter3d(
            x=plot_df["D"],
            y=plot_df["H"],
            z=plot_df["P"],
            mode="markers",
            marker=dict(
                size=sizes,
                color=color_vals,
                colorscale="Agsunset",
                symbol=symbols,
                opacity=0.8,
                cmin=color_vals.min(),
                cmax=color_vals.max(),
                colorbar=dict(title=dict(text=color_by), x=1.02, len=0.8, thickness=15),
            ),
            text=hover_texts,
            hovertemplate="%{text}<extra></extra>",
            name="Data Points",
        )
    )

    # Stability legend traces
    for stab in plot_df.get("Stability", pd.Series()).dropna().unique():
        sym = MARKER_MAP.get(stab, "circle")
        fig.add_trace(
            go.Scatter3d(
                x=[None],
                y=[None],
                z=[None],
                mode="markers",
                marker=dict(size=8 if sym == "x" else 12, symbol=sym, color="gray"),
                name=stab,
                showlegend=True,
            )
        )

    fig.update_layout(
        scene=dict(xaxis_title="D", yaxis_title="H", zaxis_title="P"),
        height=600,
        margin=dict(r=120),
        legend=dict(x=0.02, y=0.98),
    )
    return fig
