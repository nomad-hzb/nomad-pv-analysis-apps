import ipywidgets as widgets
import pandas as pd
import plotly.graph_objects as go
import pytest
from data_manager import DataManager, MeasurementRow
from plot_manager import PlotManager
from pydantic import ValidationError
from utils import ParameterManager, ProcessStepManager, get_material_column


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
