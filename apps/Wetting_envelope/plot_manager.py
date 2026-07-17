"""
plot_manager.py
---------------
Plotly-only plotting layer for the Wetting Envelope app.
No widget imports. Every method accepts domain objects from data_manager
and returns a go.Figure.
"""

from __future__ import annotations

import logging

import plotly.graph_objects as go
from data_manager import Material, Solvent, WettingCalculator

logger = logging.getLogger(__name__)
# Colour sequence that matches the HySPRINT Plotly convention.
# Long enough to cover realistic numbers of materials; cycles if needed.
_COLOURS = [
    "#636EFA",
    "#EF553B",
    "#00CC96",
    "#AB63FA",
    "#FFA15A",
    "#19D3F3",
    "#FF6692",
    "#B6E880",
    "#FF97FF",
    "#FECB52",
]


class WettingPlotManager:
    @staticmethod
    def wetting_envelope(
        materials: list[Material],
        solvents: list[Solvent],
        title: str = "Wetting Envelope",
        correction_exp: float = 2.0,
    ) -> go.Figure:
        """
        Build the complete wetting-envelope figure.

        Envelope curves
          One trace per material: the boundary curve in (dispersive, polar)
          space. Liquids whose surface-energy point falls *inside* the curve
          will wet the material (contact angle < theta for that material).

        Solvent markers
          One scatter point per solvent.
        """
        fig = go.Figure()

        # --- envelope curves ------------------------------------------------
        for i, mat in enumerate(materials):
            colour = _COLOURS[i % len(_COLOURS)]
            x, y = WettingCalculator.envelope_xy(mat, correction_exp)

            label = mat.name if mat.theta == 0.0 else f"{mat.name} (θ={mat.theta}°)"

            fig.add_trace(
                go.Scatter(
                    x=x,
                    y=y,
                    mode="lines",
                    name=label,
                    line=dict(color=colour, width=2),
                    hovertemplate=(
                        "<b>%{fullData.name}</b><br>"
                        "Dispersive: %{x:.2f} mN/m<br>"
                        "Polar: %{y:.2f} mN/m<extra></extra>"
                    ),
                )
            )

        # --- solvent markers ------------------------------------------------
        for j, sol in enumerate(solvents):
            colour = _COLOURS[(len(materials) + j) % len(_COLOURS)]
            fig.add_trace(
                go.Scatter(
                    x=[sol.dispersive],
                    y=[sol.polar],
                    mode="markers",
                    name=sol.name,
                    marker=dict(
                        color=colour,
                        size=10,
                        symbol="circle",
                        line=dict(color="white", width=1),
                    ),
                    hovertemplate=(
                        "<b>%{fullData.name}</b><br>"
                        "Dispersive: %{x:.2f} mN/m<br>"
                        "Polar: %{y:.2f} mN/m<extra></extra>"
                    ),
                )
            )

        # --- layout ---------------------------------------------------------
        fig.update_layout(
            title=dict(text=title, x=0.5, xanchor="center"),
            xaxis=dict(
                title="Dispersive Component (mN/m)",
                rangemode="tozero",
                showgrid=True,
                gridcolor="#e0e0e0",
                zeroline=True,
            ),
            yaxis=dict(
                title="Polar Component (mN/m)",
                rangemode="tozero",
                showgrid=True,
                gridcolor="#e0e0e0",
                zeroline=True,
            ),
            legend=dict(
                orientation="v",
                x=1.02,
                y=1,
                xanchor="left",
            ),
            plot_bgcolor="white",
            paper_bgcolor="white",
            margin=dict(l=60, r=160, t=60, b=60),
            height=520,
        )

        return fig
