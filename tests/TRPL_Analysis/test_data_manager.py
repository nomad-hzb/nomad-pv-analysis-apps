"""DataManager: load_offline(), filter, reset, export."""
import io
import json
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import pytest
from data_manager import MEASUREMENT_TYPE, TRPLDataManager
from plot_manager import TRPLPlotManager

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "api_responses.json"


# ---------------------------------------------------------------------------
# load_offline()
# ---------------------------------------------------------------------------


def test_load_offline_returns_true():
    dm = TRPLDataManager(url="http://mock", token="mock-token")
    assert dm.load_offline(FIXTURE_PATH) is True
    assert dm.is_loaded
    assert len(dm.data) == 3


def test_load_offline_returns_false_for_empty_fixture(tmp_path):
    fx = tmp_path / "empty.json"
    fx.write_text(json.dumps({"measurements": {}, "descriptions": {}}))
    dm = TRPLDataManager(url="http://mock", token="mock-token")
    assert dm.load_offline(fx) is False
    assert not dm.is_loaded


def test_load_offline_skips_invalid_rows(tmp_path):
    fixture = {
        "descriptions": {"S001": "ref", "S002": "var1"},
        "measurements": {
            "S001": [
                [
                    {
                        "trpl_properties": {
                            "counts": [1000.0, 800.0],
                            "time": [0.0, 1e-9],
                            "ns_per_bin": "not-a-float",
                        },
                        "name": "bad",
                        "data_file": None,
                    }
                ]
            ],
            "S002": [
                [
                    {
                        "trpl_properties": {
                            "counts": [900.0, 700.0],
                            "time": [0.0, 1e-9],
                            "ns_per_bin": 1.0,
                        },
                        "name": "good",
                        "data_file": None,
                    }
                ]
            ],
        },
    }
    fx = tmp_path / "mixed.json"
    fx.write_text(json.dumps(fixture))
    dm = TRPLDataManager(url="http://mock", token="mock-token")
    dm.load_offline(fx)
    assert len(dm.data) == 1


def test_csv_export_after_offline_load():
    dm = TRPLDataManager(url="http://mock", token="mock-token")
    dm.load_offline(FIXTURE_PATH)
    csv = dm.to_csv_string()
    df = pd.read_csv(io.StringIO(csv), index_col=0)
    assert len(df) == len(dm.data)


def test_end_to_end_load_then_plot():
    dm = TRPLDataManager(url="http://mock", token="mock-token")
    dm.load_offline(FIXTURE_PATH)
    fig = TRPLPlotManager.trpl_traces(dm.data, y_col="counts")
    assert isinstance(fig, go.Figure)
    assert len(fig.data) == len(dm.data)


# ---------------------------------------------------------------------------
# filter / reset
# ---------------------------------------------------------------------------


def test_apply_filter_reduces_rows(loaded_manager):
    success, _ = loaded_manager.apply_filter("ns_per_bin", 0.5, 0.9)
    assert success
    assert len(loaded_manager.data) == 0


def test_apply_filter_keeps_all_matching(loaded_manager):
    original_len = len(loaded_manager.data)
    success, _ = loaded_manager.apply_filter("ns_per_bin", 0.5, 2.0)
    assert success
    assert len(loaded_manager.data) == original_len


def test_apply_filter_rejects_inverted_range(loaded_manager):
    success, msg = loaded_manager.apply_filter("ns_per_bin", 2.0, 0.5)
    assert not success
    assert "cannot be greater" in msg


def test_reset_filters_restores_data(loaded_manager):
    original_len = len(loaded_manager.data)
    loaded_manager.apply_filter("ns_per_bin", 0.5, 0.9)
    loaded_manager.reset_filters()
    assert len(loaded_manager.data) == original_len


# ---------------------------------------------------------------------------
# export
# ---------------------------------------------------------------------------


def test_to_csv_string_is_valid_csv(loaded_manager):
    csv = loaded_manager.to_csv_string()
    df = pd.read_csv(io.StringIO(csv), index_col=0)
    assert len(df) == len(loaded_manager.data)


def test_measurement_type_constant():
    assert MEASUREMENT_TYPE == "HySprint_TimeResolvedPhotoluminescence"
