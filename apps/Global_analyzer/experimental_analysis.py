"""
Experimental Analysis Module

Five exploratory analyses over the shared analysis dataset - PCA, a Pareto-front
trade-off finder, Isolation-Forest outlier detection, a process-drift-over-time
trend check, and one-way ANOVA. Zero widget imports (consistent with
ml_analysis.py/data_manager.py/plot_manager.py): this module only computes and
returns plain data structures (dicts/DataFrames); rendering (Markdown text,
Plotly figures) is the caller's job.

These are intentionally simple, fixed-configuration implementations for a
first look at whether each technique is useful on this data - not a tunable
statistics workbench.
"""

import logging

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

MIN_ROWS_PCA = 5
MIN_ROWS_OUTLIER = 10
MIN_ROWS_PARETO = 3
MIN_ROWS_DRIFT = 3
MIN_GROUP_SIZE_ANOVA = 2


def run_pca(df: pd.DataFrame, feature_cols: list, n_components: int = 2) -> dict:
    """
    Standardize feature_cols and fit a PCA to see which parameters vary/cluster
    together.

    Returns a dict: feature_cols, n_samples, explained_variance_ratio (list,
    one per component), loadings_df (component x feature_cols, how much each
    original column contributes to each component), scores_df (sample_id +
    PC1..PCn, one row per complete sample).
    """
    from sklearn.decomposition import PCA
    from sklearn.preprocessing import StandardScaler

    numeric_df = df.select_dtypes(include="number")
    usable_cols = [
        col
        for col in feature_cols
        if col in numeric_df.columns and numeric_df[col].dropna().nunique() > 1
    ]
    if len(usable_cols) < 2:
        raise ValueError("Need at least 2 varying numeric parameters to run PCA.")

    model_df = df[usable_cols].dropna()
    if len(model_df) < MIN_ROWS_PCA:
        raise ValueError(
            f"Only {len(model_df)} complete rows available (need at least "
            f"{MIN_ROWS_PCA}) - load more batches, or check more parameters "
            "with fewer missing values."
        )

    n_components = min(n_components, len(usable_cols), len(model_df))

    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(model_df.to_numpy())

    pca = PCA(n_components=n_components)
    scores = pca.fit_transform(X_scaled)

    component_names = [f"PC{i + 1}" for i in range(n_components)]
    scores_df = pd.DataFrame(scores, columns=component_names, index=model_df.index)
    if "sample_id" in df.columns:
        scores_df.insert(0, "sample_id", df.loc[model_df.index, "sample_id"].to_numpy())
    scores_df = scores_df.reset_index(drop=True)

    loadings_df = pd.DataFrame(pca.components_, columns=usable_cols, index=component_names)

    logger.debug(
        "run_pca: n_samples=%d, n_features=%d, explained_variance_ratio=%s",
        len(model_df),
        len(usable_cols),
        pca.explained_variance_ratio_,
    )

    return {
        "feature_cols": usable_cols,
        "n_samples": len(model_df),
        "explained_variance_ratio": pca.explained_variance_ratio_.tolist(),
        "loadings_df": loadings_df,
        "scores_df": scores_df,
    }


def find_pareto_front(
    df: pd.DataFrame,
    target_a: str,
    target_b: str,
    direction_a: str = "maximize",
    direction_b: str = "maximize",
) -> dict:
    """
    Find the Pareto-optimal front between two objectives: points where you
    can't improve one without making the other worse.

    Returns a dict: target_a, target_b, n_samples, n_on_front, result_df (all
    complete rows plus an is_pareto_optimal bool column).
    """
    for direction in (direction_a, direction_b):
        if direction not in ("maximize", "minimize"):
            raise ValueError("direction must be 'maximize' or 'minimize'")

    if target_a not in df.columns or target_b not in df.columns:
        raise ValueError(f"'{target_a}' and/or '{target_b}' not found in the current dataset.")

    model_df = df.dropna(subset=[target_a, target_b]).reset_index(drop=True)
    if len(model_df) < MIN_ROWS_PARETO:
        raise ValueError(
            f"Only {len(model_df)} complete rows available (need at least "
            f"{MIN_ROWS_PARETO}) - load more batches, or pick targets with "
            "fewer missing values."
        )

    # Normalize both objectives to "higher is better" so a single sweep works
    # regardless of the maximize/minimize choice per axis.
    a = model_df[target_a].to_numpy() * (1 if direction_a == "maximize" else -1)
    b = model_df[target_b].to_numpy() * (1 if direction_b == "maximize" else -1)

    # Sort by a descending, then sweep keeping only points whose b beats every
    # b seen so far - a point dominated by an earlier (better-a) point with
    # equal-or-better b is not on the front.
    order = np.argsort(-a)
    is_pareto = np.zeros(len(model_df), dtype=bool)
    best_b_so_far = -np.inf
    for idx in order:
        if b[idx] > best_b_so_far:
            is_pareto[idx] = True
            best_b_so_far = b[idx]

    result_df = model_df.copy()
    result_df["is_pareto_optimal"] = is_pareto

    logger.debug(
        "find_pareto_front: target_a=%s, target_b=%s, n_samples=%d, n_on_front=%d",
        target_a,
        target_b,
        len(model_df),
        int(is_pareto.sum()),
    )

    return {
        "target_a": target_a,
        "target_b": target_b,
        "n_samples": len(model_df),
        "n_on_front": int(is_pareto.sum()),
        "result_df": result_df,
    }


def detect_outliers(df: pd.DataFrame, feature_cols: list, contamination: float = 0.05) -> dict:
    """
    Fit an Isolation Forest over feature_cols to flag samples whose overall
    parameter combination looks unusual - catches multi-column anomalies that
    a single-column threshold would miss.

    Returns a dict: feature_cols, n_samples, n_outliers, result_df (sample_id +
    feature_cols + anomaly_score + is_outlier, sorted most-anomalous first).
    """
    from sklearn.ensemble import IsolationForest

    numeric_df = df.select_dtypes(include="number")
    usable_cols = [col for col in feature_cols if col in numeric_df.columns]
    if not usable_cols:
        raise ValueError("No usable numeric parameters found to check for outliers.")

    model_df = df[usable_cols].dropna()
    if len(model_df) < MIN_ROWS_OUTLIER:
        raise ValueError(
            f"Only {len(model_df)} complete rows available (need at least "
            f"{MIN_ROWS_OUTLIER}) - load more batches, or check more parameters "
            "with fewer missing values."
        )

    model = IsolationForest(contamination=contamination, random_state=42)
    predictions = model.fit_predict(model_df.to_numpy())
    scores = model.score_samples(model_df.to_numpy())

    result_df = df.loc[model_df.index, usable_cols].copy()
    if "sample_id" in df.columns:
        result_df.insert(0, "sample_id", df.loc[model_df.index, "sample_id"])
    result_df["anomaly_score"] = scores
    result_df["is_outlier"] = predictions == -1
    result_df = result_df.sort_values("anomaly_score").reset_index(drop=True)

    n_outliers = int(result_df["is_outlier"].sum())
    logger.debug(
        "detect_outliers: n_samples=%d, n_features=%d, n_outliers=%d",
        len(model_df),
        len(usable_cols),
        n_outliers,
    )

    return {
        "feature_cols": usable_cols,
        "n_samples": len(model_df),
        "n_outliers": n_outliers,
        "result_df": result_df,
    }


def compute_process_drift(df: pd.DataFrame, param_col: str, datetime_col: str = "datetime") -> dict:
    """
    Check whether param_col trends up/down over time: parses datetime_col,
    sorts by it, and fits a simple linear trend against time order (an
    ordinal position, not clock time, so unevenly-spaced measurements don't
    distort the slope).

    Returns a dict: param_col, n_samples, slope, p_value, trend_df (sample_id
    if present, datetime_col, param_col, sorted by time).
    """
    from scipy.stats import linregress

    if param_col not in df.columns:
        raise ValueError(f"'{param_col}' not found in the current dataset.")
    if datetime_col not in df.columns:
        raise ValueError(f"'{datetime_col}' not found in the current dataset.")

    working = df[[param_col, datetime_col]].copy()
    if "sample_id" in df.columns:
        working["sample_id"] = df["sample_id"]
    working[datetime_col] = pd.to_datetime(working[datetime_col], errors="coerce")
    working = working.dropna(subset=[param_col, datetime_col]).sort_values(datetime_col)
    working = working.reset_index(drop=True)

    if len(working) < MIN_ROWS_DRIFT:
        raise ValueError(
            f"Only {len(working)} rows have both a parseable '{datetime_col}' and "
            f"'{param_col}' value (need at least {MIN_ROWS_DRIFT})."
        )

    time_ordinal = np.arange(len(working))
    slope, _, _, p_value, _ = linregress(time_ordinal, working[param_col].to_numpy())

    logger.debug(
        "compute_process_drift: param_col=%s, n_samples=%d, slope=%.4g, p_value=%.4g",
        param_col,
        len(working),
        slope,
        p_value,
    )

    return {
        "param_col": param_col,
        "datetime_col": datetime_col,
        "n_samples": len(working),
        "slope": slope,
        "p_value": p_value,
        "trend_df": working,
    }


def run_anova(df: pd.DataFrame, group_col: str, value_col: str) -> dict:
    """
    One-way ANOVA: does value_col differ significantly across the groups
    defined by group_col? Groups with fewer than MIN_GROUP_SIZE_ANOVA samples
    are dropped first (too small to say anything about).

    Returns a dict: group_col, value_col, groups (dict: group name -> n),
    f_stat, p_value, significant (p_value < 0.05).
    """
    from scipy.stats import f_oneway

    if group_col not in df.columns or value_col not in df.columns:
        raise ValueError(f"'{group_col}' and/or '{value_col}' not found in the current dataset.")

    working = df[[group_col, value_col]].dropna()
    group_sizes = working.groupby(group_col)[value_col].count()
    usable_groups = group_sizes[group_sizes >= MIN_GROUP_SIZE_ANOVA].index

    if len(usable_groups) < 2:
        raise ValueError(
            f"Need at least 2 groups in '{group_col}' with {MIN_GROUP_SIZE_ANOVA}+ "
            "samples each to run ANOVA."
        )

    samples = [
        working.loc[working[group_col] == group, value_col].to_numpy() for group in usable_groups
    ]
    f_stat, p_value = f_oneway(*samples)

    logger.debug(
        "run_anova: group_col=%s, value_col=%s, n_groups=%d, f_stat=%.4g, p_value=%.4g",
        group_col,
        value_col,
        len(usable_groups),
        f_stat,
        p_value,
    )

    return {
        "group_col": group_col,
        "value_col": value_col,
        "groups": {group: int(group_sizes[group]) for group in usable_groups},
        "f_stat": f_stat,
        "p_value": p_value,
        "significant": bool(p_value < 0.05),
    }
