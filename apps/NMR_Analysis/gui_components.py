"""
gui_components.py – NMR Plotter
All ipywidgets code. Imports data_manager and plot_manager as plain names.
"""

from __future__ import annotations

import logging

import data_manager as dm_module
import ipywidgets as widgets
import pandas as pd
import plot_manager as pm
from data_manager import MEASUREMENT_TYPE
from hysprint_utils.api_calls import get_all_batches_wth_data
from hysprint_utils.batch_selection import create_batch_selection
from hysprint_utils.error_handler import ErrorHandler
from hysprint_utils.plotting_utils import WidgetFactory
from IPython.display import display as ipydisplay

logger = logging.getLogger(__name__)
# ---------------------------------------------------------------------------
# BatchPanel
# ---------------------------------------------------------------------------


class BatchPanel:
    """
    Wraps create_batch_selection and adds an optional NMR-specific filter button.

    app.py passes on_load (a callback) which receives the SelectMultiple widget.
    """

    def __init__(self, url: str, token: str, on_load) -> None:
        self._url = url
        self._token = token

        self._batch_widget = create_batch_selection(url, token, on_load)
        # children[1] is the SelectMultiple per batch_selection.py contract
        self._selector: widgets.SelectMultiple = self._batch_widget.children[1]

        total = len(self._selector.options)

        self._filter_btn = WidgetFactory.create_button(
            description="Shown NMR batches",
            button_style="info",
            tooltip="Queries the API to find which batches have NMR measurements. May take a moment.",  # noqa: E501
        )
        self.status_out = WidgetFactory.create_output(min_height="standard")
        self._total_batches = total

        self._filter_btn.on_click(self._on_filter_clicked)

        self.widget = widgets.VBox(
            [
                widgets.HTML(
                    f"<p>Select from all {total} available batches, "
                    "or filter to batches with confirmed NMR data:</p>"
                ),
                self._filter_btn,
                self._batch_widget,
                self.status_out,
            ]
        )

    def _on_filter_clicked(self, _b) -> None:
        self._filter_btn.disabled = True
        self._filter_btn.description = "Filtering in progress..."

        with self.status_out:
            self.status_out.clear_output(wait=True)
            ErrorHandler.log_info("Querying API for batches with NMR data...", self.status_out)
            try:
                valid = get_all_batches_wth_data(self._url, self._token, MEASUREMENT_TYPE)
                self._selector.options = valid
                self._filter_btn.description = (
                    f"Done: {len(valid)} of {self._total_batches} batches have NMR data"
                )
                ErrorHandler.log_success(
                    f"Found {len(valid)} batches with NMR data.",
                    self.status_out,
                )
            except Exception as exc:  # noqa: BLE001
                ErrorHandler.log_error(
                    "Filter failed", exc, self.status_out, show_traceback=True
                )
                self._filter_btn.disabled = False
                self._filter_btn.description = "Retry filter"


# ---------------------------------------------------------------------------
# OverlayPlotPanel
# ---------------------------------------------------------------------------


class OverlayPlotPanel:
    """
    Unified overlay plot: all NMR spectra in one figure.
    Color pickers and Y-offset update the plot automatically.
    """

    def __init__(self, data_manager: dm_module.NMRDataManager) -> None:
        self._dm = data_manager

        sample_ids = self._dm.sample_ids

        # --- color pickers ---
        self._color_pickers: dict[str, widgets.ColorPicker] = {}
        for i, sid in enumerate(sample_ids):
            label = self._dm.get_sample_label(sid)
            self._color_pickers[sid] = widgets.ColorPicker(
                concise=False,
                description=f"{label}:",
                value=pm.default_color(i),
                disabled=False,
                style={"description_width": "initial"},
                layout=widgets.Layout(width="340px", margin="2px"),
            )

        # --- offset control ---
        self._offset = widgets.FloatText(
            value=0.0,
            description="Y-axis Offset:",
            style={"description_width": "initial"},
            layout=widgets.Layout(width="300px"),
            tooltip="Vertical offset between spectra (0 = overlapping)",
        )

        self._plot_out = WidgetFactory.create_output(min_height="large")

        # wire up observers
        for cp in self._color_pickers.values():
            cp.observe(lambda _c: self._redraw(), names="value")
        self._offset.observe(lambda _c: self._redraw(), names="value")

        # build widget
        color_box = widgets.VBox(
            [widgets.HTML("<h4>Spectrum Colors</h4>")] + list(self._color_pickers.values()),
            layout=widgets.Layout(border="1px solid #ddd", padding="10px", margin="5px"),
        )
        offset_box = widgets.VBox(
            [widgets.HTML("<h4>Spectrum Positioning</h4>"), self._offset],
            layout=widgets.Layout(border="1px solid #ddd", padding="10px", margin="5px"),
        )

        self.widget = widgets.VBox(
            [
                widgets.HTML("<h3>Overlay – All NMR Spectra</h3>"),
                offset_box,
                color_box,
                self._plot_out,
            ]
        )

        self._redraw()

    def _redraw(self) -> None:
        colors = {sid: cp.value for sid, cp in self._color_pickers.items()}
        fig = pm.NMRPlotManager.plot_overlay(
            self._dm.data, colors=colors, offset=self._offset.value
        )
        self._plot_out.clear_output(wait=True)
        with self._plot_out:
            ipydisplay(fig)


# ---------------------------------------------------------------------------
# SingleSpectrumPanel
# ---------------------------------------------------------------------------


class SingleSpectrumPanel:
    """
    Single-spectrum analyzer: peak detection + trapezoidal integration.
    """

    def __init__(self, data_manager: dm_module.NMRDataManager) -> None:
        self._dm = data_manager

        sample_ids = self._dm.sample_ids
        dropdown_options = [(self._dm.get_sample_label(sid), sid) for sid in sample_ids]

        # --- controls ---
        self._sample_dd = WidgetFactory.create_dropdown(
            options=dropdown_options,
            description="Sample:",
            width="wide",
        )

        self._height_slider = widgets.FloatSlider(
            value=0.1,
            min=0.01,
            max=1.0,
            step=0.01,
            description="Min Peak Height:",
            style={"description_width": "initial"},
            layout=widgets.Layout(width="340px"),
        )

        self._color_picker = widgets.ColorPicker(
            concise=False,
            description="Spectrum Color:",
            value="#1f77b4",
            disabled=False,
            style={"description_width": "initial"},
            layout=widgets.Layout(width="300px"),
        )

        self._range_start = widgets.FloatText(
            value=0.0,
            description="Range Start (ppm):",
            style={"description_width": "initial"},
            layout=widgets.Layout(width="220px"),
        )
        self._range_end = widgets.FloatText(
            value=1.0,
            description="Range End (ppm):",
            style={"description_width": "initial"},
            layout=widgets.Layout(width="220px"),
        )
        self._integrate_btn = WidgetFactory.create_button(
            description="Integrate Range",
            button_style="info",
            tooltip="Calculate integral over the specified chemical shift range",
        )

        # --- outputs ---
        self._plot_out = WidgetFactory.create_output(min_height="large")
        self._peak_out = WidgetFactory.create_output(min_height="standard")
        self._integration_out = WidgetFactory.create_output(min_height="standard")

        # wire observers
        self._sample_dd.observe(lambda _c: self._redraw(), names="value")
        self._height_slider.observe(lambda _c: self._redraw(), names="value")
        self._color_picker.observe(lambda _c: self._redraw(), names="value")
        self._range_start.observe(lambda _c: self._redraw(), names="value")
        self._range_end.observe(lambda _c: self._redraw(), names="value")
        self._integrate_btn.on_click(lambda _b: self._run_integration())

        controls = widgets.VBox(
            [
                widgets.HTML("<h4>Sample Selection</h4>"),
                self._sample_dd,
                widgets.HTML("<h4>Peak Detection</h4>"),
                self._height_slider,
                widgets.HTML("<h4>Integration Range</h4>"),
                widgets.HBox([self._range_start, self._range_end, self._integrate_btn]),
                widgets.HTML("<h4>Appearance</h4>"),
                self._color_picker,
            ],
            layout=widgets.Layout(border="1px solid #ddd", padding="10px", margin="5px"),
        )

        self.widget = widgets.VBox(
            [
                widgets.HTML("<h3>Single Spectrum Analyzer</h3>"),
                controls,
                self._plot_out,
                widgets.HTML("<h4>Peak Detection Results</h4>"),
                self._peak_out,
                widgets.HTML("<h4>Integration Results</h4>"),
                self._integration_out,
            ]
        )

        self._redraw()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _current_spectrum(self):
        sid = self._sample_dd.value
        return sid, self._dm.get_sample_label(sid), *self._dm.get_spectrum(sid)

    def _redraw(self) -> None:
        sid, label, cs, inten = self._current_spectrum()
        fig, peak_df = pm.NMRPlotManager.plot_single(
            chemical_shift=cs,
            intensity=inten,
            label=label,
            color=self._color_picker.value,
            height_threshold=self._height_slider.value,
            range_start=self._range_start.value,
            range_end=self._range_end.value,
        )

        self._plot_out.clear_output(wait=True)
        with self._plot_out:
            ipydisplay(fig)

        self._peak_out.clear_output(wait=True)
        with self._peak_out:
            if peak_df.empty:
                logger.info("No peaks found with the current threshold.")
            else:
                shifts = [float(v) for v in peak_df["Chemical Shift (ppm)"]]
                logger.info(
                    "Found %d peaks (%.2f to %.2f ppm).",
                    len(peak_df),
                    min(shifts),
                    max(shifts),
                )
                ipydisplay(peak_df)

    def _run_integration(self) -> None:
        _sid, _label, cs, inten = self._current_spectrum()
        result = pm.NMRPlotManager.compute_integral(
            cs,
            inten,
            range_start=self._range_start.value,
            range_end=self._range_end.value,
        )
        self._integration_out.clear_output(wait=True)
        with self._integration_out:
            if result is None:
                logger.info(
                    "No data points found in range %.2f to %.2f ppm.",
                    self._range_start.value,
                    self._range_end.value,
                )
            else:
                df = pd.DataFrame(
                    {
                        "Parameter": ["Start (ppm)", "End (ppm)", "Integral", "Avg Intensity"],
                        "Value": [
                            f"{result['start']:.2f}",
                            f"{result['end']:.2f}",
                            f"{result['integral']:.4f}",
                            f"{result['avg_intensity']:.4f}",
                        ],
                    }
                )
                ipydisplay(df)
                logger.info(
                    "Integral from %.2f to %.2f ppm = %.4f",
                    result["start"],
                    result["end"],
                    result["integral"],
                )
