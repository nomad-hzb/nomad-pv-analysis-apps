"""DataManager: load_offline(), filter, reset, export."""

import io
import json
from pathlib import Path

import numpy as np
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


# ---------------------------------------------------------------------------
# 5.3 physics (moved out of the GUI): units (C1, H1), noise (C2), n0 (C3), short traces (H3)
# ---------------------------------------------------------------------------

import data_manager as trpl  # noqa: E402

GLOBALS = {
    "lambda_laser": 705e-9,
    "spot_diameter": 2.72e-4,
    "thickness": 500.0,
    "bd_ratio": 0.21,
    "denoise": 0,
}
ROW = {
    "rep_rate": 1e4,
    "power": 0.4,
    "nd": 0.0,
    "integration_time": 10.0,
    "num_exponentials": 1,
}


def _single_exponential(tau_pl=100e-9, n=2000, dt=0.5e-9, background=0.0, scale=1e6):
    """A mono-exponential PL decay: counts = scale * exp(-t / tau_pl) + background."""
    time = np.arange(n) * dt
    return time, scale * np.exp(-time / tau_pl) + background


def _frame(time, counts, sample="S1", data_file="run"):
    return pd.DataFrame(
        [
            {
                "sample_id": sample,
                "data_file": data_file,
                "time": list(time),
                "counts": list(counts),
                "ns_per_bin": float(np.median(np.diff(time)) * 1e9),
            }
        ]
    )


def test_bin_width_comes_from_the_time_axis_in_seconds():
    time = np.arange(100) * 0.5e-9
    assert trpl.bin_width_seconds(trpl.time_in_seconds(time)) == pytest.approx(0.5e-9)


def test_count_rate_uses_a_bin_width_in_seconds_not_nanoseconds():
    """The bin width was passed as 0.5 (ns) where seconds were expected: rates 1e9 too small."""
    # 1e4 counts, 0.5 ns bins, 10 s, 10 kHz  ->  1e4 / (0.5e-9 * 10 * 1e4) = 2e8 counts/s
    assert float(trpl.rate_from_counts(1e4, 10.0, 0.5e-9, 1e4)) == pytest.approx(2e8)


def test_differential_lifetime_of_a_pl_proportional_to_n_squared_is_twice_the_decay():
    """Expected from the audit's synthetic trace: tau_PL = 100 ns gives tau_diff = 200 ns."""
    time, counts = _single_exponential(tau_pl=100e-9)
    frame, results = trpl.analyse_traces(_frame(time, counts), GLOBALS, [ROW])
    result = results[0]
    assert not result.error
    middle = result.tau_diff_s[100:1000]
    assert np.median(middle) == pytest.approx(200e-9, rel=0.03)  # was 9.9e-11 s or 1e12 off
    # the time axis of the analysis is in seconds: the trace spans 1 microsecond
    assert result.time_s.max() == pytest.approx(time.max(), rel=1e-6)


def test_a_background_does_not_bend_the_fit_when_it_is_subtracted():
    """C2: the model added the (already subtracted) noise back, so tau_diff diverged late."""
    background = 50.0
    time, counts = _single_exponential(tau_pl=100e-9, background=background, scale=2e5)
    params = dict(GLOBALS, denoise=-200)  # noise from the last 200 bins
    _, results = trpl.analyse_traces(_frame(time, counts), params, [ROW])
    result = results[0]
    assert not result.error
    assert result.noise_rate > 0
    early = np.median(result.tau_diff_s[50:300])
    late = np.median(result.tau_diff_s[600:900])
    assert early == pytest.approx(200e-9, rel=0.06)
    assert late == pytest.approx(200e-9, rel=0.15)  # was 357 ns mid-trace and 20 us late


def test_n0_follows_the_units_the_gui_asks_for():
    """Power [uW], spot diameter [cm], thickness [nm]: hand-computed, no hidden 1e7."""
    n0, fluence = trpl.calculate_n0(
        power_uw=0.4,
        rep_rate_hz=1e4,
        nd=0.0,
        spot_diameter_cm=2.72e-4,
        thickness_nm=500.0,
        wavelength_m=705e-9,
        bd_ratio=0.21,
    )
    pulse_energy = 0.4e-6 / 1e4  # 4e-11 J
    area = np.pi * (2.72e-4 / 2) ** 2  # cm^2
    photon_energy = 1.98645e-25 / 705e-9  # J
    expected_fluence = pulse_energy / area / photon_energy
    assert fluence == pytest.approx(expected_fluence)
    assert n0 == pytest.approx(expected_fluence * 0.21 / (500e-7))  # 500 nm = 5e-5 cm
    # about 2.4e15 photons/cm^2 per pulse and 1e19 cm^-3 for a 500 nm film
    assert 1e15 < fluence < 1e16 and 1e18 < n0 < 1e20


def test_an_nd_filter_attenuates_the_excitation():
    """ND was collected and never applied: every filtered measurement overestimated n0."""
    base = trpl.calculate_n0(0.4, 1e4, 0.0, 2.72e-4, 500.0, 705e-9, 0.21)
    filtered = trpl.calculate_n0(0.4, 1e4, 1.0, 2.72e-4, 500.0, 705e-9, 0.21)
    assert filtered[0] == pytest.approx(base[0] / 10)
    assert filtered[1] == pytest.approx(base[1] / 10)


def test_analysis_needs_a_thickness():
    time, counts = _single_exponential()
    with pytest.raises(trpl.AnalysisInputError, match="Thickness \[nm\]"):
        trpl.analyse_traces(_frame(time, counts), dict(GLOBALS, thickness=0), [ROW])


@pytest.mark.parametrize("n_points", [60, 25, 9])
def test_short_traces_adapt_the_smoothing_instead_of_failing(n_points):
    """savgol_filter(pl, 51, 3) raised for any trace with fewer than 51 points after its peak."""
    time, counts = _single_exponential(n=n_points, dt=5e-9, tau_pl=40e-9, scale=1e5)
    _, results = trpl.analyse_traces(_frame(time, counts), GLOBALS, [dict(ROW, num_exponentials=1)])
    assert results[0].error == "" or "usable point" in results[0].error


def test_smoothing_window_is_odd_and_never_larger_than_the_trace():
    assert trpl._smoothing_window(500) == 51
    assert trpl._smoothing_window(30) == 29
    assert trpl._smoothing_window(4) is None


def test_one_bad_trace_does_not_stop_the_others():
    good_time, good_counts = _single_exponential(n=500)
    short_time, short_counts = good_time[:2], good_counts[:2]
    frame = pd.concat(
        [_frame(good_time, good_counts, "S1"), _frame(short_time, short_counts, "S2")],
        ignore_index=True,
    )
    processed, results = trpl.analyse_traces(frame, GLOBALS, [ROW, ROW])
    assert results[0].error == "" and results[0].tau_diff_s is not None
    assert results[1].error != ""
    assert len(processed) == 2  # both rows kept, the failed one without analysis columns


def test_demo_fixture_runs_the_whole_analysis():
    """The 5-point demo traces made 'Run Analysis' fail in demo mode."""
    manager = trpl.TRPLDataManager("http://x", "t")
    assert manager.load_offline(FIXTURE_PATH)
    rows = [dict(ROW, num_exponentials=2) for _ in range(len(manager.data))]
    processed, results = trpl.analyse_traces(manager.data, GLOBALS, rows)
    assert [r.error for r in results] == [""] * len(results)
    assert all(np.isfinite(r.tau_diff_s).all() for r in results)
    assert np.isfinite(processed["n0s"]).all()


def test_raw_plot_shows_seconds_as_nanoseconds_and_a_rate_label():
    time, counts = _single_exponential(n=200)
    frame, _ = trpl.analyse_traces(_frame(time, counts), GLOBALS, [ROW])
    figure = TRPLPlotManager.trpl_traces(frame, y_col="counts", y_title="PL rate [counts/s]")
    assert figure.data[0].x.max() == pytest.approx(time.max() * 1e9)  # ns
    assert figure.layout.yaxis.title.text == "PL rate [counts/s]"


def test_a_failed_trace_is_left_out_of_the_raw_plot():
    frame = pd.DataFrame(
        {
            "sample_id": ["ok", "bad"],
            "time_s": [[0.0, 1e-9], None],
            "counts": [[1.0, 2.0], None],
        }
    )
    assert len(TRPLPlotManager.trpl_traces(frame, y_col="counts").data) == 1


def test_data_file_label_is_never_empty():
    manager = trpl.TRPLDataManager("http://x", "t")
    raw = {
        "S1": [
            [{"trpl_properties": {"counts": [1.0], "time": [0.0]}, "data_file": "S001_trpl.txt"}]
        ]
    }
    assert manager._build_from_raw(raw, {"S1": ""})
    assert manager.data["data_file"].iloc[0] == "S001_trpl.txt"


def test_parameter_panel_only_offers_inputs_the_analysis_uses():
    from gui_components import ParameterPanel

    panel = ParameterPanel(pd.DataFrame({"sample_id": ["S1"], "data_file": ["f"]}))
    assert set(panel.collect_global_params()) == {
        "lambda_laser",
        "spot_diameter",
        "thickness",
        "bd_ratio",
        "denoise",
    }
    assert "fitting_interval" not in panel.collect_row_params()[0]


def test_plots_are_wrapped_to_fill_the_page_and_the_noise_line_needs_a_noise():
    pytest.importorskip("anywidget")  # go.FigureWidget; not in the CI test environment
    import gui_components as gui
    import ipywidgets as widgets

    box = gui._responsive(go.Figure(go.Scatter(x=[1, 2], y=[1, 2])))
    assert isinstance(box, widgets.Box)
    assert box.layout.width == "100%" and box.layout.height.endswith("px")
    assert "trpl-plot" in box._dom_classes
    assert "width: 100% !important" in gui.PLOT_CSS

    frame = pd.DataFrame(
        {"sample_id": ["a"], "time": [[0.0, 1e-9]], "counts": [[5.0, 4.0]], "noise": [0.0]}
    )
    assert not TRPLPlotManager.trpl_traces(frame).layout.shapes  # no line at 0 on a log axis
    frame["noise"] = [0.5]
    assert len(TRPLPlotManager.trpl_traces(frame).layout.shapes) == 1
