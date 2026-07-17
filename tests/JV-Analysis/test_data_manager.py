# tests/jv_analysis/test_data_manager.py
import json
from pathlib import Path

import pandas as pd
import pytest
from data_manager import DataManager, JVRow
from pydantic import ValidationError

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "api_responses.json"


# ---------------------------------------------------------------------------
# JVRow Pydantic model
# ---------------------------------------------------------------------------


class TestJVRow:
    def test_valid_row_accepted(self):
        row = JVRow(
            voc=1.05, jsc=-18.3, ff=78.4, pce=15.1,
            v_mpp=0.87, j_mpp=-17.4, p_mpp=15.1,
            r_series=4.2, r_shunt=1200.0,
            sample="SampleA", batch="Batch01", condition="Slot_SAM",
            cell="C1", direction="Reverse", ilum="1sun",
            status="working", sample_id="sid-001",
        )
        assert row.pce == 15.1
        assert row.r_series == 4.2

    def test_optional_r_fields_accept_none(self):
        row = JVRow(
            voc=1.05, jsc=-18.3, ff=78.4, pce=15.1,
            v_mpp=0.87, j_mpp=-17.4, p_mpp=15.1,
            r_series=None, r_shunt=None,
            sample="SampleA", batch="Batch01", condition="Slot_SAM",
            cell="C1", direction="Reverse", ilum="1sun",
            status="working", sample_id="sid-001",
        )
        assert row.r_series is None
        assert row.r_shunt is None

    def test_invalid_voc_raises_validation_error(self):
        with pytest.raises(ValidationError):
            JVRow(
                voc="not_a_number", jsc=-18.3, ff=78.4, pce=15.1,
                v_mpp=0.87, j_mpp=-17.4, p_mpp=15.1,
                r_series=None, r_shunt=None,
                sample="SampleC", batch="Batch01", condition="BL Printing",
                cell="C3", direction="Reverse", ilum="1sun",
                status="working", sample_id="sid-003",
            )

    def test_model_dump_returns_dict(self):
        row = JVRow(
            voc=1.0, jsc=-18.0, ff=75.0, pce=13.5,
            v_mpp=0.85, j_mpp=-16.0, p_mpp=13.6,
            r_series=5.0, r_shunt=900.0,
            sample="S", batch="B", condition="C",
            cell="c1", direction="Reverse", ilum="1sun",
            status="working", sample_id="sid-x",
        )
        d = row.model_dump()
        assert isinstance(d, dict)
        assert "voc" in d
        assert len(d) == 17


# ---------------------------------------------------------------------------
# load_offline()
# ---------------------------------------------------------------------------


def test_load_offline_returns_true(mock_auth_manager):
    dm = DataManager(mock_auth_manager)
    assert dm.load_offline(FIXTURE_PATH) is True
    assert dm.has_data()
    assert len(dm.data["jvc"]) == 2


def test_load_offline_returns_false_for_empty_fixture(tmp_path, mock_auth_manager):
    fx = tmp_path / "empty.json"
    fx.write_text(json.dumps({"sample_ids": [], "measurements": {}, "descriptions": {}}))
    dm = DataManager(mock_auth_manager)
    assert dm.load_offline(fx) is False


def test_load_offline_skips_invalid_rows(tmp_path, mock_auth_manager):
    fixture = {
        "sample_ids": ["sid-good", "sid-bad"],
        "descriptions": {},
        "measurements": {
            "sid-good": [[
                {"data_file": "Good.nxs",
                 "jv_curve": [{"cell_name": "C1Rev",
                               "open_circuit_voltage": 1.05,
                               "short_circuit_current_density": 18.3,
                               "fill_factor": 0.784, "efficiency": 15.1,
                               "potential_at_maximum_power_point": 0.87,
                               "current_density_at_maximun_power_point": 17.4,
                               "series_resistance": 4.2, "shunt_resistance": 1200.0,
                               "voltage": [0.0, 1.0], "current_density": [-18.3, 0.0]}]},
                {"upload_id": "up1"}
            ]],
            "sid-bad": [[
                {"data_file": "Bad.nxs",
                 "jv_curve": [{"cell_name": "C2Rev",
                               "open_circuit_voltage": "INVALID",
                               "short_circuit_current_density": 18.3,
                               "fill_factor": 0.784, "efficiency": 15.1,
                               "potential_at_maximum_power_point": 0.87,
                               "current_density_at_maximun_power_point": 17.4,
                               "series_resistance": None, "shunt_resistance": None,
                               "voltage": [0.0, 1.0], "current_density": [-18.3, 0.0]}]},
                {"upload_id": "up2"}
            ]],
        },
    }
    fx = tmp_path / "mixed.json"
    fx.write_text(json.dumps(fixture))
    dm = DataManager(mock_auth_manager)
    dm.load_offline(fx)
    assert len(dm.data["jvc"]) == 1
    assert dm.data["jvc"].iloc[0]["sample_id"] == "sid-good"


def test_csv_export_after_offline_load(mock_auth_manager):
    dm = DataManager(mock_auth_manager)
    dm.load_offline(FIXTURE_PATH)
    jvc, curves = dm.get_export_data()
    assert jvc is not None
    assert not jvc.empty
    csv_str = jvc.to_csv()
    assert "PCE(%)" in csv_str


def test_end_to_end_load_then_filter(mock_auth_manager):
    dm = DataManager(mock_auth_manager)
    dm.load_offline(FIXTURE_PATH)
    filtered, omitted, options = dm.apply_filters([])
    assert filtered is not None
    assert not filtered.empty


# ---------------------------------------------------------------------------
# apply_filters / unique_vals
# ---------------------------------------------------------------------------


def test_apply_filters_returns_dataframes(loaded_manager):
    filtered, omitted, params = loaded_manager.apply_filters([])
    assert isinstance(filtered, pd.DataFrame)
    assert isinstance(omitted, pd.DataFrame)


def test_get_unique_values_returns_nonempty(loaded_manager):
    vals = loaded_manager.get_unique_values()
    assert len(vals) > 0
