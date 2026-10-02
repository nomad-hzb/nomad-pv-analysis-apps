"""
ML Analysis Module

Basic, ready-to-run analyses over the currently merged dataset - a Random Forest
"what matters most" model and a Bayesian-Optimization-style "what to try next"
suggestion step. Zero widget imports (consistent with data_manager.py/plot_manager.py):
this module only computes and returns plain data structures (dicts/DataFrames);
rendering (Markdown text, Plotly figures) is the caller's job.

Both analyses are intentionally near-fixed-configuration rather than a tunable ML
workbench - feature selection, validation scheme, and model hyperparameters are all
sensible defaults so a lab scientist can pick a target and click "Run".

Sample sizes count distinct samples (sample_id), not rows: under the "All Points"
aggregation one sample contributes one row per pixel, and those rows share every
process parameter, so they are not independent observations of the process.
"""

import logging
import warnings

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

MIN_SAMPLES_RANDOM_FOREST = 8
RECOMMENDED_SAMPLES_RANDOM_FOREST = 20
MIN_SAMPLES_BAYESIAN_OPT = 6


def select_numeric_feature_columns(df: pd.DataFrame, target_col: str) -> list:
    """Numeric columns usable as model features: everything except the target itself
    and columns with fewer than 2 distinct values (constants carry no signal)."""
    numeric_df = df.select_dtypes(include="number")
    return [
        col
        for col in numeric_df.columns
        if col != target_col and numeric_df[col].dropna().nunique() > 1
    ]


def sample_groups(df: pd.DataFrame, index) -> np.ndarray:
    """One group label per row of df.loc[index]: its sample_id, so rows of the
    same sample (pixels, repeats) are kept together, or the row index itself
    when df has no sample_id column."""
    if "sample_id" in df.columns:
        return df.loc[index, "sample_id"].astype(str).to_numpy()
    return np.asarray(index).astype(str)


def _complete_rows(df: pd.DataFrame, target_col: str, feature_cols: list):
    """Rows with the target and every feature present, the number of rows that
    have the target at all, and {feature: rows dropped because it was missing},
    largest first - so a sparse column silently halving the data shows up."""
    numeric_df = df.select_dtypes(include="number")
    with_target = numeric_df.loc[numeric_df[target_col].notna(), [target_col, *feature_cols]]
    missing = {
        col: int(with_target[col].isna().sum())
        for col in feature_cols
        if with_target[col].isna().any()
    }
    missing = dict(sorted(missing.items(), key=lambda kv: kv[1], reverse=True))
    return with_target.dropna(), len(with_target), missing


def _batch_warning(df: pd.DataFrame, index) -> list:
    """A warning when the modelled rows span several batches: batch-to-batch
    offsets (day, precursor lot, ...) are not modelled and can look like a
    parameter effect if a parameter was changed together with the batch."""
    if "batch" not in df.columns:
        return []
    n_batches = df.loc[index, "batch"].dropna().nunique()
    if n_batches < 2:
        return []
    return [
        f"The data spans {n_batches} batches. Differences between batches (day, "
        "precursor lot, ...) are not modelled; if a parameter was changed together "
        "with the batch, its effect cannot be told apart from the batch effect."
    ]


def _r2(y: np.ndarray, pred: np.ndarray) -> float:
    ss_tot = ((y - y.mean()) ** 2).sum()
    return float(1.0 - ((y - pred) ** 2).sum() / ss_tot) if ss_tot > 0 else 0.0


def run_random_forest(
    df: pd.DataFrame,
    target_col: str,
    feature_cols: list = None,
    n_estimators: int = 100,
    random_state: int = 42,
    n_folds: int = 5,
    n_repeats: int = 3,
    n_permutations: int = 3,
) -> dict:
    """
    Fit a RandomForestRegressor to predict target_col from the dataset's other
    numeric parameters, and report cross-validated performance plus permutation
    importances.

    Validation: repeated K-fold cross-validation with folds split by sample
    (sample_id), so pixels or repeats of one sample are never in both the
    training and the test part - otherwise the model "predicts" a pixel from
    its neighbours on the same sample and R² is inflated. Every row gets an
    out-of-fold prediction in every repeat; R² and RMSE are computed on those
    and reported as mean and SD over repeats. Training-set R² is never reported.

    Importance: permutation importance on the held-out folds - how much the
    cross-validated R² drops when one parameter's values are shuffled. Unlike
    the forest's built-in (impurity) importance it is not biased towards
    continuous or many-valued parameters and is measured on unseen data. It is
    ~0 (or slightly negative) for a parameter that does not help; correlated
    parameters share their importance, so both can look small.

    Returns a dict: target, n_samples (distinct samples), n_rows, n_features,
    n_folds, n_repeats, r2, r2_sd, rmse, rmse_sd, importances (list of
    (feature, mean R² drop, SD over repeats), sorted descending),
    n_rows_with_target, missing_by_column ({feature: rows dropped for it}),
    warnings (list of str).
    """
    from sklearn.ensemble import RandomForestRegressor

    numeric_df = df.select_dtypes(include="number")
    if target_col not in numeric_df.columns:
        raise ValueError(f"'{target_col}' is not a numeric column in the current dataset.")

    if feature_cols is None:
        feature_cols = select_numeric_feature_columns(df, target_col)

    if not feature_cols:
        raise ValueError("No usable numeric feature parameters found besides the target.")

    model_df, n_rows_with_target, missing = _complete_rows(df, target_col, feature_cols)
    groups = sample_groups(df, model_df.index)
    unique_groups = np.unique(groups)
    n_samples = len(unique_groups)
    if n_samples < MIN_SAMPLES_RANDOM_FOREST:
        raise ValueError(
            f"Only {n_samples} samples with complete data (need at least "
            f"{MIN_SAMPLES_RANDOM_FOREST}) - load more batches, or pick a target/feature "
            "set with fewer missing values."
        )

    X = model_df[feature_cols].to_numpy(dtype=float)
    y = model_df[target_col].to_numpy(dtype=float)
    n_rows, n_features = X.shape
    n_folds = min(n_folds, n_samples)
    rng = np.random.default_rng(random_state)

    r2s, rmses, importance_runs = [], [], []
    for repeat in range(n_repeats):
        fold_of_group = dict(zip(rng.permutation(unique_groups), np.arange(n_samples) % n_folds))
        folds = np.array([fold_of_group[g] for g in groups])
        oof = np.empty(n_rows)
        # oof_perm[j, p]: out-of-fold predictions with feature j shuffled (p-th time)
        oof_perm = np.empty((n_features, n_permutations, n_rows))
        for fold in range(n_folds):
            test = folds == fold
            model = RandomForestRegressor(
                n_estimators=n_estimators, random_state=random_state + repeat * n_folds + fold
            )
            model.fit(X[~test], y[~test])
            X_test = X[test]
            oof[test] = model.predict(X_test)
            # One predict call for every shuffled copy of the test fold.
            shuffled = np.tile(X_test, (n_features, n_permutations, 1, 1))
            for j in range(n_features):
                for p in range(n_permutations):
                    shuffled[j, p, :, j] = rng.permutation(X_test[:, j])
            preds = model.predict(shuffled.reshape(-1, n_features))
            oof_perm[:, :, test] = preds.reshape(n_features, n_permutations, -1)
        r2 = _r2(y, oof)
        r2s.append(r2)
        rmses.append(float(np.sqrt(((y - oof) ** 2).mean())))
        importance_runs.append(
            [
                r2 - np.mean([_r2(y, oof_perm[j, p]) for p in range(n_permutations)])
                for j in range(n_features)
            ]
        )

    importance_runs = np.array(importance_runs)
    importances = sorted(
        (
            (name, float(mean), float(sd))
            for name, mean, sd in zip(
                feature_cols, importance_runs.mean(axis=0), importance_runs.std(axis=0)
            )
        ),
        key=lambda item: item[1],
        reverse=True,
    )

    warnings_list = []
    if n_samples < RECOMMENDED_SAMPLES_RANDOM_FOREST:
        warnings_list.append(
            f"Only {n_samples} samples: R² and the importance ranking can change a lot "
            f"with a few more samples, so treat them as a first hint (aim for "
            f"{RECOMMENDED_SAMPLES_RANDOM_FOREST}+)."
        )
    logger.debug(
        "run_random_forest: target=%s, n_samples=%d, n_rows=%d, n_features=%d, r2=%.3f",
        target_col,
        n_samples,
        n_rows,
        n_features,
        float(np.mean(r2s)),
    )

    return {
        "target": target_col,
        "n_samples": n_samples,
        "n_rows": n_rows,
        "n_features": n_features,
        "n_folds": n_folds,
        "n_repeats": n_repeats,
        "r2": float(np.mean(r2s)),
        "r2_sd": float(np.std(r2s)),
        "rmse": float(np.mean(rmses)),
        "rmse_sd": float(np.std(rmses)),
        "importances": importances,
        "n_rows_with_target": n_rows_with_target,
        "missing_by_column": missing,
        "warnings": warnings_list,
    }


MAX_BO_SUGGESTIONS = 20
# A parameter whose observed values are all whole numbers, with at most this many
# distinct levels, is treated as integer (e.g. number of helices, layer count).
MAX_INTEGER_LEVELS = 20
# Fitted ARD length scales live on [0, 1]-scaled inputs; one pinned at this upper
# bound means the model found no detectable effect of that parameter.
LENGTH_SCALE_BOUNDS = (1e-2, 10.0)
SIGNAL_VARIANCE_BOUNDS = (1e-2, 1e2)
NOISE_LEVEL_BOUNDS = (1e-6, 1e1)
# Leave-one-sample-out R² below this: the model has no usable predictive skill.
LOO_R2_POOR = 0.2


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


def _grouped_loo(signal_kernel, noise_level, X, y, groups):
    """Leave-one-sample-out predictions of a GP with fixed hyperparameters, in
    closed form: for the rows G of one sample, with K^-1 the inverse of the full
    training covariance, mean_G = y_G - (K^-1_GG)^-1 (K^-1 y)_G and covariance
    (K^-1_GG)^-1 (Rasmussen & Williams 2006, sec. 5.4.2, extended to blocks).
    Leaving out a whole sample, not one row, stops a pixel being predicted from
    its neighbours on the same sample. The std includes measurement noise, since
    it is compared against single measurements."""
    K = signal_kernel(X) + noise_level * np.eye(len(y))
    K_inv = np.linalg.inv(K + 1e-10 * np.eye(len(y)))
    alpha = K_inv @ y
    mean = np.empty(len(y))
    std = np.empty(len(y))
    for group in np.unique(groups):
        idx = np.flatnonzero(groups == group)
        block_inv = np.linalg.inv(K_inv[np.ix_(idx, idx)])
        mean[idx] = y[idx] - block_inv @ alpha[idx]
        std[idx] = np.sqrt(np.maximum(np.diag(block_inv), 0.0))
    return mean, std


def _fit_warnings(
    signal_variance: float, noise_level: float, length_scales: dict, loo_r2: float
) -> list:
    """Hyperparameters pinned at a fit bound are information, not an error: say
    what each one means for the suggestions. A poor leave-one-out R² is the
    catch-all: the fit can also overfit noise without hitting any bound."""
    notes = []
    wiggly = [c for c, ls in length_scales.items() if ls <= LENGTH_SCALE_BOUNDS[0] * 1.01]
    if wiggly:
        notes.append(
            "The model lets the target change faster than your sample spacing can show "
            f"for: {', '.join(wiggly)} (length scale at its lower limit). It is most "
            "likely fitting the scatter, not a real trend."
        )
    if loo_r2 < LOO_R2_POOR:
        notes.append(
            f"Leave-one-sample-out R² is {loo_r2:.2f}: the model predicts unseen samples "
            "little or no better than their average, so treat the suggestions as close "
            "to a random search. More samples, fewer parameters or the log scale may help."
        )
    if signal_variance <= SIGNAL_VARIANCE_BOUNDS[0] * 1.01 or noise_level >= (
        NOISE_LEVEL_BOUNDS[1] * 0.99
    ):
        notes.append(
            "The model found no clear trend: nearly all variation in the target is "
            "attributed to noise, so the suggestions are close to a random search."
        )
    if noise_level <= NOISE_LEVEL_BOUNDS[0] * 1.01:
        notes.append(
            "The fitted measurement noise is at its lower limit: the model treats every "
            "measurement as exact. With few samples this usually means it is fitting the "
            "scatter; check the leave-one-out R² below."
        )
    return notes


def _sobol_unit(n: int, d: int, rng) -> np.ndarray:
    """n points in [0, 1)^d from a scrambled Sobol sequence, n rounded up to a power
    of 2 (Sobol's balance properties hold only then). Spreads candidates far more
    evenly than uniform random draws, which matters from ~5 parameters on."""
    from scipy.stats import qmc

    if d == 0:
        return np.empty((n, 0))
    m = int(np.ceil(np.log2(max(n, 2))))
    return qmc.Sobol(d=d, scramble=True, seed=rng).random_base2(m)


def suggest_next_experiments(
    df: pd.DataFrame,
    target_col: str,
    feature_cols: list = None,
    direction: str = "maximize",
    n_candidates: int = 8192,
    n_suggestions: int = 5,
    random_state: int = 42,
    bounds: dict = None,
    integer_cols: list = None,
    fixed: dict = None,
    min_distance: float = 0.1,
    log_target: bool = False,
) -> dict:
    """
    Fit a Gaussian Process surrogate on already-measured samples and suggest a
    batch of n_suggestions parameter combinations to measure next, chosen by
    Expected Improvement (EI) over quasi-random (Sobol) candidates inside the
    search space.

    Model: inputs min-max scaled to [0, 1] over the search space (plus the
    observed range, so older points outside new bounds still scale sensibly),
    target standardised (after log10 when log_target); kernel
    ConstantKernel * Matern(nu=2.5) with one length scale per parameter (ARD)
    + WhiteKernel, hyperparameters fit with restarts. A learned noise term
    matters: with replicate scatter comparable to the effects of interest, a
    near-noiseless GP would put the optimum on top of the single luckiest sample.

    log_target: fit log10(target) - for targets spanning decades (currents,
    resistances), where a linear-scale GP is dominated by the largest values.
    Needs every target value > 0. EI, noise_sd and the LOO R² are then in log10
    units; predicted values and ranges are back-transformed (the prediction is
    then the median, not the mean).

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

    Returns a dict: target, direction, log_target, n_samples (distinct
    samples), n_rows, n_features, best_observed, incumbent (best predicted at
    measured points), noise_sd (fitted observation noise, in target units or
    log10 units), length_scales ({col: scaled length scale}),
    length_scale_upper (the bound; at it = no detectable effect), bounds,
    integer_cols, fixed, n_rows_with_target, missing_by_column, warnings (data
    and fit diagnostics, list of str), loo_r2 (leave-one-sample-out R², model
    units), loo_df (sample_id, observed, predicted, predicted_low,
    predicted_high per row; the range is ±1 SD for a single measurement),
    suggestions (DataFrame: feature_cols + predicted_<target>, predicted_low,
    predicted_high (±1 SD of the predicted mean, excluding measurement noise),
    expected_improvement, in pick order; predicted_* are from the GP fit on
    real data only, expected_improvement is the EI at the moment of picking,
    i.e. given the earlier picks).
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

    model_df, n_rows_with_target, missing = _complete_rows(df, target_col, feature_cols)
    groups = sample_groups(df, model_df.index)
    n_samples = len(np.unique(groups))
    if n_samples < MIN_SAMPLES_BAYESIAN_OPT:
        raise ValueError(
            f"Only {n_samples} samples with complete data (need at least "
            f"{MIN_SAMPLES_BAYESIAN_OPT}) - load more batches, or pick a target/feature "
            "set with fewer missing values."
        )

    X = model_df[feature_cols].to_numpy(dtype=float)
    y_raw = model_df[target_col].to_numpy(dtype=float)
    if log_target:
        n_non_positive = int((y_raw <= 0).sum())
        if n_non_positive:
            raise ValueError(
                f"Log scale needs every '{target_col}' value to be > 0 "
                f"({n_non_positive} are not). Filter them out or use the linear scale."
            )
        y = np.log10(y_raw)
    else:
        y = y_raw
    n_features = len(feature_cols)

    def to_target_units(values):
        return 10.0**values if log_target else values

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
    for col in fixed:
        if col not in feature_cols:
            raise ValueError(f"Fixed parameter '{col}' is not one of the features.")

    warnings_list = []
    n_free = sum(col not in fixed for col in feature_cols)
    recommended = 2 * (n_free + 1)
    if n_samples < recommended:
        warnings_list.append(
            f"Only {n_samples} samples for {n_free} free parameter(s); below about "
            f"{recommended} the model mostly returns its prior and the suggestions are "
            "weakly informed. A space-filling design from the Design of Experiments tool "
            "is usually a better next step, or fix or uncheck some parameters."
        )
    warnings_list += _batch_warning(df, model_df.index)

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
    kernel = ConstantKernel(1.0, SIGNAL_VARIANCE_BOUNDS) * Matern(
        length_scale=np.ones(n_features), length_scale_bounds=LENGTH_SCALE_BOUNDS, nu=2.5
    ) + WhiteKernel(noise_level=0.5, noise_level_bounds=NOISE_LEVEL_BOUNDS)
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

    # ---- Model check: leave one sample out --------------------------------------
    loo_mean, loo_std = _grouped_loo(signal_kernel, noise_level, X_unit, y_norm, groups)
    loo_mean = loo_mean * y_std + y_mean
    loo_std = loo_std * y_std
    loo_r2 = _r2(y, loo_mean)
    warnings_list += _fit_warnings(
        float(signal_kernel.k1.constant_value),
        noise_level,
        dict(zip(feature_cols, length_scales.tolist())),
        loo_r2,
    )
    loo_df = pd.DataFrame(
        {
            "sample_id": groups,
            "observed": y_raw,
            "predicted": to_target_units(loo_mean),
            "predicted_low": to_target_units(loo_mean - loo_std),
            "predicted_high": to_target_units(loo_mean + loo_std),
        }
    )

    # ---- Candidates ----------------------------------------------------------
    rng = np.random.default_rng(random_state)
    free_idx = [i for i, col in enumerate(feature_cols) if col not in fixed]
    unit_draws = _sobol_unit(n_candidates, len(free_idx), rng)
    n_candidates = len(unit_draws)
    candidates = np.empty((n_candidates, n_features))
    for i, col in enumerate(feature_cols):
        if col in fixed:
            candidates[:, i] = fixed[col]
            continue
        u = unit_draws[:, free_idx.index(i)]
        if col in integer_set:
            levels = high[i] - low[i] + 1
            candidates[:, i] = np.minimum(low[i] + np.floor(u * levels), high[i])
        else:
            candidates[:, i] = low[i] + u * (high[i] - low[i])
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
    best_observed = y_raw.max() if direction == "maximize" else y_raw.min()

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
    suggestions[f"predicted_{target_col}"] = to_target_units(mu[picked_idx])
    suggestions["predicted_low"] = to_target_units(mu[picked_idx] - sigma[picked_idx])
    suggestions["predicted_high"] = to_target_units(mu[picked_idx] + sigma[picked_idx])
    suggestions["expected_improvement"] = picked_ei
    suggestions = suggestions.reset_index(drop=True)
    logger.debug(
        "suggest_next_experiments: target=%s, direction=%s, n_samples=%d, n_rows=%d, "
        "n_suggestions=%d, best_observed=%.4g, noise_level=%.3g, loo_r2=%.3f, kernel=%s",
        target_col,
        direction,
        n_samples,
        len(model_df),
        len(suggestions),
        best_observed,
        noise_level,
        loo_r2,
        gp.kernel_,
    )

    return {
        "target": target_col,
        "direction": direction,
        "log_target": log_target,
        "n_samples": n_samples,
        "n_rows": len(model_df),
        "n_features": n_features,
        "best_observed": best_observed,
        "incumbent": float(to_target_units(incumbent_norm * y_std + y_mean)),
        "noise_sd": float(np.sqrt(noise_level) * y_std),
        "length_scales": dict(zip(feature_cols, length_scales.tolist())),
        "length_scale_upper": LENGTH_SCALE_BOUNDS[1],
        "bounds": bounds,
        "integer_cols": [c for c in feature_cols if c in integer_set],
        "fixed": fixed,
        "n_rows_with_target": n_rows_with_target,
        "missing_by_column": missing,
        "warnings": warnings_list,
        "loo_r2": loo_r2,
        "loo_df": loo_df,
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
