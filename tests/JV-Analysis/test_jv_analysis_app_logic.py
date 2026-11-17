"""The data logic moved out of JV-Analysis app.py into data_manager (issue #267)."""

import pandas as pd
from data_manager import (
    build_analysis_workbook,
    conditions_from_inputs,
    curves_for_rows,
    filter_summary,
)


def test_conditions_prefer_typed_text_then_the_identifier_variation():
    conditions = conditions_from_inputs(
        ["B1&anneal", "B2&spin", "B3"], {"B1&anneal": "  typed  ", "B2&spin": "   "}
    )
    assert conditions == {"B1&anneal": "typed", "B2&spin": "spin", "B3": "Unknown"}


def test_filter_summary_counts_and_groups_by_condition():
    filtered = pd.DataFrame({"sample": ["S1"], "cell": ["c1"]})
    omitted = pd.DataFrame(
        {
            "sample": ["S1", "S1", "S2", "S3"],
            "cell": ["c2", "c3", "c1", "c1"],
            "filter_reason": [
                "PCE(%) > 10, ",
                "PCE(%) > 10, direction != Reverse, ",
                "sample/cell not selected, ",
                "direction != Reverse, ",
            ],
        }
    )
    s = filter_summary(5, filtered, omitted, selected_items={"S1_c1"})
    assert (s["original"], s["by_selection"], s["by_conditions"], s["final"]) == (5, 1, 3, 1)
    assert s["retention"] == 20.0
    assert s["removed_by_condition"] == {
        "PCE(%) > 10": {"S1": ["c2", "c3"]},
        "direction != Reverse": {"S1": ["c3"], "S3": ["c1"]},
    }
    # without a sample selection every exclusion counts as a filter condition
    assert filter_summary(5, filtered, omitted, None)["by_conditions"] == 4


def test_filter_summary_of_an_empty_table_does_not_divide_by_zero():
    empty = pd.DataFrame(columns=["sample", "cell"])
    assert filter_summary(0, empty, empty, None)["retention"] == 0.0


def test_curves_for_rows_falls_back_to_the_short_sample_name():
    curves = pd.DataFrame({"sample": ["HZB_X_C-11", "HZB_X_C-12"], "cell": ["a", "a"]})
    rows = pd.DataFrame({"sample": ["C-11"], "cell": ["a"]})
    assert list(curves_for_rows(curves, rows)["sample"]) == ["HZB_X_C-11"]


def test_analysis_workbook_has_a_sheet_per_boxplot_variable():
    data = pd.DataFrame(
        {
            "condition": ["A", "A", "B"],
            "sample": ["S1", "S2", "S3"],
            "PCE(%)": [10.0, 12.0, 8.0],
            "Voc(V)": [1.0, 1.1, 0.9],
            "Jsc(mA/cm2)": [-20.0, -21.0, -19.0],
            "FF(%)": [70.0, 72.0, 65.0],
        }
    )
    wb = build_analysis_workbook(
        data,
        None,
        [],
        [
            ("Boxplot", "The big 4: Voc, Jsc, FF, PCE", "by Variable"),
            ("Boxplot", "Correlation (heatmap)", "by Variable"),
            ("JV Curve", "Best device only", ""),
        ],
    )
    assert wb.sheetnames[0] == "All_data"
    assert sorted(wb.sheetnames[1:]) == sorted(
        f"{v}-by-condition" for v in ("Voc", "Jsc", "FF", "PCE")
    )
    # Jsc is exported as a magnitude
    values = [row for row in wb["All_data"].iter_rows(values_only=True)]
    header = values[2]
    jsc = [r[header.index("Jsc(mA/cm2)")] for r in values[4:]]
    assert all(v > 0 for v in jsc)
