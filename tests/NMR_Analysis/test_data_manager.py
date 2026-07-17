"""NMRDataManager: load_offline, properties, export."""
import json
from pathlib import Path

import plotly.graph_objects as go
import pytest
from data_manager import NMRDataManager, MEASUREMENT_TYPE
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
                [{"data": {"chemical_shift": "not-a-list", "intensity": "not-a-list"}, "name": "bad"}]
            ],
            "S002": [
                [{"data": {"chemical_shift": [8.0, 4.0], "intensity": [1000.0, 5000.0]}, "name": "good"}]
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
