"""
ML Analysis Module

Basic, ready-to-run analyses over the currently merged dataset - a Random Forest
"what matters most" model and a Bayesian-Optimization-style "what to try next"
suggestion step. Zero widget imports (consistent with data_manager.py/plot_manager.py):
this module only computes and returns plain data structures (dicts/DataFrames);
rendering (Markdown text, Plotly figures) is the caller's job.

Both analyses are intentionally near-fixed-configuration rather than a tunable ML
workbench - feature selection, split ratios, and model hyperparameters are all
sensible defaults so a lab scientist can pick a target and click "Run".
"""

import logging
import warnings

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

MIN_ROWS_RANDOM_FOREST = 8
MIN_ROWS_BAYESIAN_OPT = 6


def select_numeric_feature_columns(df: pd.DataFrame, target_col: str) -> list:
    """Numeric columns usable as model features: everything except the target itself
    and columns with fewer than 2 distinct values (constants carry no signal)."""
    numeric_df = df.select_dtypes(include="number")
    return [
        col
        for col in numeric_df.columns
        if col != target_col and numeric_df[col].dropna().nunique() > 1
    ]


def run_random_forest(
    df: pd.DataFrame,
    target_col: str,
    feature_cols: list = None,
    n_estimators: int = 300,
    random_state: int = 42,
) -> dict:
    """
    Fit a RandomForestRegressor to predict target_col from the dataset's other
    numeric parameters, and report held-out performance plus feature importances.

    Returns a dict: target, n_samples, n_features, held_out (bool - False means the
    dataset was too small for a train/test split and R²/RMSE are on training data),
    r2, rmse, importances (list of (feature, importance) sorted descending).
    """
    from sklearn.ensemble import RandomForestRegressor
    from sklearn.metrics import mean_squared_error, r2_score
    from sklearn.model_selection import train_test_split

    numeric_df = df.select_dtypes(include="number")
    if target_col not in numeric_df.columns:
        raise ValueError(f"'{target_col}' is not a numeric column in the current dataset.")

    if feature_cols is None:
        feature_cols = select_numeric_feature_columns(df, target_col)

    if not feature_cols:
        raise ValueError("No usable numeric feature parameters found besides the target.")

    model_df = numeric_df[[target_col, *feature_cols]].dropna()
    if len(model_df) < MIN_ROWS_RANDOM_FOREST:
        raise ValueError(
            f"Only {len(model_df)} complete rows available (need at least "
            f"{MIN_ROWS_RANDOM_FOREST}) - load more batches, or pick a target/feature "
            "set with fewer missing values."
        )

    X = model_df[feature_cols]
    y = model_df[target_col]

    held_out = len(model_df) >= 20
    if held_out:
        X_train, X_test, y_train, y_test = train_test_split(
            X, y, test_size=0.25, random_state=random_state
        )
    else:
        X_train, y_train = X, y
        X_test, y_test = X, y

    model = RandomForestRegressor(n_estimators=n_estimators, random_state=random_state)
    model.fit(X_train, y_train)

    y_pred = model.predict(X_test)
    r2 = r2_score(y_test, y_pred)
    rmse = mean_squared_error(y_test, y_pred) ** 0.5

    importances = sorted(
        zip(feature_cols, model.feature_importances_), key=lambda item: item[1], reverse=True
    )
    logger.debug(
        "run_random_forest: target=%s, n_samples=%d, n_features=%d, held_out=%s, r2=%.3f",
        target_col,
        len(model_df),
        len(feature_cols),
        held_out,
        r2,
    )

    return {
        "target": target_col,
        "n_samples": len(model_df),
        "n_features": len(feature_cols),
        "held_out": held_out,
        "r2": r2,
        "rmse": rmse,
        "importances": importances,
    }


MAX_BO_SUGGESTIONS = 20
# A parameter whose observed values are all whole numbers, with at most this many
# distinct levels, is treated as integer (e.g. number of helices, layer count).
MAX_INTEGER_LEVELS = 20
# Fitted ARD length scales live on [0, 1]-scaled inputs; one pinned at this upper
# bound means the model found no detectable effect of that parameter.
LENGTH_SCALE_BOUNDS = (1e-2, 10.0)


def detect_integer_columns(df: pd.DataFrame, cols: list) -> list:
    """Columns of df whose non-null values are all whole numbers with at most
    MAX_INTEGER_LEVELS distinct levels - the default "integer" setting for the
    BO search space, so e.g. a number-of-starts column never gets suggested as 1.4."""
    integer_cols = []
    for col in cols:
        values = pd.to_numeric(df[col], errors="coerce").dropna()
        if values.empty:
            continue
        if np.allclose(values, np.round(values)) and values.nunique() <= MAX_INTEGER_LEVELS:
            integer_cols.append(col)
    return integer_cols


def _expected_improvement(mu, sigma, incumbent, direction):
    from scipy.stats import norm

    improvement = (mu - incumbent) if direction == "maximize" else (incumbent - mu)
    z = improvement / sigma
    ei = improvement * norm.cdf(z) + sigma * norm.pdf(z)
    ei[sigma < 1e-8] = 0.0
    return ei


def suggest_next_experiments(
    df: pd.DataFrame,
    target_col: str,
    feature_cols: list = None,
    direction: str = "maximize",
    n_candidates: int = 10000,
    n_suggestions: int = 5,
    random_state: int = 42,
    bounds: dict = None,
    integer_cols: list = None,
    fixed: dict = None,
    min_distance: float = 0.1,
) -> dict:
    """
    Fit a Gaussian Process surrogate on already-measured samples and suggest a
    batch of n_suggestions parameter combinations to measure next, chosen by
    Expected Improvement (EI) over random candidates inside the search space.

    Model: inputs min-max scaled to [0, 1] over the search space (plus the
    observed range, so older points outside new bounds still scale sensibly),
    target standardised; kernel ConstantKernel * Matern(nu=2.5) with one length
    scale per parameter (ARD) + WhiteKernel, hyperparameters fit with restarts.
    A learned noise term matters: with replicate scatter comparable to the
    effects of interest, a near-noiseless GP would put the optimum on top of the
    single luckiest sample.

    Incumbent: the best *predicted* value at the measured points, not the best
    measured value. With noisy data the best measurement is partly luck (and may
    sit at the top of a bounded score scale), which would leave EI driven by
    uncertainty alone.

    Batch: Kriging Believer. After each pick, a fake observation at the model's
    predicted mean is added *without* observation noise (real points keep the
    fitted noise), so the uncertainty around the pick actually collapses and
    later picks go elsewhere. Candidates within min_distance (scaled units) of
    an earlier pick are also excluded as a backstop. n_suggestions=1 is one
    ordinary BO step.

    Search space (all optional, keyed by feature column):
        bounds: {col: (low, high)} - default: observed min/max.
        integer_cols: columns whose candidates are whole numbers - default:
            detect_integer_columns().
        fixed: {col: value} - hold a parameter at one value in every suggestion.

    Returns a dict: target, direction, n_samples, n_features, best_observed,
    incumbent (best predicted at measured points), noise_sd (fitted observation
    noise, in target units), length_scales ({col: scaled length scale}),
    length_scale_upper (the bound; at it = no detectable effect), bounds,
    integer_cols, fixed, suggestions (DataFrame: feature_cols +
    predicted_<target>, predicted_std, expected_improvement, in pick order;
    predicted_* are from the GP fit on real data only, expected_improvement is
    the EI at the moment of picking, i.e. given the earlier picks).
    """
    from sklearn.exceptions import ConvergenceWarning
    from sklearn.gaussian_process import GaussianProcessRegressor
    from sklearn.gaussian_process.kernels import ConstantKernel, Matern, WhiteKernel

    if direction not in ("maximize", "minimize"):
        raise ValueError("direction must be 'maximize' or 'minimize'")
    if not 1 <= n_suggestions <= MAX_BO_SUGGESTIONS:
        raise ValueError(f"n_suggestions must be between 1 and {MAX_BO_SUGGESTIONS}.")

    numeric_df = df.select_dtypes(include="number")
    if target_col not in numeric_df.columns:
        raise ValueError(f"'{target_col}' is not a numeric column in the current dataset.")

    if feature_cols is None:
        feature_cols = select_numeric_feature_columns(df, target_col)

    if not feature_cols:
        raise ValueError("No usable numeric feature parameters found besides the target.")

    model_df = numeric_df[[target_col, *feature_cols]].dropna()
    if len(model_df) < MIN_ROWS_BAYESIAN_OPT:
        raise ValueError(
            f"Only {len(model_df)} complete rows available (need at least "
            f"{MIN_ROWS_BAYESIAN_OPT}) - load more batches, or pick a target/feature "
            "set with fewer missing values."
        )

    X = model_df[feature_cols].to_numpy(dtype=float)
    y = model_df[target_col].to_numpy(dtype=float)
    n_features = len(feature_cols)

    # ---- Search space -----------------------------------------------------
    bounds = dict(bounds or {})
    fixed = dict(fixed or {})
    if integer_cols is None:
        integer_cols = detect_integer_columns(model_df, feature_cols)
    integer_set = set(integer_cols)
    low = np.empty(n_features)
    high = np.empty(n_features)
    for i, col in enumerate(feature_cols):
        lo, hi = bounds.get(col, (X[:, i].min(), X[:, i].max()))
        if col in integer_set:
            lo, hi = np.ceil(lo - 1e-9), np.floor(hi + 1e-9)
        if lo > hi:
            raise ValueError(f"Search range for '{col}' is empty (min {lo:g} > max {hi:g}).")
        low[i], high[i] = lo, hi
        bounds[col] = (float(lo), float(hi))
    for col, value in fixed.items():
        if col not in feature_cols:
            raise ValueError(f"Fixed parameter '{col}' is not one of the features.")

    # ---- Scaling ------------------------------------------------------------
    scale_low = np.minimum(low, X.min(axis=0))
    scale_span = np.maximum(high, X.max(axis=0)) - scale_low
    scale_span[scale_span == 0] = 1.0

    def to_unit(values):
        return (values - scale_low) / scale_span

    X_unit = to_unit(X)
    y_mean, y_std = y.mean(), y.std()
    y_std = y_std if y_std > 0 else 1.0
    y_norm = (y - y_mean) / y_std

    # ---- Fit ---------------------------------------------------------------
    kernel = ConstantKernel(1.0, (1e-2, 1e2)) * Matern(
        length_scale=np.ones(n_features), length_scale_bounds=LENGTH_SCALE_BOUNDS, nu=2.5
    ) + WhiteKernel(noise_level=0.5, noise_level_bounds=(1e-6, 1e1))
    gp = GaussianProcessRegressor(
        kernel=kernel, normalize_y=False, n_restarts_optimizer=5, random_state=random_state
    )
    # A hyperparameter pinned against its bound (e.g. a length scale at the upper
    # bound = "no detectable effect") is informative here, not an error, so the
    # sklearn ConvergenceWarning about it is suppressed and reported instead.
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", category=ConvergenceWarning)
        gp.fit(X_unit, y_norm)

    signal_kernel = gp.kernel_.k1  # ConstantKernel * Matern, no noise term
    noise_level = float(gp.kernel_.k2.noise_level)
    length_scales = np.atleast_1d(signal_kernel.k2.length_scale)

    # ---- Candidates ----------------------------------------------------------
    rng = np.random.default_rng(random_state)
    candidates = np.empty((n_candidates, n_features))
    for i, col in enumerate(feature_cols):
        if col in fixed:
            candidates[:, i] = fixed[col]
        elif col in integer_set:
            candidates[:, i] = rng.integers(int(low[i]), int(high[i]) + 1, size=n_candidates)
        else:
            candidates[:, i] = rng.uniform(low[i], high[i], size=n_candidates)
    candidates_unit = to_unit(candidates)

    # Same posterior as gp, but with the noise moved from the kernel into alpha:
    # predict() then returns the latent (noise-free) std - the uncertainty EI
    # should explore, since no amount of sampling reduces measurement noise -
    # and fake batch points can be added with alpha ~0 below.
    believer = GaussianProcessRegressor(kernel=signal_kernel, optimizer=None, normalize_y=False)
    believer.set_params(alpha=np.full(len(y_norm), noise_level))
    believer.fit(X_unit, y_norm)
    mu_step, sigma_step = believer.predict(candidates_unit, return_std=True)
    sigma_step = np.maximum(sigma_step, 1e-9)
    mu = mu_step * y_std + y_mean
    sigma = sigma_step * y_std

    fitted_at_samples = believer.predict(X_unit)
    incumbent_norm = fitted_at_samples.max() if direction == "maximize" else fitted_at_samples.min()
    best_observed = y.max() if direction == "maximize" else y.min()

    # ---- Kriging Believer batch ---------------------------------------------
    X_train, y_train = X_unit, y_norm
    alpha = np.full(len(y_norm), noise_level)
    incumbent = incumbent_norm
    available = np.ones(n_candidates, dtype=bool)
    picked_idx, picked_ei = [], []
    for _ in range(min(n_suggestions, n_candidates)):
        ei = _expected_improvement(mu_step, sigma_step, incumbent, direction)
        ei[~available] = -np.inf
        idx = int(np.argmax(ei))
        if not np.isfinite(ei[idx]):
            break
        picked_idx.append(idx)
        picked_ei.append(max(float(ei[idx]), 0.0) * y_std)

        distance = np.linalg.norm(candidates_unit - candidates_unit[idx], axis=1)
        available &= distance > min_distance
        available[idx] = False

        fake_y = mu_step[idx]
        X_train = np.vstack([X_train, candidates_unit[idx]])
        y_train = np.append(y_train, fake_y)
        alpha = np.append(alpha, 1e-8)
        if direction == "maximize":
            incumbent = max(incumbent, fake_y)
        else:
            incumbent = min(incumbent, fake_y)
        if len(picked_idx) < n_suggestions:
            believer.set_params(alpha=alpha)
            believer.fit(X_train, y_train)
            mu_step, sigma_step = believer.predict(candidates_unit, return_std=True)
            sigma_step = np.maximum(sigma_step, 1e-9)

    suggestions = pd.DataFrame(candidates[picked_idx], columns=feature_cols)
    for col in integer_set:
        suggestions[col] = suggestions[col].round().astype(int)
    suggestions[f"predicted_{target_col}"] = mu[picked_idx]
    suggestions["predicted_std"] = sigma[picked_idx]
    suggestions["expected_improvement"] = picked_ei
    suggestions = suggestions.reset_index(drop=True)
    logger.debug(
        "suggest_next_experiments: target=%s, direction=%s, n_samples=%d, "
        "n_suggestions=%d, best_observed=%.4g, noise_level=%.3g, kernel=%s",
        target_col,
        direction,
        len(model_df),
        len(suggestions),
        best_observed,
        noise_level,
        gp.kernel_,
    )

    return {
        "target": target_col,
        "direction": direction,
        "n_samples": len(model_df),
        "n_features": n_features,
        "best_observed": best_observed,
        "incumbent": incumbent_norm * y_std + y_mean,
        "noise_sd": float(np.sqrt(noise_level) * y_std),
        "length_scales": dict(zip(feature_cols, length_scales.tolist())),
        "length_scale_upper": LENGTH_SCALE_BOUNDS[1],
        "bounds": bounds,
        "integer_cols": [c for c in feature_cols if c in integer_set],
        "fixed": fixed,
        "suggestions": suggestions,
    }


def estimate_max_bo_steps(n_features: int, min_steps: int = 10, max_steps: int = 200) -> dict:
    """Rule-of-thumb estimate for how many optimization rounds a GP-based Bayesian
    Optimization typically needs to converge in a low-dimensional setting: roughly
    10-20 evaluations per active dimension is common guidance for this class of
    surrogate model. This is a heuristic, not derived from the current dataset -
    treat it as a ballpark, not a guarantee.

    Returns a dict: n_features, suggested_max_steps, rationale.
    """
    suggested_max_steps = min(max(15 * n_features, min_steps), max_steps)
    rationale = (
        f"Rough guideline: ~10-20 evaluations per active parameter. With "
        f"{n_features} parameter(s), a typical GP-based search converges within "
        f"roughly {suggested_max_steps} total experiments (including ones already run)."
    )
    return {
        "n_features": n_features,
        "suggested_max_steps": suggested_max_steps,
        "rationale": rationale,
    }
