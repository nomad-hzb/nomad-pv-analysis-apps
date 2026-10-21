"""Tests for the SEM plots, GUI panels and app assembly, driven with the demo data. Clicks
are simulated the way Plotly delivers them (points.xs / points.ys in pixels)."""

from pathlib import Path
from types import SimpleNamespace

import app as app_module
import data_manager as dm
import gui_components as gui
import ipywidgets as widgets
import numpy as np
import plot_manager as pm
import plotly.graph_objects as go
import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def demo():
    manager = dm.SemDataManager()
    manager.load_offline(FIXTURES / "demo_images.json")
    manager.analyse_all()
    return manager


def _click(panel, y, x, ctrl=False):
    """A Plotly click at pixel (y, x), as delivered to the trace's on_click callback."""
    panel._on_figure_click(None, SimpleNamespace(xs=[x], ys=[y]), SimpleNamespace(ctrl=ctrl))


def test_overlay_figure_keeps_pixel_coordinates():
    rgb = np.zeros((100, 200, 3), dtype=np.uint8)
    fig = pm.overlay_figure(rgb)
    assert fig.data[0].source.startswith("data:image/png;base64,")
    # autorange (not fixed ranges), so a double-click returns to this image's full extent
    assert fig.layout.xaxis.autorange is True
    assert fig.layout.yaxis.autorange == "reversed"  # rows grow downwards, like the image


def test_result_plots_and_empty_states(demo):
    assert pm.size_histogram(demo.grains_table()).data
    assert pm.sample_bars(demo.sample_table()).data
    assert pm.size_histogram(demo.grains_table().iloc[:0]).layout.annotations
    assert pm.sample_bars(demo.sample_table().iloc[:0]).layout.annotations


def test_review_panel_click_mode_adds_holes_and_removes_dots(demo):
    panel = gui.ReviewPanel(demo, on_changed=lambda: None)
    panel.refresh()
    name = "DEMO_A_01.tif"
    panel._image.value = name
    panel._source.value = gui.CLICKS  # switching starts from the automatic grains
    entry = demo.entries[name]
    n_auto = len(entry.clicks)
    assert entry.use_clicks and n_auto > 0
    panel._action.value = "adds a hole"
    _click(panel, 5, 5)
    assert entry.clicks[-1][2] == dm.HOLE
    _click(panel, 5, 5)  # a second click on the dot adds nothing (no duplicate dots)
    assert len(entry.clicks) == n_auto + 1
    _click(panel, 6, 6, ctrl=True)  # ctrl+click removes the nearest dot
    assert len(entry.clicks) == n_auto
    panel._action.value = "removes a dot"
    y, x, _ = entry.clicks[0]
    _click(panel, int(y), int(x))
    assert len(entry.clicks) == n_auto - 1
    assert "grain clicks" in panel._info.value
    panel._source.value = gui.AUTO
    assert not entry.use_clicks


def test_review_panel_merge_needs_two_clicks(demo):
    panel = gui.ReviewPanel(demo, on_changed=lambda: None)
    panel.refresh()
    name = "DEMO_A_02.tif"
    panel._image.value = name
    panel._action.value = "merges two grains"
    labels = demo.final_result(name)[0].labels
    first = np.argwhere(labels == 1)[0]
    other = next(lab for lab in range(2, labels.max() + 1) if (labels == lab).any())
    second = np.argwhere(labels == other)[0]
    _click(panel, *first)
    assert panel._pending is not None and not demo.entries[name].edits
    _click(panel, *second)
    assert demo.entries[name].edits[-1]["op"] == "merge"
    panel._undo(None)
    assert not demo.entries[name].edits


def test_analysis_panel_refresh_and_download(demo, monkeypatch):
    shown = []
    monkeypatch.setattr(gui, "ipydisplay", shown.append)  # Output() captures nothing here
    panel = gui.AnalysisPanel(demo)
    panel.refresh()
    assert any(getattr(x, "value", None) == "<h4>Samples</h4>" for x in shown)
    tables = [x.data for x in shown if "<table" in str(getattr(x, "data", ""))]
    assert len(tables) == 2 and "Mean diameter (nm)" in tables[0]  # plain HTML, no Styler
    panel._download_results()
    script = shown[-1].data
    assert "sem_results_" in script and ".xlsx" in script
    assert "spreadsheetml.sheet;base64," in script


def test_app_demo_load_end_to_end(monkeypatch):
    class FakeAuth:
        def __init__(self, url_base, api_endpoint):
            self.api_client = SimpleNamespace(get_api_url=lambda: "https://e.test/api")
            self.current_token = "tok"

        def authenticate_with_token(self, token):
            pass

    monkeypatch.setattr(app_module, "AuthenticationManager", FakeAuth)
    monkeypatch.setattr(
        gui,
        "create_batch_selection",
        lambda url, token, on_load: widgets.VBox([widgets.SelectMultiple(options=["B1"])]),
    )
    sem_app = app_module.SEMApp("https://e.test", "/api", "tok")
    sem_app._on_demo_load(None)
    assert len(sem_app._dm.entries) == 3
    assert all(e.analysed for e in sem_app._dm.entries.values())
    assert list(sem_app._review._image.options) == sem_app._dm.names


def test_app_still_works_when_nomad_is_unreachable(monkeypatch):
    class FakeAuth:
        def __init__(self, url_base, api_endpoint):
            self.api_client = SimpleNamespace(get_api_url=lambda: "https://e.test/api")
            self.current_token = "expired"

        def authenticate_with_token(self, token):
            pass

    def refuse(url, token, on_load):
        raise PermissionError("401 Unauthorized")

    monkeypatch.setattr(app_module, "AuthenticationManager", FakeAuth)
    monkeypatch.setattr(gui, "create_batch_selection", refuse)
    sem_app = app_module.SEMApp("https://e.test", "/api", "expired")
    assert "Could not get the batch list" in sem_app._sources.children[0].value
    sem_app._on_demo_load(None)  # demo (and upload) still work
    assert len(sem_app._dm.entries) == 3


def test_whole_image_button_resets_the_zoom(demo):
    panel = gui.ReviewPanel(demo, on_changed=lambda: None)
    panel.refresh()
    panel._figure.layout.xaxis.range = [10, 50]  # as after zooming in
    panel._whole_btn.click()
    x0, x1 = panel._figure.layout.xaxis.range
    assert x0 == pytest.approx(-0.5, abs=1e-3) and x1 == 640 - 0.5  # the demo images are 640 wide
    first = tuple(panel._figure.layout.xaxis.range)
    panel._whole_btn.click()  # a second reset is still a change, so the browser gets it
    assert tuple(panel._figure.layout.xaxis.range) != first


def test_navigation_counter_and_ignore(demo):
    panel = gui.ReviewPanel(demo, on_changed=lambda: None)
    panel.refresh()
    panel._image.value = demo.names[0]
    assert panel._counter.value == "1 / 3"
    panel._step(1)
    assert panel._image.value == demo.names[1] and panel._counter.value == "2 / 3"
    panel._step(-2)  # wraps around to the last image
    assert panel._counter.value == "3 / 3"
    name = panel._image.value
    panel._ignore.value = True
    assert demo.entries[name].ignored
    assert name not in set(demo.grains_table()["image"])
    assert "ignored" in panel._info.value
    panel._ignore.value = False
    assert name in set(demo.grains_table()["image"])


def test_cut_needs_two_clicks_across_a_grain(demo):
    panel = gui.ReviewPanel(demo, on_changed=lambda: None)
    panel.refresh()
    name = "DEMO_A_02.tif"
    panel._image.value = name
    panel._source.value = gui.AUTO
    panel._action.value = "cuts along a line"
    before = demo.final_result(name)[0].summary["n_grains"]
    labels = demo.final_result(name)[0].labels
    ys, xs = np.nonzero(labels == np.argmax(np.bincount(labels.ravel())))  # largest grain
    row = int(np.median(ys))
    cols = xs[ys == row]
    _click(panel, row, int(cols.min()) - 3)  # just outside its left border ...
    assert panel._pending is not None and not demo.entries[name].edits
    _click(panel, row, int(cols.max()) + 3)  # ... to just outside its right border
    assert demo.entries[name].edits[-1]["op"] == "cut"
    assert demo.final_result(name)[0].summary["n_grains"] == before + 1
    demo.clear_corrections(name)


def test_detection_settings_re_analyse_one_image(demo):
    panel = gui.ReviewPanel(demo, on_changed=lambda: None)
    panel.refresh()
    name = "DEMO_A_01.tif"
    panel._image.value = name
    before = demo.final_result(name)[0].summary["n_grains"]
    panel._sliders["min_grain_diameter_nm"].value = 400.0
    panel._apply_settings(all_images=False)
    entry = demo.entries[name]
    assert entry.overrides == {"min_grain_diameter_nm": 400.0}
    assert demo.final_result(name)[0].summary["n_grains"] < before
    assert "own settings" in demo.image_table().set_index("image").loc[name, "preset"]
    panel._reset_settings()
    assert entry.overrides == {}
    assert demo.final_result(name)[0].summary["n_grains"] == before


def test_ruler_measures_in_nm(demo):
    panel = gui.ReviewPanel(demo, on_changed=lambda: None)
    panel.refresh()
    panel._image.value = "DEMO_A_01.tif"  # 3.722 nm/px
    panel._action.value = gui.RULER
    edits = list(demo.entries["DEMO_A_01.tif"].edits)
    _click(panel, 10, 10)
    assert "second point" in panel._ruler_info.value
    _click(panel, 10, 110)
    assert "Ruler: 372 nm" in panel._ruler_info.value
    assert demo.entries["DEMO_A_01.tif"].edits == edits  # the grains are not touched
    _click(panel, 50, 50)  # a third click starts a new measurement
    assert panel._ruler == [(50, 50)]
    panel._undo(None)
    assert panel._ruler == [] and panel._ruler_info.value == ""


def test_review_of_a_cross_section_draws_the_film_bottom(make_tiff, cross_section, monkeypatch):
    manager = dm.SemDataManager()
    content = make_tiff(cross_section(top_row=100, film_rows=200), b"Image Pixel Size = 5.0 nm")
    manager.add_uploads([("VP3_cs.tif", content)])
    manager.analyse_all()
    panel = gui.ReviewPanel(manager, on_changed=lambda: None)
    panel.refresh()
    assert panel._kind.value == dm.CROSS and gui.BOTTOM in panel._action.options
    assert "Thickness 1" in panel._info.value  # about 1000 nm
    panel._action.value = gui.BOTTOM
    panel._bottom_apply_btn.click()  # no points yet: nothing happens
    assert manager.entries["VP3_cs.tif"].bottom_points == []
    _click(panel, 250, 0)
    _click(panel, 250, 499)
    panel._bottom_apply_btn.click()
    summary = manager.final_result("VP3_cs.tif")[0].summary
    assert summary["bottom_drawn"] and "film bottom drawn" in panel._info.value
    panel._bottom_auto_btn.click()
    assert not manager.final_result("VP3_cs.tif")[0].summary["bottom_drawn"]

    shown = []
    monkeypatch.setattr(gui, "ipydisplay", shown.append)
    gui.CrossSectionPanel(manager).refresh()
    tables = [x.data for x in shown if "<table" in str(getattr(x, "data", ""))]
    assert len(tables) == 2 and "Thickness, median (nm)" in tables[0]
    assert any(isinstance(x, go.FigureWidget) for x in shown)  # histogram and profile plots

    panel._kind.value = dm.TOP  # the user says it is a top view
    assert manager.entries["VP3_cs.tif"].kind == dm.TOP
    assert gui.BOTTOM not in panel._action.options


def test_thickness_profile_does_not_need_webgl():
    import pandas as pd

    profiles = pd.DataFrame(
        {"image": "a.tif", "x_nm": np.arange(2048.0), "thickness_nm": np.full(2048, 500.0)}
    )
    # above 1000 points plotly express would pick scattergl, which fails without WebGL
    assert {t.type for t in pm.thickness_profile(profiles).data} == {"scatter"}
