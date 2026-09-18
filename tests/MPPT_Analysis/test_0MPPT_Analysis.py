"""
Tests for MPPT_Analysis — data_manager and plot_manager.
"""

import json
from pathlib import Path

import fitting_tools
import numpy as np
import plotly.graph_objects as go
import pytest
from data_manager import DataManager, MPPTRow
from pydantic import ValidationError

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "api_responses.json"

# Mirror of conftest.FIXTURE_ROWS — kept local to avoid cross-conftest import
_TIME = np.array([0.0, 0.5, 1.0, 1.5, 2.0])
_POWER = np.array([15.2, 14.8, 14.4, 14.1, 13.9])


def _make_curve(sample_id="batch1&sample1", curve_id=0):
    return {
        "sample_id": sample_id,
        "curve_id": curve_id,
        "time": _TIME.copy(),
        "data": _POWER.copy(),
    }


# ===========================================================================
# MPPTRow model
# ===========================================================================


class TestMPPTRow:
    def test_valid_row_accepted(self):
        row = MPPTRow(time=0.0, power_density=15.2, voltage=0.92, current_density=-16.5)
        assert row.time == 0.0
        assert row.power_density == 15.2

    def test_model_dump_returns_all_fields(self):
        row = MPPTRow(time=0.0, power_density=15.2, voltage=0.92, current_density=-16.5)
        assert set(row.model_dump().keys()) == {
            "time",
            "power_density",
            "voltage",
            "current_density",
        }

    def test_none_coerced_to_nan(self):
        row = MPPTRow(time=0.0, power_density=None, voltage=0.9, current_density=-16.0)
        assert np.isnan(row.power_density)

    def test_invalid_time_raises_validation_error(self):
        with pytest.raises(ValidationError):
            MPPTRow(time="bad", power_density=15.0, voltage=0.9, current_density=-16.0)

    def test_string_numeric_coerced(self):
        row = MPPTRow(time="1.5", power_density="14.1", voltage="0.89", current_density="-15.8")
        assert row.time == 1.5


# ===========================================================================
# DataManager.load_offline
# ===========================================================================


def test_load_offline_populates_curves_and_ids(loaded_manager):
    assert loaded_manager.curves is not None
    assert loaded_manager.sample_ids is not None


def test_load_offline_returns_false_for_empty_fixture(tmp_path):
    fp = tmp_path / "empty.json"
    fp.write_text(json.dumps({"descriptions": {}, "measurements": {}}))
    assert DataManager(url="http://mock", token="tok").load_offline(fp) is False


def test_load_offline_skips_entirely_invalid_rows(tmp_path):
    bad = {
        "descriptions": {"s1": "bad"},
        "measurements": {
            "s1": [
                [
                    [
                        {
                            "time": "not-a-number",
                            "power_density": "x",
                            "voltage": "y",
                            "current_density": "z",
                        }
                    ],
                    {},
                ]  # noqa: E501
            ]
        },
    }
    fp = tmp_path / "bad.json"
    fp.write_text(json.dumps(bad))
    assert DataManager(url="http://mock", token="tok").load_offline(fp) is False


def test_curves_has_three_level_multiindex(loaded_manager):
    assert loaded_manager.curves.index.nlevels == 3


def test_sample_ids_populated(loaded_manager):
    sids = list(loaded_manager.sample_ids)
    assert "batch1&sample1" in sids
    assert "batch1&sample2" in sids


def test_sign_and_scale_transformations_applied(loaded_manager):
    row = loaded_manager.curves.loc["batch1&sample1"].iloc[0]
    # Original: power_density=15.2 → inverted to -15.2
    assert abs(row["power_density"] - (-15.2)) < 1e-9
    # Original: current_density=-16.5 → inverted to 16.5
    assert abs(row["current_density"] - 16.5) < 1e-9
    # Original: time=0.0 → scaled by 1/3600 → still 0.0
    assert row["time"] == pytest.approx(0.0)


def test_properties_contains_descriptions(loaded_manager):
    props = loaded_manager.properties
    assert "batch1&sample1" in props.index
    assert props.loc["batch1&sample1", "description"] == "Sample 1"


def test_entries_dataframe_present(loaded_manager):
    assert loaded_manager.entries is not None
    assert "entry_names" in loaded_manager.entries.columns


# ===========================================================================
# PlotManager — individual curves
# ===========================================================================


class TestPlotIndividualCurves:
    def test_returns_list_of_figures(self, plot_manager):
        figs = plot_manager.plot_individual_curves(
            [_make_curve(), _make_curve(curve_id=1)], "power_density"
        )
        assert isinstance(figs, list)
        assert len(figs) == 2
        assert all(isinstance(f, go.Figure) for f in figs)

    def test_scatter_trace_present(self, plot_manager):
        figs = plot_manager.plot_individual_curves([_make_curve()], "power_density")
        assert any(isinstance(t, go.Scatter) for t in figs[0].data)

    def test_fixture_power_values_reach_figure(self, plot_manager):
        figs = plot_manager.plot_individual_curves([_make_curve()], "power_density")
        y_vals = list(figs[0].data[0].y)
        assert 15.2 in y_vals
        assert 13.9 in y_vals

    def test_fixture_time_values_reach_figure(self, plot_manager):
        figs = plot_manager.plot_individual_curves([_make_curve()], "power_density")
        x_vals = list(figs[0].data[0].x)
        assert 0.0 in x_vals
        assert 2.0 in x_vals


# ===========================================================================
# PlotManager — all together
# ===========================================================================


class TestPlotAllTogether:
    def test_returns_single_figure(self, plot_manager):
        curves = [_make_curve(), _make_curve(sample_id="batch1&sample2")]
        assert isinstance(plot_manager.plot_all_together(curves, "power_density"), go.Figure)

    def test_one_trace_per_curve(self, plot_manager):
        curves = [_make_curve(), _make_curve(sample_id="batch1&sample2")]
        assert len(plot_manager.plot_all_together(curves, "power_density").data) == 2

    def test_fixture_time_values_in_first_trace(self, plot_manager):
        fig = plot_manager.plot_all_together([_make_curve()], "power_density")
        x_vals = list(fig.data[0].x)
        assert 0.0 in x_vals
        assert 2.0 in x_vals


# ===========================================================================
# PlotManager — by sample
# ===========================================================================


class TestPlotBySample:
    def test_one_figure_per_sample(self, plot_manager):
        curves = [
            _make_curve(sample_id="s1", curve_id=0),
            _make_curve(sample_id="s1", curve_id=1),
            _make_curve(sample_id="s2", curve_id=0),
        ]
        figs = plot_manager.plot_by_sample(curves, "power_density")
        assert isinstance(figs, list)
        assert len(figs) == 2

    def test_each_figure_is_go_figure(self, plot_manager):
        figs = plot_manager.plot_by_sample([_make_curve()], "power_density")
        assert all(isinstance(f, go.Figure) for f in figs)


# ===========================================================================
# PlotManager — area quartiles
# ===========================================================================


class TestPlotAreaQuartiles:
    def test_returns_list_of_figures(self, plot_manager):
        curves = [_make_curve(curve_id=i) for i in range(3)]
        figs = plot_manager.plot_area_quartiles(curves, "power_density")
        assert isinstance(figs, list)
        assert all(isinstance(f, go.Figure) for f in figs)

    def test_skips_single_curve_samples(self, plot_manager):
        assert plot_manager.plot_area_quartiles([_make_curve()], "power_density") == []

    def test_fill_trace_present(self, plot_manager):
        curves = [_make_curve(curve_id=i) for i in range(3)]
        figs = plot_manager.plot_area_quartiles(curves, "power_density")
        if figs:
            fill_traces = [t for t in figs[0].data if getattr(t, "fill", None) == "toself"]
            assert len(fill_traces) > 0


# ===========================================================================
# PlotManager — area std
# ===========================================================================


class TestPlotAreaStd:
    def test_returns_list_of_figures(self, plot_manager):
        curves = [_make_curve(curve_id=i) for i in range(3)]
        figs = plot_manager.plot_area_std(curves, "power_density")
        assert isinstance(figs, list)
        assert all(isinstance(f, go.Figure) for f in figs)

    def test_skips_single_curve_samples(self, plot_manager):
        assert plot_manager.plot_area_std([_make_curve()], "power_density") == []


# ===========================================================================
# PlotManager — histograms
# ===========================================================================


class TestPlotHistograms:
    def test_returns_none_when_no_fit_results(self, plot_manager):
        assert plot_manager.plot_histograms() is None

    def test_returns_figure_when_T80_column_present(self, plot_manager):
        import pandas as pd

        plot_manager.app_state.fit_results = pd.DataFrame(
            {"sample_id": ["s1", "s2", "s3"], "T80": [100.0, 120.0, 90.0]}
        )
        fig = plot_manager.plot_histograms()
        assert isinstance(fig, go.Figure)
        assert len(fig.data) > 0

    def test_histogram_trace_type_and_values(self, plot_manager):
        import pandas as pd

        plot_manager.app_state.fit_results = pd.DataFrame(
            {"sample_id": ["s1", "s2"], "t80": [80.0, 95.0]}
        )
        fig = plot_manager.plot_histograms()
        hist_traces = [t for t in fig.data if isinstance(t, go.Histogram)]
        assert len(hist_traces) > 0
        # The 80.0 and 95.0 values should appear in the histogram x data
        x_vals = list(hist_traces[0].x)
        assert 80.0 in x_vals
        assert 95.0 in x_vals


# ===========================================================================
# fitting_tools: unified ISOS figures of merit (issue #26)
# ===========================================================================


class TestCrossingTimePolicy:
    """crossing_time(): real-if-reached, else-extrapolated (bounded to
    EXTRAPOLATION_HORIZON_FACTOR), else-NaN - see the policy documented
    above find_tS in fitting_tools.py."""

    def test_returns_real_time_when_raw_data_reaches_threshold(self):
        times = np.linspace(0, 20, 500)
        power = 18 * np.exp(-times / 3.0)
        reference = fitting_tools.initial_reference(power)
        result = fitting_tools.crossing_time(
            times, power, reference, 0.8, lambda t: 18 * np.exp(-t / 3.0)
        )
        expected = times[np.argmax(power <= 0.8 * reference)]
        assert result == pytest.approx(expected)

    def test_extrapolates_when_not_reached_within_measurement(self):
        # True crossing is at t=-3*ln(0.8)=0.669 - measure only up to t=0.3,
        # well before it, so real data never reaches 80% and this must
        # extrapolate from the model instead.
        times = np.linspace(0, 0.3, 50)
        power = 18 * np.exp(-times / 3.0)
        result = fitting_tools.crossing_time(
            times, power, 18.0, 0.8, lambda t: 18 * np.exp(-t / 3.0)
        )
        expected = -3.0 * np.log(0.8)  # closed-form crossing for this exact curve
        assert result == pytest.approx(expected, rel=1e-3)
        assert result > times[-1]  # genuinely extrapolated, not clamped to measurement end

    def test_returns_nan_for_flat_trend(self):
        times = np.linspace(0, 20, 50)
        power = np.full_like(times, 18.0)
        result = fitting_tools.crossing_time(times, power, 18.0, 0.8, lambda t: 18.0)
        assert np.isnan(result)

    def test_returns_nan_for_improving_trend(self):
        times = np.linspace(0, 20, 50)
        power = 18.0 + 0.1 * times
        result = fitting_tools.crossing_time(times, power, 18.0, 0.8, lambda t: 18.0 + 0.1 * t)
        assert np.isnan(result)

    def test_closed_form_used_when_provided(self):
        times = np.linspace(0, 0.3, 50)  # before the true crossing at t=0.669 - see above
        power = 18 * np.exp(-times / 3.0)

        def closed_form(threshold):
            return -3.0 * np.log(threshold / 18.0)

        result = fitting_tools.crossing_time(
            times, power, 18.0, 0.8, lambda t: 18 * np.exp(-t / 3.0), closed_form
        )
        assert result == pytest.approx(-3.0 * np.log(0.8), rel=1e-6)


class TestPceAfter1000h:
    def test_reads_real_value_when_measurement_covers_1000h(self):
        times = np.linspace(0, 1500, 500)
        power = 18 * np.exp(-times / 2000.0)
        result = fitting_tools.pce_after_1000h(times, power, lambda t: 18 * np.exp(-t / 2000.0))
        assert result == pytest.approx(np.interp(1000.0, times, power))

    def test_extrapolates_within_ten_x_horizon(self):
        times = np.linspace(0, 150, 50)  # 10x horizon = 1500h, covers 1000h
        power = 18 * np.exp(-times / 2000.0)
        result = fitting_tools.pce_after_1000h(times, power, lambda t: 18 * np.exp(-t / 2000.0))
        assert result == pytest.approx(18 * np.exp(-1000.0 / 2000.0), rel=1e-6)

    def test_nan_beyond_ten_x_horizon(self):
        times = np.linspace(0, 20, 50)  # 10x horizon = 200h, doesn't reach 1000h
        power = 18 * np.exp(-times / 2000.0)
        result = fitting_tools.pce_after_1000h(times, power, lambda t: 18 * np.exp(-t / 2000.0))
        assert np.isnan(result)


class TestModelListProducesFullMetricSet:
    """Every model (direct product feedback on issue #26) computes the same
    full set of figures of merit, not a hand-picked subset per model."""

    _REQUIRED_COLUMNS = {"R2", "T80", "T95", "Ts80", "Ts95", "tS", "PCE_after_1000_h", "LEY"}

    @pytest.mark.parametrize("model", fitting_tools.available_fit_model_list, ids=lambda m: m.name)
    def test_columns_include_full_metric_set(self, model):
        assert self._REQUIRED_COLUMNS.issubset(set(model.columns))

    @pytest.mark.parametrize("model", fitting_tools.available_fit_model_list, ids=lambda m: m.name)
    def test_fit_produces_a_value_for_every_declared_column(self, model):
        times = np.linspace(0.01, 20, 200)
        power = 18 * np.exp(-((times / 5.0) ** 0.8))
        values, fitted_curve, result = model.parfunc(power, times)
        assert len(values) == len(model.columns)
        assert len(fitted_curve) == len(power)


class TestWriteFitResultsToNomadNaNHandling:
    def test_nan_metrics_are_removed_not_written(self, mocker):
        import pandas as pd

        dm = DataManager.__new__(DataManager)
        dm.url = "https://test-oasis.example.org/nomad-oasis/api/v1"
        dm.token = "test-token"

        entries_data = pd.DataFrame(
            {"entry_id": ["entry-1"], "upload_id": ["upload-1"]},
            index=pd.MultiIndex.from_tuples([("sample1", 0)]),
        )
        model = fitting_tools.available_fit_model_list[1]  # Linear
        fit = {
            "model": model,
            "time": np.array([0.0, 1.0, 2.0]),
            "params": {
                "slope": 0.1,
                "intercept": 18.0,
                "R2": 0.9,
                "T80": float("nan"),
                "T95": float("nan"),
                "Ts80": float("nan"),
                "Ts95": float("nan"),
                "tS": 0.0,
                "PCE_after_1000_h": float("nan"),
                "LEY": 12.3,
            },
            "lmfit_result": None,
        }
        mock_edit = mocker.patch("hysprint_utils.api_calls.edit_entry")
        outcomes = dm.write_fit_results_to_nomad(
            entries_data, {("sample1", 0): fit}, "test-computed-by"
        )

        assert outcomes[0]["success"] is True
        changes = mock_edit.call_args.args[3]
        by_path = {c["path"]: c for c in changes}
        assert by_path["data/results/0/T80"]["action"] == "remove"
        assert by_path["data/results/0/PCE_after_1000_h"]["action"] == "remove"
        assert by_path["data/results/0/fit_r_squared"]["new_value"] == pytest.approx(0.9)
        assert by_path["data/results/0/lifetime_energy_yield"]["new_value"] == pytest.approx(12.3)
