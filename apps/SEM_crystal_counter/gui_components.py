"""
SEM GUI Components
==================
ipywidgets panels. All state lives in the SemDataManager; these panels only display it and
forward user actions to it.
"""

from __future__ import annotations

import base64
import logging
from datetime import datetime

import grain_core as gc
import ipywidgets as widgets
import plot_manager as pm
import plotly.graph_objects as go
from data_manager import HOLE, MEASUREMENT_TYPE, SHEETS, SemDataManager
from IPython.display import HTML
from IPython.display import display as ipydisplay

from hysprint_utils.api_calls import get_all_batches_wth_data
from hysprint_utils.batch_selection import create_batch_selection
from hysprint_utils.error_handler import ErrorHandler
from hysprint_utils.plotting_utils import WidgetFactory

logger = logging.getLogger(__name__)

PRESET_OPTIONS = [
    ("automatic (recommended)", "auto"),
    ("smooth films", "smooth"),
    ("striped films", "striped"),
]
AUTO, CLICKS = "Automatic detection", "My clicks (one per grain)"
XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


# ---------------------------------------------------------------------------
# Sources
# ---------------------------------------------------------------------------
class BatchFilterPanel:
    """Wraps create_batch_selection with a button that keeps only batches with SEM images."""

    def __init__(self, url: str, token: str, on_load) -> None:
        self._url = url
        self._token = token
        self._status_out = widgets.Output()
        self._filter_btn = WidgetFactory.create_button(
            "Show only batches with SEM images", button_style="info"
        )
        self._filter_btn.on_click(self._do_filter)
        self._batch_widget = create_batch_selection(url, token, on_load)
        self._batch_selector = next(
            (c for c in self._batch_widget.children if isinstance(c, widgets.SelectMultiple)),
            None,
        )
        total = len(self._batch_selector.options) if self._batch_selector else "?"
        self.widget = widgets.VBox(
            [
                widgets.HTML(
                    f"<p>Select batches (of {total}); every SEM image of their samples is "
                    "downloaded and analysed.</p>"
                ),
                self._filter_btn,
                self._status_out,
                self._batch_widget,
            ]
        )

    def _do_filter(self, _b) -> None:
        self._filter_btn.disabled = True
        self._filter_btn.description = "Filtering..."
        try:
            valid = sorted(get_all_batches_wth_data(self._url, self._token, MEASUREMENT_TYPE))
        except Exception as exc:
            ErrorHandler.log_error("Could not query batches", exc, output_widget=self._status_out)
            self._filter_btn.description = "Show only batches with SEM images"
            self._filter_btn.disabled = False
            return
        if self._batch_selector is not None:
            self._batch_selector.options = valid
        self._filter_btn.description = f"{len(valid)} batches with SEM images"


class UploadPanel:
    """TIFF upload, independent of NOMAD."""

    def __init__(self, on_add) -> None:
        self._on_add = on_add
        self._upload = widgets.FileUpload(
            accept=".tif,.tiff", multiple=True, description="Choose TIFFs"
        )
        self._add_btn = WidgetFactory.create_button("Add and analyse", button_style="primary")
        self._add_btn.on_click(self._add)
        self.widget = widgets.VBox(
            [
                widgets.HTML(
                    "<p>Zeiss SEM TIFFs with the pixel size in their metadata. The sample is "
                    "taken from the file name: <code>VP317_01.tif</code> belongs to "
                    "<code>VP317</code>.</p>"
                ),
                widgets.HBox([self._upload, self._add_btn]),
            ]
        )

    def _add(self, _b) -> None:
        files = [(f["name"], bytes(f["content"])) for f in self._upload.value]
        if files:
            self._on_add(files)
            self._upload.value = ()


# ---------------------------------------------------------------------------
# Results
# ---------------------------------------------------------------------------
class AnalysisPanel:
    """Analysis controls, tables, plots and downloads."""

    def __init__(self, dm: SemDataManager) -> None:
        self.dm = dm
        self._preset = widgets.Dropdown(
            options=PRESET_OPTIONS,
            value="auto",
            description="Preset",
            tooltip="'automatic' chooses smooth or striped per image from its grain counts.",
        )
        self._analyse_btn = WidgetFactory.create_button("Analyse new images", "primary")
        self._reanalyse_btn = WidgetFactory.create_button(
            "Re-analyse all with this preset", min_width=False
        )
        self._analyse_btn.on_click(lambda _b: self.analyse(only_new=True))
        self._reanalyse_btn.on_click(lambda _b: self.analyse(only_new=False))
        self._progress = widgets.IntProgress(value=0, min=0, max=1, layout={"width": "300px"})
        self._progress_label = widgets.Label("")
        self._status = widgets.Output()
        self._tables = widgets.Output()
        self._plots = widgets.Output()
        self._downloads = widgets.Output()
        self._download_btn = WidgetFactory.create_button(
            "Download results (Excel)", icon="download", min_width=False
        )
        self._download_btn.on_click(lambda _b: self._download_results())
        self._sheet_boxes = {
            sheet: widgets.Checkbox(
                value=True, description=sheet, indent=False, layout={"width": "110px"}
            )
            for sheet in SHEETS
        }
        self.widget = widgets.VBox(
            [
                widgets.HBox([self._preset, self._analyse_btn, self._reanalyse_btn]),
                widgets.HBox([self._progress, self._progress_label]),
                self._status,
                self._tables,
                self._plots,
                widgets.HTML(
                    "<b>Download</b> one Excel file with the ticked sheets: <i>About</i> (what "
                    "the file holds), <i>Samples</i>, <i>Images</i>, <i>Grains</i> (every "
                    "grain; the largest sheet) and <i>Settings</i> (every parameter used)."
                ),
                widgets.HBox(list(self._sheet_boxes.values())),
                self._download_btn,
                self._downloads,
            ]
        )

    def analyse(self, only_new: bool = True) -> None:
        self._analyse_btn.disabled = self._reanalyse_btn.disabled = True
        try:
            self.dm.analyse_all(self._preset.value, progress=self._on_progress, only_new=only_new)
            self._progress.value = self._progress.max
            self._progress_label.value = "Analysis done."
        except Exception as exc:
            ErrorHandler.log_error("Analysis failed", exc, output_widget=self._status)
        finally:
            self._analyse_btn.disabled = self._reanalyse_btn.disabled = False
        self.refresh()

    def _on_progress(self, i: int, n: int, name: str) -> None:
        self._progress.max = max(n, 1)
        self._progress.value = i
        self._progress_label.value = f"Analysing {i + 1} of {n}: {name}"

    def refresh(self) -> None:
        images = self.dm.image_table()
        samples = self.dm.sample_table()
        with self._tables:
            self._tables.clear_output(wait=True)
            if images.empty:
                ipydisplay(widgets.HTML("<i>No images loaded yet.</i>"))
                return
            ipydisplay(widgets.HTML("<h4>Images</h4>"))
            ipydisplay(_readable(images, IMAGE_COLUMNS))
            unreliable = images[images.get("reliable", True) == False]  # noqa: E712
            if len(unreliable):
                ipydisplay(
                    widgets.HTML(
                        f"<p style='color:#b00'>{len(unreliable)} image(s) hold fewer than "
                        f"{gc.MIN_GRAINS_FOR_STATS} grains and are left out of the sample "
                        "statistics. Use a lower magnification for grain statistics.</p>"
                    )
                )
            if not samples.empty:
                ipydisplay(widgets.HTML("<h4>Samples</h4>"))
                ipydisplay(_readable(samples, SAMPLE_COLUMNS))
        with self._plots:
            self._plots.clear_output(wait=True)
            if not samples.empty:
                ipydisplay(go.FigureWidget(pm.size_histogram(self.dm.grains_table())))
                ipydisplay(go.FigureWidget(pm.sample_bars(samples)))

    def _download_results(self) -> None:
        if not any(e.analysed for e in self.dm.entries.values()):
            ErrorHandler.log_error("Nothing analysed yet.", output_widget=self._downloads)
            return
        sheets = [sheet for sheet, box in self._sheet_boxes.items() if box.value]
        if not sheets:
            ErrorHandler.log_error("Tick at least one sheet.", output_widget=self._downloads)
            return
        stamp = datetime.now().strftime("%Y%m%d_%H%M")
        self._download(self.dm.results_workbook(sheets), f"sem_results_{stamp}.xlsx", XLSX_MIME)

    def _download(self, content: bytes, filename: str, mime: str) -> None:
        """Trigger a browser download through an injected anchor click."""
        data = base64.b64encode(content).decode()
        js = (
            "var a = document.createElement('a');"
            f"a.setAttribute('download', '{filename}');"
            f"a.setAttribute('href', 'data:{mime};base64,{data}');"
            "a.click();"
        )
        with self._downloads:
            self._downloads.clear_output()
            ipydisplay(HTML(f"<script>{js}</script>"))


# ---------------------------------------------------------------------------
# Review and correction
# ---------------------------------------------------------------------------
class ReviewPanel:
    """One image at a time: navigation, overlay, corrections, detection settings, review."""

    def __init__(self, dm: SemDataManager, on_changed) -> None:
        self.dm = dm
        self._on_changed = on_changed
        self._pending: tuple[str, tuple[int, int]] | None = None  # (action, first point)
        self._resets = 0  # makes every view reset a real change (see redraw)

        # navigation
        self._image = widgets.Dropdown(description="Image", layout={"width": "380px"})
        self._prev_btn = WidgetFactory.create_button("◀ Previous", min_width=False)
        self._next_btn = WidgetFactory.create_button("Next ▶", min_width=False)
        self._counter = widgets.Label("0 / 0", layout={"width": "80px"})
        self._prev_btn.on_click(lambda _b: self._step(-1))
        self._next_btn.on_click(lambda _b: self._step(1))
        self._ignore = widgets.Checkbox(
            description="Ignore this image (left out of every result, e.g. a cross-section)",
            indent=False,
            layout={"width": "auto"},
        )

        # corrections
        self._source = widgets.ToggleButtons(
            options=[AUTO, CLICKS],
            description="Grains from",
            tooltips=[
                "The program finds the grains; fix mistakes by merging or cutting.",
                "Click the centre of every grain; the program finds the borders.",
            ],
            style={"button_width": "220px"},
        )
        self._action = widgets.ToggleButtons(description="A click", style={"button_width": "170px"})
        self._action_help = widgets.HTML()
        self._outlines = widgets.Checkbox(value=True, description="Grain outlines", indent=False)
        self._seeds = widgets.Checkbox(value=False, description="Seeds", indent=False)
        self._start_btn = WidgetFactory.create_button(
            "Start from the automatic grains", min_width=False
        )
        self._undo_btn = WidgetFactory.create_button("Undo")
        self._clear_btn = WidgetFactory.create_button("Clear corrections", "warning")
        self._whole_btn = WidgetFactory.create_button("Whole image", icon="expand", min_width=False)
        self._whole_btn.on_click(lambda _b: self.redraw(reset_view=True))
        self._info = widgets.HTML()
        self._figure = go.FigureWidget(pm.overlay_figure(_blank()))
        self._figure._config = {"scrollZoom": True, "displaylogo": False}
        self._figure.data[0].on_click(self._on_figure_click)

        # detection settings of this image (the main sliders of the dev tuner)
        self._sliders = {
            field: widgets.FloatSlider(
                description=label,
                min=lo,
                max=hi,
                step=step,
                continuous_update=False,
                style={"description_width": "200px"},
                layout={"width": "560px"},
            )
            for field, (label, lo, hi, step) in SLIDERS.items()
        }
        self._apply_btn = WidgetFactory.create_button("Apply to this image", "primary")
        self._apply_all_btn = WidgetFactory.create_button("Apply to all images", min_width=False)
        self._reset_btn = WidgetFactory.create_button("Back to the preset", min_width=False)
        self._settings_status = widgets.HTML()
        self._apply_btn.on_click(lambda _b: self._apply_settings(all_images=False))
        self._apply_all_btn.on_click(lambda _b: self._apply_settings(all_images=True))
        self._reset_btn.on_click(lambda _b: self._reset_settings())
        settings = widgets.VBox(
            [
                widgets.HTML(SETTINGS_HELP),
                *self._sliders.values(),
                widgets.HBox([self._apply_btn, self._apply_all_btn, self._reset_btn]),
                self._settings_status,
            ]
        )
        self._settings = widgets.Accordion(children=[settings], selected_index=None)
        self._settings.set_title(0, "Detection settings for this image")

        # review
        self._note = widgets.Text(placeholder="Note (optional)", layout={"width": "320px"})
        self._save_btn = WidgetFactory.create_button("Save as reviewed", "success")
        self._messages = widgets.Output()

        self._image.observe(lambda _c: self._select_image(), names="value")
        self._ignore.observe(self._on_ignore, names="value")
        self._source.observe(self._on_source, names="value")
        self._action.observe(lambda _c: self._on_action(), names="value")
        for box in (self._outlines, self._seeds):
            box.observe(lambda _c: self.redraw(), names="value")
        self._start_btn.on_click(self._start_from_automatic)
        self._undo_btn.on_click(self._undo)
        self._clear_btn.on_click(self._clear)
        self._save_btn.on_click(self._save)

        self.widget = widgets.VBox(
            [
                widgets.HTML(
                    "<p>Check each image. If the automatic grains are wrong, merge or cut them, "
                    "or switch to <b>My clicks</b> and click the centre of every grain: the "
                    "program then finds the borders.</p>"
                ),
                widgets.HBox([self._prev_btn, self._counter, self._next_btn, self._image]),
                widgets.HBox([self._ignore, self._outlines, self._seeds]),
                self._source,
                self._action,
                self._action_help,
                widgets.HBox([self._start_btn, self._undo_btn, self._clear_btn, self._whole_btn]),
                self._info,
                self._figure,
                widgets.HTML(LEGEND_HTML),
                self._settings,
                widgets.HBox([self._note, self._save_btn]),
                widgets.HTML(TRAINING_NOTE),
                self._messages,
            ]
        )
        self._set_actions()

    # -- public ------------------------------------------------------------
    def refresh(self) -> None:
        """Update the image list after loading or analysis."""
        names = [e.name for e in self.dm.entries.values() if e.analysed]
        current = self._image.value
        self._image.options = names
        if names:
            self._image.value = current if current in names else names[0]
        self._select_image()

    def redraw(self, reset_view: bool = False) -> None:
        """Re-render the overlay. The zoom is kept unless reset_view (a new image)."""
        name = self._image.value
        self._update_counter()
        if not name or not self.dm.entries[name].analysed:
            self._figure.data[0].source = pm.png_source(_blank())
            self._info.value = "<i>No analysed image selected.</i>"
            return
        entry = self.dm.entries[name]
        result, warnings = self.dm.final_result(name)
        rgb = gc.overlay(result, show_seeds=self._seeds.value, show_outlines=self._outlines.value)
        if entry.use_clicks:
            for kind, color in ((0, (40, 110, 255)), (HOLE, (255, 40, 40))):
                dots = [(y, x) for y, x, k in entry.clicks if (k == HOLE) == (kind == HOLE)]
                gc.draw_dots(rgb, [d[0] for d in dots], [d[1] for d in dots], color, radius=3)
        if self._pending is not None:
            y, x = self._pending[1]
            gc.draw_dots(rgb, [y], [x], (255, 0, 255), 5)
        height, width = rgb.shape[:2]
        with self._figure.batch_update():
            self._figure.data[0].source = pm.png_source(rgb)
            if reset_view:
                # Explicit full ranges: zooming happens in the browser only, so Python still
                # holds the old values and re-setting "autorange" would send nothing.
                self._figure.layout.xaxis.range = [-0.5 - 1e-6 * self._resets, width - 0.5]
                self._figure.layout.yaxis.range = [height - 0.5, -0.5]
                self._figure.layout.height = int(pm.OVERLAY_WIDTH * height / width) + 10
                self._resets += 1
        self._info.value = _info_html(entry, result, warnings)

    # -- navigation ----------------------------------------------------------
    def _step(self, delta: int) -> None:
        names = list(self._image.options)
        if not names:
            return
        index = names.index(self._image.value) if self._image.value in names else 0
        self._image.value = names[(index + delta) % len(names)]

    def _update_counter(self) -> None:
        names = list(self._image.options)
        index = names.index(self._image.value) + 1 if self._image.value in names else 0
        self._counter.value = f"{index} / {len(names)}"
        self._prev_btn.disabled = self._next_btn.disabled = len(names) < 2

    def _select_image(self) -> None:
        self._pending = None
        name = self._image.value
        if name:
            entry = self.dm.entries[name]
            # show the image's stored state without triggering the handlers
            self._source.unobserve(self._on_source, names="value")
            self._source.value = CLICKS if entry.use_clicks else AUTO
            self._source.observe(self._on_source, names="value")
            self._ignore.unobserve(self._on_ignore, names="value")
            self._ignore.value = entry.ignored
            self._ignore.observe(self._on_ignore, names="value")
            params = self.dm.params(name)
            for field, slider in self._sliders.items():
                slider.value = getattr(params, field)
            self._settings_status.value = (
                "<i>This image uses its own settings.</i>" if entry.overrides else ""
            )
        self._set_actions()
        self.redraw(reset_view=True)

    # -- events -------------------------------------------------------------
    def _on_ignore(self, change) -> None:
        if self._image.value:
            self.dm.set_ignored(self._image.value, change["new"])
            self.redraw()
            self._on_changed()

    def _on_source(self, change) -> None:
        name = self._image.value
        if not name:
            return
        clicks = change["new"] == CLICKS
        self.dm.set_click_mode(name, clicks)
        if clicks and not self.dm.entries[name].clicks:
            self.dm.start_clicks_from_automatic(name)
        self._pending = None
        self._set_actions()
        self.redraw()
        self._on_changed()

    def _set_actions(self) -> None:
        clicks = self._source.value == CLICKS
        options = CLICK_ACTIONS if clicks else AUTO_ACTIONS
        self._action.options = options
        self._action.value = options[0]  # replacing the options leaves no button selected
        self._start_btn.layout.display = "" if clicks else "none"
        self._on_action()

    def _on_action(self) -> None:
        self._pending = None
        # while the options are being replaced the value is briefly None
        help_text = ACTION_HELP.get(self._action.value, "")
        self._action_help.value = f"<p style='margin:0 0 6px 0'>{help_text}</p>"

    def _on_figure_click(self, _trace, points, state) -> None:
        name = self._image.value
        if not name or not points.xs:
            return
        x, y = int(round(points.xs[0])), int(round(points.ys[0]))
        # Plotly reports only the first click of a double-click (the second resets the zoom
        # in the browser), so a double-click in an editing mode counts as one click.
        entry = self.dm.entries[name]
        action = self._action.value
        ctrl = bool(getattr(state, "ctrl", False))
        if entry.use_clicks:
            if ctrl or action == "removes a dot":
                self.dm.remove_click(name, y, x)
            else:
                self.dm.add_click(name, y, x, HOLE if action == "adds a hole" else 0)
        elif action in ("merges two grains", "cuts along a line"):
            if self._pending is None:
                self._pending = (action, (y, x))
                self.redraw()
                return
            first = list(self._pending[1])
            op = "merge" if action == "merges two grains" else "cut"
            self.dm.add_edit(name, {"op": op, "points": [first, [y, x]]})
            self._pending = None
        else:
            return
        self.redraw()
        self._on_changed()

    def _start_from_automatic(self, _b) -> None:
        if self._image.value:
            self.dm.start_clicks_from_automatic(self._image.value)
            self.redraw()
            self._on_changed()

    def _undo(self, _b) -> None:
        if self._image.value:
            self._pending = None
            self.dm.undo(self._image.value)
            self.redraw()
            self._on_changed()

    def _clear(self, _b) -> None:
        if self._image.value:
            self.dm.clear_corrections(self._image.value)
            self._pending = None
            self.redraw()
            self._on_changed()

    # -- detection settings ----------------------------------------------------
    def _apply_settings(self, all_images: bool) -> None:
        name = self._image.value
        if not name:
            return
        values = {field: float(slider.value) for field, slider in self._sliders.items()}
        targets = (
            [e.name for e in self.dm.entries.values() if e.analysed and not e.ignored]
            if all_images
            else [name]
        )
        for i, target in enumerate(targets):
            self._settings_status.value = f"Re-analysing {i + 1} of {len(targets)}: {target}..."
            preset = gc.PRESETS[self.dm.entries[target].result.summary.get("preset", "smooth")]
            overrides = {f: v for f, v in values.items() if v != getattr(preset, f)}
            self.dm.set_overrides(target, overrides)
        self._settings_status.value = (
            f"Applied to {len(targets)} image(s). Corrections made before are kept; check "
            "them, the grains may have changed."
        )
        self.redraw()
        self._on_changed()

    def _reset_settings(self) -> None:
        name = self._image.value
        if not name:
            return
        self._settings_status.value = "Re-analysing with the preset..."
        self.dm.set_overrides(name, {})
        self._select_image()
        self._settings_status.value = "Back to the preset settings."
        self._on_changed()

    # -- review ------------------------------------------------------------------
    def _save(self, _b) -> None:
        name = self._image.value
        if not name:
            return
        try:
            folder = self.dm.save_review(name, note=self._note.value)
        except Exception as exc:
            ErrorHandler.log_error("Could not save the review", exc, output_widget=self._messages)
            return
        ErrorHandler.log_success(f"Saved {name} to {folder}", output_widget=self._messages)


AUTO_ACTIONS = ["does nothing", "merges two grains", "cuts along a line"]
CLICK_ACTIONS = ["adds a grain", "adds a hole", "removes a dot"]
ACTION_HELP = {
    "does nothing": "Clicks on the image are ignored. Choose an action to correct the grains.",
    "merges two grains": "Click one grain (it is marked magenta), then the neighbouring grain: "
    "the border between them is removed.",
    "cuts along a line": "Click a start point, then an end point: the grain(s) the straight line "
    "crosses from one border to the other are cut along it. A line that does not cross a "
    "grain completely does nothing (a message says so).",
    "adds a grain": "Click the centre of a grain that has no blue dot. Every grain needs one "
    "dot: a grain without a dot is absorbed by its neighbours. <b>Ctrl+click</b> removes a dot.",
    "adds a hole": "Click inside a pinhole or void: its area is left out of the grain "
    "statistics and reported as hole area. <b>Ctrl+click</b> removes a dot.",
    "removes a dot": "Click on a blue (grain) or red (hole) dot to remove it. "
    "<b>Ctrl+click</b> does the same in the other modes.",
}
LEGEND_HTML = (
    "<p style='font-size:90%'><b>Outlines:</b> "
    "<span style='color:#28a745'><b>green</b></span> = grain fully inside the image (counted); "
    "<span style='color:#e69500'><b>orange</b></span> = grain cut by the image border (left out "
    "of the size averages, counted as half a grain in the density). "
    "<b>Dots:</b> <span style='color:#2a6eff'>blue</span> = your grain clicks, "
    "<span style='color:#e02828'>red</span> = holes (hole areas are tinted red), "
    "<span style='color:#e000e0'>magenta</span> = first point of a merge or cut.<br>"
    "<b>Zoom:</b> drag a box over the image, or use the scroll wheel. <b>Whole image</b> (or a "
    "double-click) zooms back out. While an editing action is selected, the first click of a "
    "double-click also counts as a click: <b>Undo</b> removes it. To move a zoomed image, pick "
    "the pan tool (crossed arrows, top right of the image).</p>"
)
SETTINGS_HELP = (
    "<p>Change these only if the automatic grains are systematically wrong on this image; "
    "<b>Apply</b> re-analyses it (a few seconds per image).<br>"
    "<b>Smallest grain diameter</b>: the most important one. Many small pieces inside grains: "
    "raise it. Neighbouring grains glued together: lower it.<br>"
    "<b>Merge threshold</b>: higher merges more (removes false borders such as stripes inside "
    "grains); lower keeps more borders.<br>"
    "<b>Boundary threshold</b>: lower treats more of the image as boundary (fewer grains); "
    "higher ignores weak lines (more grains).</p>"
)
SLIDERS = {
    "min_grain_diameter_nm": ("Smallest grain diameter (nm)", 20.0, 800.0, 10.0),
    "merge_threshold": ("Merge threshold", 0.0, 1.5, 0.05),
    "boundary_threshold": ("Boundary threshold", 0.5, 2.0, 0.05),
}
TRAINING_NOTE = (
    "<p style='font-size:90%;color:#555'>Saved reviews (the final grains, your clicks and "
    "corrections, and the settings) are collected for the whole team and used to tune and train "
    "the automatic detection in later versions. Saving an image that needed no correction helps "
    "too.</p>"
)


# Columns shown on the page, with readable names; the downloads hold every column.
IMAGE_COLUMNS = {
    "image": "Image",
    "sample": "Sample",
    "preset": "Preset",
    "n_grains": "Grains",
    "mean_eq_diameter_nm": "Mean diameter (nm)",
    "grains_per_um2": "Grains per µm²",
    "hole_area_fraction": "Hole area",
    "reliable": "Reliable",
    "corrected": "Corrected",
    "status": "Status",
}
SAMPLE_COLUMNS = {
    "sample": "Sample",
    "n_images": "Images used",
    "n_images_flagged": "Images left out",
    "n_grains_total": "Grains",
    "mean_eq_diameter_nm_mean": "Mean diameter (nm)",
    "mean_eq_diameter_nm_std": "± between images",
    "grains_per_um2_mean": "Grains per µm²",
    "magnification_spread": "Magnification spread",
}


def _readable(table, columns: dict) -> HTML:
    """The listed columns that exist, renamed and rounded, as an HTML table without the index.
    Plain DataFrame.to_html: pandas' Styler would need jinja2, which the app does not declare."""
    shown = table[[c for c in columns if c in table.columns]].rename(columns=columns).copy()
    if "Hole area" in shown:
        shown["Hole area"] = shown["Hole area"].map(
            lambda v: f"{100 * v:.1f}%" if v == v and v is not None else ""
        )
    return HTML(shown.to_html(index=False, na_rep="", float_format=lambda v: f"{v:.2f}"))


def _blank():
    import numpy as np

    return np.full((300, 450, 3), 240, dtype=np.uint8)


def _info_html(entry, result, warnings) -> str:
    s = result.summary
    if entry.ignored:
        return (
            f"<b>{entry.name}</b>: <span style='color:#b00'>ignored, left out of every "
            "result</span> (untick <i>Ignore this image</i> to use it again)"
        )
    parts = [
        f"<b>{entry.name}</b> (sample {entry.sample_id}, preset "
        f"{entry.result.summary.get('preset')}"
        f"{' with its own settings' if entry.overrides else ''}, "
        f"{entry.sem.pixel_size_nm:.3f} nm/px)",
        f"{s.get('n_grains', 0)} grains ({s.get('n_edge', 0)} at the edge), "
        f"mean diameter {s.get('mean_eq_diameter_nm', float('nan')):.0f} nm",
    ]
    if entry.use_clicks:
        n_holes = sum(k == HOLE for _, _, k in entry.clicks)
        parts.append(f"{len(entry.clicks) - n_holes} grain clicks, {n_holes} holes")
    elif entry.edits:
        parts.append(f"{len(entry.edits)} manual edits")
    if not s.get("reliable", True):
        parts.append("<span style='color:#b00'>too few grains for a reliable mean</span>")
    parts += [f"<span style='color:#b60'>edit skipped: {w}</span>" for w in warnings]
    if s.get("hole_area_fraction"):
        parts.append(f"holes: {100 * s['hole_area_fraction']:.1f}% of the area")
    return "<br>".join(parts)
