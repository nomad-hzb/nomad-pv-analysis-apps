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
import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def demo():
    manager = dm.SemDataManager()
    manager.load_offline(FIXTURES / "demo_images.json")
    manager.analyse_all()
    return manager


def _click(panel, y, x):
    panel._on_figure_click(None, SimpleNamespace(xs=[x], ys=[y]), None)


def test_overlay_figure_keeps_pixel_coordinates():
    rgb = np.zeros((100, 200, 3), dtype=np.uint8)
    fig = pm.overlay_figure(rgb)
    assert fig.data[0].source.startswith("data:image/png;base64,")
    assert list(fig.layout.xaxis.range) == [0, 200]
    assert list(fig.layout.yaxis.range) == [100, 0]  # rows grow downwards, like the image


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
    _click(panel, 5, 5)  # clicking the same spot removes the dot again
    assert len(entry.clicks) == n_auto
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
    assert panel._pending_merge is not None and not demo.entries[name].edits
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
    panel._download("a,b\n1,2\n", "test.csv")
    script = shown[-1].data
    assert "a.setAttribute('download', 'test.csv')" in script and "base64," in script


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
