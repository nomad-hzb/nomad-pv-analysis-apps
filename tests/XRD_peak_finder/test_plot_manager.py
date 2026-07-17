"""test_plot_manager.py — XRDPlotManager figure and trace checks."""

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
        ENTRY, "S001",
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
    positions, intensities = XRDPlotManager.detect_peaks(x, y)
    assert len(positions) >= 1
    assert abs(positions[0] - 25) < 2


def test_detect_peaks_returns_lists():
    x = [10.0, 20.0, 30.0]
    y = [100.0, 2000.0, 100.0]
    pos, inten = XRDPlotManager.detect_peaks(x, y)
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
