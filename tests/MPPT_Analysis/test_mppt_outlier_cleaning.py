"""
Tests for MPPT_Analysis outlier cleaning (issue #71).
"""

import numpy as np
from app_state import AppState
from data_manager import find_outliers, remove_outliers


def _decay(n=300):
    """Burn-in style decay with a little measurement noise."""
    rng = np.random.default_rng(0)
    t = np.arange(n)
    return 2.0 + 1.0 * np.exp(-t / 15.0) + rng.normal(0, 0.003, n)


class TestFindOutliers:
    def test_flags_isolated_spikes_and_dips(self):
        y = _decay()
        y[100] = 200.0
        y[200] = 0.1
        assert list(np.flatnonzero(find_outliers(y))) == [100, 200]

    def test_keeps_the_burn_in_decay(self):
        assert not find_outliers(_decay()).any()

    def test_edges_are_never_flagged(self):
        y = _decay()
        y[0] = 50.0
        y[-1] = 50.0
        assert not find_outliers(y).any()

    def test_lower_threshold_removes_more(self):
        y = _decay()
        assert find_outliers(y, threshold=1.5).sum() > find_outliers(y, threshold=6.0).sum()

    def test_short_or_flat_curves_are_untouched(self):
        assert not find_outliers(np.array([1.0, 50.0, 1.0])).any()
        assert not find_outliers(np.full(200, 3.0)).any()


class TestRemoveOutliers:
    def test_returns_nan_copy_with_same_length_and_leaves_input(self):
        y = _decay()
        y[100] = 200.0
        original = y.copy()
        cleaned, n = remove_outliers(y)
        assert n == 1
        assert len(cleaned) == len(y)
        assert np.isnan(cleaned[100])
        assert np.array_equal(y, original)

    def test_cleaned_curve_still_fits(self, loaded_manager):
        from fitting_tools import available_fit_model_list

        sample_id = loaded_manager.sample_ids[0]
        curve_id = loaded_manager.get_curve_ids_for_sample(
            loaded_manager.curves, loaded_manager.sample_ids, sample_id
        )[0]
        _, y = loaded_manager.get_raw_curve(
            loaded_manager.curves, loaded_manager.sample_ids, sample_id, curve_id
        )
        cleaned = {(sample_id, curve_id): y.copy()}
        cleaned[(sample_id, curve_id)][1] = np.nan
        fits = loaded_manager.fit_sample(
            loaded_manager.curves,
            loaded_manager.sample_ids,
            sample_id,
            next(m for m in available_fit_model_list if m.abbreviated_name == "Linear"),
            curve_ids=[curve_id],
            cleaned=cleaned,
        )
        assert len(fits[curve_id]["original_power"]) == len(y) - 1


class TestCleanedLayer:
    def test_get_curve_prefers_cleaned_and_raw_stays_unchanged(self, loaded_manager):
        dm = loaded_manager
        sample_id = dm.sample_ids[0]
        curve_id = dm.get_curve_ids_for_sample(dm.curves, dm.sample_ids, sample_id)[0]
        t_raw, y_raw = dm.get_raw_curve(dm.curves, dm.sample_ids, sample_id, curve_id)
        marker = np.full(len(y_raw), 7.0)
        cleaned = {(sample_id, curve_id): marker}

        t, y = dm.get_curve(dm.curves, dm.sample_ids, sample_id, curve_id, cleaned)
        assert np.array_equal(y, marker)
        assert np.array_equal(t, t_raw)
        _, y_after = dm.get_raw_curve(dm.curves, dm.sample_ids, sample_id, curve_id)
        assert not np.array_equal(y_after, marker)
        _, y_none = dm.get_curve(dm.curves, dm.sample_ids, sample_id, curve_id, None)
        assert np.array_equal(y_none, y_raw)

    def test_selected_curve_data_uses_cleaned_power_only(self, loaded_manager):
        dm = loaded_manager
        sample_id = dm.sample_ids[0]
        curve_id = dm.get_curve_ids_for_sample(dm.curves, dm.sample_ids, sample_id)[0]
        n = len(dm.get_raw_curve(dm.curves, dm.sample_ids, sample_id, curve_id)[1])
        cleaned = {(sample_id, curve_id): np.full(n, 7.0)}
        power = dm.get_selected_curve_data(
            dm.curves, dm.sample_ids, [sample_id], "power_density", cleaned=cleaned
        )
        voltage = dm.get_selected_curve_data(
            dm.curves, dm.sample_ids, [sample_id], "voltage", cleaned=cleaned
        )
        assert all(np.all(item["data"] == 7.0) for item in power if item["curve_id"] == curve_id)
        assert not any(np.all(item["data"] == 7.0) for item in voltage)

    def test_cleaning_drops_stale_fits_and_restore_clears_layer(self):
        state = AppState()
        model = type("M", (), {"abbreviated_name": "M"})()
        fit = {"model": model, "time": np.array([0.0, 1.0]), "params": {}}
        state.set_fit_results({("s", 0): fit, ("s", 1): fit})

        state.set_cleaned_power({("s", 0): np.array([1.0, np.nan])})
        assert ("s", 0) not in state.fitted_curves_data
        assert ("s", 1) in state.fitted_curves_data

        state.clear_cleaned_power()
        assert state.cleaned_power == {}

    def test_reset_data_clears_cleaned_layer(self):
        state = AppState()
        state.cleaned_power[("s", 0)] = np.array([1.0])
        state.reset_data()
        assert state.cleaned_power == {}


class TestNaNSeeds:
    """A guess made on NaN-containing data is NaN for some models (Linear,
    Exponential); it must not abort the fit."""

    def test_nan_initial_values_are_ignored(self):
        from data_manager import fit_curve
        from fitting_tools import available_fit_model_list

        t = np.linspace(0, 50, 400)
        y = 2.0 + np.exp(-t / 10.0)
        y[100] = np.nan
        for model in available_fit_model_list:
            if model.abbreviated_name not in ("Linear", "Exponential"):
                continue
            seeds = dict.fromkeys(model.columns[: model.n_params], np.nan)
            fit = fit_curve(t, y, model, (0, None), seeds)
            assert fit is not None, model.abbreviated_name
