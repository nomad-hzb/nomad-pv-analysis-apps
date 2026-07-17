"""AbsPlDataManager: load_offline, filter, export."""
import io
import json
from pathlib import Path

import pandas as pd
import pytest
from data_manager import AbsPlDataManager, MEASUREMENT_TYPE

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "api_responses.json"


# ---------------------------------------------------------------------------
# load_offline()
# ---------------------------------------------------------------------------


def test_load_offline_returns_true():
    dm = AbsPlDataManager(url="http://mock", token="mock-token")
    assert dm.load_offline(FIXTURE_PATH) is True
    assert dm.is_loaded
    assert len(dm.data) == 2


def test_load_offline_returns_false_for_empty_fixture(tmp_path):
    fx = tmp_path / "empty.json"
    fx.write_text(json.dumps({"measurements": {}, "descriptions": {}}))
    dm = AbsPlDataManager(url="http://mock", token="mock-token")
    assert dm.load_offline(fx) is False
    assert not dm.is_loaded


def test_load_offline_skips_invalid_rows(tmp_path):
    fixture = {
        "descriptions": {"S001": "ref", "S002": "var1"},
        "measurements": {
            "S001": [
                [{"results": [{"bandgap": "not-a-float"}], "name": "bad"}]
            ],
            "S002": [
                [{"results": [{"bandgap": 1.58, "luminescence_quantum_yield": 0.08}], "name": "good"}]
            ],
        },
    }
    fx = tmp_path / "mixed.json"
    fx.write_text(json.dumps(fixture))
    dm = AbsPlDataManager(url="http://mock", token="mock-token")
    dm.load_offline(fx)
    assert len(dm.data) == 1


def test_csv_export_after_offline_load():
    dm = AbsPlDataManager(url="http://mock", token="mock-token")
    dm.load_offline(FIXTURE_PATH)
    csv = dm.to_csv_string()
    df = pd.read_csv(io.StringIO(csv), index_col=0)
    assert len(df) == len(dm.data)


def test_end_to_end_load_then_filter(loaded_manager):
    original_len = len(loaded_manager.data)
    ok, msg = loaded_manager.apply_filter("bandgap", 1.5, 2.0)
    assert ok
    assert len(loaded_manager.data) <= original_len


# ---------------------------------------------------------------------------
# filter / reset
# ---------------------------------------------------------------------------


def test_apply_filter_rejects_inverted_range(loaded_manager):
    ok, msg = loaded_manager.apply_filter("bandgap", 2.0, 1.0)
    assert not ok
    assert "cannot be greater" in msg.lower() or "min" in msg.lower()


def test_reset_filters_restores_data(loaded_manager):
    original_len = len(loaded_manager.data)
    loaded_manager.apply_filter("bandgap", 1.9, 2.0)
    loaded_manager.reset_filters()
    assert len(loaded_manager.data) == original_len


# ---------------------------------------------------------------------------
# numeric columns
# ---------------------------------------------------------------------------


def test_numeric_columns_present(loaded_manager):
    assert "bandgap" in loaded_manager.numeric_columns


# ---------------------------------------------------------------------------
# MEASUREMENT_TYPE constant
# ---------------------------------------------------------------------------


def test_measurement_type_constant():
    assert MEASUREMENT_TYPE == "HySprint_AbsPLMeasurement"
