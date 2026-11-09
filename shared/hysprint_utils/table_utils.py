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


# A spreadsheet runs a text cell that starts with one of these as a formula (CSV formula
# injection). NOMAD free text (sample names, descriptions, comments) can start with any of them.
FORMULA_TRIGGERS = ("=", "+", "-", "@", "\t", "\r")


def escape_formula_text(value):
    """value with an apostrophe in front if it is text a spreadsheet would run as a formula.

    Everything else comes back unchanged: numbers, NaN, and text that is a plain number such as
    "-0.5" (a spreadsheet reads that as the number, which is harmless)."""
    if not isinstance(value, str) or not value.startswith(FORMULA_TRIGGERS):
        return value
    try:
        float(value)
    except ValueError:
        return "'" + value
    return value


def csv_safe(data: pd.DataFrame) -> pd.DataFrame:
    """Copy of data to write as CSV: escape_formula_text on every text cell, column label and
    index label. Numeric columns are not touched."""
    safe = data.rename(columns=escape_formula_text, index=escape_formula_text)
    for i in range(safe.shape[1]):
        column = safe.iloc[:, i]
        if column.dtype == object or pd.api.types.is_string_dtype(column.dtype):
            safe.isetitem(i, column.map(escape_formula_text))
    return safe


def keep_text_as_text(workbook):
    """Store every formula cell of an openpyxl workbook as plain text, unchanged, and return it.

    openpyxl (and pandas' to_excel with it) turns any text that starts with "=" into a formula.
    Call this before saving a workbook that holds data only, never one with formulas of its own;
    for pandas, on writer.book inside the ExcelWriter block."""
    for sheet in workbook.worksheets:
        for row in sheet.iter_rows():
            for cell in row:
                if cell.data_type == "f":
                    cell.data_type = "s"
    return workbook
