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


def _complete_rows(
    df: pd.DataFrame, target_col: str, feature_cols: list, categorical_cols: list = ()
):
    """Rows with the target and every feature present, the number of rows that
    have the target at all, and {feature: rows dropped because it was missing},
    largest first - so a sparse column silently halving the data shows up."""
    cols = [*feature_cols, *categorical_cols]
    target = pd.to_numeric(df[target_col], errors="coerce")
    with_target = df.loc[target.notna(), cols].assign(**{target_col: target[target.notna()]})
    with_target = with_target[[target_col, *cols]]
    missing = {
        col: int(with_target[col].isna().sum()) for col in cols if with_target[col].isna().any()
    }
    missing = dict(sorted(missing.items(), key=lambda kv: kv[1], reverse=True))
    return with_target.dropna(), len(with_target), missing


def _check_categoricals(model_df: pd.DataFrame, categorical_cols: list) -> tuple:
    """Categorical columns with at least 2 levels among the complete rows (a
    single level carries no information), plus a note for each one dropped."""
    usable, notes = [], []
    for col in categorical_cols:
        if model_df[col].astype(str).nunique() >= 2:
            usable.append(col)
        else:
            notes.append(f"'{col}' has a single value in the rows used, so it was left out.")
    return usable, notes


def _design_matrix(model_df: pd.DataFrame, numeric_cols: list, categorical_cols: list):
    """Numeric columns as-is plus one 0/1 column per level of each categorical.

    Returns (X, feature_index {feature: [column positions in X]}, levels
    {categorical: [level, ...]}). Categoricals are matched as text, so 1 and
    "1" are the same level.
    """
    blocks, feature_index, levels = [], {}, {}
    position = 0
    for col in numeric_cols:
        blocks.append(model_df[col].to_numpy(dtype=float)[:, None])
        feature_index[col] = [position]
        position += 1
    for col in categorical_cols:
        values = model_df[col].astype(str).to_numpy()
        col_levels = sorted(set(values))
        levels[col] = col_levels
        blocks.append((values[:, None] == np.array(col_levels)[None, :]).astype(float))
        feature_index[col] = list(range(position, position + len(col_levels)))
        position += len(col_levels)
    return np.hstack(blocks), feature_index, levels


def _first_row_per_sample(groups: np.ndarray) -> np.ndarray:
    """Row positions of the first row of each sample, in order of appearance."""
    _, first = np.unique(groups, return_index=True)
    return np.sort(first)


# Parameter pairs at least this correlated (|Pearson r|, one row per sample)
# share their importance, which can make both look unimportant.
CORRELATED_PAIR_THRESHOLD = 0.7
N_PARTIAL_DEPENDENCE = 3
PARTIAL_DEPENDENCE_GRID = 20


def _correlated_pairs(per_sample: pd.DataFrame, numeric_cols: list) -> list:
    if len(numeric_cols) < 2:
        return []
    corr = per_sample[numeric_cols].corr()
    pairs = []
    for i, a in enumerate(numeric_cols):
        for b in numeric_cols[i + 1 :]:
            r = corr.loc[a, b]
            if np.isfinite(r) and abs(r) >= CORRELATED_PAIR_THRESHOLD:
                pairs.append((a, b, float(r)))
    return sorted(pairs, key=lambda p: abs(p[2]), reverse=True)


def _partial_dependence(model, X_ref, feature, feature_index, levels):
    """Average prediction over the reference rows as one feature is swept over
    its range (numeric) or set to each level (categorical), all else as measured."""
    idx = feature_index[feature]
    if feature in levels:
        grid, averages = list(levels[feature]), []
        for k in range(len(idx)):
            X_mod = X_ref.copy()
            X_mod[:, idx] = 0.0
            X_mod[:, idx[k]] = 1.0
            averages.append(float(model.predict(X_mod).mean()))
        return {"feature": feature, "kind": "categorical", "grid": grid, "average": averages}
    values = X_ref[:, idx[0]]
    unique = np.unique(values)
    if len(unique) <= PARTIAL_DEPENDENCE_GRID:
        grid = unique
    else:
        grid = np.unique(np.quantile(values, np.linspace(0.05, 0.95, PARTIAL_DEPENDENCE_GRID)))
    stacked = np.repeat(X_ref[None], len(grid), axis=0)
    stacked[:, :, idx[0]] = grid[:, None]
    preds = model.predict(stacked.reshape(-1, X_ref.shape[1])).reshape(len(grid), -1)
    return {
        "feature": feature,
        "kind": "numeric",
        "grid": grid.tolist(),
        "average": preds.mean(axis=1).tolist(),
    }


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
        "with the batch, its effect cannot be told apart from the batch effect. "
        "Adding 'batch' as a categorical parameter in the Analysis Data tab "
        "models it."
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
    categorical_cols: list = None,
) -> dict:
    """
    Fit a RandomForestRegressor to predict target_col from the dataset's other
    parameters, and report cross-validated performance, permutation
    importances, partial dependence and strongly correlated parameter pairs.

    Validation: repeated K-fold cross-validation with folds split by sample
    (sample_id), so pixels or repeats of one sample are never in both the
    training and the test part - otherwise the model "predicts" a pixel from
    its neighbours on the same sample and R² is inflated. Every row gets an
    out-of-fold prediction in every repeat; R² and RMSE are computed on those
    and reported as mean and SD over repeats. Training-set R² is never reported.

    Importance: permutation importance on the held-out folds - how much the
    cross-validated R² drops when one parameter's values are shuffled (all
    level columns of a categorical together). Unlike the forest's built-in
    (impurity) importance it is not biased towards continuous or many-valued
    parameters and is measured on unseen data. It is ~0 (or slightly negative)
    for a parameter that does not help; correlated parameters share their
    importance, so both can look small - see correlated_pairs.

    categorical_cols: text-like parameters (material, batch, ...), one-hot
    encoded. Ones with a single value in the rows used are left out with a note.

    Partial dependence: a forest refit on all rows; for each of the top
    N_PARTIAL_DEPENDENCE parameters, the average prediction over the measured
    samples as that parameter alone is swept. Where it is strongly correlated
    with another, the sweep reaches combinations never measured.

    Returns a dict: target, n_samples (distinct samples), n_rows, n_features,
    n_folds, n_repeats, r2, r2_sd, rmse, rmse_sd, importances (list of
    (feature, mean R² drop, SD over repeats), sorted descending),
    partial_dependence (list of {"feature", "kind", "grid", "average"}),
    correlated_pairs (list of (a, b, r)), n_rows_with_target,
    missing_by_column ({feature: rows dropped for it}), warnings (list of str).
    """
    from sklearn.ensemble import RandomForestRegressor

    numeric_df = df.select_dtypes(include="number")
    if target_col not in numeric_df.columns:
        raise ValueError(f"'{target_col}' is not a numeric column in the current dataset.")

    if feature_cols is None:
        feature_cols = select_numeric_feature_columns(df, target_col)
    categorical_cols = [c for c in (categorical_cols or []) if c != target_col]

    if not feature_cols and not categorical_cols:
        raise ValueError("No usable feature parameters found besides the target.")

    model_df, n_rows_with_target, missing = _complete_rows(
        df, target_col, feature_cols, categorical_cols
    )
    categorical_cols, warnings_list = _check_categoricals(model_df, categorical_cols)
    features = [*feature_cols, *categorical_cols]
    if not features:
        raise ValueError("No usable feature parameters found besides the target.")
    groups = sample_groups(df, model_df.index)
    unique_groups = np.unique(groups)
    n_samples = len(unique_groups)
    if n_samples < MIN_SAMPLES_RANDOM_FOREST:
        raise ValueError(
            f"Only {n_samples} samples with complete data (need at least "
            f"{MIN_SAMPLES_RANDOM_FOREST}) - load more batches, or pick a target/feature "
            "set with fewer missing values."
        )

    X, feature_index, levels = _design_matrix(model_df, feature_cols, categorical_cols)
    y = model_df[target_col].to_numpy(dtype=float)
    n_rows, n_columns = X.shape
    n_features = len(features)
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
            for j, feature in enumerate(features):
                idx = feature_index[feature]
                for p in range(n_permutations):
                    order = rng.permutation(len(X_test))
                    shuffled[j, p][:, idx] = X_test[order][:, idx]
            preds = model.predict(shuffled.reshape(-1, n_columns))
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
                features, importance_runs.mean(axis=0), importance_runs.std(axis=0)
            )
        ),
        key=lambda item: item[1],
        reverse=True,
    )

    final_model = RandomForestRegressor(n_estimators=n_estimators, random_state=random_state)
    final_model.fit(X, y)
    first_rows = _first_row_per_sample(groups)
    partial_dependence = [
        _partial_dependence(final_model, X[first_rows], name, feature_index, levels)
        for name, _, _ in importances[:N_PARTIAL_DEPENDENCE]
    ]
    correlated_pairs = _correlated_pairs(model_df.iloc[first_rows], feature_cols)

    if n_samples < RECOMMENDED_SAMPLES_RANDOM_FOREST:
        warnings_list.append(
            f"Only {n_samples} samples: R² and the importance ranking can change a lot "
            f"with a few more samples, so treat them as a first hint (aim for "
            f"{RECOMMENDED_SAMPLES_RANDOM_FOREST}+)."
        )
    if correlated_pairs:
        listed = ", ".join(f"{a} / {b} (r = {r:.2f})" for a, b, r in correlated_pairs[:3])
        warnings_list.append(
            f"Strongly correlated parameters: {listed}. They share their importance, "
            "so each can look less important than it is, and the data cannot tell "
            "which of them matters. Varying them independently in the next batch would."
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
        "partial_dependence": partial_dependence,
        "correlated_pairs": correlated_pairs,
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


def is_measured_parameter(col: str, measured_names) -> bool:
    """True if col is one of measured_names, or one with the process-type
    suffix the merge adds ("<name>_<process type>")."""
    return any(col == name or col.startswith(f"{name}_") for name in measured_names)


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


def _gp_kernel_classes():
    """Two small sklearn kernels the GP needs when a batch column is modelled,
    defined lazily so importing this module stays free of sklearn."""
    from sklearn.gaussian_process.kernels import Hyperparameter, Kernel

    class OnColumns(Kernel):
        """Apply `kernel` to the given input columns only (sklearn kernels always
        see every column). Mirrors sklearn's Exponentiation wrapper for the
        hyperparameter plumbing."""

        def __init__(self, kernel, columns):
            self.kernel = kernel
            self.columns = columns

        def get_params(self, deep=True):
            params = {"kernel": self.kernel, "columns": self.columns}
            if deep:
                for key, value in self.kernel.get_params().items():
                    params["kernel__" + key] = value
            return params

        @property
        def hyperparameters(self):
            return [
                Hyperparameter("kernel__" + h.name, h.value_type, h.bounds, h.n_elements)
                for h in self.kernel.hyperparameters
            ]

        @property
        def theta(self):
            return self.kernel.theta

        @theta.setter
        def theta(self, theta):
            self.kernel.theta = theta

        @property
        def bounds(self):
            return self.kernel.bounds

        def __call__(self, X, Y=None, eval_gradient=False):
            X = np.asarray(X)[:, self.columns]
            if Y is not None:
                Y = np.asarray(Y)[:, self.columns]
            return self.kernel(X, Y, eval_gradient=eval_gradient)

        def diag(self, X):
            return self.kernel.diag(np.asarray(X)[:, self.columns])

        def is_stationary(self):
            return self.kernel.is_stationary()

        def __repr__(self):
            return f"OnColumns({self.kernel!r})"

    class BatchOffset(Kernel):
        """offset_variance if two rows share a batch code, else 0: every batch
        gets its own constant offset, estimated from the data. Code -1 means
        "no batch" and matches nothing, not even itself - used to predict the
        process effect alone, without any batch's offset."""

        def __init__(self, offset_variance=0.1, offset_variance_bounds=(1e-6, 1e1), column=-1):
            self.offset_variance = offset_variance
            self.offset_variance_bounds = offset_variance_bounds
            self.column = column

        @property
        def hyperparameter_offset_variance(self):
            return Hyperparameter("offset_variance", "numeric", self.offset_variance_bounds)

        def __call__(self, X, Y=None, eval_gradient=False):
            a = np.asarray(X)[:, self.column]
            b = a if Y is None else np.asarray(Y)[:, self.column]
            K = self.offset_variance * ((a[:, None] == b[None, :]) & (a[:, None] >= 0))
            if eval_gradient:
                if self.hyperparameter_offset_variance.fixed:
                    return K, np.empty((len(a), len(a), 0))
                return K, K[:, :, None]
            return K

        def diag(self, X):
            return self.offset_variance * (np.asarray(X)[:, self.column] >= 0)

        def is_stationary(self):
            return False

        def __repr__(self):
            return f"BatchOffset(offset_variance={self.offset_variance:.3g})"

    return OnColumns, BatchOffset


CONSTRAINT_OPS = ("<=", ">=")
BATCH_OFFSET_BOUNDS = (1e-6, 1e1)


def _build_gp(n_process_cols: int, with_batch: bool, random_state: int):
    """GP with ConstantKernel * Matern(ARD) [+ BatchOffset] + WhiteKernel. With
    a batch column, the Matern sees only the process columns and the batch code
    sits in the last column."""
    from sklearn.gaussian_process import GaussianProcessRegressor
    from sklearn.gaussian_process.kernels import ConstantKernel, Matern, WhiteKernel

    matern = Matern(
        length_scale=np.ones(n_process_cols), length_scale_bounds=LENGTH_SCALE_BOUNDS, nu=2.5
    )
    if with_batch:
        OnColumns, BatchOffset = _gp_kernel_classes()
        signal = ConstantKernel(1.0, SIGNAL_VARIANCE_BOUNDS) * OnColumns(
            matern, list(range(n_process_cols))
        ) + BatchOffset(0.1, BATCH_OFFSET_BOUNDS, column=n_process_cols)
    else:
        signal = ConstantKernel(1.0, SIGNAL_VARIANCE_BOUNDS) * matern
    kernel = signal + WhiteKernel(noise_level=0.5, noise_level_bounds=NOISE_LEVEL_BOUNDS)
    return GaussianProcessRegressor(
        kernel=kernel, normalize_y=False, n_restarts_optimizer=5, random_state=random_state
    )


def _fit_quietly(gp, X, y):
    """A hyperparameter pinned against its bound (e.g. a length scale at the upper
    bound = "no detectable effect") is informative here, not an error, so the
    sklearn ConvergenceWarning about it is suppressed and reported instead."""
    from sklearn.exceptions import ConvergenceWarning

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", category=ConvergenceWarning)
        gp.fit(X, y)
    return gp


def _kernel_parts(kernel_, with_batch: bool) -> dict:
    """Pull the fitted pieces out of _build_gp's kernel structure."""
    signal = kernel_.k1
    if with_batch:
        product, batch = signal.k1, signal.k2
        return {
            "signal": signal,
            "signal_variance": float(product.k1.constant_value),
            "length_scales": np.atleast_1d(product.k2.kernel.length_scale),
            "offset_variance": float(batch.offset_variance),
            "noise_level": float(kernel_.k2.noise_level),
        }
    return {
        "signal": signal,
        "signal_variance": float(signal.k1.constant_value),
        "length_scales": np.atleast_1d(signal.k2.length_scale),
        "offset_variance": 0.0,
        "noise_level": float(kernel_.k2.noise_level),
    }


def _posterior(kernel, noise_level, X_train, y_train, alpha=None):
    """A fixed-hyperparameter GP with the measurement noise in alpha, so predict()
    returns the latent (noise-free) std. alpha can be overridden per point."""
    from sklearn.gaussian_process import GaussianProcessRegressor

    gp = GaussianProcessRegressor(kernel=kernel, optimizer=None, normalize_y=False)
    gp.set_params(alpha=np.full(len(y_train), noise_level) if alpha is None else alpha)
    return gp.fit(X_train, y_train)


def _log_probability_within(posterior, points, limit, op) -> np.ndarray:
    """log P(latent value <= limit) (op "<=") or >= limit, at points. In log
    space so far-infeasible candidates still rank against each other instead
    of all underflowing to 0."""
    from scipy.stats import norm

    m, s = posterior.predict(points, return_std=True)
    z = (limit - m) / np.maximum(s, 1e-9)
    return norm.logcdf(z) if op == "<=" else norm.logsf(z)


def _one_hot(values, levels) -> np.ndarray:
    values = np.asarray(values).astype(str)
    return (values[:, None] == np.array(levels)[None, :]).astype(float)


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
    categorical_cols: list = None,
    batch_col: str = None,
    constraints: list = None,
    avoid: pd.DataFrame = None,
    predict_at: pd.DataFrame = None,
) -> dict:
    """
    Fit a Gaussian Process surrogate on already-measured samples and suggest a
    batch of n_suggestions parameter combinations to measure next, chosen by
    Expected Improvement (EI) over quasi-random (Sobol) candidates inside the
    search space.

    Model: numeric inputs min-max scaled to [0, 1] over the search space (plus
    the observed range, so older points outside new bounds still scale
    sensibly), categorical inputs one-hot encoded, target standardised (after
    log10 when log_target); kernel ConstantKernel * Matern(nu=2.5) with one
    length scale per input column (ARD) + WhiteKernel, hyperparameters fit with
    restarts. A learned noise term matters: with replicate scatter comparable
    to the effects of interest, a near-noiseless GP would put the optimum on top
    of the single luckiest sample.

    categorical_cols: text-like parameters (material, solvent, ...). Candidates
    only take levels already in the data. A categorical's length scale is the
    smallest over its levels' one-hot columns.

    batch_col: model a constant offset per batch (day, precursor lot) instead of
    letting it leak into the parameter effects: a BatchOffset kernel term
    with its own fitted variance. Predictions, the incumbent and EI are for the
    process effect alone (a new batch with an unknown offset of about
    ±batch_offset_sd). Ignored, with a note, if the rows span a single batch.

    constraints: [{"col", "op" ("<=" or ">="), "value"}] on other result
    columns, e.g. dark current <= 1e-9. Each gets its own GP (same inputs, rows
    where that column is measured); the acquisition is EI times the probability
    of meeting every constraint, and the incumbent is the best predicted value
    among measured samples predicted to be feasible. With no feasible sample
    yet, candidates are ranked by probability of feasibility alone.

    avoid: feature-column rows (e.g. picks from another call) - candidates
    within min_distance of these are excluded.

    predict_at: feature-column rows to also return the posterior mean at
    (target units, process effect only), as "predictions_at".

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
        fixed: {col: value} - hold a parameter at one value (a level, for a
            categorical) in every suggestion.

    Returns a dict: target, direction, log_target, n_samples (distinct
    samples), n_rows, n_features, best_observed, incumbent (best predicted at
    measured points), noise_sd (fitted observation noise, in target units or
    log10 units), length_scales ({col: scaled length scale}),
    length_scale_upper (the bound; at it = no detectable effect), bounds,
    integer_cols, categorical_cols, batch_col, n_batches, batch_offset_sd
    (target or log10 units), constraints, fixed, n_rows_with_target,
    missing_by_column, warnings (data and fit diagnostics, list of str), fit_warnings (the
    fit-diagnostic subset of warnings), loo_r2
    (leave-one-sample-out R², model units), loo_df (sample_id, observed,
    predicted, predicted_low, predicted_high per row; the range is ±1 SD for a
    single measurement), suggestions (DataFrame: feature_cols +
    categorical_cols + predicted_<target>, predicted_low, predicted_high (±1 SD
    of the predicted mean, excluding measurement noise), expected_improvement
    (times the probability of feasibility with constraints), and
    probability_feasible with constraints; in pick order. predicted_* are from
    the GP fit on real data only; expected_improvement is the value at the
    moment of picking, i.e. given the earlier picks).
    """
    if direction not in ("maximize", "minimize"):
        raise ValueError("direction must be 'maximize' or 'minimize'")
    if not 1 <= n_suggestions <= MAX_BO_SUGGESTIONS:
        raise ValueError(f"n_suggestions must be between 1 and {MAX_BO_SUGGESTIONS}.")

    numeric_df = df.select_dtypes(include="number")
    if target_col not in numeric_df.columns:
        raise ValueError(f"'{target_col}' is not a numeric column in the current dataset.")

    if feature_cols is None:
        feature_cols = select_numeric_feature_columns(df, target_col)
    feature_cols = list(feature_cols)
    categorical_cols = [
        c for c in (categorical_cols or []) if c not in (target_col, batch_col, *feature_cols)
    ]
    constraints = list(constraints or [])
    for c in constraints:
        if c["op"] not in CONSTRAINT_OPS:
            raise ValueError(f"Constraint operator must be one of {CONSTRAINT_OPS}.")
        if c["col"] not in numeric_df.columns:
            raise ValueError(f"Constraint column '{c['col']}' is not a numeric column.")
        if c["col"] == target_col:
            raise ValueError("A constraint cannot be on the target itself; use the goal instead.")

    if not feature_cols and not categorical_cols:
        raise ValueError("No usable feature parameters found besides the target.")

    extra_cols = [*categorical_cols, *([batch_col] if batch_col else [])]
    model_df, n_rows_with_target, missing = _complete_rows(df, target_col, feature_cols, extra_cols)
    categorical_cols, warnings_list = _check_categoricals(model_df, categorical_cols)
    if not feature_cols and not categorical_cols:
        raise ValueError("No usable feature parameters found besides the target.")
    groups = sample_groups(df, model_df.index)
    n_samples = len(np.unique(groups))
    if n_samples < MIN_SAMPLES_BAYESIAN_OPT:
        raise ValueError(
            f"Only {n_samples} samples with complete data (need at least "
            f"{MIN_SAMPLES_BAYESIAN_OPT}) - load more batches, or pick a target/feature "
            "set with fewer missing values."
        )

    X = model_df[feature_cols].to_numpy(dtype=float).reshape(len(model_df), len(feature_cols))
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
    n_numeric = len(feature_cols)

    def to_target_units(values):
        return 10.0**values if log_target else values

    # ---- Search space -----------------------------------------------------
    bounds = dict(bounds or {})
    fixed = dict(fixed or {})
    if integer_cols is None:
        integer_cols = detect_integer_columns(model_df, feature_cols)
    integer_set = set(integer_cols) & set(feature_cols)
    low = np.empty(n_numeric)
    high = np.empty(n_numeric)
    for i, col in enumerate(feature_cols):
        lo, hi = bounds.get(col, (X[:, i].min(), X[:, i].max()))
        if col in integer_set:
            lo, hi = np.ceil(lo - 1e-9), np.floor(hi + 1e-9)
        if lo > hi:
            raise ValueError(f"Search range for '{col}' is empty (min {lo:g} > max {hi:g}).")
        low[i], high[i] = lo, hi
        bounds[col] = (float(lo), float(hi))
    levels = {c: sorted(model_df[c].astype(str).unique()) for c in categorical_cols}
    for col, value in fixed.items():
        if col in levels:
            if str(value) not in levels[col]:
                raise ValueError(f"'{value}' is not a level of '{col}' in the data.")
        elif col not in feature_cols:
            raise ValueError(f"Fixed parameter '{col}' is not one of the features.")

    # ---- Batch -------------------------------------------------------------------
    n_batches = 0
    if batch_col:
        batch_values = model_df[batch_col].astype(str).to_numpy()
        batch_levels = sorted(set(batch_values))
        n_batches = len(batch_levels)
        if n_batches < 2:
            warnings_list.append(
                f"All rows come from one '{batch_col}' value, so no batch offset was modelled."
            )
            batch_col = None
        else:
            batch_codes = np.searchsorted(batch_levels, batch_values).astype(float)
    if not batch_col:
        warnings_list += _batch_warning(df, model_df.index)

    n_free = sum(c not in fixed for c in [*feature_cols, *categorical_cols])
    recommended = 2 * (n_free + 1)
    if n_samples < recommended:
        warnings_list.append(
            f"Only {n_samples} samples for {n_free} free parameter(s); below about "
            f"{recommended} the model mostly returns its prior and the suggestions are "
            "weakly informed. A space-filling design from the Design of Experiments tool "
            "is usually a better next step, or fix or uncheck some parameters."
        )

    # ---- Inputs ---------------------------------------------------------------
    scale_low = np.minimum(low, X.min(axis=0)) if n_numeric else low
    scale_span = (np.maximum(high, X.max(axis=0)) - scale_low) if n_numeric else high
    scale_span = np.where(scale_span == 0, 1.0, scale_span)

    def process_unit(numeric_values, categorical_values):
        """[0, 1]-scaled numeric columns followed by one-hot categoricals."""
        parts = [(numeric_values - scale_low) / scale_span]
        parts += [_one_hot(categorical_values[c], levels[c]) for c in categorical_cols]
        return np.hstack(parts)

    def with_batch_code(unit, codes):
        if not batch_col:
            return unit
        return np.hstack([unit, np.broadcast_to(codes, (len(unit),))[:, None]])

    X_process = process_unit(X, {c: model_df[c].to_numpy() for c in categorical_cols})
    n_process_cols = X_process.shape[1]
    X_fit = with_batch_code(X_process, batch_codes if batch_col else None)
    # Measured points without their batch offset: the process effect alone.
    X_ref = with_batch_code(X_process, -1.0)

    y_mean, y_std = y.mean(), y.std()
    y_std = y_std if y_std > 0 else 1.0
    y_norm = (y - y_mean) / y_std

    # ---- Fit ---------------------------------------------------------------
    gp = _fit_quietly(_build_gp(n_process_cols, bool(batch_col), random_state), X_fit, y_norm)
    parts = _kernel_parts(gp.kernel_, bool(batch_col))
    signal_kernel, noise_level = parts["signal"], parts["noise_level"]
    ls_columns = parts["length_scales"]
    length_scales = {col: float(ls_columns[i]) for i, col in enumerate(feature_cols)}
    position = n_numeric
    for col in categorical_cols:
        length_scales[col] = float(ls_columns[position : position + len(levels[col])].min())
        position += len(levels[col])

    # ---- Model check: leave one sample out --------------------------------------
    loo_mean, loo_std = _grouped_loo(signal_kernel, noise_level, X_fit, y_norm, groups)
    loo_mean = loo_mean * y_std + y_mean
    loo_std = loo_std * y_std
    loo_r2 = _r2(y, loo_mean)
    loo_df = pd.DataFrame(
        {
            "sample_id": groups,
            "observed": y_raw,
            "predicted": to_target_units(loo_mean),
            "predicted_low": to_target_units(loo_mean - loo_std),
            "predicted_high": to_target_units(loo_mean + loo_std),
        }
    )
    fit_warnings = _fit_warnings(parts["signal_variance"], noise_level, length_scales, loo_r2)
    warnings_list += fit_warnings

    # ---- Candidates ----------------------------------------------------------
    rng = np.random.default_rng(random_state)
    free_numeric = [i for i, col in enumerate(feature_cols) if col not in fixed]
    free_categorical = [c for c in categorical_cols if c not in fixed]
    unit_draws = _sobol_unit(n_candidates, len(free_numeric) + len(free_categorical), rng)
    n_candidates = len(unit_draws)
    candidates = np.empty((n_candidates, n_numeric))
    for i, col in enumerate(feature_cols):
        if col in fixed:
            candidates[:, i] = fixed[col]
            continue
        u = unit_draws[:, free_numeric.index(i)]
        if col in integer_set:
            n_levels = high[i] - low[i] + 1
            candidates[:, i] = np.minimum(low[i] + np.floor(u * n_levels), high[i])
        else:
            candidates[:, i] = low[i] + u * (high[i] - low[i])
    candidate_levels = {}
    for col in categorical_cols:
        if col in fixed:
            candidate_levels[col] = np.full(n_candidates, str(fixed[col]), dtype=object)
            continue
        u = unit_draws[:, len(free_numeric) + free_categorical.index(col)]
        index = np.minimum((u * len(levels[col])).astype(int), len(levels[col]) - 1)
        candidate_levels[col] = np.array(levels[col], dtype=object)[index]
    candidates_process = process_unit(candidates, candidate_levels)
    candidates_fit = with_batch_code(candidates_process, -1.0)

    available = np.ones(n_candidates, dtype=bool)
    if avoid is not None and len(avoid):
        avoid_unit = process_unit(
            avoid[feature_cols].to_numpy(dtype=float).reshape(len(avoid), n_numeric),
            {c: avoid[c].to_numpy() for c in categorical_cols},
        )
        for point in avoid_unit:
            available &= np.linalg.norm(candidates_process - point, axis=1) > min_distance

    # ---- Constraints: probability of feasibility ---------------------------------
    log_feasible = np.zeros(n_candidates)
    log_feasible_ref = np.zeros(len(y))
    for c in constraints:
        values = pd.to_numeric(df.loc[model_df.index, c["col"]], errors="coerce").to_numpy()
        known = np.isfinite(values)
        if len(np.unique(groups[known])) < MIN_SAMPLES_BAYESIAN_OPT:
            raise ValueError(
                f"Constraint '{c['col']}' is measured on fewer than "
                f"{MIN_SAMPLES_BAYESIAN_OPT} of the samples used."
            )
        c_mean, c_std = values[known].mean(), values[known].std() or 1.0
        c_gp = _fit_quietly(
            _build_gp(n_process_cols, bool(batch_col), random_state),
            X_fit[known],
            (values[known] - c_mean) / c_std,
        )
        c_parts = _kernel_parts(c_gp.kernel_, bool(batch_col))
        c_post = _posterior(
            c_parts["signal"],
            c_parts["noise_level"],
            X_fit[known],
            (values[known] - c_mean) / c_std,
        )
        limit = (c["value"] - c_mean) / c_std
        log_feasible += _log_probability_within(c_post, candidates_fit, limit, c["op"])
        log_feasible_ref += _log_probability_within(c_post, X_ref, limit, c["op"])
    p_feasible = np.exp(log_feasible)

    # ---- Posterior for EI --------------------------------------------------------
    believer = _posterior(signal_kernel, noise_level, X_fit, y_norm)
    mu_step, sigma_step = believer.predict(candidates_fit, return_std=True)
    sigma_step = np.maximum(sigma_step, 1e-9)
    mu = mu_step * y_std + y_mean
    sigma = sigma_step * y_std

    fitted_at_samples = believer.predict(X_ref)
    feasible_ref = log_feasible_ref >= np.log(0.5)
    if constraints and not feasible_ref.any():
        incumbent_norm = None
        warnings_list.append(
            "No measured sample is predicted to meet the constraints yet, so the "
            "suggestions aim at meeting them first (highest probability of "
            "feasibility), not at improving the target."
        )
    else:
        pool = fitted_at_samples[feasible_ref]
        incumbent_norm = pool.max() if direction == "maximize" else pool.min()
    best_observed = y_raw.max() if direction == "maximize" else y_raw.min()

    # ---- Kriging Believer batch ---------------------------------------------
    X_train, y_train = X_fit, y_norm
    alpha = np.full(len(y_norm), noise_level)
    incumbent = incumbent_norm
    picked_idx, picked_score = [], []
    for _ in range(min(n_suggestions, n_candidates)):
        if incumbent is None:
            score = log_feasible.copy()
        else:
            score = _expected_improvement(mu_step, sigma_step, incumbent, direction) * p_feasible
        score[~available] = -np.inf
        idx = int(np.argmax(score))
        if not np.isfinite(score[idx]):
            break
        picked_idx.append(idx)
        if incumbent is None:
            picked_score.append(0.0)
        else:
            picked_score.append(max(float(score[idx]), 0.0) * y_std)

        distance = np.linalg.norm(candidates_process - candidates_process[idx], axis=1)
        available &= distance > min_distance
        available[idx] = False

        fake_y = mu_step[idx]
        X_train = np.vstack([X_train, candidates_fit[idx]])
        y_train = np.append(y_train, fake_y)
        alpha = np.append(alpha, 1e-8)
        if incumbent is not None and p_feasible[idx] >= 0.5:
            incumbent = (
                max(incumbent, fake_y) if direction == "maximize" else min(incumbent, fake_y)
            )
        if len(picked_idx) < n_suggestions:
            believer = _posterior(signal_kernel, noise_level, X_train, y_train, alpha)
            mu_step, sigma_step = believer.predict(candidates_fit, return_std=True)
            sigma_step = np.maximum(sigma_step, 1e-9)

    suggestions = pd.DataFrame(candidates[picked_idx], columns=feature_cols)
    for col in integer_set:
        suggestions[col] = suggestions[col].round().astype(int)
    for col in categorical_cols:
        suggestions[col] = candidate_levels[col][picked_idx]
    suggestions[f"predicted_{target_col}"] = to_target_units(mu[picked_idx])
    suggestions["predicted_low"] = to_target_units(mu[picked_idx] - sigma[picked_idx])
    suggestions["predicted_high"] = to_target_units(mu[picked_idx] + sigma[picked_idx])
    suggestions["expected_improvement"] = picked_score
    if constraints:
        suggestions["probability_feasible"] = p_feasible[picked_idx]
    suggestions = suggestions.reset_index(drop=True)

    predictions_at = None
    if predict_at is not None and len(predict_at):
        at_fit = with_batch_code(
            process_unit(
                predict_at[feature_cols].to_numpy(dtype=float).reshape(len(predict_at), n_numeric),
                {c: predict_at[c].to_numpy() for c in categorical_cols},
            ),
            -1.0,
        )
        at_post = _posterior(signal_kernel, noise_level, X_fit, y_norm)
        predictions_at = to_target_units(at_post.predict(at_fit) * y_std + y_mean)
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
        "n_features": n_numeric + len(categorical_cols),
        "best_observed": best_observed,
        "incumbent": (
            None
            if incumbent_norm is None
            else float(to_target_units(incumbent_norm * y_std + y_mean))
        ),
        "noise_sd": float(np.sqrt(noise_level) * y_std),
        "length_scales": length_scales,
        "length_scale_upper": LENGTH_SCALE_BOUNDS[1],
        "bounds": bounds,
        "integer_cols": [c for c in feature_cols if c in integer_set],
        "categorical_cols": categorical_cols,
        "batch_col": batch_col,
        "n_batches": n_batches,
        "batch_offset_sd": float(np.sqrt(parts["offset_variance"]) * y_std),
        "constraints": constraints,
        "fixed": fixed,
        "n_rows_with_target": n_rows_with_target,
        "missing_by_column": missing,
        "warnings": warnings_list,
        "fit_warnings": fit_warnings,
        "loo_r2": loo_r2,
        "loo_df": loo_df,
        "suggestions": suggestions,
        "predictions_at": predictions_at,
    }


def _per_sample_objectives(df: pd.DataFrame, objectives: list) -> pd.DataFrame:
    """Objective columns rescaled to [0, 1] with 1 = best, using the per-sample
    mean so samples with more pixels don't stretch the range."""
    cols = [col for col, _ in objectives]
    if "sample_id" in df.columns:
        means = df.groupby("sample_id")[cols].transform("mean")
    else:
        means = df[cols]
    scaled = pd.DataFrame(index=df.index)
    for col, direction in objectives:
        values = pd.to_numeric(means[col], errors="coerce")
        span = values.max() - values.min()
        unit = (values - values.min()) / (span if span > 0 else 1.0)
        scaled[col] = unit if direction == "maximize" else 1.0 - unit
    return scaled


def suggest_pareto_experiments(
    df: pd.DataFrame,
    objectives: list,
    n_suggestions: int = 5,
    random_state: int = 42,
    **kwargs,
) -> dict:
    """
    Suggest a batch spread along the trade-off between two (or more) objectives
    - ParEGO-style (Knowles 2006): each suggestion optimises a different
    weighting of the objectives, scaled to [0, 1] with 1 = best, combined by the
    augmented Chebyshev scalarisation: minimise the largest weighted shortfall
    from the best, max_k(w_k (1 - f_k)) + 0.05 sum_k(w_k (1 - f_k)), which
    (unlike a weighted sum) can reach every point of a concave front. A high
    weight on an objective penalises falling short on it, so favours it.
    Weights run evenly from favouring the first objective to favouring the
    last. Each pick is excluded for the following ones (avoid=).

    objectives: [(col, "maximize"|"minimize"), ...], at least two.
    kwargs: passed through to suggest_next_experiments (feature_cols, bounds,
    fixed, categorical_cols, batch_col, constraints, ...).

    Returns a dict: objectives, n_samples, weights, warnings (data warnings, union over picks,
    first-seen order), suggestions (feature columns + weight_<col> per
    objective + predicted_<col> for each objective from its own GP).
    """
    if len(objectives) < 2:
        raise ValueError("Pick at least two objectives.")
    if len({col for col, _ in objectives}) < len(objectives):
        raise ValueError("Pick different objectives.")
    if not 1 <= n_suggestions <= MAX_BO_SUGGESTIONS:
        raise ValueError(f"n_suggestions must be between 1 and {MAX_BO_SUGGESTIONS}.")

    n_obj = len(objectives)
    if n_suggestions == 1:
        weight_sets = [np.full(n_obj, 1.0 / n_obj)]
    else:
        t = np.linspace(0.05, 0.95, n_suggestions)
        if n_obj == 2:
            weight_sets = [np.array([1 - ti, ti]) for ti in t]
        else:
            rng = np.random.default_rng(random_state)
            weight_sets = list(rng.dirichlet(np.ones(n_obj), n_suggestions))

    scaled = _per_sample_objectives(df, objectives)
    rows, warnings_seen, n_samples = [], [], None
    avoid = None
    feature_out = None
    for k, weights in enumerate(weight_sets):
        shortfall = (1.0 - scaled.to_numpy()) * weights
        combined = -(shortfall.max(axis=1) + 0.05 * shortfall.sum(axis=1))
        work = df.assign(_pareto_score=combined)
        result = suggest_next_experiments(
            work,
            "_pareto_score",
            direction="maximize",
            n_suggestions=1,
            random_state=random_state + k,
            avoid=avoid,
            **kwargs,
        )
        n_samples = result["n_samples"]
        # Fit diagnostics describe the internal combined score, not either
        # objective, so only the data warnings are passed on.
        for w in result["warnings"]:
            if w in result["fit_warnings"]:
                continue
            if w not in warnings_seen:
                warnings_seen.append(w)
        pick = result["suggestions"]
        if pick.empty:
            continue
        feature_out = [
            c
            for c in pick.columns
            if c
            not in (
                "predicted__pareto_score",
                "predicted_low",
                "predicted_high",
                "expected_improvement",
                "probability_feasible",
            )
        ]
        row = pick.iloc[0][feature_out].to_dict()
        for (col, _), w in zip(objectives, weights):
            row[f"weight_{col}"] = float(w)
        rows.append(row)
        avoid = pd.DataFrame(rows)[feature_out]

    suggestions = pd.DataFrame(rows)
    # Each objective's own prediction at the picks, for the table.
    if not suggestions.empty:
        for col, direction in objectives:
            own = suggest_next_experiments(
                df,
                col,
                direction=direction,
                n_suggestions=1,
                random_state=random_state,
                predict_at=suggestions,
                **kwargs,
            )
            suggestions[f"predicted_{col}"] = own["predictions_at"]
    return {
        "objectives": objectives,
        "n_samples": n_samples,
        "weights": [w.tolist() for w in weight_sets],
        "warnings": warnings_seen,
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
