"""Widget-free helpers for tables that more than one app exports."""

import pandas as pd


def pivot_by_group(data: pd.DataFrame, value_col: str, group_col: str) -> pd.DataFrame:
    """One column per group, one row per measurement in it.

    Groups of different sizes keep every measurement (the shorter ones are padded with empty
    cells); a measurement without a group is listed under "(none)". Building the frame column by
    column cuts every group to the length of the first one."""
    groups = data.groupby(group_col, dropna=False, sort=False)[value_col]
    columns = {
        ("(none)" if pd.isna(key) else key): values.reset_index(drop=True) for key, values in groups
    }
    return pd.concat(columns, axis=1) if columns else pd.DataFrame()
