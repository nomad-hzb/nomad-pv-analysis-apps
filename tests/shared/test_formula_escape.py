"""Formula injection: text from NOMAD must reach a CSV or XLSX export as text, not a formula."""

import io

import numpy as np
import openpyxl
import pandas as pd
import pytest

from hysprint_utils.table_utils import csv_safe, escape_formula_text, keep_text_as_text


@pytest.mark.parametrize(
    "value",
    ["=1+1", "+cmd", "-2+3+cmd|' /C calc'!A0", "@SUM(A1)", "\tx", "\rx", "-", "=HYPERLINK(x)"],
)
def test_text_that_would_run_as_a_formula_gets_an_apostrophe(value):
    assert escape_formula_text(value) == "'" + value


@pytest.mark.parametrize("value", ["sample_1", "-0.5", "+3", "1e-3", "", 5, -1.5, None, np.nan])
def test_ordinary_text_numbers_and_missing_values_stay_unchanged(value):
    result = escape_formula_text(value)
    assert result is value or (result != result and value != value)


def test_csv_safe_escapes_text_cells_and_labels_but_not_numbers():
    data = pd.DataFrame(
        {"name": ["=evil()", "ok", None], "=col": ["-x", "y", "z"], "pce": [-1.0, 2.0, 3.0]},
        index=pd.Index(["@idx", "b", "c"], name="sample"),
    )
    safe = csv_safe(data)
    assert list(safe["name"])[:2] == ["'=evil()", "ok"] and pd.isna(safe["name"].iloc[2])
    assert list(safe.columns) == ["name", "'=col", "pce"]
    assert list(safe["'=col"]) == ["'-x", "y", "z"]
    assert list(safe.index) == ["'@idx", "b", "c"]
    assert safe["pce"].tolist() == [-1.0, 2.0, 3.0]
    assert data.loc["@idx", "name"] == "=evil()"  # the original is not changed
    assert "'=evil()" in safe.to_csv()


def test_csv_safe_handles_duplicate_column_labels():
    data = pd.DataFrame([["=a", "=b"]], columns=["x", "x"])
    assert csv_safe(data).iloc[0].tolist() == ["'=a", "'=b"]


def test_keep_text_as_text_turns_formula_cells_into_unchanged_text():
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        pd.DataFrame({"name": ["=1+1", "plain"], "v": [1, 2]}).to_excel(writer, index=False)
        assert writer.book.active["A2"].data_type == "f"
        keep_text_as_text(writer.book)
    cell = openpyxl.load_workbook(io.BytesIO(buffer.getvalue())).active["A2"]
    assert (cell.value, cell.data_type) == ("=1+1", "s")
