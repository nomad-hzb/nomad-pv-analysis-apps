"""EQEDataManager: load_offline, MultiIndex structure, export."""
import json
from pathlib import Path

import pandas as pd
import pytest
from data_manager import EQEDataManager, MEASUREMENT_TYPE

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "api_responses.json"


# ---------------------------------------------------------------------------
# load_offline()
# ---------------------------------------------------------------------------


def test_load_offline_returns_true():
    dm = EQEDataManager()
    assert dm.load_offline(FIXTURE_PATH) is True
    assert dm.is_loaded


def test_load_offline_populates_all_dataframes(loaded_manager):
    assert loaded_manager.curves is not None
    assert loaded_manager.params is not None
    assert loaded_manager.entries is not None
    assert loaded_manager.properties is not None


def test_load_offline_returns_false_for_empty_fixture(tmp_path):
    fx = tmp_path / "empty.json"
    fx.write_text(json.dumps({"measurements": {}, "descriptions": {}}))
    dm = EQEDataManager()
    assert dm.load_offline(fx) is False
    assert not dm.is_loaded


def test_load_offline_skips_invalid_rows(tmp_path):
    fixture = {
        "descriptions": {"S001": "ref", "S002": "var1"},
        "measurements": {
            "S001": [
                [{"name": "bad", "description": "", "eqe_data": [{"bad_field": 999}]}]
            ],
            "S002": [
                [{"name": "good", "description": "", "eqe_data": [
                    {"photon_energy_array": [1.4, 1.6],
                     "wavelength_array": [886.0, 775.0],
                     "eqe_array": [0.5, 0.8],
                     "bandgap_eqe": 1.35, "integrated_jsc": 18.0}
                ]}]
            ],
        },
    }
    fx = tmp_path / "mixed.json"
    fx.write_text(json.dumps(fixture))
    dm = EQEDataManager()
    dm.load_offline(fx)
    assert dm.is_loaded
    assert len(dm.params) == 1


def test_csv_export_after_offline_load(loaded_manager):
    csv_dict = loaded_manager.to_csv_dict()
    assert "eqe_curve.csv" in csv_dict
    assert "eqe_params.csv" in csv_dict
    assert len(csv_dict["eqe_params.csv"]) > 0


def test_end_to_end_load_sample_ids(loaded_manager):
    assert len(loaded_manager.sample_ids) == 2
    assert "S001" in loaded_manager.sample_ids.values
    assert "S002" in loaded_manager.sample_ids.values


# ---------------------------------------------------------------------------
# MultiIndex structure
# ---------------------------------------------------------------------------


def test_params_multiindex_levels(loaded_manager):
    assert loaded_manager.params.index.names == ["sample_id", "entry_idx", "curve_idx"]


def test_curves_has_expected_columns(loaded_manager):
    assert "eqe_array" in loaded_manager.curves.columns
    assert "photon_energy_array" in loaded_manager.curves.columns


# ---------------------------------------------------------------------------
# MEASUREMENT_TYPE constant
# ---------------------------------------------------------------------------


def test_measurement_type_constant():
    assert MEASUREMENT_TYPE == "HySprint_EQEmeasurement"
