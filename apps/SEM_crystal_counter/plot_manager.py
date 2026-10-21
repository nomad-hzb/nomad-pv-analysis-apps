"""
SEM Plot Manager
================
Plotly figures, no widgets. The GUI wraps them in go.FigureWidget.
"""

from __future__ import annotations

import base64
import io

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from PIL import Image

OVERLAY_WIDTH = 900  # px on screen; the image keeps its aspect ratio


def png_source(rgb: np.ndarray) -> str:
    """RGB array -> PNG data URI. Sent to the browser instead of the raw array: about ten
    times smaller, which matters because the overlay is re-sent after every click."""
    buffer = io.BytesIO()
    Image.fromarray(rgb.astype(np.uint8)).save(buffer, format="PNG", optimize=False)
    return "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode()


def overlay_figure(rgb: np.ndarray, title: str = "") -> go.Figure:
    """The image with outlines as one Image trace. Click events report pixel coordinates
    (x = column, y = row), which the GUI turns into grain/hole clicks or edits."""
    height, width = rgb.shape[:2]
    fig = go.Figure(go.Image(source=png_source(rgb), hoverinfo="x+y"))
    fig.update_layout(
        title=title,
        width=OVERLAY_WIDTH,
        height=int(OVERLAY_WIDTH * height / width) + (40 if title else 10),
        margin=dict(l=0, r=0, t=40 if title else 0, b=0),
        # autorange, not fixed ranges: a double-click restores the ranges the figure was
        # created with, which must be the current image's full extent
        xaxis=dict(visible=False, autorange=True),
        yaxis=dict(visible=False, autorange="reversed", scaleanchor="x"),
        # zoom, not pan: in pan mode Plotly sends no click event for Ctrl+click
        dragmode="zoom",
    )
    return fig


def size_histogram(grains: pd.DataFrame) -> go.Figure:
    """Equivalent-diameter distribution per sample (grains cut by the image edge excluded,
    as in the statistics)."""
    if grains.empty:
        return _empty("No analysed grains yet")
    interior = grains[~grains["touches_edge"].astype(bool)]
    fig = px.histogram(
        interior,
        x="eq_diameter_nm",
        color="sample",
        barmode="overlay",
        histnorm="probability",
        nbins=40,
        opacity=0.65,
        labels={"eq_diameter_nm": "Equivalent grain diameter (nm)"},
    )
    fig.update_layout(title="Grain size distribution", yaxis_title="Fraction of grains", height=380)
    return fig


def sample_bars(samples: pd.DataFrame) -> go.Figure:
    """Mean equivalent diameter per sample, error bars = spread between images."""
    if samples.empty:
        return _empty("No analysed samples yet")
    fig = go.Figure(
        go.Bar(
            x=samples["sample"],
            y=samples["mean_eq_diameter_nm_mean"],
            error_y=dict(type="data", array=samples["mean_eq_diameter_nm_std"].fillna(0)),
            text=[f"{n} img" for n in samples["n_images"]],
            textposition="outside",
        )
    )
    fig.update_layout(
        title="Mean grain diameter per sample (error bar: spread between images)",
        yaxis_title="Mean equivalent diameter (nm)",
        height=380,
    )
    return fig


def _empty(message: str) -> go.Figure:
    fig = go.Figure()
    fig.add_annotation(text=message, showarrow=False, x=0.5, y=0.5, xref="paper", yref="paper")
    fig.update_layout(height=200, xaxis=dict(visible=False), yaxis=dict(visible=False))
    return fig


def scalebar_script(container_class: str, nm_per_px: float) -> str:
    """JavaScript for a scale bar below the overlay figure inside the element with
    container_class. It runs in the browser and follows every zoom, pan and double-click
    reset: Python is not told about those, so the bar is computed from the figure's current
    x range. Length about 1/10 of the visible width, rounded to 1, 2 or 5 x 10^n nm."""
    return f"""
(function () {{
  window.semScale = window.semScale || {{}};
  window.semScale["{container_class}"] = {nm_per_px};
  function nice(v) {{
    var p = Math.pow(10, Math.floor(Math.log10(v)));
    var m = v / p;
    return (m < 1.5 ? 1 : m < 3.5 ? 2 : m < 7.5 ? 5 : 10) * p;
  }}
  function label(nm) {{
    return nm >= 1000 ? (nm / 1000) + " \u00b5m" : nm + " nm";
  }}
  function install(tries) {{
    var box = document.querySelector(".{container_class}");
    var gd = box && box.querySelector(".js-plotly-plot");
    if (!gd || !gd._fullLayout || !gd._fullLayout.xaxis) {{
      if (tries > 0) setTimeout(function () {{ install(tries - 1); }}, 300);
      return;
    }}
    var bar = box.querySelector(".sem-scalebar");
    if (!bar) {{
      bar = document.createElement("div");
      bar.className = "sem-scalebar";
      bar.style.cssText = "margin:4px 0 6px 0;font:13px sans-serif;";
      box.appendChild(bar);  // the wrapper stacks vertically: the bar goes below the image
    }}
    function update() {{
      var xa = gd._fullLayout.xaxis, px = window.semScale["{container_class}"];
      if (!xa || !xa.range || !px) return;
      var visible = Math.abs(xa.range[1] - xa.range[0]);
      var nm = nice(visible * px / 10);
      var width = nm / px / visible * xa._length;
      bar.innerHTML = '<div style="margin-left:' + xa._offset + 'px;width:' + width.toFixed(1) +
        'px;height:5px;background:#000"></div><div class="sem-scalebar-label" style="margin-left:' +
        xa._offset + 'px">' + label(nm) + '</div>';
    }}
    if (!gd._semScalebar) {{
      gd.on("plotly_relayout", update);
      gd.on("plotly_afterplot", update);
      gd._semScalebar = true;
    }}
    update();
  }}
  install(40);
}})();
"""
