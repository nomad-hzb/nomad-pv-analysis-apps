"""test_data_manager.py -- XRDDataManager: load_offline, file parse, export."""

import io
import json
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import pytest
from data_manager import XRDDataManager, parse_xy_file, MEASUREMENT_TYPE
from plot_manager import XRDPlotManager

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "api_responses.json"


# ---------------------------------------------------------------------------
# parse_xy_file
# ---------------------------------------------------------------------------

SAMPLE_XY = """'Id: "SAMPLE01" Operator: "testuser"'
10.0 100.0
20.0 500.0
30.0 2000.0
40.0 300.0
"""


def test_parse_xy_returns_correct_length():
    x, y, meta = parse_xy_file(SAMPLE_XY, "test.xy")
    assert len(x) == 4
    assert len(y) == 4


def test_parse_xy_extracts_metadata():
    _, _, meta = parse_xy_file(SAMPLE_XY, "test.xy")
    assert meta.get("Id") == "SAMPLE01"
    assert meta.get("Operator") == "testuser"


def test_parse_xy_skips_bad_lines():
    content = "# header\n10.0 100.0\nnot_a_number still_bad\n20.0 200.0\n"
    x, y, _ = parse_xy_file(content, "test.xy")
    assert len(x) == 2


# ---------------------------------------------------------------------------
# load_offline()
# ---------------------------------------------------------------------------


def test_load_offline_returns_true():
    mgr = XRDDataManager(url="http://mock", token="mock-token")
    assert mgr.load_offline(FIXTURE_PATH) is True
    assert mgr.is_loaded
    assert len(mgr.data) == 3  # S001_meas_1, S001_meas_2, S002


def test_load_offline_returns_false_for_empty_fixture(tmp_path):
    fx = tmp_path / "empty.json"
    fx.write_text(json.dumps({"measurements": {}, "descriptions": {}}))
    mgr = XRDDataManager(url="http://mock", token="mock-token")
    assert mgr.load_offline(fx) is False
    assert not mgr.is_loaded


def test_load_offline_skips_invalid_rows(tmp_path):
    fixture = {
        "descriptions": {"S001": "ref"},
        "measurements": {
            "S001": [
                [{"data": {}, "name": "bad"}],
                [{"data": {"angle": [10.0, 20.0], "intensity": [100.0, 500.0]}, "name": "good"}],
            ]
        },
    }
    fx = tmp_path / "mixed.json"
    fx.write_text(json.dumps(fixture))
    mgr = XRDDataManager(url="http://mock", token="mock-token")
    mgr.load_offline(fx)
    assert len(mgr.data) == 1


def test_csv_export_after_offline_load():
    mgr = XRDDataManager(url="http://mock", token="mock-token")
    mgr.load_offline(FIXTURE_PATH)
    csv = mgr.to_csv_string()
    df = pd.read_csv(io.StringIO(csv))
    assert "angle" in df.columns
    assert len(df) > 0


def test_end_to_end_load_then_plot():
    mgr = XRDDataManager(url="http://mock", token="mock-token")
    mgr.load_offline(FIXTURE_PATH)
    first_key = next(iter(mgr.data))
    fig = XRDPlotManager.individual(mgr.data[first_key], first_key)
    assert isinstance(fig, go.Figure)
    assert len(fig.data) >= 1


# ---------------------------------------------------------------------------
# load_xy_file
# ---------------------------------------------------------------------------


def test_load_xy_file_adds_entry(loaded_manager):
    count_before = len(loaded_manager.data)
    ok = loaded_manager.load_xy_file("extra.xy", SAMPLE_XY)
    assert ok is True
    assert len(loaded_manager.data) == count_before + 1


def test_load_xy_file_fails_on_empty_content(loaded_manager):
    ok = loaded_manager.load_xy_file("empty.xy", "")
    assert ok is False


# ---------------------------------------------------------------------------
# to_csv_string
# ---------------------------------------------------------------------------


def test_to_csv_string_is_valid_csv(loaded_manager):
    csv = loaded_manager.to_csv_string()
    df = pd.read_csv(io.StringIO(csv))
    assert "angle" in df.columns
    assert "intensity" in df.columns
    assert len(df) > 0


# ---------------------------------------------------------------------------
# MEASUREMENT_TYPE constant
# ---------------------------------------------------------------------------


def test_measurement_type_constant():
    assert MEASUREMENT_TYPE == "HySprint_XRD_XY"
