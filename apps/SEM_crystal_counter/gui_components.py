"""
SEM GUI Components
==================
ipywidgets panels. All state lives in the SemDataManager; these panels only display it and
forward user actions to it.
"""

from __future__ import annotations

import base64
import logging

import grain_core as gc
import ipywidgets as widgets
import plot_manager as pm
import plotly.graph_objects as go
from data_manager import HOLE, MEASUREMENT_TYPE, SemDataManager
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
        buttons = [
            (
                "Grains (CSV)",
                lambda: (self.dm.grains_table().to_csv(index=False), "sem_grains.csv"),
            ),
            ("Images (CSV)", lambda: (self.dm.image_table().to_csv(index=False), "sem_images.csv")),
            (
                "Samples (CSV)",
                lambda: (self.dm.sample_table().to_csv(index=False), "sem_samples.csv"),
            ),
            ("Settings (JSON)", lambda: (self.dm.settings_json(), "sem_settings.json")),
        ]
        download_btns = []
        for label, make in buttons:
            btn = WidgetFactory.create_button(label, icon="download")
            btn.on_click(lambda _b, make=make: self._download(*make()))
            download_btns.append(btn)
        self.widget = widgets.VBox(
            [
                widgets.HBox([self._preset, self._analyse_btn, self._reanalyse_btn]),
                widgets.HBox([self._progress, self._progress_label]),
                self._status,
                self._tables,
                self._plots,
                widgets.HTML("<b>Download</b>"),
                widgets.HBox(download_btns),
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

    def _download(self, content: str, filename: str) -> None:
        """Trigger a browser download through an injected anchor click."""
        data = base64.b64encode(content.encode()).decode()
        js = (
            "var a = document.createElement('a');"
            f"a.setAttribute('download', '{filename}');"
            f"a.setAttribute('href', 'data:text/plain;charset=utf-8;base64,{data}');"
            "a.click();"
        )
        with self._downloads:
            self._downloads.clear_output()
            ipydisplay(HTML(f"<script>{js}</script>"))


# ---------------------------------------------------------------------------
# Review and correction
# ---------------------------------------------------------------------------
class ReviewPanel:
    """One image at a time: overlay, click mode (grains/holes), merge/split edits, review."""

    def __init__(self, dm: SemDataManager, on_changed) -> None:
        self.dm = dm
        self._on_changed = on_changed
        self._pending_merge: tuple[int, int] | None = None
        self._image = widgets.Dropdown(description="Image", layout={"width": "420px"})
        self._source = widgets.ToggleButtons(
            options=[AUTO, CLICKS],
            description="Grains from",
            tooltips=[
                "The program finds the grains; fix mistakes by merging or splitting.",
                "Click the centre of every grain; the program finds the borders.",
            ],
            style={"button_width": "220px"},
        )
        self._action = widgets.ToggleButtons(description="A click", style={"button_width": "160px"})
        self._outlines = widgets.Checkbox(value=True, description="Grain outlines", indent=False)
        self._seeds = widgets.Checkbox(value=False, description="Seeds", indent=False)
        self._start_btn = WidgetFactory.create_button(
            "Start from the automatic grains", min_width=False
        )
        self._undo_btn = WidgetFactory.create_button("Undo")
        self._clear_btn = WidgetFactory.create_button("Clear corrections", "warning")
        self._note = widgets.Text(placeholder="Note (optional)", layout={"width": "320px"})
        self._save_btn = WidgetFactory.create_button("Save as reviewed", "success")
        self._info = widgets.HTML()
        self._messages = widgets.Output()
        self._figure = go.FigureWidget(pm.overlay_figure(_blank()))
        self._figure.data[0].on_click(self._on_figure_click)

        self._image.observe(lambda _c: self._select_image(), names="value")
        self._source.observe(self._on_source, names="value")
        self._action.observe(lambda _c: self._clear_pending(), names="value")
        for box in (self._outlines, self._seeds):
            box.observe(lambda _c: self.redraw(), names="value")
        self._start_btn.on_click(self._start_from_automatic)
        self._undo_btn.on_click(self._undo)
        self._clear_btn.on_click(self._clear)
        self._save_btn.on_click(self._save)

        self.widget = widgets.VBox(
            [
                widgets.HTML(
                    "<p>Check each image. If the automatic grains are wrong, merge or split "
                    "them, or switch to <b>My clicks</b> and click the centre of every grain: "
                    "the program then finds the borders. Click on a dot again to remove it. "
                    "<b>Save as reviewed</b> adds the image to the training log.</p>"
                ),
                widgets.HBox([self._image, self._outlines, self._seeds]),
                self._source,
                self._action,
                widgets.HBox([self._start_btn, self._undo_btn, self._clear_btn]),
                self._info,
                self._figure,
                widgets.HBox([self._note, self._save_btn]),
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

    def redraw(self) -> None:
        name = self._image.value
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
        if self._pending_merge is not None:
            gc.draw_dots(rgb, [self._pending_merge[0]], [self._pending_merge[1]], (255, 0, 255), 5)
        height, width = rgb.shape[:2]
        with self._figure.batch_update():
            self._figure.data[0].source = pm.png_source(rgb)
            self._figure.layout.xaxis.range = [0, width]
            self._figure.layout.yaxis.range = [height, 0]
            self._figure.layout.height = int(pm.OVERLAY_WIDTH * height / width) + 10
        self._info.value = _info_html(entry, result, warnings)

    # -- events -------------------------------------------------------------
    def _select_image(self) -> None:
        self._clear_pending()
        name = self._image.value
        if name:
            # keep the toggle in line with the image's stored mode without re-triggering
            self._source.unobserve(self._on_source, names="value")
            self._source.value = CLICKS if self.dm.entries[name].use_clicks else AUTO
            self._source.observe(self._on_source, names="value")
        self._set_actions()
        self.redraw()

    def _on_source(self, change) -> None:
        name = self._image.value
        if not name:
            return
        clicks = change["new"] == CLICKS
        self.dm.set_click_mode(name, clicks)
        if clicks and not self.dm.entries[name].clicks:
            self.dm.start_clicks_from_automatic(name)
        self._clear_pending()
        self._set_actions()
        self.redraw()
        self._on_changed()

    def _set_actions(self) -> None:
        clicks = self._source.value == CLICKS
        self._action.options = (
            ["adds a grain", "adds a hole"]
            if clicks
            else ["does nothing", "merges two grains", "splits a grain"]
        )
        self._start_btn.layout.display = "" if clicks else "none"

    def _on_figure_click(self, _trace, points, _state) -> None:
        name = self._image.value
        if not name or not points.xs:
            return
        x, y = int(round(points.xs[0])), int(round(points.ys[0]))
        entry = self.dm.entries[name]
        action = self._action.value
        if entry.use_clicks:
            self.dm.toggle_click(name, y, x, HOLE if action == "adds a hole" else 0)
        elif action == "splits a grain":
            self.dm.add_edit(name, {"op": "split", "point": [y, x]})
        elif action == "merges two grains":
            if self._pending_merge is None:
                self._pending_merge = (y, x)
                self.redraw()
                return
            self.dm.add_edit(name, {"op": "merge", "points": [list(self._pending_merge), [y, x]]})
            self._pending_merge = None
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
            self.dm.undo(self._image.value)
            self.redraw()
            self._on_changed()

    def _clear(self, _b) -> None:
        if self._image.value:
            self.dm.clear_corrections(self._image.value)
            self._clear_pending()
            self.redraw()
            self._on_changed()

    def _clear_pending(self) -> None:
        self._pending_merge = None

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


def _readable(table, columns: dict):
    """The listed columns that exist, renamed and rounded, without the index."""
    shown = table[[c for c in columns if c in table.columns]].rename(columns=columns)
    numeric = shown.select_dtypes("number").columns
    shown[numeric] = shown[numeric].round(2)
    if "Hole area" in shown:
        shown["Hole area"] = shown["Hole area"].map(
            lambda v: f"{100 * v:.1f}%" if v == v and v is not None else ""
        )
    return shown.style.hide(axis="index").format(precision=2, na_rep="")


def _blank():
    import numpy as np

    return np.full((300, 450, 3), 240, dtype=np.uint8)


def _info_html(entry, result, warnings) -> str:
    s = result.summary
    parts = [
        f"<b>{entry.name}</b> (sample {entry.sample_id}, preset "
        f"{entry.result.summary.get('preset')}, {entry.sem.pixel_size_nm:.3f} nm/px)",
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
