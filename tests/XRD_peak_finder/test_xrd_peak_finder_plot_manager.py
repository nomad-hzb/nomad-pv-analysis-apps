"""test_plot_manager.py — XRDPlotManager figure and trace checks."""

import numpy as np
import plotly.graph_objects as go
import pytest
from plot_manager import XRDPlotManager

ENTRY = {
    "angle": [10.0, 20.0, 30.0, 40.0],
    "intensity": [100.0, 500.0, 2000.0, 300.0],
    "variation": "ref",
    "name": "meas_1",
    "sample_id": "S001",
}

FILE_ENTRY = {
    "angle": [10.0, 20.0, 30.0],
    "intensity": [50.0, 300.0, 100.0],
    "variation": "",
    "name": "test.xy",
    "sample_id": "test.xy",
    "file_metadata": {"Id": "TEST01", "Operator": "user"},
}


# ---------------------------------------------------------------------------
# individual()
# ---------------------------------------------------------------------------


def test_individual_returns_figure():
    fig = XRDPlotManager.individual(ENTRY, "S001")
    assert isinstance(fig, go.Figure)


def test_individual_has_data_trace():
    fig = XRDPlotManager.individual(ENTRY, "S001")
    assert len(fig.data) >= 1
    assert fig.data[0].mode == "lines"


def test_individual_with_peaks_has_two_traces():
    fig = XRDPlotManager.individual(
        ENTRY,
        "S001",
        peak_positions=[30.0],
        peak_intensities=[2000.0],
    )
    assert len(fig.data) == 2
    assert fig.data[1].mode == "markers"


def test_individual_file_entry_uses_filename_title():
    fig = XRDPlotManager.individual(FILE_ENTRY, "test.xy")
    assert "test.xy" in fig.layout.title.text


# ---------------------------------------------------------------------------
# overlay()
# ---------------------------------------------------------------------------


def test_overlay_returns_figure():
    data = {"S001": ENTRY, "S002": dict(ENTRY, sample_id="S002", variation="var1")}
    fig = XRDPlotManager.overlay(data, ["S001", "S002"])
    assert isinstance(fig, go.Figure)


def test_overlay_has_one_trace_per_selection():
    data = {"S001": ENTRY, "S002": dict(ENTRY, sample_id="S002")}
    fig = XRDPlotManager.overlay(data, ["S001", "S002"])
    assert len(fig.data) == 2


def test_overlay_stagger_shifts_y():
    data = {"S001": ENTRY, "S002": dict(ENTRY, sample_id="S002")}
    fig = XRDPlotManager.overlay(data, ["S001", "S002"], stagger_offset=500.0)
    # second trace should be shifted up
    assert fig.data[1].y[0] > fig.data[0].y[0]


def test_overlay_empty_selection_returns_empty_figure():
    data = {"S001": ENTRY}
    fig = XRDPlotManager.overlay(data, [])
    assert len(fig.data) == 0


# ---------------------------------------------------------------------------
# detect_peaks()
# ---------------------------------------------------------------------------


def test_detect_peaks_finds_obvious_peak():
    x = list(range(50))
    y = [0.0] * 50
    y[25] = 5000.0  # one clear peak
    positions, intensities, areas, segments = XRDPlotManager.detect_peaks(x, y)
    assert len(positions) >= 1
    assert abs(positions[0] - 25) < 2


def test_detect_peaks_returns_lists():
    x = [10.0, 20.0, 30.0]
    y = [100.0, 2000.0, 100.0]
    pos, inten, areas, segments = XRDPlotManager.detect_peaks(x, y)
    assert isinstance(pos, list)
    assert isinstance(inten, list)


# ---------------------------------------------------------------------------
# suggested_stagger_range()
# ---------------------------------------------------------------------------


def test_suggested_stagger_range_returns_tuple():
    data = {"S001": ENTRY}
    result = XRDPlotManager.suggested_stagger_range(data)
    assert len(result) == 3
    slider_max, default_val, step = result
    assert slider_max > 0
    assert default_val <= slider_max
    assert step > 0


# ---------------------------------------------------------------------------
# 6.8: overlapping peaks, headerless files, slider scale
# ---------------------------------------------------------------------------


def test_overlapping_peaks_are_not_counted_twice():
    """Two Gaussians at 30.0 and 30.5 deg (sigma 0.1; true areas 250.7 and 200.5) reported
    442.9 and 164.4: the first window contained most of the second peak."""
    x = np.linspace(28, 32, 801)
    y = 1000 * np.exp(-((x - 30.0) ** 2) / (2 * 0.1**2)) + 800 * np.exp(
        -((x - 30.5) ** 2) / (2 * 0.1**2)
    )
    positions, _, areas, segments = XRDPlotManager.detect_peaks(list(x), list(y))
    assert len(positions) == 2
    assert areas[0] == pytest.approx(250.7, rel=0.25)  # splitting at the valley is approximate
    assert areas[1] == pytest.approx(200.5, rel=0.25)
    assert 0.8 * (250.7 + 200.5) < sum(areas) < 1.05 * (250.7 + 200.5)  # was 607 (+35 %)
    # the two windows share no points
    assert segments[0][0][-1] <= segments[1][0][0]


def test_stagger_slider_follows_the_data_scale():
    low = XRDPlotManager.suggested_stagger_range({"s": {"intensity": [0.0, 0.4, 1.0]}})
    high = XRDPlotManager.suggested_stagger_range({"s": {"intensity": [0.0, 4000.0]}})
    assert low[2] == pytest.approx(0.01)  # a step of 1 on data that ends at 1 was unusable
    assert high[2] == pytest.approx(100.0)
