"""
ML Analysis Module

Basic, ready-to-run analyses over the currently merged dataset - a Random Forest
"what matters most" model and a Bayesian-Optimization-style "what to try next"
suggestion step. Zero widget imports (consistent with data_manager.py/plot_manager.py):
this module only computes and returns plain data structures (dicts/DataFrames);
rendering (Markdown text, Plotly figures) is the caller's job.

Both analyses are intentionally fixed-configuration rather than a tunable ML
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


def suggest_next_experiments(
    df: pd.DataFrame,
    target_col: str,
    feature_cols: list = None,
    direction: str = "maximize",
    n_candidates: int = 3000,
    n_suggestions: int = 5,
    random_state: int = 42,
) -> dict:
    """
    Fit a Gaussian Process surrogate model on already-measured samples and suggest
    the next parameter combinations most likely to improve target_col, ranked by
    Expected Improvement over randomly sampled candidates within the observed
    parameter ranges.

    This is a single-shot "propose next experiments" step, not a full closed-loop
    optimizer - re-run it after each new batch of measurements comes in.

    Returns a dict: target, direction, n_samples, n_features, best_observed,
    suggestions (DataFrame with feature_cols + predicted_<target>, predicted_std,
    expected_improvement columns, sorted by expected_improvement descending).
    """
    from scipy.stats import norm
    from sklearn.exceptions import ConvergenceWarning
    from sklearn.gaussian_process import GaussianProcessRegressor
    from sklearn.gaussian_process.kernels import RBF, WhiteKernel
    from sklearn.preprocessing import StandardScaler

    if direction not in ("maximize", "minimize"):
        raise ValueError("direction must be 'maximize' or 'minimize'")

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

    X = model_df[feature_cols].to_numpy()
    y = model_df[target_col].to_numpy()

    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)

    kernel = RBF(length_scale=1.0, length_scale_bounds=(1e-2, 1e2)) + WhiteKernel(
        noise_level=1.0, noise_level_bounds=(1e-8, 1e1)
    )
    gp = GaussianProcessRegressor(kernel=kernel, normalize_y=True, random_state=random_state)
    # A near-zero fitted noise level (the optimizer pinned against noise_level_bounds'
    # lower edge) just means the data looks near-noiseless to the model - harmless for
    # this "basic" suggestion tool, so the sklearn ConvergenceWarning about it is
    # suppressed rather than surfaced as an error to the user.
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", category=ConvergenceWarning)
        gp.fit(X_scaled, y)

    rng = np.random.default_rng(random_state)
    mins = X.min(axis=0)
    maxs = X.max(axis=0)
    candidates = rng.uniform(mins, maxs, size=(n_candidates, len(feature_cols)))
    candidates_scaled = scaler.transform(candidates)

    mu, sigma = gp.predict(candidates_scaled, return_std=True)
    sigma = np.maximum(sigma, 1e-9)

    best_observed = y.max() if direction == "maximize" else y.min()
    improvement = (mu - best_observed) if direction == "maximize" else (best_observed - mu)
    z = improvement / sigma
    ei = improvement * norm.cdf(z) + sigma * norm.pdf(z)
    ei[sigma < 1e-8] = 0.0

    top_idx = np.argsort(ei)[::-1][:n_suggestions]

    suggestions = pd.DataFrame(candidates[top_idx], columns=feature_cols)
    suggestions[f"predicted_{target_col}"] = mu[top_idx]
    suggestions["predicted_std"] = sigma[top_idx]
    suggestions["expected_improvement"] = ei[top_idx]
    suggestions = suggestions.reset_index(drop=True)
    logger.debug(
        "suggest_next_experiments: target=%s, direction=%s, n_samples=%d, best_observed=%.4g",
        target_col,
        direction,
        len(model_df),
        best_observed,
    )

    return {
        "target": target_col,
        "direction": direction,
        "n_samples": len(model_df),
        "n_features": len(feature_cols),
        "best_observed": best_observed,
        "suggestions": suggestions,
    }
