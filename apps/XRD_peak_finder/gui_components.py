"""
gui_components.py — XY Visualizer
All ipywidgets code lives here and only here.
"""

from __future__ import annotations

import logging

import ipywidgets as widgets
import plotly.graph_objects as go
from data_manager import MEASUREMENT_TYPE, XRDDataManager
from natsort import natsorted
from hysprint_utils.error_handler import ErrorHandler
from hysprint_utils.plotting_utils import WidgetFactory
from IPython.display import display as ipydisplay
from plot_manager import XRDPlotManager

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# BatchFilterPanel
# ---------------------------------------------------------------------------


class BatchFilterPanel:
    """Wraps batch selection with an optional 'filter to XRD only' button."""

    def __init__(self, data_manager: XRDDataManager, on_load_callback) -> None:
        self._dm = data_manager
        self._on_load_callback = on_load_callback
        self._build()

    def _build(self) -> None:
        from hysprint_utils.batch_selection import create_batch_selection

        self._batch_widget = create_batch_selection(
            self._dm._url, self._dm._token, self._on_load_callback
        )

        # Locate the SelectMultiple inside the batch widget
        self._batch_selector = None
        for child in self._batch_widget.children:
            if isinstance(child, widgets.SelectMultiple):
                self._batch_selector = child
                break

        total = len(self._batch_selector.options) if self._batch_selector else 0

        self._filter_btn = WidgetFactory.create_button(
            "Show XRD batches",
            button_style="info",
            tooltip="May take a few minutes",
        )
        self._filter_status = WidgetFactory.create_output(min_height="standard")
        self._filter_btn.on_click(self._start_filtering)

        self.widget = widgets.VBox(
            [
                widgets.HTML(
                    f"<p>Select from all <b>{total}</b> available batches, or filter first:</p>"
                ),
                self._filter_btn,
                self._batch_widget,
                self._filter_status,
            ]
        )

    def _start_filtering(self, _btn) -> None:
        self._filter_btn.disabled = True
        self._filter_btn.description = "Filtering…"

        with self._filter_status:
            self._filter_status.clear_output(wait=True)
            try:
                valid = natsorted(self._dm.get_batches_with_data())
                if self._batch_selector:
                    self._batch_selector.options = valid
                ErrorHandler.log_success(
                    f"Done — {len(valid)} batches with {MEASUREMENT_TYPE} data found",
                    self._filter_status,
                )
                self._filter_btn.description = f"Filter complete — {len(valid)} batches found"
            except Exception as exc:
                ErrorHandler.log_error("Filtering failed", exc, self._filter_status)
                self._filter_btn.disabled = False
                self._filter_btn.description = "Retry filter"


# ---------------------------------------------------------------------------
# PeakControlPanel — per-sample peak detection controls
# ---------------------------------------------------------------------------


class PeakControlPanel:
    """Slider-based peak detection controls for a single sample."""

    def __init__(self, key: str, entry: dict, plot_widget) -> None:
        self._key = key
        self._entry = entry
        self._plot_widget = plot_widget  # go.FigureWidget
        self._peak_info = WidgetFactory.create_output(min_height="standard", border=False)

        y_data = entry.get("intensity") or []
        max_i = float(max(y_data)) if y_data else 1.0

        self._height_slider = widgets.FloatSlider(
            value=max_i * 0.1,
            min=0.0,
            max=max_i,
            step=max(1.0, max_i / 200),
            description="Min Height:",
            style={"description_width": "80px"},
            layout=widgets.Layout(width="300px"),
        )
        self._prominence_slider = widgets.FloatSlider(
            value=max_i * 0.05,
            min=0.0,
            max=max_i,
            step=max(1.0, max_i / 200),
            description="Prominence:",
            style={"description_width": "80px"},
            layout=widgets.Layout(width="300px"),
        )
        self._show_peaks_cb = widgets.Checkbox(
            value=True,
            description="Show Peaks",
            style={"description_width": "initial"},
        )

        for w in (self._height_slider, self._prominence_slider, self._show_peaks_cb):
            w.observe(self._update, names="value")

        self.widget = widgets.VBox(
            [
                widgets.HTML("<b>Peak Detection Controls:</b>"),
                widgets.HBox([self._height_slider, self._prominence_slider]),
                self._show_peaks_cb,
                widgets.HTML("<b>Detected Peaks:</b>"),
                self._peak_info,
            ],
            layout=widgets.Layout(width="100%"),
        )

        self._update()

    def _update(self, _change=None) -> None:
        x = self._entry.get("angle", [])
        y = self._entry.get("intensity", [])

        if self._show_peaks_cb.value and x and y:
            positions, intensities, areas, segments = XRDPlotManager.detect_peaks(
                x, y, self._height_slider.value, self._prominence_slider.value
            )
        else:
            positions, intensities, areas, segments = [], [], [], []

        # Rebuild the FigureWidget in place
        fig = XRDPlotManager.individual(
            self._entry,
            self._key,
            peak_positions=positions if self._show_peaks_cb.value else None,
            peak_intensities=intensities if self._show_peaks_cb.value else None,
            peak_segments=segments if self._show_peaks_cb.value else None,
        )
        with self._plot_widget.batch_update():
            self._plot_widget.data = []
            for trace in fig.data:
                self._plot_widget.add_trace(trace)

        with self._peak_info:
            self._peak_info.clear_output(wait=True)
            if positions:
                print(f"Found {len(positions)} peak(s):")
                for i, (p, intensity, area) in enumerate(zip(positions, intensities, areas)):
                    print(f"  Peak {i + 1}: 2θ = {p:.2f}°  I = {intensity:.1f}  Area = {area:.1f}")
            else:
                print("No peaks detected.")


# ---------------------------------------------------------------------------
# FileUploadPanel
# ---------------------------------------------------------------------------


class FileUploadPanel:
    """Handles .xy file uploads and populates the sample grid."""

    def __init__(self, data_manager: XRDDataManager, on_data_loaded) -> None:
        self._dm = data_manager
        self._on_data_loaded = on_data_loaded

        self._upload = widgets.FileUpload(
            accept=".xy", multiple=True, description="Upload .xy files"
        )
        self._upload.observe(self._handle_upload, names="value")

        self.widget = widgets.VBox(
            [
                widgets.HTML("<h3>Upload local .xy files</h3>"),
                self._upload,
            ]
        )

    def _handle_upload(self, change) -> None:
        for file_obj in change["new"]:
            filename = file_obj.name
            if not filename.endswith(".xy"):
                continue
            content = bytes(file_obj.content).decode("utf-8")
            ok = self._dm.load_xy_file(filename, content)
            if ok:
                logger.info("Loaded %s", filename)
            else:
                logger.error("Could not parse %s", filename)
        self._on_data_loaded()


# ---------------------------------------------------------------------------
# SampleGridPanel — individual plots + per-sample checkboxes
# ---------------------------------------------------------------------------


class SampleGridPanel:
    """Renders one row per loaded sample: checkbox, FigureWidget, peak controls."""

    def __init__(self) -> None:
        self._checkboxes: dict[str, widgets.Checkbox] = {}
        self._figure_widgets: dict[str, object] = {}  # go.FigureWidget
        self._peak_panels: dict[str, PeakControlPanel] = {}
        self._on_selection_change = None

        self._container = widgets.VBox([])
        self.widget = self._container

    def set_selection_callback(self, cb) -> None:
        self._on_selection_change = cb

    def refresh(self, data: dict) -> None:
        """Re-render all samples from data_manager.data."""
        self._checkboxes = {}
        self._figure_widgets = {}
        self._peak_panels = {}

        if not data:
            self._container.children = []
            return

        rows: list = []
        for key, entry in data.items():
            cb = widgets.Checkbox(
                value=False,
                description=f"Include in overlay: {key}",
                style={"description_width": "initial"},
            )
            if self._on_selection_change:
                cb.observe(self._on_selection_change, names="value")
            self._checkboxes[key] = cb

            fig = XRDPlotManager.individual(entry, key)
            fw = go.FigureWidget(fig)
            self._figure_widgets[key] = fw

            peak_panel = PeakControlPanel(key, entry, fw)
            self._peak_panels[key] = peak_panel

            rows.extend([cb, fw, peak_panel.widget])

        self._container.children = rows

    @property
    def selected_keys(self) -> list[str]:
        return [k for k, cb in self._checkboxes.items() if cb.value]


# ---------------------------------------------------------------------------
# OverlayPanel
# ---------------------------------------------------------------------------


class OverlayPanel:
    """Stagger slider + overlay plot output."""

    def __init__(self, data_manager: XRDDataManager, sample_grid: SampleGridPanel) -> None:
        self._dm = data_manager
        self._grid = sample_grid
        self._download_area = widgets.Output()

        self._stagger_slider = widgets.FloatSlider(
            value=0.0,
            min=0.0,
            max=1000.0,
            step=10.0,
            description="Stagger Offset:",
            style={"description_width": "initial"},
            layout=widgets.Layout(width="400px"),
        )
        self._stagger_slider.observe(self._redraw, names="value")

        self._plot_output = WidgetFactory.create_output(min_height="large")

        self._export_btn = WidgetFactory.create_button(
            "Export CSV", button_style="", tooltip="Download all loaded data as CSV"
        )
        self._export_btn.on_click(self._export_csv)

        self.widget = widgets.VBox(
            [
                widgets.HTML("<h3>Overlay Plot Controls</h3>"),
                self._stagger_slider,
                self._plot_output,
                self._export_btn,
                self._download_area,
            ]
        )

    def update_slider_range(self) -> None:
        slider_max, default_val, step = XRDPlotManager.suggested_stagger_range(self._dm.data)
        self._stagger_slider.max = slider_max
        self._stagger_slider.value = default_val
        self._stagger_slider.step = step

    def _redraw(self, _change=None) -> None:
        selected = self._grid.selected_keys
        with self._plot_output:
            self._plot_output.clear_output(wait=True)
            if not selected:
                logger.info("No samples selected for overlay plot.")
                return
            fig = XRDPlotManager.overlay(self._dm.data, selected, self._stagger_slider.value)
            ipydisplay(fig)

    def on_selection_changed(self, _change=None) -> None:
        self._redraw()

    def _export_csv(self, _btn) -> None:
        csv = self._dm.to_csv_string()
        if not csv:
            return
        encoded = csv.encode("utf-8")
        with self._download_area:
            self._download_area.clear_output(wait=True)
            import base64

            from IPython.display import Javascript

            b64 = base64.b64encode(encoded).decode()
            js = Javascript(
                f"""
                var a = document.createElement('a');
                a.href = 'data:text/csv;base64,{b64}';
                a.download = 'xrd_data.csv';
                a.click();
                """
            )
            ipydisplay(js)
