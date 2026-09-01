import ipywidgets as widgets
import pandas as pd
import plotly.graph_objects as go
import pytest
from data_loader import HySprintDataLoader
from data_manager import DataManager, MeasurementRow, variation_warning
from experimental_analysis import (
    compute_process_drift,
    detect_outliers,
    find_pareto_front,
    run_anova,
    run_pca,
)
from ml_analysis import estimate_max_bo_steps
from plot_manager import PlotManager, bin_numeric_column
from pydantic import ValidationError
from utils import (
    ParameterManager,
    ProcessStepManager,
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
