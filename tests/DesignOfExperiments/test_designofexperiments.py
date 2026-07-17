"""Tests for the Design of Experiments (DoE) application.

Covers DataManager, SamplingEngine, and PlotManager.
"""

import pandas as pd
import plotly.graph_objects as go
import pytest

from data_manager import DataManager, Variable, VariableType
from plot_manager import PlotManager
from sampling_algorithms import SamplingEngine


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _continuous(name="thickness", lo=10.0, hi=100.0):
    return Variable(name=name, type=VariableType.CONTINUOUS, min_value=lo, max_value=hi)


def _discrete(name="layers", lo=1.0, hi=5.0, step=1.0):
    return Variable(
        name=name, type=VariableType.DISCRETE, min_value=lo, max_value=hi, step_size=step
    )


def _categorical(name="solvent", cats=None):
    return Variable(
        name=name, type=VariableType.CATEGORICAL, categories=cats or ["DMF", "DMSO", "GBL"]
    )


# ---------------------------------------------------------------------------
# DataManager — add_variable
# ---------------------------------------------------------------------------


def test_add_continuous_variable_succeeds():
    dm = DataManager()
    ok, msg = dm.add_variable(_continuous())
    assert ok
    assert "thickness" in dm.get_variable_names()


def test_add_duplicate_variable_fails():
    dm = DataManager()
    dm.add_variable(_continuous())
    ok, msg = dm.add_variable(_continuous())
    assert not ok
    assert "already exists" in msg


def test_add_discrete_variable_succeeds():
    dm = DataManager()
    ok, _ = dm.add_variable(_discrete())
    assert ok


def test_add_categorical_variable_succeeds():
    dm = DataManager()
    ok, _ = dm.add_variable(_categorical())
    assert ok


# ---------------------------------------------------------------------------
# DataManager — remove_variable
# ---------------------------------------------------------------------------


def test_remove_variable_succeeds():
    dm = DataManager()
    dm.add_variable(_continuous())
    ok, _ = dm.remove_variable("thickness")
    assert ok
    assert dm.get_variable_names() == []


def test_remove_nonexistent_variable_fails():
    dm = DataManager()
    ok, msg = dm.remove_variable("no_such_var")
    assert not ok
    assert "not found" in msg


# ---------------------------------------------------------------------------
# DataManager — update_variable
# ---------------------------------------------------------------------------


def test_update_variable_succeeds():
    dm = DataManager()
    dm.add_variable(_continuous())
    updated = Variable(
        name="thickness", type=VariableType.CONTINUOUS, min_value=5.0, max_value=200.0
    )
    ok, _ = dm.update_variable("thickness", updated)
    assert ok
    assert dm.get_variable("thickness").max_value == 200.0


# ---------------------------------------------------------------------------
# DataManager — set_variables
# ---------------------------------------------------------------------------


def test_set_variables_from_list_of_dicts():
    dm = DataManager()
    var_dicts = [
        {"name": "x", "type": "continuous", "min_value": 0.0, "max_value": 1.0},
        {"name": "y", "type": "categorical", "categories": ["A", "B"]},
    ]
    ok, msg = dm.set_variables(var_dicts)
    assert ok
    assert len(dm.get_variables()) == 2


# ---------------------------------------------------------------------------
# DataManager — has_variables / clear_all_variables
# ---------------------------------------------------------------------------


def test_has_variables_true_after_adding():
    dm = DataManager()
    assert not dm.has_variables()
    dm.add_variable(_continuous())
    assert dm.has_variables()


def test_clear_all_variables_empties_list():
    dm = DataManager()
    dm.add_variable(_continuous())
    dm.clear_all_variables()
    assert not dm.has_variables()


# ---------------------------------------------------------------------------
# DataManager — parse_text_variables
# ---------------------------------------------------------------------------


def test_parse_text_continuous_variable():
    dm = DataManager()
    ok, msg, parsed = dm.parse_text_variables("thickness,continuous,10,100")
    assert ok
    assert len(parsed) == 1
    assert parsed[0]["type"] == "continuous"
    assert parsed[0]["min_value"] == 10.0


def test_parse_text_categorical_variable():
    dm = DataManager()
    ok, msg, parsed = dm.parse_text_variables("solvent,categorical,DMF,DMSO,GBL")
    assert ok
    assert parsed[0]["categories"] == ["DMF", "DMSO", "GBL"]


def test_parse_text_invalid_type_fails():
    dm = DataManager()
    ok, msg, parsed = dm.parse_text_variables("x,unknown,0,1")
    assert not ok


# ---------------------------------------------------------------------------
# DataManager — validate_sample_data
# ---------------------------------------------------------------------------


def test_validate_sample_data_valid():
    dm = DataManager()
    dm.add_variable(_continuous("x", 0.0, 10.0))
    df = pd.DataFrame({"x": [1.0, 5.0, 9.0]})
    ok, msg, info = dm.validate_sample_data(df)
    assert ok


def test_validate_sample_data_out_of_range():
    dm = DataManager()
    dm.add_variable(_continuous("x", 0.0, 10.0))
    df = pd.DataFrame({"x": [1.0, 15.0]})
    ok, msg, info = dm.validate_sample_data(df)
    assert not ok or info["variable_stats"]["x"]["out_of_range_count"] > 0


def test_validate_sample_data_missing_column():
    dm = DataManager()
    dm.add_variable(_continuous("x", 0.0, 10.0))
    df = pd.DataFrame({"y": [1.0, 2.0]})
    ok, msg, info = dm.validate_sample_data(df)
    assert not ok


# ---------------------------------------------------------------------------
# SamplingEngine
# ---------------------------------------------------------------------------


def test_lhs_produces_correct_shape():
    se = SamplingEngine()
    variables = [_continuous("x", 0.0, 1.0), _continuous("y", 0.0, 1.0)]
    df = se.generate_samples(variables, "Latin Hypercube Sampling", n_samples=10, random_state=42)
    assert df.shape == (10, 2)
    assert list(df.columns) == ["x", "y"]


def test_lhs_values_within_range():
    se = SamplingEngine()
    variables = [_continuous("x", 5.0, 10.0)]
    df = se.generate_samples(variables, "Latin Hypercube Sampling", n_samples=20, random_state=1)
    assert (df["x"] >= 5.0).all()
    assert (df["x"] <= 10.0).all()


def test_sobol_produces_correct_shape():
    se = SamplingEngine()
    variables = [_continuous("a", 0.0, 1.0), _continuous("b", 0.0, 1.0)]
    df = se.generate_samples(variables, "Sobol Sequences", n_samples=8, random_state=42)
    assert df.shape == (8, 2)


def test_random_sampling_produces_correct_shape():
    se = SamplingEngine()
    variables = [_continuous("t", 100.0, 500.0), _discrete("n", 1.0, 5.0, 1.0)]
    df = se.generate_samples(variables, "Random Sampling", n_samples=15, random_state=7)
    assert df.shape == (15, 2)


def test_sampling_with_seed_is_reproducible():
    se = SamplingEngine()
    variables = [_continuous("x", 0.0, 1.0), _continuous("y", 0.0, 1.0)]
    df1 = se.generate_samples(variables, "Latin Hypercube Sampling", n_samples=5, random_state=99)
    df2 = se.generate_samples(variables, "Latin Hypercube Sampling", n_samples=5, random_state=99)
    assert df1.equals(df2)


def test_no_experiment_id_column():
    se = SamplingEngine()
    variables = [_continuous("x", 0.0, 1.0)]
    df = se.generate_samples(variables, "Latin Hypercube Sampling", n_samples=5, random_state=1)
    assert "Experiment_ID" not in df.columns


# ---------------------------------------------------------------------------
# PlotManager
# ---------------------------------------------------------------------------


@pytest.fixture
def two_var_data():
    return pd.DataFrame({"x": [0.1, 0.5, 0.9], "y": [0.2, 0.6, 0.8]})


@pytest.fixture
def two_vars():
    return [_continuous("x", 0.0, 1.0), _continuous("y", 0.0, 1.0)]


def test_splom_returns_figure(two_var_data, two_vars):
    pm = PlotManager()
    fig = pm.create_plot("splom", two_var_data, two_vars)
    assert isinstance(fig, go.Figure)


def test_parallel_returns_figure(two_var_data, two_vars):
    pm = PlotManager()
    fig = pm.create_plot("parallel", two_var_data, two_vars)
    assert isinstance(fig, go.Figure)


def test_distributions_returns_figure(two_var_data, two_vars):
    pm = PlotManager()
    fig = pm.create_plot("distributions", two_var_data, two_vars)
    assert isinstance(fig, go.Figure)


def test_unknown_plot_type_returns_none(two_var_data, two_vars):
    pm = PlotManager()
    fig = pm.create_plot("not_a_real_type", two_var_data, two_vars)
    assert fig is None


def test_empty_data_returns_none(two_vars):
    pm = PlotManager()
    fig = pm.create_plot("splom", pd.DataFrame(), two_vars)
    assert fig is None
