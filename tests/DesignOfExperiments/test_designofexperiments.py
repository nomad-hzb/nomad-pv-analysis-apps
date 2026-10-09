"""Tests for the Design of Experiments (DoE) application.

Covers DataManager, SamplingEngine, and PlotManager.
"""

import itertools

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import pytest
from data_manager import DataManager, Variable, VariableType
from plot_manager import PlotManager
from sampling_algorithms import (
    SamplingEngine,
    conference_matrix,
    design_space,
    get_notes,
    maximin_selection,
    orthogonal_array,
)
from scipy.spatial.distance import pdist

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


# ---------------------------------------------------------------------------
# Issue #49: orthogonal arrays, DSD, log scale, balance, augment, run sheet
# ---------------------------------------------------------------------------


def _strength2(design: pd.DataFrame) -> bool:
    """Every pair of columns shows every level combination equally often."""
    for a, b in itertools.combinations(design.columns, 2):
        counts = design.groupby([a, b]).size()
        n_combos = design[a].nunique() * design[b].nunique()
        if len(counts) != n_combos or counts.nunique() != 1:
            return False
    return True


@pytest.mark.parametrize(
    ("p", "n_factors", "runs"), [(2, 3, 4), (2, 7, 8), (3, 4, 9), (3, 5, 27), (5, 6, 25)]
)
def test_orthogonal_array_is_strength_two_with_standard_size(p, n_factors, runs):
    array = orthogonal_array(p, n_factors)

    assert array.shape == (runs, n_factors)
    assert _strength2(pd.DataFrame(array))


def test_orthogonal_arrays_four_three_level_factors_gives_l9_not_random():
    # The old pyDOE2.gsd(levels, n_samples) call failed for this case and fell
    # back to 16 random points labelled as an orthogonal array.
    se = SamplingEngine()
    variables = [_discrete(f"x{i}", 1.0, 3.0, 1.0) for i in range(4)]

    df = se.generate_samples(variables, "Orthogonal Arrays", n_samples=16, random_state=1)

    assert len(df) == 9
    assert _strength2(df)
    assert any("9 runs" in note for note in get_notes(df))


def test_orthogonal_arrays_continuous_and_collapsed_levels():
    se = SamplingEngine()
    variables = [_continuous("t", 100.0, 200.0), _categorical("s", ["A", "B"])]

    df = se.generate_samples(
        variables, "Orthogonal Arrays", n_samples=10, random_state=1, continuous_levels=3
    )

    assert sorted(df["t"].unique()) == [100.0, 150.0, 200.0]
    assert set(df["s"]) == {"A", "B"}
    assert any("collapsed" in note for note in get_notes(df))


def test_orthogonal_arrays_reject_too_many_levels_instead_of_random_fallback():
    se = SamplingEngine()
    variables = [_discrete("n", 1.0, 9.0, 1.0)]

    with pytest.raises(ValueError, match="up to 7 levels"):
        se.generate_samples(variables, "Orthogonal Arrays", n_samples=9, random_state=1)


@pytest.mark.parametrize("order", [4, 6, 8, 12, 14, 18, 20, 24])
def test_conference_matrix_is_orthogonal(order):
    C = conference_matrix(order)

    assert (np.diag(C) == 0).all()
    assert np.array_equal(C @ C.T, (order - 1) * np.eye(order, dtype=int))


def test_definitive_screening_design_shape_levels_and_orthogonal_main_effects():
    se = SamplingEngine()
    variables = [_continuous(f"x{i}", 0.0, 10.0) for i in range(6)]

    df = se.generate_samples(variables, "Definitive Screening Design", n_samples=5, random_state=1)

    assert len(df) == 13  # 2 x 6 + 1
    coded = (df.to_numpy(dtype=float) - 5.0) / 5.0
    assert set(np.unique(coded)) == {-1.0, 0.0, 1.0}
    # Main-effect columns are mutually orthogonal.
    gram = coded.T @ coded
    assert np.allclose(gram - np.diag(np.diag(gram)), 0)


def test_definitive_screening_design_rejects_categorical():
    se = SamplingEngine()
    with pytest.raises(ValueError, match="numeric variables"):
        se.generate_samples(
            [_continuous("x"), _categorical()], "Definitive Screening Design", n_samples=5
        )


def test_log_scale_spreads_points_evenly_over_decades():
    se = SamplingEngine()
    load = Variable(
        name="load", type=VariableType.CONTINUOUS, min_value=1.0, max_value=1000.0, log_scale=True
    )

    df = se.generate_samples([load], "Latin Hypercube Sampling", n_samples=30, random_state=3)

    decades = np.floor(np.log10(df["load"])).value_counts()
    assert list(decades.sort_index()) == [10, 10, 10]


def test_log_scale_needs_positive_continuous_range():
    assert not Variable(
        name="x", type=VariableType.CONTINUOUS, min_value=0.0, max_value=1.0, log_scale=True
    ).validate()[0]
    assert not Variable(
        name="x",
        type=VariableType.DISCRETE,
        min_value=1.0,
        max_value=5.0,
        step_size=1.0,
        log_scale=True,
    ).validate()[0]


def test_log_scale_round_trips_through_dict():
    var = Variable(
        name="t", type=VariableType.CONTINUOUS, min_value=1.0, max_value=100.0, log_scale=True
    )

    assert Variable.from_dict(var.to_dict()).log_scale is True


def test_lhs_balances_categorical_levels():
    se = SamplingEngine()

    for seed in range(5):
        df = se.generate_samples(
            [_continuous("x"), _categorical()], "Latin Hypercube Sampling", 10, seed
        )
        counts = df["solvent"].value_counts()
        assert counts.max() - counts.min() <= 1
        assert len(counts) == 3


def test_grid_subsampling_is_reported():
    se = SamplingEngine()

    df = se.generate_samples(
        [_continuous("x"), _continuous("y")], "Uniform Grid Sampling", 10, random_state=1
    )

    assert len(df) == 10
    assert any("no longer a regular grid" in note for note in get_notes(df))


def test_sobol_non_power_of_two_is_reported():
    se = SamplingEngine()

    df = se.generate_samples([_continuous("x")], "Sobol Sequences", 10, random_state=1)

    assert any("power-of-2" in note for note in get_notes(df))


def test_design_space_treats_categories_as_equally_different():
    variables = [_categorical()]
    df = pd.DataFrame({"solvent": ["DMF", "DMSO", "GBL"]})

    points = design_space(df, variables)

    assert np.allclose(pdist(points), 1.0)


def test_maximin_selection_spreads_points_and_respects_fixed_ones():
    grid = np.array([[x, y] for x in np.linspace(0, 1, 11) for y in np.linspace(0, 1, 11)])

    picked = maximin_selection(grid, 4, random_state=0)
    assert pdist(grid[picked]).min() > 0.9  # the four corners

    fixed = np.array([[0.0, 0.0], [1.0, 1.0]])
    picked = maximin_selection(grid, 2, random_state=0, fixed=fixed)
    chosen = {tuple(np.round(p, 1)) for p in grid[picked]}
    assert chosen == {(0.0, 1.0), (1.0, 0.0)}


def test_augment_adds_runs_away_from_existing_design():
    se = SamplingEngine()
    variables = [_continuous("x", 0.0, 1.0), _continuous("y", 0.0, 1.0)]
    existing = pd.DataFrame({"x": [0.0, 0.0, 1.0, 1.0], "y": [0.0, 1.0, 0.0, 1.0], "pce": 1})

    df = se.generate_samples(
        variables, "Augment Existing Design", n_samples=1, random_state=0, existing=existing
    )

    assert len(df) == 1
    assert abs(df.loc[0, "x"] - 0.5) < 0.15 and abs(df.loc[0, "y"] - 0.5) < 0.15


def test_augment_requires_existing_design_with_matching_columns():
    se = SamplingEngine()
    with pytest.raises(ValueError, match="Upload the existing design"):
        se.generate_samples([_continuous("x")], "Augment Existing Design", 2)
    with pytest.raises(ValueError, match="no column for"):
        se.generate_samples(
            [_continuous("x")], "Augment Existing Design", 2, existing=pd.DataFrame({"y": [1]})
        )


def test_finalize_design_defaults_leave_design_unchanged():
    se = SamplingEngine()
    variables = [_continuous("x")]
    design = se.generate_samples(variables, "Latin Hypercube Sampling", 5, random_state=1)

    out = se.finalize_design(design, variables)

    assert list(out.columns) == ["x"]
    pd.testing.assert_frame_equal(out, design)


def test_finalize_design_adds_centre_points_replicates_blocks_and_run_order():
    se = SamplingEngine()
    variables = [_continuous("x", 0.0, 10.0), _discrete("n", 1.0, 4.0, 1.0), _categorical()]
    design = se.generate_samples(variables, "Latin Hypercube Sampling", 6, random_state=1)

    out = se.finalize_design(
        design, variables, n_center=2, n_replicates=2, n_blocks=2, randomize=True, random_state=3
    )

    assert len(out) == (6 + 2) * 2
    assert list(out.columns[:4]) == ["run_order", "block", "point_type", "replicate"]
    assert list(out["run_order"]) == list(range(1, 17))
    centre = out[out["point_type"] == "centre"]
    assert (centre["x"] == 5.0).all()
    assert set(centre["n"]) <= {2.0, 3.0}
    # Blocks get equal shares of design and of centre runs, and run in block order.
    shares = out.groupby(["point_type", "block"]).size()
    assert shares["design"].nunique() == 1 and shares["centre"].nunique() == 1
    assert out["block"].is_monotonic_increasing
    again = se.finalize_design(
        design, variables, n_center=2, n_replicates=2, n_blocks=2, randomize=True, random_state=3
    )
    pd.testing.assert_frame_equal(out, again)


def test_variable_form_keeps_a_zero_min_value():
    from gui_components import GUIComponents

    gui = GUIComponents()
    gui.create_variable_configurator()
    row = gui._create_variable_widget(_continuous("x", 0.0, 1.0))

    assert float(row.min_input.value) == 0.0


@pytest.mark.parametrize(
    ("algorithm", "param"),
    [
        ("Latin Hypercube Sampling", "optimization"),
        ("Sobol Sequences", "scramble"),
        ("Orthogonal Arrays", "continuous_levels"),
    ],
)
def test_advanced_options_reach_the_algorithm_under_its_parameter_name(algorithm, param):
    from gui_components import GUIComponents

    gui = GUIComponents()
    gui.create_advanced_options()
    gui.update_advanced_options(algorithm)

    assert param in gui.get_sampling_parameters()
