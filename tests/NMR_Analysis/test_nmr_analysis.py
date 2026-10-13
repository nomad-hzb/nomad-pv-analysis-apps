"""NMRDataManager: load_offline, properties, export."""

import json
from pathlib import Path

import numpy as np
import plotly.graph_objects as go
import pytest
from data_manager import MEASUREMENT_TYPE, NMRDataManager
from plot_manager import NMRPlotManager

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "api_responses.json"


# ---------------------------------------------------------------------------
# load_offline()
# ---------------------------------------------------------------------------


def test_load_offline_returns_true():
    dm = NMRDataManager()
    assert dm.load_offline(FIXTURE_PATH) is True
    assert dm.is_loaded
    assert len(dm.data) == 2


def test_load_offline_returns_false_for_empty_fixture(tmp_path):
    fx = tmp_path / "empty.json"
    fx.write_text(json.dumps({"measurements": {}, "descriptions": {}}))
    dm = NMRDataManager()
    assert dm.load_offline(fx) is False
    assert not dm.is_loaded


def test_load_offline_skips_invalid_rows(tmp_path):
    fixture = {
        "descriptions": {"S001": "ref", "S002": "var1"},
        "measurements": {
            "S001": [
                [
                    {
                        "data": {"chemical_shift": "not-a-list", "intensity": "not-a-list"},
                        "name": "bad",
                    }
                ]
            ],
            "S002": [
                [
                    {
                        "data": {"chemical_shift": [8.0, 4.0], "intensity": [1000.0, 5000.0]},
                        "name": "good",
                    }
                ]
            ],
        },
    }
    fx = tmp_path / "mixed.json"
    fx.write_text(json.dumps(fixture))
    dm = NMRDataManager()
    dm.load_offline(fx)
    assert len(dm.data) == 1


def test_csv_export_after_offline_load():
    import io

    import pandas as pd

    dm = NMRDataManager()
    dm.load_offline(FIXTURE_PATH)
    csv = dm.data.to_csv()
    df = pd.read_csv(io.StringIO(csv), index_col=0)
    assert len(df) == len(dm.data)


def test_end_to_end_load_then_plot():
    dm = NMRDataManager()
    dm.load_offline(FIXTURE_PATH)
    colors = {sid: "#1f77b4" for sid in dm.sample_ids}
    fig = NMRPlotManager.plot_overlay(dm.data, colors)
    assert isinstance(fig, go.Figure)


# ---------------------------------------------------------------------------
# Properties
# ---------------------------------------------------------------------------


def test_sample_ids_populated(loaded_manager):
    assert "S001" in loaded_manager.sample_ids
    assert "S002" in loaded_manager.sample_ids


def test_get_spectrum_returns_arrays(loaded_manager):
    shift, intensity = loaded_manager.get_spectrum("S001")
    assert isinstance(shift, list)
    assert isinstance(intensity, list)
    assert len(shift) == len(intensity)


def test_get_sample_label_with_variation(loaded_manager):
    label = loaded_manager.get_sample_label("S001")
    assert "S001" in label


# ---------------------------------------------------------------------------
# MEASUREMENT_TYPE constant
# ---------------------------------------------------------------------------


def test_measurement_type_constant():
    assert MEASUREMENT_TYPE == "HySprint_Simple_NMR"


# ---------------------------------------------------------------------------
# 5.10: the whole spectrum (C1), integrals independent of axis order (H1), every measurement (H2)
# ---------------------------------------------------------------------------


def _spectrum(shifts, intensities, name="meas"):
    return [{"data": {"chemical_shift": shifts, "intensity": intensities}, "name": name}, {}]


def test_overlay_draws_every_point_of_the_spectrum(loaded_manager):
    """A hidden 'keep points above 20x the median' filter left 2 of 6 points and joined them."""
    fig = NMRPlotManager.plot_overlay(loaded_manager.data, colors={})
    for trace, (_, row) in zip(fig.data, loaded_manager.data.iterrows()):
        assert len(trace.x) == len(row["chemical_shift"])
        assert list(trace.y) == list(row["intensity"])


def test_overlay_keeps_a_zero_mean_baseline():
    """With a baseline around 0 the median-based filter dropped every negative sample."""
    manager = NMRDataManager()
    shifts = list(np.linspace(10, 0, 200))
    intensity = list(np.sin(np.linspace(0, 20, 200)))  # positive and negative
    assert manager._build_from_raw({"S": [_spectrum(shifts, intensity)]}, {})
    fig = NMRPlotManager.plot_overlay(manager.data, colors={})
    assert len(fig.data[0].y) == 200
    assert min(fig.data[0].y) < 0


def test_overlay_applies_the_offset_per_measurement(loaded_manager):
    flat = NMRPlotManager.plot_overlay(loaded_manager.data, colors={}, offset=0.0)
    shifted = NMRPlotManager.plot_overlay(loaded_manager.data, colors={}, offset=100.0)
    assert list(shifted.data[1].y) == [v + 100.0 for v in flat.data[1].y]


@pytest.mark.parametrize("descending", [True, False])
def test_integral_has_the_same_positive_value_for_either_axis_order(descending):
    """-1 * trapz was only right for a descending ppm axis; ascending data came out negative."""
    shifts = np.linspace(10, 0, 101) if descending else np.linspace(0, 10, 101)
    intensity = np.full_like(shifts, 3.0)
    result = NMRPlotManager.compute_integral(list(shifts), list(intensity), 2.0, 4.0)
    assert result["integral"] == pytest.approx(3.0 * 2.0)  # height 3 over 2 ppm


def test_integral_of_a_range_without_points_is_none():
    assert NMRPlotManager.compute_integral([1.0, 2.0], [1.0, 1.0], 5.0, 6.0) is None


def _two_measurements_of_one_sample():
    manager = NMRDataManager()
    raw = {
        "S1": [
            _spectrum([3.0, 2.0, 1.0], [10.0, 20.0, 30.0], name="1H"),
            _spectrum([3.0, 2.0, 1.0], [1.0, 2.0, 3.0], name="13C"),
        ],
        "S2": [_spectrum([3.0, 2.0, 1.0], [5.0, 5.0, 5.0], name="1H")],
    }
    assert manager._build_from_raw(raw, {"S1": "film A", "S2": "film B"})
    return manager


def test_a_sample_measured_twice_keeps_both_measurements_reachable():
    """Only the first NMR entry per sample was ever shown, peak-picked or integrated."""
    manager = _two_measurements_of_one_sample()
    assert manager.sample_ids == ["S1", "S2"]
    assert manager.measurement_ids == ["S1 #1", "S1 #2", "S2"]  # single measurement keeps its id
    assert manager.get_spectrum("S1 #1")[1] == [10.0, 20.0, 30.0]
    assert manager.get_spectrum("S1 #2")[1] == [1.0, 2.0, 3.0]
    assert manager.get_spectrum("S2")[1] == [5.0, 5.0, 5.0]


def test_measurement_labels_tell_the_measurements_apart():
    manager = _two_measurements_of_one_sample()
    labels = [manager.get_measurement_label(m) for m in manager.measurement_ids]
    assert len(set(labels)) == 3
    assert "1H" in labels[0] and "13C" in labels[1]
    assert labels[2] == manager.get_sample_label("S2")


def test_overlay_has_a_trace_per_measurement_with_distinct_legend_names():
    manager = _two_measurements_of_one_sample()
    labels = {m: manager.get_measurement_label(m) for m in manager.measurement_ids}
    fig = NMRPlotManager.plot_overlay(manager.data, colors={"S1 #2": "#ff0000"}, labels=labels)
    assert len(fig.data) == 3
    assert [t.name for t in fig.data] == list(labels.values())
    assert fig.data[1].line.color == "#ff0000"


def test_gui_panels_offer_every_measurement():
    import gui_components as gui

    manager = _two_measurements_of_one_sample()
    single = gui.SingleSpectrumPanel(manager)
    assert [value for _, value in single._sample_dd.options] == manager.measurement_ids
    overlay = gui.OverlayPlotPanel(manager)
    assert list(overlay._color_pickers) == manager.measurement_ids


def test_large_spectra_are_decimated_for_display_but_keep_their_peak_tops():
    """22 MB of full-resolution spectra broke the Voila websocket and the app reset."""
    from plot_manager import MAX_PLOT_POINTS, decimate_minmax

    x = np.linspace(12, -2, 65536)
    y = np.random.default_rng(0).normal(0, 0.01, x.size)
    y[30000] = 5.0  # one narrow peak
    y[40000] = -3.0  # and a dip
    xd, yd = decimate_minmax(x, y)
    assert len(xd) <= MAX_PLOT_POINTS + 2
    assert yd.max() == 5.0 and yd.min() == -3.0  # extremes survive
    assert xd[0] == x[0] and xd[-1] == x[-1]  # ends are kept
    assert np.all(np.diff(np.searchsorted(-x, -xd)) >= 0)  # original order preserved


def test_small_spectra_are_not_touched_by_decimation():
    from plot_manager import decimate_minmax

    x = np.linspace(10, 0, 500)
    y = np.sin(x)
    xd, yd = decimate_minmax(x, y)
    assert np.array_equal(xd, x) and np.array_equal(yd, y)


def test_decimation_copes_with_nan_and_analysis_still_uses_full_data():
    from plot_manager import decimate_minmax

    y = np.random.default_rng(1).normal(0, 1, 20000)
    y[100:130] = np.nan
    xd, yd = decimate_minmax(np.arange(y.size), y)
    assert len(yd) < y.size
    manager = NMRDataManager()
    shifts = list(np.linspace(10, 0, 20000))
    assert manager._build_from_raw({"S": [_spectrum(shifts, [1.0] * 20000)]}, {})
    result = NMRPlotManager.compute_integral(shifts, [1.0] * 20000, 2.0, 4.0)
    assert result["integral"] == pytest.approx(2.0, rel=1e-3)  # full resolution
    fig = NMRPlotManager.plot_overlay(manager.data, colors={})
    assert len(fig.data[0].x) <= 4002
