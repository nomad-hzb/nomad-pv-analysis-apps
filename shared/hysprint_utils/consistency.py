"""
consistency.py
Field-consistency helpers shared across apps that audit tabular NOMAD data for
inconsistent/wrong values (e.g. a misspelled sample name or glovebox name repeated
across a batch). Zero widget imports - pandas only.
"""

from __future__ import annotations

import pandas as pd

DEFAULT_EXCLUDE_COLUMNS = frozenset(
    {
        "sample_id",
        "variation",
        "data_file",
        "position_in_plan",
        "timestamp",
        "datetime",
        "measured_at",
        "raw_data",
        "data_path",
        "measurement_id",
        "_entry_id",
        "_upload_id",
        "_mainfile",
        "_gui_url",
    }
)


def get_string_columns(
    df: pd.DataFrame,
    exclude_columns: frozenset[str] | set[str] = DEFAULT_EXCLUDE_COLUMNS,
    max_unique: int = 50,
) -> list[str]:
    """Columns worth auditing: string-typed, not in exclude_columns, with between 1 and
    max_unique non-empty unique values, and not holding NOMAD archive reference paths
    (e.g. "../uploads/...")."""
    columns = []
    for column in df.columns:
        if column in exclude_columns:
            continue
        if df[column].dtype != object:
            continue
        series = df[column].replace("", None).dropna()
        if series.empty or series.nunique() > max_unique:
            continue
        try:
            if series.astype(str).str.startswith("../uploads/").any():
                continue
        except (TypeError, ValueError):
            continue
        columns.append(column)
    return columns


def summarize_field_values(df: pd.DataFrame, column: str) -> list[dict]:
    """Per-unique-value summary for one column: value, occurrence count, and the row
    indices where it occurs - the data backing an inconsistency-review table. Sorted by
    value (case-insensitive) for stable display order."""
    series = df[column].replace("", None).dropna()
    summary = []
    for value in sorted(series.unique(), key=lambda v: str(v).lower()):
        matching = df[df[column] == value]
        summary.append(
            {
                "value": value,
                "count": len(matching),
                "row_indices": list(matching.index),
            }
        )
    return summary


def is_field_consistent(df: pd.DataFrame, column: str) -> bool:
    """True if column has at most one non-empty unique value across df."""
    series = df[column].replace("", None).dropna()
    return series.nunique() <= 1
