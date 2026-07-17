"""Tests for data_manager.py"""
import numpy as np
import pandas as pd
import pytest

from data_manager import (
    SolventDataManager,
    InkDataManager,
    PerovskiteDataManager,
    find_optimal_blend,
    weighted_average,
    calculate_enclosing_sphere,
    create_sphere_mesh,
    export_blend_csv,
)


# ---------------------------------------------------------------------------
# SolventDataManager
# ---------------------------------------------------------------------------

class TestSolventDataManager:
    def test_load_missing_file(self):
        sdm = SolventDataManager(csv_path="nonexistent.csv")
        ok, msg = sdm.load()
        assert not ok
        assert "not found" in msg.lower() or "nonexistent" in msg.lower()
        assert not sdm.is_loaded

    def test_search_by_name(self, loaded_solvent_dm):
        result = loaded_solvent_dm.search("acetone")
        assert len(result) == 1
        assert result.iloc[0]["Name"] == "Acetone"

    def test_search_by_cas(self, loaded_solvent_dm):
        result = loaded_solvent_dm.search("67-64-1")
        assert len(result) == 1

    def test_search_empty_term_returns_empty(self, loaded_solvent_dm):
        result = loaded_solvent_dm.search("")
        assert result.empty

    def test_search_no_match_returns_empty(self, loaded_solvent_dm):
        result = loaded_solvent_dm.search("xyzzy_notasolvent")
        assert result.empty

    def test_numeric_columns_excludes_text(self, loaded_solvent_dm):
        cols = loaded_solvent_dm.numeric_columns
        assert "Name" not in cols
        assert "CAS" not in cols
        assert "D" not in cols  # excluded by SOLVENT_DB_EXCLUDE
        assert "DN" in cols or "BP" in cols  # at least one numeric

    def test_get_by_index(self, loaded_solvent_dm):
        row = loaded_solvent_dm.get_by_index(0)
        assert row is not None
        assert row["Name"] == "Acetone"

    def test_get_by_missing_index_returns_none(self, loaded_solvent_dm):
        row = loaded_solvent_dm.get_by_index(9999)
        assert row is None


# ---------------------------------------------------------------------------
# InkDataManager
# ---------------------------------------------------------------------------

class TestInkDataManager:
    def test_load_missing_file(self):
        idm = InkDataManager(xlsx_path="nonexistent.xlsx")
        ok, msg = idm.load()
        assert not ok
        assert not idm.is_loaded

    def test_solute_list(self, loaded_ink_dm):
        solutes = loaded_ink_dm.solute_list
        assert "PbI2" in solutes
        assert "MAPbI3" in solutes

    def test_formatted_solvents_column_exists(self, loaded_ink_dm):
        assert "formatted_solvents" in loaded_ink_dm.data.columns


# ---------------------------------------------------------------------------
# PerovskiteDataManager
# ---------------------------------------------------------------------------

class TestPerovskiteDataManager:
    def test_get_sheet2(self, loaded_perov_dm, perov_df):
        df = loaded_perov_dm.get_sheet("Sheet2")
        assert len(df) == len(perov_df)

    def test_get_sheet3(self, loaded_perov_dm, perov_df):
        df = loaded_perov_dm.get_sheet("Sheet3")
        assert len(df) == len(perov_df)

    def test_solute_list(self, loaded_perov_dm):
        solutes = loaded_perov_dm.solute_list("Sheet2")
        assert "MAPbI3" in solutes
        assert "FAPbI3" in solutes

    def test_color_columns(self, loaded_perov_dm):
        cols = loaded_perov_dm.color_columns("Sheet2")
        assert "DN" in cols


# ---------------------------------------------------------------------------
# find_optimal_blend
# ---------------------------------------------------------------------------

class TestFindOptimalBlend:
    def test_single_solvent_returns_fraction_1(self, solvent_df):
        one = solvent_df.iloc[[0]]
        fracs, dist, blend = find_optimal_blend(
            [one["D"].iloc[0], one["P"].iloc[0], one["H"].iloc[0]], one)
        assert abs(fracs.sum() - 1.0) < 1e-6
        assert dist < 1e-3

    def test_fractions_sum_to_one(self, solvent_df):
        fracs, _, _ = find_optimal_blend([17.0, 10.0, 10.0], solvent_df)
        assert abs(fracs.sum() - 1.0) < 1e-5

    def test_min_percentage_respected(self, solvent_df):
        fracs, _, _ = find_optimal_blend([17.0, 10.0, 10.0], solvent_df,
                                          min_percentage=0.05)
        assert all(f >= 0.049 for f in fracs)

    def test_empty_df_returns_inf(self):
        empty = pd.DataFrame(columns=["D", "P", "H"])
        fracs, dist, blend = find_optimal_blend([17.0, 10.0, 10.0], empty)
        assert dist == float("inf")
        assert len(fracs) == 0


# ---------------------------------------------------------------------------
# weighted_average
# ---------------------------------------------------------------------------

class TestWeightedAverage:
    def test_equal_parts(self, solvent_df):
        selected = {
            0: {"data": solvent_df.iloc[0], "percentage": 50.0},
            1: {"data": solvent_df.iloc[1], "percentage": 50.0},
        }
        result = weighted_average(selected, solvent_df)
        expected_D = (15.5 * 0.5 + 15.8 * 0.5)
        assert abs(result["D"] - expected_D) < 1e-6

    def test_missing_values_handled(self, solvent_df):
        # DN is None for chloroform (index 2)
        selected = {
            0: {"data": solvent_df.iloc[0], "percentage": 50.0},
            2: {"data": solvent_df.iloc[2], "percentage": 50.0},
        }
        result = weighted_average(selected, solvent_df)
        # DN for acetone=17.0, chloroform=None  → only acetone contributes
        assert result.get("DN") is not None  # acetone contributes

    def test_returns_none_for_all_missing(self, solvent_df):
        # Both solvents have None for a made-up column; use DN from rows where both None
        rows = [
            {"No.": 10, "Name": "X", "D": 15.0, "P": 5.0, "H": 5.0, "DN": None},
            {"No.": 11, "Name": "Y", "D": 16.0, "P": 6.0, "H": 6.0, "DN": None},
        ]
        fake_df = pd.DataFrame(rows)
        selected = {
            0: {"data": fake_df.iloc[0], "percentage": 50.0},
            1: {"data": fake_df.iloc[1], "percentage": 50.0},
        }
        result = weighted_average(selected, fake_df)
        assert result.get("DN") is None


# ---------------------------------------------------------------------------
# Geometry helpers
# ---------------------------------------------------------------------------

class TestSphereHelpers:
    def test_single_point_radius(self, perov_df):
        center, radius = calculate_enclosing_sphere(perov_df.iloc[[0]])
        assert radius == pytest.approx(0.1)

    def test_multi_point_radius_positive(self, perov_df):
        _, radius = calculate_enclosing_sphere(perov_df)
        assert radius > 0

    def test_sphere_mesh_shape(self, perov_df):
        center, radius = calculate_enclosing_sphere(perov_df)
        x, y, z = create_sphere_mesh(center, radius, resolution=10)
        assert x.shape == (10, 10)
        assert y.shape == (10, 10)
        assert z.shape == (10, 10)


# ---------------------------------------------------------------------------
# export_blend_csv
# ---------------------------------------------------------------------------

class TestExportBlendCsv:
    def test_returns_string(self, solvent_df):
        res_df = pd.DataFrame([{"Solvent": "Acetone", "Fraction": 1.0, "Percentage": 100.0}])
        out = export_blend_csv([17.0, 8.0, 10.0], [17.0, 8.0, 10.0], 0.0,
                               res_df, solvent_df.iloc[:1])
        assert isinstance(out, str)
        assert "Target_D" in out

    def test_includes_temperature_when_given(self, solvent_df):
        res_df = pd.DataFrame([{"Solvent": "Acetone", "Fraction": 1.0, "Percentage": 100.0}])
        out = export_blend_csv([17.0, 8.0, 10.0], [17.0, 8.0, 10.0], 0.0,
                               res_df, solvent_df.iloc[:1], temperature_k=298.15)
        assert "Temperature_K" in out
        assert "298.15" in out
