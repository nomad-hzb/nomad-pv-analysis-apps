import ipywidgets as widgets
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import pytest
from data_loader import HySprintDataLoader
from data_manager import (
    DataManager,
    MeasurementRow,
    aggregate_results_per_sample,
    apply_row_filters,
    average_rows_per_sample,
    exclude_samples,
    get_categorical_columns,
    get_layer_type_options,
    merge_results_per_sample,
    merged_result_column_names,
    parse_uploaded_analysis_csv,
    process_type_label,
    result_type_label,
    select_layer_row_per_sample,
    uploaded_numeric_columns,
    variation_warning,
)
from experimental_analysis import (
    compute_process_drift,
    detect_outliers,
    find_pareto_front,
    run_anova,
    run_pca,
)
from gui_components import GUIManager
from ml_analysis import (
    detect_integer_columns,
    estimate_max_bo_steps,
    is_measured_parameter,
    run_random_forest,
    suggest_next_experiments,
    suggest_pareto_experiments,
)
from plot_manager import PlotManager, bin_numeric_column
from pydantic import ValidationError
from utils import (
    ParameterManager,
    ProcessStepManager,
    _round_preserving_significance,
    build_doe_voila_url,
    get_material_column,
    get_uploads_path,
    trigger_csv_download,
)


def test_measurement_row_valid_data_populates_fields():
    row = MeasurementRow(sample_id="s1", variation="v1", efficiency=18.2, description="test")

    assert row.model_dump()["sample_id"] == "s1"
    assert row.efficiency == pytest.approx(18.2)


def test_measurement_row_coerces_single_element_list_to_scalar():
    row = MeasurementRow(sample_id="s1", efficiency=[18.2])

    assert row.efficiency == pytest.approx(18.2)


def test_measurement_row_optional_fields_default_to_none():
    row = MeasurementRow(sample_id="s1")

    assert row.efficiency is None
    assert row.description is None


def test_measurement_row_missing_required_field_raises_validation_error():
    with pytest.raises(ValidationError):
        MeasurementRow(variation="v1")


def test_get_material_column_prefers_layer_material_name():
    df = pd.DataFrame({"layer_material_name": ["SnO2"], "layer_material": ["other"]})
    assert get_material_column(df) == "layer_material_name"


def test_get_material_column_falls_back_to_fuzzy_match():
    df = pd.DataFrame({"perovskite_layer_material_2": ["MAPI"]})
    assert get_material_column(df) == "perovskite_layer_material_2"


def test_get_material_column_returns_none_when_absent():
    df = pd.DataFrame({"x": [1]})
    assert get_material_column(df) is None


def test_data_manager_get_material_column_delegates_to_shared_helper():
    dm = DataManager(data_loader=None, param_manager=ParameterManager())
    df = pd.DataFrame({"layer_material": ["SnO2"]})

    assert dm.get_material_column(df) == "layer_material"


def test_parameter_manager_filters_blacklist_and_renames_description():
    pm = ParameterManager()
    result = pm.filter_parameters(["sample_id", "data_file", "description"], "x_parameters")

    assert "data_file" not in result
    assert "Notes" in result
    assert "description" not in result


def test_parameter_manager_detects_varying_parameters():
    pm = ParameterManager()
    df = pd.DataFrame({"constant": [1, 1, 1], "varies": [1, 2, 3], "sample_id": ["a", "b", "c"]})

    varying = pm.detect_varying_parameters(df)

    assert varying == ["varies"]


def test_process_step_manager_extract_process_types_deduplicates():
    psm = ProcessStepManager()
    step = {
        "name": "HySprint_SpinCoating",
        "layer": [{"layer_type": "ETL", "layer_material_name": "SnO2"}],
    }
    steps = [step, dict(step)]

    process_types = psm.extract_process_types(steps)

    assert process_types == [("SpinCoating - ETL", "HySprint_SpinCoating")]


def test_process_step_manager_extract_process_types_empty_input():
    psm = ProcessStepManager()
    assert psm.extract_process_types([]) == []


def test_process_step_manager_maps_annealing_display_name():
    psm = ProcessStepManager()
    assert psm.map_display_to_measurement_type("Annealing") == "annealing"


def _plot_manager():
    return PlotManager(plot_widget=go.FigureWidget(), stats_output=widgets.Output())


def test_create_scatter_plot_adds_expected_trace():
    pmgr = _plot_manager()
    df = pd.DataFrame({"sample_id": ["s1", "s2"], "x": [1, 2], "y": [10, 20]})

    pmgr.create_scatter_plot(df, "x", "y", None, "X Label", "Y Label")

    assert isinstance(pmgr.plot_widget, go.FigureWidget)
    assert len(pmgr.plot_widget.data) == 1
    trace = pmgr.plot_widget.data[0]
    assert trace.mode == "markers"
    assert list(trace.x) == [1, 2]
    assert list(trace.y) == [10, 20]


def test_create_scatter_plot_colors_by_category():
    pmgr = _plot_manager()
    df = pd.DataFrame(
        {
            "sample_id": ["s1", "s2", "s3"],
            "x": [1, 2, 3],
            "y": [10, 20, 30],
            "material": ["A", "A", "B"],
        }
    )

    pmgr.create_scatter_plot(df, "x", "y", "material", "X Label", "Y Label")

    assert len(pmgr.plot_widget.data) == 2
    names = sorted(t.name for t in pmgr.plot_widget.data)
    assert names == ["A", "B"]


def test_prepare_plot_data_material_type_without_material_column_raises():
    pmgr = _plot_manager()
    df = pd.DataFrame({"x": [1, 2], "y": [10, 20]})

    with pytest.raises(ValueError):
        pmgr.prepare_plot_data(df, "Material Type", "y", None, "none")


def _fake_loader(fake_data: dict) -> HySprintDataLoader:
    return HySprintDataLoader(
        url="http://example.test",
        token="token",
        get_all_data_func=lambda *args, **kwargs: fake_data,
    )


def test_load_spin_coating_data_extracts_operator():
    fake_data = {"s1": [[{"name": "spin", "operator": "Alice"}]]}
    loader = _fake_loader(fake_data)

    df = loader.load_spin_coating_data(["s1"], {"s1": "v1"})

    assert df is not None
    assert df.loc[0, "operator"] == "Alice"


def test_load_slot_die_coating_data_extracts_operator():
    fake_data = {"s1": [[{"name": "sdc", "operator": "Bob"}]]}
    loader = _fake_loader(fake_data)

    df = loader.load_slot_die_coating_data(["s1"], {"s1": "v1"})

    assert df is not None
    assert df.loc[0, "operator"] == "Bob"


def test_load_inkjet_printing_data_extracts_operator():
    fake_data = {"s1": [[{"name": "ijp", "operator": "Carol"}]]}
    loader = _fake_loader(fake_data)

    df = loader.load_inkjet_printing_data(["s1"], {"s1": "v1"})

    assert df is not None
    assert df.loc[0, "operator"] == "Carol"


def test_load_spin_coating_data_operator_defaults_to_empty_string():
    fake_data = {"s1": [[{"name": "spin"}]]}
    loader = _fake_loader(fake_data)

    df = loader.load_spin_coating_data(["s1"], {"s1": "v1"})

    assert df.loc[0, "operator"] == ""


def test_load_annealing_data_renames_columns_to_avoid_embedded_annealing_collision():
    # HySprint_Annealing (a standalone entry) nests temperature/time/atmosphere
    # under the same "annealing" key the embedded per-process extractors
    # (load_spin_coating_data etc.) also read - left as the generic flattener's
    # raw dotted names, "annealing.temperature" would be easy to confuse with
    # those extractors' own "annealing_temperature" column for a *different*,
    # embedded annealing step once both end up in the same merged dataset.
    fake_data = {
        "s1": [
            [
                {
                    "name": "standalone anneal",
                    "annealing": {"temperature": 120.0, "time": 600.0, "atmosphere": "N2"},
                }
            ]
        ]
    }
    loader = _fake_loader(fake_data)

    df = loader.load_annealing_data(["s1"], {"s1": "v1"})

    assert df is not None
    assert "standalone_annealing_temperature" in df.columns
    assert "standalone_annealing_time" in df.columns
    assert "standalone_annealing_atmosphere" in df.columns
    assert not any(col.startswith("annealing.") for col in df.columns)
    assert df.loc[0, "standalone_annealing_temperature"] == 120.0
    assert df.loc[0, "standalone_annealing_time"] == 600.0
    assert df.loc[0, "standalone_annealing_atmosphere"] == "N2"


def test_set_analysis_columns_preserves_unchecked_state_across_rebuild():
    # Recalculate rebuilds these checklists from scratch (new column set after
    # a dataframe rebuild) - a column the user already unchecked must stay
    # unchecked, not silently revert to checked, or "Recalculate" becomes
    # indistinguishable from "reset my selection".
    gui = GUIManager()
    gui.set_analysis_columns(["r1", "r2"], ["m1", "m2"])

    gui.results_checklist_box.children[1].value = False  # uncheck r2
    gui.metadata_checklist_box.children[0].value = False  # uncheck m1

    gui.set_analysis_columns(["r1", "r2"], ["m1", "m2"])

    assert gui.get_checked_results_columns() == ["r1"]
    assert gui.get_checked_metadata_columns() == ["m2"]


def test_download_output_widgets_are_distinct_per_tab():
    # Regression guard: a single Output() widget instance placed in multiple
    # tabs gets one live DOM view per tab under Voila (every tab stays
    # mounted, just hidden) - the Javascript that triggers a browser download
    # then fires once per view, i.e. the file downloads once per tab the
    # widget appears in, all at once. Each download button needs its own
    # dedicated Output.
    gui = GUIManager()
    outputs = [
        gui.download_output,
        gui.correlation_download_output,
        gui.rf_download_output,
        gui.bo_download_output,
    ]
    assert len(outputs) == len({id(o) for o in outputs})


def test_set_analysis_columns_defaults_new_columns_to_checked():
    gui = GUIManager()
    gui.set_analysis_columns(["r1"], ["m1"])
    gui.results_checklist_box.children[0].value = False  # uncheck r1

    # r2/m2 are new (e.g. after a batch reload) - only r1 has a prior choice.
    gui.set_analysis_columns(["r1", "r2"], ["m1", "m2"])

    assert gui.get_checked_results_columns() == ["r2"]
    assert gui.get_checked_metadata_columns() == ["m1", "m2"]


def test_results_tree_has_one_static_group_per_schema_jv_first():
    gui = GUIManager()
    gui.set_analysis_columns(
        ["tracking_time", "efficiency", "fill_factor"],
        ["m1"],
        results_groups={
            "tracking_time": "MPP Tracking",
            "efficiency": "JV",
            "fill_factor": "JV",
        },
    )

    branches = gui.results_tree_box.children
    # Plain headings (not accordions), so nothing can be collapsed.
    assert [type(b.children[0]).__name__ for b in branches] == ["HTML", "HTML"]
    assert "JV" in branches[0].children[0].value
    assert "MPP Tracking" in branches[1].children[0].value
    # Branch checkboxes are the same widgets read by get_checked_results_columns.
    assert sorted(gui.get_checked_results_columns()) == [
        "efficiency",
        "fill_factor",
        "tracking_time",
    ]


def test_results_tree_select_all_toggles_branch():
    gui = GUIManager()
    gui.set_analysis_columns(["a", "b", "c"], [], results_groups={"a": "JV", "b": "JV", "c": "EQE"})
    jv_branch = next(b for b in gui.results_tree_box.children if "JV" in b.children[0].value)
    jv_branch.children[1].value = False  # "Select all" off

    assert gui.get_checked_results_columns() == ["c"]


def test_merged_result_column_names_suffixes_only_overlapping_columns():
    names = merged_result_column_names(
        ["sample_id", "datetime", "efficiency"],
        ["sample_id", "datetime", "power"],
        "mpp_tracking",
    )
    assert names == {"datetime": "datetime_mpp_tracking", "power": "power"}
    assert result_type_label("mpp_tracking") == "MPP Tracking"


def test_set_layer_selectors_creates_one_dropdown_per_source():
    gui = GUIManager()
    gui.set_layer_selectors({"spin_coating": ["Active Layer", "ETL"], "slot_die_coating": ["HTL"]})

    assert len(gui.layer_selector_box.children) == 2
    assert gui.get_layer_selections() == {"spin_coating": "Active Layer", "slot_die_coating": "HTL"}


def test_set_layer_selectors_empty_input_clears_dropdowns():
    gui = GUIManager()
    gui.set_layer_selectors({"spin_coating": ["Active Layer", "ETL"]})

    gui.set_layer_selectors({})

    assert gui.layer_selector_box.children == ()
    assert gui.get_layer_selections() == {}


def test_set_layer_selectors_preserves_choice_across_rebuild():
    gui = GUIManager()
    gui.set_layer_selectors({"spin_coating": ["Active Layer", "ETL"]})
    gui.layer_selector_box.children[0].value = "ETL"

    gui.set_layer_selectors({"spin_coating": ["Active Layer", "ETL"]})

    assert gui.get_layer_selections() == {"spin_coating": "ETL"}


def test_set_layer_selectors_resets_to_first_option_when_choice_no_longer_valid():
    gui = GUIManager()
    gui.set_layer_selectors({"spin_coating": ["Active Layer", "ETL"]})
    gui.layer_selector_box.children[0].value = "ETL"

    # ETL no longer present after a batch reload - falls back to first option.
    gui.set_layer_selectors({"spin_coating": ["Active Layer", "HTL"]})

    assert gui.get_layer_selections() == {"spin_coating": "Active Layer"}


def test_set_sample_exclusion_checklist_all_checked_by_default():
    gui = GUIManager()
    gui.set_sample_exclusion_checklist(["S1", "S2", "S3"], on_toggle=lambda _change: None)

    assert len(gui.sample_exclusion_checklist_box.children) == 3
    assert gui.get_excluded_sample_ids() == set()


def test_set_sample_exclusion_checklist_unchecked_sample_is_excluded():
    gui = GUIManager()
    gui.set_sample_exclusion_checklist(["S1", "S2"], on_toggle=lambda _change: None)

    gui.sample_exclusion_checklist_box.children[0].value = False

    assert gui.get_excluded_sample_ids() == {"S1"}


def test_set_sample_exclusion_checklist_preserves_exclusion_across_rebuild():
    gui = GUIManager()
    gui.set_sample_exclusion_checklist(["S1", "S2"], on_toggle=lambda _change: None)
    gui.sample_exclusion_checklist_box.children[0].value = False  # exclude S1

    # A Recalculate/layer-selection change rebuilds the list - S1 must stay excluded.
    gui.set_sample_exclusion_checklist(["S1", "S2", "S3"], on_toggle=lambda _change: None)

    assert gui.get_excluded_sample_ids() == {"S1"}


def test_set_sample_exclusion_checklist_toggle_invokes_callback():
    gui = GUIManager()
    calls = []
    gui.set_sample_exclusion_checklist(["S1"], on_toggle=lambda change: calls.append(change))

    gui.sample_exclusion_checklist_box.children[0].value = False

    assert len(calls) == 1


def test_set_analysis_columns_populates_filter_column_dropdown():
    gui = GUIManager()
    gui.set_analysis_columns(["r1", "r2"], ["m1"])
    assert [value for _label, value in gui.filter_column_selector.options] == ["m1", "r1", "r2"]


def test_filter_column_dropdown_labels_columns_with_their_schema():
    gui = GUIManager()
    gui.set_analysis_columns(
        ["efficiency", "plain"],
        ["annealing_temperature"],
        results_groups={"efficiency": "JV"},
        metadata_groups={"annealing_temperature": "Spin Coating"},
    )

    options = dict(gui.filter_column_selector.options)
    assert options["annealing_temperature (Spin Coating)"] == "annealing_temperature"
    assert options["efficiency (JV)"] == "efficiency"
    assert "plain" in options
    # Filters keep working on the bare column name.
    gui.filter_column_selector.value = "efficiency"
    gui.render_active_filters(
        [{"id": 1, "column": "efficiency", "op": ">=", "value": 5.0}], on_remove=lambda _id: None
    )
    assert "efficiency (JV) &gt;=" in gui.active_filters_box.children[0].children[0].value or (
        "efficiency (JV) >=" in gui.active_filters_box.children[0].children[0].value
    )


def test_process_type_label():
    assert process_type_label("spin_coating") == "Spin Coating"
    assert process_type_label("ald") == "ALD"


def test_render_active_filters_shows_placeholder_when_none_active():
    gui = GUIManager()
    gui.render_active_filters([], on_remove=lambda _fid: None)
    assert len(gui.active_filters_box.children) == 1
    assert "No filters active" in gui.active_filters_box.children[0].value


def test_render_active_filters_renders_one_row_per_filter():
    gui = GUIManager()
    row_filters = [
        {"id": 1, "column": "fill_factor", "op": ">=", "value": 0.3},
        {"id": 2, "column": "voc", "op": "<", "value": 1.2},
    ]
    gui.render_active_filters(row_filters, on_remove=lambda _fid: None)
    assert len(gui.active_filters_box.children) == 2


def test_render_active_filters_remove_button_calls_on_remove_with_correct_id():
    gui = GUIManager()
    removed_ids = []
    row_filters = [
        {"id": 1, "column": "fill_factor", "op": ">=", "value": 0.3},
        {"id": 2, "column": "voc", "op": "<", "value": 1.2},
    ]
    gui.render_active_filters(row_filters, on_remove=removed_ids.append)

    remove_button = gui.active_filters_box.children[1].children[1]
    remove_button.click()

    assert removed_ids == [2]


def test_load_all_data_for_summary_attaches_batch_column(monkeypatch):
    dm = DataManager(data_loader=None, param_manager=ParameterManager())

    def fake_spin_coating(sample_ids, variation):
        return pd.DataFrame(
            {
                "sample_id": ["HZB_FiNa_1_3_C-1"],
                "variation": [variation.get("HZB_FiNa_1_3_C-1", "")],
            }
        )

    dm.data_loader = type(
        "FakeLoader",
        (),
        {
            "url": "http://example.test",
            "token": "token",
            "load_inkjet_printing_data": staticmethod(lambda *a, **k: None),
            "load_cleaning_data": staticmethod(lambda *a, **k: None),
            "load_substrate_data": staticmethod(lambda *a, **k: None),
            "load_evaporation_data": staticmethod(lambda *a, **k: None),
            "load_slot_die_coating_data": staticmethod(lambda *a, **k: None),
            "load_spin_coating_data": staticmethod(fake_spin_coating),
            "load_ald_data": staticmethod(lambda *a, **k: None),
            "load_blade_coating_data": staticmethod(lambda *a, **k: None),
            "load_dip_coating_data": staticmethod(lambda *a, **k: None),
            "load_laser_scribing_data": staticmethod(lambda *a, **k: None),
            "load_annealing_data": staticmethod(lambda *a, **k: None),
        },
    )()

    monkeypatch.setattr("data_manager.get_all_eqe", lambda *a, **k: None, raising=False)

    dm.load_all_data_for_summary(["HZB_FiNa_1_3_C-1"], {"HZB_FiNa_1_3_C-1": "v1"})

    assert dm.current_metadata["spin_coating"].loc[0, "batch"] == "HZB_FiNa_1_3"


def test_build_parameter_summary_markdown_excludes_batch_column():
    """ "batch" is a derived subbatch label (extract_subbatch), not a real
    process parameter - it never feeds Correlation/RF/BO (string, not
    numeric) and should not clutter the Parameter Summary tables either,
    even when it varies (e.g. a load spanning more than one subbatch)."""
    dm = DataManager(data_loader=None, param_manager=ParameterManager())
    dm.current_metadata = {
        "spin_coating": pd.DataFrame(
            {
                "sample_id": ["S1", "S2"],
                "batch": ["HZB_JJ_19_", "HZB_JJ_19_ns_"],
                "annealing_temperature": [40.0, 50.0],
            }
        )
    }

    markdown = dm.build_parameter_summary_markdown()

    assert "annealing_temperature" in markdown
    assert "batch" not in markdown


def test_load_all_data_for_summary_keeps_every_entry_per_sample(monkeypatch):
    """Regression test for issue #34: a sample re-measured more than once for
    the same result type (e.g. JV measured on two different dates) must keep
    every entry, not just the first."""
    dm = DataManager(data_loader=None, param_manager=ParameterManager())
    dm.data_loader = type(
        "FakeLoader",
        (),
        {
            "url": "http://example.test",
            "token": "token",
            "load_inkjet_printing_data": staticmethod(lambda *a, **k: None),
            "load_cleaning_data": staticmethod(lambda *a, **k: None),
            "load_substrate_data": staticmethod(lambda *a, **k: None),
            "load_evaporation_data": staticmethod(lambda *a, **k: None),
            "load_slot_die_coating_data": staticmethod(lambda *a, **k: None),
            "load_spin_coating_data": staticmethod(lambda *a, **k: None),
            "load_ald_data": staticmethod(lambda *a, **k: None),
            "load_blade_coating_data": staticmethod(lambda *a, **k: None),
            "load_dip_coating_data": staticmethod(lambda *a, **k: None),
            "load_laser_scribing_data": staticmethod(lambda *a, **k: None),
            "load_annealing_data": staticmethod(lambda *a, **k: None),
        },
    )()

    def fake_get_all_eqe(url, token, sample_ids, measurement_type):
        if measurement_type != "HySprint_JVmeasurement":
            return None
        first_measurement = {"jv_curve": [{"fill_factor": 0.5}], "datetime": "2024-01-01"}
        second_measurement = {"jv_curve": [{"fill_factor": 0.8}], "datetime": "2024-02-01"}
        return {"S1": [(first_measurement, {}), (second_measurement, {})]}

    monkeypatch.setattr("data_manager.get_all_eqe", fake_get_all_eqe, raising=False)

    dm.load_all_data_for_summary(["S1"], {"S1": ""})

    jv_df = dm.current_results["jv_measurement"]
    assert len(jv_df) == 2
    assert set(jv_df["fill_factor"]) == {0.5, 0.8}
    assert (jv_df["sample_id"] == "S1").all()


def test_get_uploads_path_derives_from_cwd(monkeypatch):
    monkeypatch.setattr(
        "os.getcwd",
        lambda: "/home/jovyan/uploads/upload123/apps/Global_analyzer",
    )

    assert get_uploads_path() == "uploads/upload123/apps"


def test_build_doe_voila_url_includes_user_and_uploads_path():
    url = build_doe_voila_url("jdoe", "uploads/upload123/apps")

    assert url == (
        "/nomad-oasis/north/user/jdoe/voila/voila/render/"
        "uploads/upload123/apps/DesignOfExperiments/DoE.ipynb"
    )


def test_bin_numeric_column_produces_requested_bin_count():
    series = pd.Series([1.0, 5.0, 10.0, 50.0, 100.0])

    binned = bin_numeric_column(series, n_bins=4)

    assert binned.dropna().nunique() <= 4
    assert binned.cat.ordered is True


def test_bin_numeric_column_preserves_numeric_order_not_alphabetical():
    # 0-100 in 10 bins produces labels like "0 to 10", "10 to 20", ..., "90 to 100" -
    # a plain string sort would put "10 to 20" before "0 to 10".
    series = pd.Series(range(0, 101, 10), dtype=float)

    binned = bin_numeric_column(series, n_bins=10)
    categories = list(binned.cat.categories)

    numeric_starts = [float(label.split(" to ")[0]) for label in categories]
    assert numeric_starts == sorted(numeric_starts)


def test_bin_numeric_column_keeps_nan_as_nan():
    series = pd.Series([1.0, float("nan"), 3.0])

    binned = bin_numeric_column(series, n_bins=2)

    assert pd.isna(binned.iloc[1])


def test_create_box_plot_with_bin_count_creates_one_trace_per_bin_in_order():
    pmgr = _plot_manager()
    df = pd.DataFrame(
        {
            "sample_id": ["s1", "s2", "s3", "s4"],
            "x": [1.0, 2.0, 90.0, 95.0],
            "y": [10, 20, 30, 40],
        }
    )

    pmgr.create_box_plot(df, "x", "y", None, "X Label", "Y Label", bin_count=2)

    assert len(pmgr.plot_widget.data) == 2
    names = [trace.name for trace in pmgr.plot_widget.data]
    first_start = float(names[0].split(" to ")[0])
    second_start = float(names[1].split(" to ")[0])
    assert first_start < second_start


def test_parse_uploaded_analysis_csv_keeps_existing_sample_id():
    csv_bytes = b"sample_id,rise_pct,hydration_pct\nS1,120.0,75\nS2,140.0,80\n"

    df = parse_uploaded_analysis_csv(csv_bytes)

    assert list(df["sample_id"]) == ["S1", "S2"]
    assert list(df.columns) == ["sample_id", "rise_pct", "hydration_pct"]


def test_parse_uploaded_analysis_csv_generates_sample_id_when_missing():
    csv_bytes = b"rise_pct,hydration_pct\n120.0,75\n140.0,80\n"

    df = parse_uploaded_analysis_csv(csv_bytes)

    assert list(df["sample_id"]) == ["row_1", "row_2"]
    assert list(df.columns) == ["sample_id", "rise_pct", "hydration_pct"]


def test_uploaded_numeric_columns_skips_sample_id_text_and_constant_columns():
    df = pd.DataFrame(
        {
            "sample_id": [1, 2, 3],
            "temp": [100, 120, 140],
            "constant": [5, 5, 5],
            "material": ["a", "b", "a"],
            "pce": [15.0, 17.5, 16.0],
        }
    )

    assert uploaded_numeric_columns(df) == ["temp", "pce"]


def _bo_dataset():
    rng = np.random.default_rng(0)
    x1 = rng.uniform(0, 10, 20)
    x2 = rng.uniform(100, 200, 20)
    return pd.DataFrame({"x1": x1, "x2": x2, "y": -((x1 - 6) ** 2) - ((x2 - 150) / 10) ** 2})


@pytest.mark.parametrize("n_suggestions", [1, 3, 8])
def test_suggest_next_experiments_returns_requested_number_of_distinct_points(n_suggestions):
    result = suggest_next_experiments(
        _bo_dataset(), "y", feature_cols=["x1", "x2"], n_suggestions=n_suggestions
    )

    suggestions = result["suggestions"]
    assert len(suggestions) == n_suggestions
    assert len(suggestions[["x1", "x2"]].drop_duplicates()) == n_suggestions


def test_suggest_next_experiments_first_pick_is_the_single_step_bo_choice():
    df = _bo_dataset()
    single = suggest_next_experiments(df, "y", feature_cols=["x1", "x2"], n_suggestions=1)
    batch = suggest_next_experiments(df, "y", feature_cols=["x1", "x2"], n_suggestions=5)

    pd.testing.assert_series_equal(
        single["suggestions"].iloc[0], batch["suggestions"].iloc[0], check_names=False
    )


def test_suggest_next_experiments_batch_spreads_out_instead_of_clustering():
    # Kriging Believer should push later picks away from the first one; plain
    # top-N-by-EI returns near-duplicates of the single best candidate.
    result = suggest_next_experiments(
        _bo_dataset(), "y", feature_cols=["x1", "x2"], n_suggestions=5
    )
    points = result["suggestions"][["x1", "x2"]].to_numpy()
    scaled = (points - points.min(axis=0)) / (np.ptp(points, axis=0) + 1e-12)
    distances = np.linalg.norm(scaled[:, None, :] - scaled[None, :, :], axis=-1)
    assert distances[np.triu_indices(5, k=1)].min() > 0.05


def test_suggest_next_experiments_rejects_out_of_range_suggestion_count():
    with pytest.raises(ValueError):
        suggest_next_experiments(_bo_dataset(), "y", feature_cols=["x1", "x2"], n_suggestions=0)
    with pytest.raises(ValueError):
        suggest_next_experiments(_bo_dataset(), "y", feature_cols=["x1", "x2"], n_suggestions=21)


def _noisy_bo_dataset():
    # Integer "starts" (1-3), two continuous params, one irrelevant param, and
    # replicate scatter (SD 1) comparable to the effect size - the regime where
    # a near-noiseless GP or a noisy batch method collapses onto one point.
    # Length scales fitted from 60 noisy points are themselves uncertain: with
    # other seeds (e.g. 3) the sampled data happens to hide the gap effect and
    # the fit reasonably reports it as undetectable.
    rng = np.random.default_rng(0)
    n = 60
    starts = rng.integers(1, 4, n)
    gap = rng.uniform(0.6, 2.0, n)
    width = rng.uniform(0.9, 2.0, n)
    irrelevant = rng.uniform(0, 1, n)
    signal = 4 - 1.5 * (starts - 1) - 6 * (gap - 1.3) ** 2
    y = np.clip(signal + rng.normal(0, 1.0, n), 0, 4)
    return pd.DataFrame(
        {"starts": starts, "gap": gap, "width": width, "irrelevant": irrelevant, "y": y}
    )


_NOISY_FEATURES = ["starts", "gap", "width", "irrelevant"]


def test_detect_integer_columns_only_flags_whole_number_columns():
    df = pd.DataFrame(
        {"starts": [1, 2, 3, 2], "gap": [1.1, 1.5, 2.0, 0.9], "n": [1.0, 2.0, 2.0, 1.0]}
    )

    assert detect_integer_columns(df, ["starts", "gap", "n"]) == ["starts", "n"]


def test_suggest_next_experiments_respects_integer_bounds_and_fixed_values():
    result = suggest_next_experiments(
        _noisy_bo_dataset(),
        "y",
        feature_cols=_NOISY_FEATURES,
        n_suggestions=9,
        bounds={"starts": (1, 2), "gap": (1.1, 2.0), "width": (0.9, 1.5)},
        fixed={"irrelevant": 0.6},
    )

    s = result["suggestions"]
    assert result["integer_cols"] == ["starts"]
    assert set(s["starts"]) <= {1, 2}
    assert s["starts"].dtype.kind == "i"
    assert s["gap"].between(1.1, 2.0).all()
    assert s["width"].between(0.9, 1.5).all()
    assert (s["irrelevant"] == 0.6).all()


def test_suggest_next_experiments_uses_best_prediction_not_best_measurement_as_incumbent():
    result = suggest_next_experiments(
        _noisy_bo_dataset(), "y", feature_cols=_NOISY_FEATURES, n_suggestions=1
    )

    # The top measurement (4.0, the clipped scale maximum) is partly luck.
    assert result["best_observed"] == 4.0
    assert result["incumbent"] < result["best_observed"]


def test_suggest_next_experiments_learns_noise_and_ard_length_scales():
    result = suggest_next_experiments(
        _noisy_bo_dataset(), "y", feature_cols=_NOISY_FEATURES, n_suggestions=1
    )

    assert 0.4 < result["noise_sd"] < 1.6
    ls = result["length_scales"]
    assert ls["gap"] < ls["irrelevant"]
    assert ls["starts"] < ls["irrelevant"]


def test_suggest_next_experiments_noisy_batch_stays_diverse():
    # Regression test: with noise-carrying fake points, Kriging Believer barely
    # reduced uncertainty and returned 9 near-identical suggestions.
    bounds = {"starts": (1, 2), "gap": (1.1, 2.0), "width": (0.9, 1.5)}
    result = suggest_next_experiments(
        _noisy_bo_dataset(),
        "y",
        feature_cols=_NOISY_FEATURES,
        n_suggestions=9,
        bounds=bounds,
        fixed={"irrelevant": 0.5},
    )

    s = result["suggestions"]
    scaled = np.column_stack([(s[c] - lo) / (hi - lo) for c, (lo, hi) in bounds.items()])
    distances = np.linalg.norm(scaled[:, None, :] - scaled[None, :, :], axis=-1)
    assert distances[np.triu_indices(9, k=1)].min() > 0.1


def test_suggest_next_experiments_is_deterministic_for_a_fixed_seed():
    kwargs = dict(feature_cols=_NOISY_FEATURES, n_suggestions=4)
    first = suggest_next_experiments(_noisy_bo_dataset(), "y", **kwargs)["suggestions"]
    second = suggest_next_experiments(_noisy_bo_dataset(), "y", **kwargs)["suggestions"]

    pd.testing.assert_frame_equal(first, second)


def test_suggest_next_experiments_finds_optimum_of_branin_with_integer_offset():
    # Minimise Branin(x1, x2) + 2 * |k - 2| over k in {0..4}: global minimum
    # 0.398 at k = 2. Start from 10 random points, run 6 batches of 5. The
    # integer term is small next to Branin's range, so it needs a few rounds.
    def objective(frame):
        x1, x2, k = frame["x1"], frame["x2"], frame["k"]
        branin = (
            (x2 - 5.1 / (4 * np.pi**2) * x1**2 + 5 / np.pi * x1 - 6) ** 2
            + 10 * (1 - 1 / (8 * np.pi)) * np.cos(x1)
            + 10
        )
        return branin + 2 * (k - 2).abs()

    rng = np.random.default_rng(7)
    data = pd.DataFrame(
        {"x1": rng.uniform(-5, 10, 10), "x2": rng.uniform(0, 15, 10), "k": rng.integers(0, 5, 10)}
    )
    data["y"] = objective(data)
    bounds = {"x1": (-5, 10), "x2": (0, 15), "k": (0, 4)}
    for round_ in range(6):
        s = suggest_next_experiments(
            data,
            "y",
            feature_cols=["x1", "x2", "k"],
            direction="minimize",
            n_suggestions=5,
            bounds=bounds,
            integer_cols=["k"],
            random_state=round_,
        )["suggestions"][["x1", "x2", "k"]]
        s["y"] = objective(s)
        data = pd.concat([data, s], ignore_index=True)

    best = data.loc[data["y"].idxmin()]
    assert best["k"] == 2
    assert best["y"] < 1.0


def test_variation_warning_flags_low_variation_columns():
    df = pd.DataFrame(
        {
            "constant_ish": [1, 1, 1, 1, 1, 2],
            "varies_a_lot": [1, 2, 3, 4, 5, 6],
        }
    )

    flagged = variation_warning(df, ["constant_ish", "varies_a_lot"], min_unique=6)

    assert flagged == ["constant_ish"]


def test_variation_warning_ignores_columns_not_in_df():
    df = pd.DataFrame({"a": [1, 2, 3, 4, 5, 6]})

    flagged = variation_warning(df, ["a", "missing_col"], min_unique=6)

    assert flagged == []


def test_apply_row_filters_no_filters_returns_all_rows():
    df = pd.DataFrame({"fill_factor": [0.1, 0.5, 0.9]})

    result = apply_row_filters(df, [])

    assert len(result) == 3


def test_apply_row_filters_drops_rows_below_threshold():
    df = pd.DataFrame({"fill_factor": [0.1, 0.5, 0.9]})

    result = apply_row_filters(df, [{"column": "fill_factor", "op": ">=", "value": 0.3}])

    assert list(result["fill_factor"]) == [0.5, 0.9]


def test_apply_row_filters_combines_multiple_filters_with_and():
    df = pd.DataFrame({"fill_factor": [0.1, 0.5, 0.9], "voc": [0.0, 1.0, 1.3]})

    result = apply_row_filters(
        df,
        [
            {"column": "fill_factor", "op": ">=", "value": 0.3},
            {"column": "voc", "op": "<", "value": 1.2},
        ],
    )

    assert list(result["fill_factor"]) == [0.5]


def test_apply_row_filters_skips_filter_on_missing_column():
    df = pd.DataFrame({"fill_factor": [0.1, 0.5, 0.9]})

    result = apply_row_filters(df, [{"column": "not_a_column", "op": ">=", "value": 0.3}])

    assert len(result) == 3


def test_apply_row_filters_resets_index():
    df = pd.DataFrame({"fill_factor": [0.1, 0.5, 0.9]})

    result = apply_row_filters(df, [{"column": "fill_factor", "op": ">=", "value": 0.3}])

    assert list(result.index) == [0, 1]


def test_exclude_samples_drops_matching_sample_ids():
    df = pd.DataFrame({"sample_id": ["S1", "S2", "S3"], "fill_factor": [0.9, 0.0, 0.8]})

    result = exclude_samples(df, {"S2"})

    assert list(result["sample_id"]) == ["S1", "S3"]


def test_exclude_samples_drops_every_row_of_an_excluded_sample():
    """Unlike apply_row_filters, exclusion is by identity - a sample with
    several rows (e.g. "All Points" JV pixels) must lose all of them, not
    just the ones with unflattering values."""
    df = pd.DataFrame({"sample_id": ["S1", "S1", "S2"], "fill_factor": [0.9, 0.05, 0.8]})

    result = exclude_samples(df, {"S1"})

    assert list(result["sample_id"]) == ["S2"]


def test_exclude_samples_empty_set_returns_all_rows():
    df = pd.DataFrame({"sample_id": ["S1", "S2"], "fill_factor": [0.9, 0.8]})

    result = exclude_samples(df, set())

    assert len(result) == 2


def test_exclude_samples_resets_index():
    df = pd.DataFrame({"sample_id": ["S1", "S2", "S3"], "fill_factor": [0.9, 0.0, 0.8]})

    result = exclude_samples(df, {"S2"})

    assert list(result.index) == [0, 1]


def test_get_layer_type_options_flags_multi_layer_sources_only():
    metadata = {
        "spin_coating": pd.DataFrame(
            {"sample_id": ["S1", "S1"], "layer_type": ["ETL", "Active Layer"]}
        ),
        "cleaning": pd.DataFrame({"sample_id": ["S1"], "layer_type": ["Substrate"]}),
        "evaporation": pd.DataFrame({"sample_id": ["S1"]}),  # no layer_type column
    }

    options = get_layer_type_options(metadata)

    assert options == {"spin_coating": ["Active Layer", "ETL"]}


def test_select_layer_row_per_sample_keeps_only_matching_layer():
    df = pd.DataFrame(
        {
            "sample_id": ["S1", "S1", "S2"],
            "layer_type": ["ETL", "Active Layer", "Active Layer"],
            "annealing_temperature": [None, 50, 60],
        }
    )

    result = select_layer_row_per_sample(df, "Active Layer")

    assert list(result["sample_id"]) == ["S1", "S2"]
    assert list(result["annealing_temperature"]) == [50, 60]


def test_select_layer_row_per_sample_passes_through_single_layer_source():
    df = pd.DataFrame({"sample_id": ["S1", "S2"], "layer_type": ["Substrate", "Substrate"]})

    result = select_layer_row_per_sample(df, "irrelevant")

    assert len(result) == 2


def test_select_layer_row_per_sample_passes_through_no_layer_type_column():
    df = pd.DataFrame({"sample_id": ["S1", "S2"], "fill_factor": [0.5, 0.8]})

    result = select_layer_row_per_sample(df, "Active Layer")

    assert len(result) == 2


def test_aggregate_results_per_sample_mean_is_default():
    df = pd.DataFrame({"sample_id": ["S1", "S1"], "fill_factor": [0.2, 0.8]})

    result = aggregate_results_per_sample(df)

    assert result.loc[result["sample_id"] == "S1", "fill_factor"].iloc[0] == pytest.approx(0.5)


def test_aggregate_results_per_sample_median():
    df = pd.DataFrame({"sample_id": ["S1", "S1", "S1"], "fill_factor": [0.1, 0.5, 0.9]})

    result = aggregate_results_per_sample(df, method="Median")

    assert result.loc[result["sample_id"] == "S1", "fill_factor"].iloc[0] == pytest.approx(0.5)


def test_aggregate_results_per_sample_max():
    df = pd.DataFrame({"sample_id": ["S1", "S1"], "fill_factor": [0.2, 0.8]})

    result = aggregate_results_per_sample(df, method="Max")

    assert result.loc[result["sample_id"] == "S1", "fill_factor"].iloc[0] == pytest.approx(0.8)


def test_aggregate_results_per_sample_all_points_passes_through_unchanged():
    df = pd.DataFrame({"sample_id": ["S1", "S1", "S2"], "fill_factor": [0.2, 0.8, 0.5]})

    result = aggregate_results_per_sample(df, method="All Points")

    assert len(result) == 3
    assert list(result["fill_factor"]) == [0.2, 0.8, 0.5]


def test_get_categorical_columns_identifies_real_grouping_variables():
    df = pd.DataFrame(
        {
            "sample_id": ["S1", "S2", "S3", "S4"],
            "material": ["A", "A", "B", "B"],
            "constant": ["X", "X", "X", "X"],
            "all_unique": ["a", "b", "c", "d"],
        }
    )

    assert get_categorical_columns(df) == ["material"]


def test_get_categorical_columns_skips_unhashable_values_without_raising():
    """Regression test: raw JV voltage/current_density curve arrays pass
    through as their own object-dtype columns unaggregated when "All Points"
    is the chosen results-aggregation method. nunique() on a list-valued
    column raises TypeError (lists aren't hashable) - this must be skipped,
    not propagate and abort the whole Recalculate/ANOVA-selector refresh."""
    df = pd.DataFrame(
        {
            "sample_id": ["S1", "S2", "S3"],
            "material": ["A", "A", "B"],
            "voltage": [[1.0, 2.0], [3.0, 4.0], [5.0, 6.0]],
        }
    )

    assert get_categorical_columns(df) == ["material"]


def test_get_categorical_columns_excludes_custom_columns():
    df = pd.DataFrame(
        {
            "sample_id": ["S1", "S2", "S3"],
            "batch": ["b1", "b2", "b3"],
            "material": ["A", "A", "B"],
        }
    )

    assert get_categorical_columns(df, exclude=["sample_id", "batch"]) == ["material"]


def test_aggregate_results_per_sample_keeps_first_datetime():
    df = pd.DataFrame(
        {
            "sample_id": ["S1", "S1"],
            "fill_factor": [0.2, 0.8],
            "datetime": ["2024-01-01", "2024-01-02"],
        }
    )

    result = aggregate_results_per_sample(df)

    assert result.loc[result["sample_id"] == "S1", "datetime"].iloc[0] == "2024-01-01"


def test_variation_warning_empty_when_all_vary_enough():
    df = pd.DataFrame({"a": [1, 2, 3, 4, 5, 6, 7]})

    assert variation_warning(df, ["a"], min_unique=6) == []


def test_create_metadata_results_heatmap_returns_results_on_x_metadata_on_y():
    pmgr = PlotManager(
        plot_widget=go.FigureWidget(),
        stats_output=widgets.Output(),
        correlation_widget=go.FigureWidget(),
    )
    df = pd.DataFrame(
        {
            "efficiency": [1, 2, 3, 4, 5, 6, 7],
            "voc": [0.9, 1.0, 1.1, 1.2, 1.3, 1.4, 1.5],
            "annealing_temperature": [100, 110, 120, 130, 140, 150, 160],
        }
    )

    results_used, metadata_used = pmgr.create_metadata_results_heatmap(
        df,
        results_cols=["efficiency", "voc"],
        metadata_cols=["annealing_temperature"],
        min_unique=1,
    )

    assert results_used == ["efficiency", "voc"]
    assert metadata_used == ["annealing_temperature"]
    trace = pmgr.correlation_widget.data[0]
    assert list(trace.x) == ["efficiency", "voc"]
    assert list(trace.y) == ["annealing_temperature"]


def test_create_metadata_results_heatmap_empty_when_not_enough_variation():
    pmgr = PlotManager(
        plot_widget=go.FigureWidget(),
        stats_output=widgets.Output(),
        correlation_widget=go.FigureWidget(),
    )
    df = pd.DataFrame(
        {
            "efficiency": [1, 1, 1],
            "annealing_temperature": [100, 100, 100],
        }
    )

    results_used, metadata_used = pmgr.create_metadata_results_heatmap(
        df, results_cols=["efficiency"], metadata_cols=["annealing_temperature"], min_unique=5
    )

    assert results_used == []
    assert metadata_used == []


def test_estimate_max_bo_steps_scales_with_feature_count():
    fewer = estimate_max_bo_steps(2)
    more = estimate_max_bo_steps(5)

    assert more["suggested_max_steps"] > fewer["suggested_max_steps"]
    assert fewer["n_features"] == 2
    assert "2 parameter(s)" in fewer["rationale"]


def test_estimate_max_bo_steps_clamps_to_min_and_max():
    tiny = estimate_max_bo_steps(0, min_steps=10, max_steps=200)
    huge = estimate_max_bo_steps(1000, min_steps=10, max_steps=200)

    assert tiny["suggested_max_steps"] == 10
    assert huge["suggested_max_steps"] == 200


def test_trigger_csv_download_returns_filename_and_displays_js(monkeypatch):
    captured = {}
    monkeypatch.setattr(
        "utils.ipy_display", lambda js_obj: captured.setdefault("data", js_obj.data)
    )
    df = pd.DataFrame({"a": [1, 2], "b": [3, 4]})

    filename = trigger_csv_download(df, "my_export")

    assert filename.startswith("my_export_") and filename.endswith(".csv")
    assert "atob" in captured["data"]
    assert "download" in captured["data"]


def test_round_preserving_significance_keeps_integer_part_intact():
    # A plain fixed-decimal round would zero out anything smaller than
    # 0.0001 entirely - values under 1 need extra decimals to keep 4
    # significant digits instead. The integer part, however large, is
    # never touched (round() only ever rounds fractional digits).
    assert _round_preserving_significance(0.0000238798798) == "0.00002388"
    assert _round_preserving_significance(-0.0000238798798) == "-0.00002388"
    assert _round_preserving_significance(0.28971234) == 0.2897
    assert _round_preserving_significance(44.891234567) == 44.8912
    assert _round_preserving_significance(5897873.0) == 5897873.0
    assert _round_preserving_significance(9827340897234) == 9827340897234
    assert _round_preserving_significance(0) == 0.0
    nan_result = _round_preserving_significance(float("nan"))
    assert nan_result != nan_result  # nan != nan


def test_trigger_csv_download_rounds_floats_preserving_significance(monkeypatch):
    import base64

    captured = {}
    monkeypatch.setattr(
        "utils.ipy_display", lambda js_obj: captured.setdefault("data", js_obj.data)
    )
    df = pd.DataFrame(
        {
            "value": [44.891234567, 0.28971234, 5897873.0, 1.0 / 3, 0.0000238798798],
            "label": ["a", "b", "c", "d", "e"],
        }
    )

    trigger_csv_download(df, "my_export")

    b64 = captured["data"].split("atob('")[1].split("')")[0]
    csv_text = base64.b64decode(b64).decode()

    assert "44.8912" in csv_text
    assert "0.2897" in csv_text
    assert "5897873.0" in csv_text
    assert "0.3333" in csv_text
    assert "0.00002388" in csv_text
    # Never more than 4 digits after the decimal point for values >= 1, and
    # never scientific notation for the tiny value.
    assert "44.891234567" not in csv_text
    assert "0.3333333333333333" not in csv_text
    assert "e-05" not in csv_text


def test_run_pca_returns_scores_and_variance_ratio():
    df = pd.DataFrame(
        {
            "sample_id": [f"s{i}" for i in range(6)],
            "a": [1, 2, 3, 4, 5, 6],
            "b": [2, 4, 6, 8, 10, 12],
        }
    )

    result = run_pca(df, feature_cols=["a", "b"], n_components=2)

    assert result["n_samples"] == 6
    assert set(result["scores_df"].columns) == {"sample_id", "PC1", "PC2"}
    assert len(result["explained_variance_ratio"]) == 2
    assert sum(result["explained_variance_ratio"]) == pytest.approx(1.0, abs=1e-6)
    assert list(result["loadings_df"].columns) == ["a", "b"]


def test_run_pca_raises_when_fewer_than_two_varying_columns():
    df = pd.DataFrame({"a": [1, 2, 3, 4, 5], "constant": [1, 1, 1, 1, 1]})

    with pytest.raises(ValueError):
        run_pca(df, feature_cols=["a", "constant"])


def test_run_pca_raises_when_too_few_rows():
    df = pd.DataFrame({"a": [1, 2], "b": [3, 4]})

    with pytest.raises(ValueError):
        run_pca(df, feature_cols=["a", "b"])


def test_find_pareto_front_identifies_non_dominated_points():
    # (1,4) and (4,1) trade off, (3,3) trades off too - all three non-dominated.
    # (2,2) is dominated by (3,3) (>= in both, strictly greater in both).
    df = pd.DataFrame(
        {
            "sample_id": ["s1", "s2", "s3", "s4"],
            "efficiency": [1, 4, 2, 3],
            "stability": [4, 1, 2, 3],
        }
    )

    result = find_pareto_front(df, "efficiency", "stability")

    front_samples = set(
        result["result_df"].loc[result["result_df"]["is_pareto_optimal"], "sample_id"]
    )
    assert front_samples == {"s1", "s2", "s4"}
    assert result["n_on_front"] == 3


def test_find_pareto_front_invalid_direction_raises():
    df = pd.DataFrame({"a": [1, 2, 3], "b": [3, 2, 1]})

    with pytest.raises(ValueError):
        find_pareto_front(df, "a", "b", direction_a="sideways")


def test_find_pareto_front_raises_when_too_few_rows():
    df = pd.DataFrame({"a": [1], "b": [2]})

    with pytest.raises(ValueError):
        find_pareto_front(df, "a", "b")


def test_detect_outliers_flags_the_extreme_point():
    normal = pd.DataFrame({"x": range(9), "y": range(9)})
    outlier = pd.DataFrame({"x": [500], "y": [-500]})
    df = pd.concat([normal, outlier], ignore_index=True)
    df.insert(0, "sample_id", [f"s{i}" for i in range(10)])

    result = detect_outliers(df, feature_cols=["x", "y"], contamination=0.1)

    assert result["n_samples"] == 10
    most_anomalous = result["result_df"].iloc[0]
    assert most_anomalous["sample_id"] == "s9"
    assert most_anomalous["is_outlier"]


def test_detect_outliers_raises_when_too_few_rows():
    df = pd.DataFrame({"x": [1, 2, 3], "y": [1, 2, 3]})

    with pytest.raises(ValueError):
        detect_outliers(df, feature_cols=["x", "y"])


def test_compute_process_drift_detects_upward_trend():
    df = pd.DataFrame(
        {
            "sample_id": [f"s{i}" for i in range(6)],
            "datetime": pd.date_range("2026-01-01", periods=6, freq="D").astype(str),
            "annealing_temperature": [100, 110, 120, 130, 140, 150],
        }
    )

    result = compute_process_drift(df, "annealing_temperature")

    assert result["n_samples"] == 6
    assert result["slope"] > 0
    assert list(result["trend_df"]["annealing_temperature"]) == [100, 110, 120, 130, 140, 150]


def test_compute_process_drift_raises_when_column_missing():
    df = pd.DataFrame({"datetime": ["2026-01-01"], "x": [1]})

    with pytest.raises(ValueError):
        compute_process_drift(df, "missing_col")


def test_compute_process_drift_raises_when_too_few_valid_rows():
    df = pd.DataFrame({"datetime": ["not-a-date", "also-not-a-date"], "x": [1, 2]})

    with pytest.raises(ValueError):
        compute_process_drift(df, "x")


def test_run_anova_detects_significant_difference():
    df = pd.DataFrame(
        {
            "material": ["A", "A", "A", "B", "B", "B"],
            "efficiency": [10, 11, 10.5, 20, 21, 20.5],
        }
    )

    result = run_anova(df, "material", "efficiency")

    assert result["groups"] == {"A": 3, "B": 3}
    assert result["significant"] is True
    assert result["p_value"] < 0.05


def test_run_anova_raises_when_fewer_than_two_usable_groups():
    df = pd.DataFrame({"material": ["A", "A", "B"], "efficiency": [10, 11, 20]})

    with pytest.raises(ValueError):
        run_anova(df, "material", "efficiency")


# ---------------------------------------------------------------------------
# Issue #46: row duplication, per-sample counting, model validation
# ---------------------------------------------------------------------------


def _jv_and_eqe():
    jv = pd.DataFrame({"sample_id": ["s1"] * 4 + ["s2"] * 4, "efficiency": np.arange(8.0)})
    eqe = pd.DataFrame(
        {"sample_id": ["s1"] * 3 + ["s2"] * 3, "bandgap": [1.5, 1.6, 1.7, 1.4, 1.5, 1.6]}
    )
    return {"JV": jv, "EQE": eqe}


def test_merge_results_all_points_does_not_cross_pair_two_repeated_types():
    merged, collapsed = merge_results_per_sample(_jv_and_eqe(), "All Points")

    # 4 JV pixels per sample kept, EQE averaged: 8 rows, not 4 x 3 x 2 = 24.
    assert len(merged) == 8
    assert collapsed == ["EQE"]
    s1 = merged[merged["sample_id"] == "s1"]
    assert list(s1["efficiency"]) == [0.0, 1.0, 2.0, 3.0]
    assert np.allclose(s1["bandgap"], 1.6)


def test_merge_results_mean_collapses_everything_without_flagging():
    merged, collapsed = merge_results_per_sample(_jv_and_eqe(), "Mean")

    assert len(merged) == 2
    assert collapsed == []


def test_merge_results_all_points_with_one_repeated_type_collapses_nothing():
    results = _jv_and_eqe()
    results["EQE"] = results["EQE"].groupby("sample_id", as_index=False).mean()

    merged, collapsed = merge_results_per_sample(results, "All Points")

    assert len(merged) == 8
    assert collapsed == []


def test_merge_results_skips_empty_and_returns_none_when_nothing_usable():
    assert merge_results_per_sample({"JV": pd.DataFrame()}, "Mean") == (None, [])


def _rf_dataset(n_samples=30, pixels=1, seed=0):
    rng = np.random.default_rng(seed)
    temp = rng.uniform(100, 200, n_samples)
    noise_param = rng.uniform(0, 1, n_samples)
    rows = []
    for i in range(n_samples):
        for _ in range(pixels):
            rows.append(
                {
                    "sample_id": f"s{i}",
                    "temp": temp[i],
                    "noise_param": noise_param[i],
                    "pce": 0.1 * temp[i] + rng.normal(0, 0.5),
                }
            )
    return pd.DataFrame(rows)


def test_run_random_forest_reports_cross_validated_r2_and_ranks_real_effect_first():
    result = run_random_forest(_rf_dataset(), "pce", ["temp", "noise_param"])

    assert result["r2"] > 0.7
    assert result["n_samples"] == 30
    assert result["importances"][0][0] == "temp"
    name, mean, sd = result["importances"][1]
    assert name == "noise_param" and abs(mean) < 0.1 and sd >= 0


def test_run_random_forest_counts_samples_not_pixels():
    # 2 samples x 4 pixels used to pass the 8-row minimum.
    df = _rf_dataset(n_samples=2, pixels=4)

    with pytest.raises(ValueError, match="2 samples"):
        run_random_forest(df, "pce", ["temp"])


def test_run_random_forest_does_not_leak_pixels_of_one_sample_across_folds():
    # The target is a per-sample offset unrelated to the parameter, plus small
    # pixel scatter. A row-wise split predicts each pixel from its siblings and
    # scores a high R²; split by sample, there is nothing to learn.
    rng = np.random.default_rng(1)
    rows = []
    for i in range(20):
        param, offset = rng.uniform(0, 1), rng.normal(0, 5)
        for _ in range(6):
            rows.append({"sample_id": f"s{i}", "param": param, "pce": offset + rng.normal(0, 0.1)})
    df = pd.DataFrame(rows)

    result = run_random_forest(df, "pce", ["param"])

    assert result["n_samples"] == 20 and result["n_rows"] == 120
    assert result["r2"] < 0.2


def test_run_random_forest_reports_rows_lost_to_missing_values():
    df = _rf_dataset()
    df.loc[:9, "noise_param"] = np.nan

    result = run_random_forest(df, "pce", ["temp", "noise_param"])

    assert result["n_rows_with_target"] == 30
    assert result["n_rows"] == 20
    assert result["missing_by_column"] == {"noise_param": 10}


def test_run_random_forest_warns_below_recommended_sample_count():
    result = run_random_forest(_rf_dataset(n_samples=10), "pce", ["temp"])

    assert any("10 samples" in w for w in result["warnings"])


def test_suggest_next_experiments_counts_samples_not_pixels():
    df = pd.DataFrame(
        {
            "sample_id": np.repeat(["a", "b", "c"], 4),
            "x": np.repeat([1.0, 2.0, 3.0], 4),
            "y": np.arange(12.0),
        }
    )

    with pytest.raises(ValueError, match="3 samples"):
        suggest_next_experiments(df, "y", feature_cols=["x"])


def test_suggest_next_experiments_loo_r2_is_high_on_smooth_data_and_ranges_bracket_mean():
    result = suggest_next_experiments(_bo_dataset(), "y", feature_cols=["x1", "x2"])

    assert result["loo_r2"] > 0.8
    assert len(result["loo_df"]) == 20
    s = result["suggestions"]
    assert (s["predicted_low"] <= s["predicted_y"]).all()
    assert (s["predicted_y"] <= s["predicted_high"]).all()


def test_suggest_next_experiments_flags_pure_noise():
    rng = np.random.default_rng(3)
    df = pd.DataFrame({"x": rng.uniform(0, 1, 30), "y": rng.normal(0, 1, 30)})

    result = suggest_next_experiments(df, "y", feature_cols=["x"])

    assert result["loo_r2"] < 0.2
    assert any("Leave-one-sample-out" in w for w in result["warnings"])


def test_suggest_next_experiments_warns_with_few_samples_per_parameter():
    df = _bo_dataset().head(7)
    df["x3"] = np.linspace(0, 1, 7)

    result = suggest_next_experiments(df, "y", feature_cols=["x1", "x2", "x3"])

    assert any("free parameter" in w for w in result["warnings"])


def test_suggest_next_experiments_warns_when_data_spans_batches():
    df = _bo_dataset()
    df["batch"] = ["b1"] * 10 + ["b2"] * 10

    result = suggest_next_experiments(df, "y", feature_cols=["x1", "x2"])

    assert any("2 batches" in w for w in result["warnings"])


def test_suggest_next_experiments_log_target_back_transforms_predictions():
    rng = np.random.default_rng(5)
    x = rng.uniform(0, 4, 25)
    df = pd.DataFrame({"x": x, "current": 10.0 ** (-x) * rng.lognormal(0, 0.1, 25)})

    result = suggest_next_experiments(
        df, "current", feature_cols=["x"], direction="minimize", log_target=True
    )

    assert result["log_target"] is True
    assert result["loo_r2"] > 0.9
    s = result["suggestions"]
    assert (s["predicted_current"] > 0).all()
    # Pick #1 sits at the optimum; with near-noiseless data later picks have
    # ~zero EI and are arbitrary, so only the first is checked.
    assert s.loc[0, "x"] > 3.5
    assert s.loc[0, "predicted_current"] < 1e-3


def test_suggest_next_experiments_log_target_rejects_non_positive_values():
    df = _bo_dataset()

    with pytest.raises(ValueError, match="> 0"):
        suggest_next_experiments(df, "y", feature_cols=["x1", "x2"], log_target=True)


def test_find_pareto_front_tie_on_first_objective_keeps_only_the_better_point():
    df = pd.DataFrame({"a": [1.0, 1.0, 0.5], "b": [0.0, 1.0, 0.5]})

    flags = find_pareto_front(df, "a", "b")["result_df"]["is_pareto_optimal"].tolist()

    assert flags == [False, True, False]


def _pixel_metadata_df():
    rng = np.random.default_rng(0)
    return pd.DataFrame(
        {
            "sample_id": np.repeat([f"s{i}" for i in range(6)], 3),
            "p1": np.repeat(rng.normal(size=6), 3),
            "p2": np.repeat(rng.normal(size=6), 3),
            "eff": rng.normal(size=18),
        }
    )


def test_run_pca_counts_each_sample_once_and_returns_source_index():
    df = _pixel_metadata_df()

    result = run_pca(df, ["p1", "p2"])

    assert result["n_samples"] == 6
    assert len(result["source_index"]) == 6
    assert list(df.loc[result["source_index"], "sample_id"]) == list(
        result["scores_df"]["sample_id"]
    )


def test_outlier_flags_align_with_pca_points_when_sample_ids_repeat():
    df = _pixel_metadata_df()
    outliers = detect_outliers(df, ["p1", "p2", "eff"])
    pca = run_pca(outliers["result_df"], feature_cols=outliers["feature_cols"])

    flags = outliers["result_df"].loc[pca["source_index"], "is_outlier"]

    assert len(flags) == len(pca["scores_df"]) == 18


def test_run_anova_uses_per_sample_means():
    # 2 samples per group, 5 pixels each: 10 pixel rows per group, but only 2
    # independent observations.
    df = pd.DataFrame(
        {
            "sample_id": np.repeat(["a1", "a2", "b1", "b2"], 5),
            "material": np.repeat(["A", "A", "B", "B"], 5),
            "efficiency": np.repeat([10.0, 12.0, 11.0, 13.0], 5) + np.tile(np.arange(5) * 0.01, 4),
        }
    )

    result = run_anova(df, "material", "efficiency")

    assert result["groups"] == {"A": 2, "B": 2}
    assert result["p_value"] > 0.05


def test_compute_process_drift_uses_one_point_per_sample():
    df = pd.DataFrame(
        {
            "sample_id": np.repeat(["s1", "s2", "s3", "s4"], 3),
            "datetime": np.repeat(["2026-01-01", "2026-01-02", "2026-01-03", "2026-01-04"], 3),
            "temp": np.repeat([100.0, 110.0, 120.0, 130.0], 3),
        }
    )

    result = compute_process_drift(df, "temp")

    assert result["n_samples"] == 4
    assert result["slope"] == pytest.approx(10.0)


def test_create_bo_loo_plot_and_importance_plot_render():
    pmgr = PlotManager(
        plot_widget=go.FigureWidget(),
        stats_output=widgets.Output(),
        rf_widget=go.FigureWidget(),
        bo_widget=go.FigureWidget(),
        bo_loo_widget=go.FigureWidget(),
    )
    result = suggest_next_experiments(_bo_dataset(), "y", feature_cols=["x1", "x2"])

    pmgr.create_bo_loo_plot(result["loo_df"], "y", result["loo_r2"], False)
    pmgr.create_bo_suggestions_plot(result["suggestions"], "y")
    pmgr.create_feature_importance_plot([("temp", 0.5, 0.1), ("gap", 0.1, 0.05)], "pce")

    assert len(pmgr.bo_loo_widget.data[1].x) == 20
    assert list(pmgr.rf_widget.data[0].y) == ["gap", "temp"]


def test_merge_results_per_sample_fills_column_groups_with_merged_names():
    jv = pd.DataFrame({"sample_id": ["a", "b"], "efficiency": [1.0, 2.0], "datetime": ["x", "y"]})
    mpp = pd.DataFrame({"sample_id": ["a", "b"], "power": [3.0, 4.0], "datetime": ["x", "y"]})
    groups = {}

    merged, _ = merge_results_per_sample(
        {"jv_measurement": jv, "mpp_tracking": mpp}, "Mean", column_groups=groups
    )

    assert groups["efficiency"] == "JV"
    assert groups["power"] == "MPP Tracking"
    assert groups["datetime_mpp_tracking"] == "MPP Tracking"
    assert set(groups) == set(merged.columns) - {"sample_id"}


# ---------------------------------------------------------------------------
# Issue #48
# ---------------------------------------------------------------------------


def test_average_rows_per_sample_gives_one_row_per_sample():
    df = pd.DataFrame(
        {"sample_id": ["a", "a", "b"], "temp": [100, 100, 120], "pce": [10.0, 12.0, 15.0]}
    )

    out = average_rows_per_sample(df, ["temp", "pce"])

    assert list(out["sample_id"]) == ["a", "b"]
    assert list(out["pce"]) == [11.0, 15.0]


def test_average_rows_per_sample_passes_through_when_nothing_repeats():
    df = pd.DataFrame({"sample_id": ["a", "b"], "pce": [1.0, 2.0]})

    assert average_rows_per_sample(df, ["pce"]) is df


def test_is_measured_parameter_matches_base_name_and_merge_suffix():
    measured = {"relative_humidity"}

    assert is_measured_parameter("relative_humidity", measured)
    assert is_measured_parameter("relative_humidity_Inkjet Printing", measured)
    assert not is_measured_parameter("annealing_temperature", measured)


def test_bo_search_space_row_for_measured_parameter_starts_fixed_at_median():
    gui = GUIManager()
    gui.set_bo_search_space(
        [
            {"col": "temp", "min": 100.0, "max": 150.0, "integer": False},
            {
                "col": "relative_humidity",
                "min": 20.0,
                "max": 40.0,
                "integer": False,
                "measured": True,
                "median": 31.0,
            },
        ]
    )

    space = gui.get_bo_search_space()

    assert space["temp"]["fixed"] is None
    assert space["relative_humidity"]["fixed"] == 31.0


def _categorical_dataset(seed=0, n=40):
    rng = np.random.default_rng(seed)
    material = rng.choice(["A", "B", "C"], n)
    temp = rng.uniform(100, 200, n)
    offset = pd.Series(material).map({"A": 0.0, "B": 5.0, "C": 1.0}).to_numpy()
    pce = offset - ((temp - 150) / 25) ** 2 + rng.normal(0, 0.3, n)
    return pd.DataFrame(
        {"sample_id": [f"s{i}" for i in range(n)], "material": material, "temp": temp, "pce": pce}
    )


def test_run_random_forest_uses_categorical_parameter_and_its_partial_dependence():
    result = run_random_forest(
        _categorical_dataset(), "pce", ["temp"], categorical_cols=["material"]
    )

    assert result["importances"][0][0] == "material"
    pd_material = next(p for p in result["partial_dependence"] if p["feature"] == "material")
    assert pd_material["kind"] == "categorical"
    best = pd_material["grid"][int(np.argmax(pd_material["average"]))]
    assert best == "B"


def test_run_random_forest_drops_single_level_categorical_with_a_note():
    df = _categorical_dataset()
    df["lab"] = "HZB"

    result = run_random_forest(df, "pce", ["temp"], categorical_cols=["lab"])

    assert [name for name, _, _ in result["importances"]] == ["temp"]
    assert any("'lab' has a single value" in w for w in result["warnings"])


def test_run_random_forest_numeric_partial_dependence_follows_the_effect():
    result = run_random_forest(_rf_dataset(), "pce", ["temp", "noise_param"])

    temp_pd = next(p for p in result["partial_dependence"] if p["feature"] == "temp")
    assert temp_pd["kind"] == "numeric"
    assert temp_pd["average"][-1] > temp_pd["average"][0]


def test_run_random_forest_flags_strongly_correlated_parameters():
    df = _rf_dataset()
    df["temp_copy"] = df["temp"] * 2 + 1

    result = run_random_forest(df, "pce", ["temp", "temp_copy", "noise_param"])

    assert ("temp", "temp_copy") == result["correlated_pairs"][0][:2]
    assert any("Strongly correlated" in w for w in result["warnings"])


def test_suggest_next_experiments_picks_the_best_categorical_level():
    result = suggest_next_experiments(
        _categorical_dataset(),
        "pce",
        feature_cols=["temp"],
        categorical_cols=["material"],
        n_suggestions=1,
    )

    s = result["suggestions"]
    assert s.loc[0, "material"] == "B"
    assert 125 < s.loc[0, "temp"] < 175
    assert "material" in result["length_scales"]


def test_suggest_next_experiments_respects_fixed_categorical_level():
    result = suggest_next_experiments(
        _categorical_dataset(),
        "pce",
        feature_cols=["temp"],
        categorical_cols=["material"],
        fixed={"material": "A"},
        n_suggestions=3,
    )

    assert (result["suggestions"]["material"] == "A").all()


def test_suggest_next_experiments_rejects_unknown_fixed_level():
    with pytest.raises(ValueError, match="not a level"):
        suggest_next_experiments(
            _categorical_dataset(),
            "pce",
            feature_cols=["temp"],
            categorical_cols=["material"],
            fixed={"material": "Z"},
        )


def _batch_dataset(seed=0):
    # Four batches with large offsets on top of a smooth temp effect.
    rng = np.random.default_rng(seed)
    rows = []
    for b, offset in enumerate([0.0, 4.0, -3.0, 2.0]):
        for _ in range(8):
            temp = rng.uniform(100, 200)
            pce = 10 + offset - ((temp - 150) / 25) ** 2 + rng.normal(0, 0.2)
            rows.append({"batch": f"b{b}", "temp": temp, "pce": pce})
    df = pd.DataFrame(rows)
    df.insert(0, "sample_id", [f"s{i}" for i in range(len(df))])
    return df


def test_suggest_next_experiments_models_batch_offsets():
    df = _batch_dataset()

    with_batch = suggest_next_experiments(
        df, "pce", feature_cols=["temp"], batch_col="batch", n_suggestions=1
    )
    without = suggest_next_experiments(df, "pce", feature_cols=["temp"], n_suggestions=1)

    assert with_batch["n_batches"] == 4
    assert 1.5 < with_batch["batch_offset_sd"] < 6
    assert with_batch["loo_r2"] > without["loo_r2"]
    # The batch-free noise estimate is far below the batch-to-batch scatter.
    assert with_batch["noise_sd"] < without["noise_sd"]
    assert 135 < with_batch["suggestions"].loc[0, "temp"] < 165


def test_suggest_next_experiments_single_batch_is_not_modelled():
    df = _batch_dataset()
    df["batch"] = "only"

    result = suggest_next_experiments(df, "pce", feature_cols=["temp"], batch_col="batch")

    assert result["batch_col"] is None
    assert any("one 'batch' value" in w for w in result["warnings"])


def _constraint_dataset(seed=0, n=40):
    rng = np.random.default_rng(seed)
    x1, x2 = rng.uniform(0, 1, n), rng.uniform(0, 1, n)
    return pd.DataFrame(
        {
            "sample_id": [f"s{i}" for i in range(n)],
            "x1": x1,
            "x2": x2,
            "y": x1 + 0.2 * x2,
            "dark": x1 + x2 + rng.normal(0, 0.02, n),
        }
    )


def test_suggest_next_experiments_constraint_keeps_suggestions_feasible():
    result = suggest_next_experiments(
        _constraint_dataset(),
        "y",
        feature_cols=["x1", "x2"],
        n_suggestions=3,
        constraints=[{"col": "dark", "op": "<=", "value": 1.0}],
    )

    s = result["suggestions"]
    # Constrained optima sit on the boundary, so picks land close to it.
    assert (s["x1"] + s["x2"] < 1.15).all()
    # Later picks in the batch can be weakly motivated (near-zero score); the
    # first is the real constrained-BO choice.
    assert s.loc[0, "probability_feasible"] > 0.5
    # Unconstrained, the best is at x1 = x2 = 1 (dark ~2).
    assert s.loc[0, "x1"] > 0.6


def test_suggest_next_experiments_without_feasible_sample_aims_at_feasibility():
    result = suggest_next_experiments(
        _constraint_dataset(),
        "y",
        feature_cols=["x1", "x2"],
        n_suggestions=1,
        constraints=[{"col": "dark", "op": "<=", "value": -0.5}],
    )

    assert result["incumbent"] is None
    assert any("meet the constraints" in w for w in result["warnings"])
    s = result["suggestions"]
    assert s.loc[0, "x1"] + s.loc[0, "x2"] < 0.3


def test_suggest_next_experiments_rejects_constraint_on_target():
    with pytest.raises(ValueError, match="target itself"):
        suggest_next_experiments(
            _constraint_dataset(),
            "y",
            feature_cols=["x1"],
            constraints=[{"col": "y", "op": "<=", "value": 1}],
        )


def test_suggest_pareto_experiments_spreads_along_the_trade_off():
    # a prefers high x, b prefers low x: every x is Pareto-optimal.
    rng = np.random.default_rng(0)
    x = rng.uniform(0, 1, 25)
    df = pd.DataFrame({"sample_id": [f"s{i}" for i in range(25)], "x": x, "a": x, "b": 1 - x**2})

    result = suggest_pareto_experiments(
        df,
        [("a", "maximize"), ("b", "maximize")],
        n_suggestions=5,
        feature_cols=["x"],
    )

    s = result["suggestions"]
    assert len(s) == 5
    assert s["x"].max() - s["x"].min() > 0.4
    assert {"predicted_a", "predicted_b", "weight_a", "weight_b"} <= set(s.columns)
    # Picks that favour a (high weight_a) sit at higher x.
    assert s.sort_values("weight_a")["x"].iloc[-1] > s.sort_values("weight_a")["x"].iloc[0]


def test_suggest_pareto_experiments_needs_two_distinct_objectives():
    df = _bo_dataset()
    with pytest.raises(ValueError):
        suggest_pareto_experiments(df, [("y", "maximize")], feature_cols=["x1"])
    with pytest.raises(ValueError):
        suggest_pareto_experiments(df, [("y", "maximize"), ("y", "minimize")], feature_cols=["x1"])
