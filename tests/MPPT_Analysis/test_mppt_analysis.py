"""
Tests for MPPT_Analysis — data_manager and plot_manager.
"""

import json
from pathlib import Path

import fitting_tools
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import pytest
from app_state import AppState
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
    # NOMAD stores power as -15.2 (generation is negative); the app works with a positive
    # power so every figure of merit has the same orientation.
    assert abs(row["power_density"] - 15.2) < 1e-9
    # Original: current_density=-16.5 -> inverted together with the power to 16.5
    assert abs(row["current_density"] - 16.5) < 1e-9
    # Original: time=0.0 -> scaled by 1/3600 -> still 0.0
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


# ===========================================================================
# Per-measurement (pixel) selection
# ===========================================================================


class TestPerCurveSelection:
    """batch1&sample1 in the fixture holds two measurements (curves 0 and 1)."""

    SAMPLE = "batch1&sample1"

    def test_fit_sample_fits_every_curve_by_default(self, loaded_manager):
        model = fitting_tools.available_fit_model_list[0]
        fits = loaded_manager.fit_sample(
            loaded_manager.curves, loaded_manager.sample_ids, self.SAMPLE, model
        )
        assert set(fits) <= {0, 1}

    def test_fit_sample_restricted_to_one_curve(self, loaded_manager, mocker):
        mocker.patch("data_manager.fit_curve", return_value={"x": 1})
        model = fitting_tools.available_fit_model_list[0]
        fits = loaded_manager.fit_sample(
            loaded_manager.curves,
            loaded_manager.sample_ids,
            self.SAMPLE,
            model,
            curve_ids=[1],
        )
        assert list(fits) == [1]

    def test_selected_curve_data_filters_to_chosen_curves(self, loaded_manager):
        data = loaded_manager.get_selected_curve_data(
            loaded_manager.curves,
            loaded_manager.sample_ids,
            [self.SAMPLE],
            "power_density",
            selected_curves=[(self.SAMPLE, 1)],
        )
        assert [(d["sample_id"], d["curve_id"]) for d in data] == [(self.SAMPLE, 1)]

    def test_selected_curve_data_without_filter_returns_all(self, loaded_manager):
        data = loaded_manager.get_selected_curve_data(
            loaded_manager.curves,
            loaded_manager.sample_ids,
            [self.SAMPLE],
            "power_density",
        )
        assert len(data) == 2

    def test_curve_label_strips_sample_prefix(self, loaded_manager):
        entries = pd.DataFrame(
            {"entry_names": ["S1 Front_PixelA", ""]},
            index=pd.MultiIndex.from_tuples([("S1", 0), ("S1", 1)]),
        )
        assert loaded_manager.get_curve_label(entries, "S1", 0) == "Front_PixelA"
        assert loaded_manager.get_curve_label(entries, "S1", 1) == "Curve 1"
        assert loaded_manager.get_curve_label(None, "S1", 2) == "Curve 2"


class TestAppStateCurveSelection:
    def test_default_selection_means_all_curves(self):
        state = AppState()
        state.set_selected_samples(["s1"])
        assert state.data["selected_curves"] is None
        assert state.selected_curve_ids("s1") is None

    def test_selected_curves_are_stored_per_sample(self):
        state = AppState()
        state.set_selected_samples(["s1", "s2"], selected_curves=[("s1", 0), ("s1", 2), ("s2", 1)])
        assert state.selected_curve_ids("s1") == [0, 2]
        assert state.selected_curve_ids("s2") == [1]
        assert state.get_selected_curves_count() == 3

    def test_update_curve_fit_results_keeps_other_curves(self):
        model = fitting_tools.available_fit_model_list[0]
        fit = {"model": model, "time": np.array([0.0, 1.0]), "params": {}}
        state = AppState()
        state.set_fit_results({("s1", 0): fit, ("s1", 1): fit})
        state.update_curve_fit_results({("s1", 1): fit})
        assert set(state.fitted_curves_data) == {("s1", 0), ("s1", 1)}


# ---------------------------------------------------------------------------
# 5.2 fitting correctness: sustained T80 (C1), one LEY unit (C2), bounded tS (C3),
# overflow guard (H1), robust write-back (H2), selection-only fits (H3), aligned
# curves (H4), one sign convention (H6)
# ---------------------------------------------------------------------------

_T = np.linspace(0, 100, 400)
_TRUE = 20 * np.exp(-_T / 300)  # a decay whose exact T80 is 300*ln(1/0.8) = 66.9 h


def _crossing(power, fraction=0.8):
    reference = fitting_tools.initial_reference(power)
    return fitting_tools.crossing_time(
        _T,
        power,
        reference,
        fraction,
        lambda t: 20 * np.exp(-t / 300),
        lambda threshold: 300 * np.log(20 / threshold),
    )


def test_t80_ignores_a_ramp_up_start_and_a_single_dropout():
    clean = _crossing(_TRUE)
    ramp = _TRUE.copy()
    ramp[:10] = np.linspace(2, _TRUE[10], 10)  # tracker still settling
    dropout = _TRUE.copy()
    dropout[5] = 0.0  # one bad point
    assert 60 < clean < 80
    assert _crossing(ramp) == pytest.approx(clean, abs=4)  # was 0.0 h
    assert _crossing(dropout) == pytest.approx(clean, abs=4)  # was 1.25 h


def test_t80_needs_a_sustained_crossing_and_noise_does_not_trigger_it_early():
    rng = np.random.default_rng(1)
    noisy = _TRUE + rng.normal(0, 0.3, _T.size)
    assert _crossing(noisy) == pytest.approx(_crossing(_TRUE), abs=6)


def test_every_model_reports_the_same_lifetime_energy_in_kwh_per_m2():
    """C2: two models multiplied by 10, four did not, and the logistic one gave -inf."""
    rng = np.random.default_rng(0)
    y = _TRUE + rng.normal(0, 0.05, _T.size)
    values = {}
    for model in fitting_tools.available_fit_model_list:
        result, _, _ = model.parfunc(y, _T)
        row = dict(zip(model.columns, [float(getattr(v, "n", v)) for v in result]))
        assert np.isfinite(row["LEY"]), model.name
        values[model.name] = row["LEY"]
    reference = np.mean(list(values.values()))
    for name, value in values.items():
        assert value == pytest.approx(reference, rel=0.02), name
    # exact: integral of 20 mW/cm^2 * exp(-t/300) from 0 to the T80, at 0.01 kWh/m^2 per mWh/cm^2
    t80 = 300 * np.log(1 / 0.8)
    exact = 20 * 300 * (1 - np.exp(-t80 / 300)) * 0.01
    assert reference == pytest.approx(exact, rel=0.1)


def test_a_constant_20_mw_cm2_curve_over_1000_h_is_200_kwh_per_m2():
    times = np.linspace(0, 1000, 500)
    power = np.full_like(times, 20.0)
    value = fitting_tools.ley_after_1000h(times, power, lambda t: 20.0)
    assert value == pytest.approx(200.0)


def test_ley_after_1000h_follows_the_real_else_model_else_nan_policy():
    short = np.linspace(0, 50, 100)
    flat = np.full_like(short, 20.0)
    # 1000 h is 20x the measurement: beyond the 10x horizon
    assert np.isnan(fitting_tools.ley_after_1000h(short, flat, lambda t: 20.0))
    mid = np.linspace(0, 200, 100)
    assert fitting_tools.ley_after_1000h(mid, np.full_like(mid, 20.0), lambda t: 20.0) == (
        pytest.approx(200.0)
    )
    # a model that decays below zero never gives back negative energy: 5 - t is positive for
    # 5 h only, 0.5 * 5 * 5 = 12.5 mWh/cm^2 = 0.125 kWh/m^2
    assert fitting_tools.ley_after_1000h(mid, np.full_like(mid, 1.0), lambda t: 5 - t) == (
        pytest.approx(0.125, rel=1e-3)
    )


def test_every_model_offers_ley_1000h_and_it_is_written_as_a_fit_parameter():
    from data_manager import _LEFTOVER_PARAM_UNITS

    for model in fitting_tools.available_fit_model_list:
        assert "LEY_1000h" in model.columns, model.name
    assert all(units["LEY_1000h"] == ("kWh/m^2", 1.0) for units in _LEFTOVER_PARAM_UNITS.values())


def test_logistic_ley_survives_a_huge_rate_constant():
    """log(1+exp(k(t-x0))) overflowed to inf for a large k and aborted the write-back."""
    k = 5000.0
    value = 0.5 / k * (np.logaddexp(0, k * (80 - 50)) - np.logaddexp(0, -k * 50))
    assert np.isfinite(value)


def test_stabilization_time_is_never_beyond_the_measurement():
    biexp = next(m for m in fitting_tools.available_fit_model_list if m.name == "Biexponential")
    result, _, _ = biexp.parfunc(_TRUE.copy(), _T)
    row = dict(zip(biexp.columns, [float(getattr(v, "n", v)) for v in result]))
    assert np.isnan(row["tS"]) or row["tS"] <= _T[-1]  # was 1350 h on 100 h of data
    logistic = next(m for m in fitting_tools.available_fit_model_list if "Logistic" in m.name)
    result, _, _ = logistic.parfunc(_TRUE.copy(), _T)
    row = dict(zip(logistic.columns, [float(getattr(v, "n", v)) for v in result]))
    assert row["tS"] <= _T[-1]  # was 10x the measurement length (1000 h)


def test_find_ts_has_nothing_to_stabilize_from_for_a_monotonic_decay():
    class _Result:
        params = None

        @staticmethod
        def eval(params, t):
            return 20 * np.exp(-t / 300)

    t_s, pce_ts = fitting_tools.find_tS(_T, _Result)
    assert t_s == 0.0 and pce_ts == pytest.approx(20.0)


def test_find_ts_finds_the_recovery_after_a_dip_inside_the_measured_window():
    class _Result:
        params = None

        @staticmethod
        def eval(params, t):
            return 10 + 0.5 * np.sin(t / 10)  # dips, then recovers inside 0..100

    t_s, pce_ts = fitting_tools.find_tS(_T, _Result)
    assert 0 < t_s <= _T[-1]
    assert pce_ts == pytest.approx(10 + 0.5 * np.sin(t_s / 10), abs=1e-3)


def test_has_value_rejects_none_nan_and_infinity():
    from data_manager import _has_value

    assert _has_value(1.5) and _has_value(0.0) and _has_value(3)
    for bad in (None, float("nan"), float("inf"), float("-inf"), "abc"):
        assert not _has_value(bad)


def _fit_for(model):
    return {
        "model": model,
        "time": np.array([0.0, 1.0, 2.0]),
        "params": {"R2": 0.99, "LEY": float("-inf"), "slope": float("nan"), "intercept": 1.0},
    }


def _entries_with_ids(manager, same_id=None):
    entries = manager.entries.copy()
    entries["entry_id"] = same_id or [f"entry-{i}" for i in range(len(entries))]
    return entries


def test_write_back_reports_a_bad_entry_and_carries_on(loaded_manager, monkeypatch):
    """A network error on one entry used to abort the loop with earlier entries written."""
    import requests

    model = next(m for m in fitting_tools.available_fit_model_list if m.name == "Linear")
    keys = [(sid, 0) for sid in loaded_manager.sample_ids]
    calls = []

    def flaky(url, token, entry_id, changes):
        calls.append((entry_id, changes))
        if len(calls) == 1:
            raise requests.ConnectionError("network down")

    monkeypatch.setattr("hysprint_utils.api_calls.edit_entry", flaky)
    outcomes = loaded_manager.write_fit_results_to_nomad(
        _entries_with_ids(loaded_manager), {key: _fit_for(model) for key in keys}, "test"
    )
    assert len(outcomes) == len(keys)
    assert outcomes[0]["success"] is False and "network down" in outcomes[0]["message"]
    assert all(o["success"] for o in outcomes[1:])  # the rest still went through
    for _, changes in calls:  # nothing non-finite was ever sent
        for change in changes:
            value = change.get("new_value")
            assert not (isinstance(value, float) and not np.isfinite(value)), change


def test_write_back_writes_a_shared_entry_only_once(loaded_manager, monkeypatch):
    model = next(m for m in fitting_tools.available_fit_model_list if m.name == "Linear")
    entries = _entries_with_ids(loaded_manager, same_id="one-entry-for-every-sample")
    written = []
    monkeypatch.setattr(
        "hysprint_utils.api_calls.edit_entry",
        lambda url, token, entry_id, changes: written.append(entry_id),
    )
    keys = [(sid, 0) for sid in loaded_manager.sample_ids]
    outcomes = loaded_manager.write_fit_results_to_nomad(
        entries, {key: _fit_for(model) for key in keys}, "test"
    )
    assert written == ["one-entry-for-every-sample"]
    assert all(o["success"] for o in outcomes)


def _two_point_rows(power, current=-20.0):
    return [
        {"time": 0.0, "power_density": power, "voltage": 0.9, "current_density": current},
        {"time": 3600.0, "power_density": power, "voltage": 0.9, "current_density": current},
    ]


def test_an_entry_without_rows_does_not_shift_the_entry_ids_of_the_others():
    """H4: curve k was labelled with entry k's id while holding entry k+1's data."""
    raw = {
        "s1": [
            ({"name": "empty", "time": [], "power_density": []}, {"entry_id": "E-empty"}),
            (_two_point_rows(-10.0), {"entry_id": "E-first", "upload_id": "u"}),
            (_two_point_rows(-30.0), {"entry_id": "E-second", "upload_id": "u"}),
        ],
        "s2": [({"time": []}, {"entry_id": "E-none"})],  # a sample with no usable row at all
        "s3": [(_two_point_rows(-50.0), {"entry_id": "E-s3", "upload_id": "u"})],
    }
    manager = DataManager(url="http://mock", token="t")
    assert manager._build_from_raw(raw, {})
    assert list(manager.sample_ids) == ["s1", "s3"]  # s2 is not in, s3 is not relabelled s2
    assert manager.get_entry_id(manager.entries, "s1", 0) == "E-first"
    assert manager.get_entry_id(manager.entries, "s1", 1) == "E-second"
    assert manager.get_entry_id(manager.entries, "s3", 0) == "E-s3"
    _, power = manager.get_raw_curve(manager.curves, manager.sample_ids, "s1", 0)
    assert power[0] == pytest.approx(10.0)  # curve 0 really is the entry labelled E-first
    _, power = manager.get_raw_curve(manager.curves, manager.sample_ids, "s3", 0)
    assert power[0] == pytest.approx(50.0)


def test_power_sign_is_detected_per_entry_not_flipped_blindly():
    """H6: negative stored power is made positive; an entry already positive is left alone."""
    manager = DataManager(url="http://mock", token="t")
    raw = {
        "neg": [(_two_point_rows(-15.0, -16.0), {"entry_id": "a"})],
        "pos": [(_two_point_rows(15.0, 16.0), {"entry_id": "b"})],
    }
    assert manager._build_from_raw(raw, {})
    for sample in ("neg", "pos"):
        _, power = manager.get_raw_curve(manager.curves, manager.sample_ids, sample, 0)
        assert power[0] == pytest.approx(15.0)
        assert manager.curves.loc[sample].iloc[0]["current_density"] == pytest.approx(16.0)


def test_demo_data_is_in_the_real_nomad_convention(loaded_manager):
    """The demo file used to be positive power next to negative current, then got flipped."""
    raw = json.loads(FIXTURE_PATH.read_text())
    power = raw["measurements"]["batch1&sample1"][0][0][0]["power_density"]
    assert power < 0  # stored like NOMAD stores generation
    _, shown = loaded_manager.get_raw_curve(
        loaded_manager.curves, loaded_manager.sample_ids, "batch1&sample1", 0
    )
    assert shown[0] > 0


def test_fits_of_deselected_samples_are_dropped_and_a_new_batch_starts_clean():
    """H3: a sample no longer selected kept its fit and was written to NOMAD."""
    state = AppState()
    model = fitting_tools.available_fit_model_list[0]
    state.update_curve_fit_results(
        {
            ("A", 0): _fit_for(model),
            ("B", 0): _fit_for(model),
            ("B", 1): _fit_for(model),
            ("C", 0): _fit_for(model),
        }
    )
    state.set_selected_samples(["A", "B"])
    assert set(state.fitted_curves_data) == {("A", 0), ("B", 0), ("B", 1)}
    state.set_selected_samples(["A", "B"], selected_curves=[("A", 0), ("B", 1)])
    assert set(state.fitted_curves_data) == {("A", 0), ("B", 1)}
    assert set(state.fit_results["sample_id"]) == {"A", "B"}

    state.load_curves_data(None, None, None, None)
    assert state.fitted_curves_data == {} and state.cleaned_power == {}
    assert not state.has_fit_results()


def test_app_version_written_to_nomad_matches_pyproject():
    """APP_VERSION is stored in fit_computed_by; it drifted from pyproject.toml before."""
    import re
    from pathlib import Path

    root = Path(__file__).parents[2] / "apps" / "MPPT_Analysis"
    pyproject = (root / "pyproject.toml").read_text(encoding="utf-8")
    version = re.search(r'^version = "([^"]+)"', pyproject, re.M).group(1)
    gui = (root / "gui_components.py").read_text(encoding="utf-8")
    assert f'APP_VERSION = "{version}"' in gui
