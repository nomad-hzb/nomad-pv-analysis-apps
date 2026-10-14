"""Regression tests for the JV-Analysis identity, filter and plot-dispatch fixes (audit 6.1)."""

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import pytest
from data_manager import DataManager, parse_cell_name
from plot_manager import PlotManager, plotting_string_action


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("a_Forward_Light", ("a", "Forward", "Light")),
        ("c_Reverse_Light", ("c", "Reverse", "Light")),
        ("C1Rev", ("C1", "Reverse", "Light")),
        ("C2For", ("C2", "Forward", "Light")),
        ("11_Reverse_Dark", ("11", "Reverse", "Dark")),
    ],
)
def test_cell_name_keeps_the_whole_pixel_name(name, expected):
    assert parse_cell_name(name) == expected


def _curve(cell_name, pce=15.0):
    return {
        "cell_name": cell_name,
        "open_circuit_voltage": 1.0,
        "short_circuit_current_density": 20.0,
        "fill_factor": 0.75,
        "efficiency": pce,
        "potential_at_maximum_power_point": 0.8,
        "current_density_at_maximun_power_point": 18.0,
        "voltage": [0.0, 0.5, 1.0],
        "current_density": [20.0, 19.0, 0.0],
    }


def _raw(stem="HZB_Batch_1_C-1", cells=("C1Rev", "C2Rev")):
    data = {"data_file": f"{stem}.1727.jv.txt", "jv_curve": [_curve(c) for c in cells]}
    return {"HZB_Batch_1_C-1": [(data, {"upload_id": "up1"})]}


@pytest.fixture
def manager(mocker):
    return DataManager(mocker.MagicMock())


def test_two_pixels_with_longer_names_stay_two_cells(manager):
    jvc, curves = manager._build_from_raw(_raw(), ["HZB_Batch_1_C-1"])
    assert sorted(jvc["cell"]) == ["C1", "C2"]
    assert set(curves["cell"]) == {"C1", "C2"}


def test_batch_is_the_selected_batch_not_unknown_or_the_upload(manager):
    jvc, _ = manager._build_from_raw(
        _raw(), ["HZB_Batch_1_C-1"], sample_batch={"HZB_Batch_1_C-1": "HZB_Batch_1"}
    )
    assert set(jvc["batch"]) == {"HZB_Batch_1"}
    manager.data["jvc"] = jvc
    manager._process_sample_info({})
    assert set(manager.data["jvc"]["batch"]) == {"HZB_Batch_1"}  # no overwrite with "unknown"


def test_variation_is_looked_up_by_sample_id_even_when_the_file_is_named_differently(manager):
    raw = _raw(stem="some_other_file_name")
    jvc, _ = manager._build_from_raw(raw, ["HZB_Batch_1_C-1"])
    manager.data["jvc"] = jvc
    manager._process_sample_info({"HZB_Batch_1_C-1": "0.5 M"})
    assert set(manager.data["jvc"]["identifier"]) == {"some_other_file&0.5 M"}


def test_unreadable_curves_are_reported_not_silently_dropped(manager):
    raw = _raw()
    del raw["HZB_Batch_1_C-1"][0][0]["jv_curve"][0]["fill_factor"]
    jvc, _ = manager._build_from_raw(raw, ["HZB_Batch_1_C-1", "missing"])
    assert len(jvc) == 1
    problems = {p["sample_id"]: p["error"] for p in manager.load_problems}
    assert "invalid curve" in problems["HZB_Batch_1_C-1"] and "no JV data" in problems["missing"]


def _filtered_manager(manager):
    jvc, _ = manager._build_from_raw(
        _raw(cells=("a_Reverse_Light", "b_Reverse_Light")), ["HZB_Batch_1_C-1"]
    )
    jvc.loc[0, "FF(%)"] = 10.0  # below the default FF > 24 filter
    manager.data["jvc"] = jvc
    return manager


def test_an_empty_filter_list_applies_no_filter_but_none_means_the_defaults(manager):
    manager = _filtered_manager(manager)
    kept, omitted, _ = manager.apply_filters([], "Both", None)
    assert (len(kept), len(omitted)) == (2, 0)
    kept, omitted, _ = manager.apply_filters(None, "Both", None)
    assert (len(kept), len(omitted)) == (1, 1)


def test_selecting_no_samples_keeps_nothing(manager):
    manager = _filtered_manager(manager)
    kept, omitted, _ = manager.apply_filters([], "Both", [])
    assert len(kept) == 0 and len(omitted) == 2


def test_sample_selector_reports_an_empty_selection_as_empty_not_everything(mocker):
    from gui_components import FilterUI

    ui = FilterUI.__new__(FilterUI)
    assert ui.get_selected_items.__func__ is FilterUI.get_selected_items  # exists
    ui.sample_checkboxes = {}
    ui.selected_samples = set()
    ui.sample_data = None
    assert ui.get_selected_items() is None  # no selector built
    ui.sample_checkboxes = {("b", "s"): object()}
    ui.sample_data = {
        "jvc": pd.DataFrame({"batch": ["b"], "sample": ["s"], "condition": ["w"], "cell": ["a"]})
    }
    assert ui.get_selected_items() == []  # the user cleared every sample


def _jvc(direction_values=("Reverse", "Forward"), pce=15.0):
    rows = []
    for direction in direction_values:
        rows.append(
            {
                "Voc(V)": 1.0,
                "Jsc(mA/cm2)": -20.0,
                "FF(%)": 75.0,
                "PCE(%)": pce,
                "V_mpp(V)": 0.8,
                "J_mpp(mA/cm2)": -18.0,
                "P_mpp(mW/cm2)": -14.4,
                "R_series(Ohmcm2)": 4.0,
                "R_shunt(Ohmcm2)": 1000.0,
                "sample": "S1",
                "batch": "B",
                "condition": "w",
                "cell": "a",
                "direction": direction,
                "ilum": "Light",
                "status": "L1",
                "sample_id": "sid",
            }
        )
    return pd.DataFrame(rows)


def _curves(direction_values=("Reverse", "Forward")):
    rows = []
    n = 5
    for direction in direction_values:
        for variable, values in (
            ("Voltage (V)", np.linspace(0, 1, n)),
            ("Current Density(mA/cm2)", np.linspace(20, 0, n)),
        ):
            rows.append(
                {
                    "index": f"{variable}_a_{direction}_Light",
                    "sample": "S1",
                    "batch": "B",
                    "condition": "w",
                    "variable": variable,
                    "cell": "a",
                    "direction": direction,
                    "ilum": "Light",
                    "sample_id": "sid",
                    "status": "L1",
                    **dict(enumerate(values)),
                }
            )
    return pd.DataFrame(rows)


@pytest.mark.parametrize("directions", [("Reverse",), ("Forward",)])
def test_best_device_plot_with_a_single_scan_direction_still_draws(directions):
    figure = PlotManager().create_jv_best_device_plot(
        _jvc(directions), _curves(directions), show_summary=True
    )[0]
    assert isinstance(figure, go.Figure)
    assert len(figure.data) > 0
    assert len(figure.layout.annotations) == 1  # the one direction that exists


def test_omitted_combination_plots_are_built_from_the_omitted_rows():
    kept, omitted = _jvc(pce=18.0), _jvc(pce=2.0)
    figures, names = plotting_string_action(
        ["Jpsg"], (kept, kept, _curves()), (omitted, [], True, ".", [])
    )
    assert figures, "no figure was produced"
    plotted = np.concatenate(
        [
            np.asarray(t.y, dtype=float)
            for f in figures
            for t in f.data
            if getattr(t, "y", None) is not None
        ]
    )
    assert plotted.max() < 5  # the omitted PCE (2), not the kept one (18)
    assert all("omitted" in n for n in names)
