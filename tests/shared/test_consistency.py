import pandas as pd

from hysprint_utils.consistency import (
    get_string_columns,
    is_field_consistent,
    summarize_field_values,
)


def _sample_df():
    return pd.DataFrame(
        {
            "sample_id": ["S1", "S2", "S3"],
            "glovebox": ["HySpinBox", "HySpinBox", "HySpinbox"],
            "solvent": ["N2", "N2", "N2"],
            "data_file": ["../uploads/a/raw/f1", "../uploads/a/raw/f2", "../uploads/a/raw/f3"],
            "count": [1, 2, 3],
        }
    )


def test_get_string_columns_excludes_known_columns():
    columns = get_string_columns(_sample_df())
    assert "sample_id" not in columns
    assert "data_file" not in columns


def test_get_string_columns_excludes_non_string_columns():
    columns = get_string_columns(_sample_df())
    assert "count" not in columns


def test_get_string_columns_includes_inconsistent_and_consistent_string_fields():
    columns = get_string_columns(_sample_df())
    assert "glovebox" in columns
    assert "solvent" in columns


def test_get_string_columns_respects_max_unique():
    df = pd.DataFrame({"noisy": [str(i) for i in range(60)]})
    assert get_string_columns(df, max_unique=50) == []


def test_get_string_columns_skips_archive_reference_columns():
    df = pd.DataFrame({"ref": ["../uploads/a/raw/f1", "../uploads/a/raw/f2"]})
    assert get_string_columns(df) == []


def test_is_field_consistent_true_for_single_value():
    assert is_field_consistent(_sample_df(), "solvent") is True


def test_is_field_consistent_false_for_multiple_values():
    assert is_field_consistent(_sample_df(), "glovebox") is False


def test_is_field_consistent_ignores_blank_values():
    df = pd.DataFrame({"field": ["A", "A", ""]})
    assert is_field_consistent(df, "field") is True


def test_summarize_field_values_groups_and_counts():
    summary = summarize_field_values(_sample_df(), "glovebox")
    values = {row["value"]: row["count"] for row in summary}
    assert values == {"HySpinBox": 2, "HySpinbox": 1}


def test_summarize_field_values_sorted_case_insensitive():
    df = pd.DataFrame({"field": ["banana", "Apple", "cherry"]})
    summary = summarize_field_values(df, "field")
    assert [row["value"] for row in summary] == ["Apple", "banana", "cherry"]


def test_summarize_field_values_row_indices_map_back_to_dataframe():
    df = _sample_df()
    summary = summarize_field_values(df, "glovebox")
    row = next(r for r in summary if r["value"] == "HySpinBox")
    assert row["row_indices"] == [0, 1]
