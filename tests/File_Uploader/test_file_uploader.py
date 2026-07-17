"""
File_Uploader: unit tests for data_manager functions.

Tests cover: JSON splitting, file categorisation, type detection,
NOMAD filename construction, and AppState mutations.
"""
import json

import pytest

from data_manager import (
    AppState,
    categorize_files,
    create_nomad_filename,
    extract_filenames_from_vuetify,
    extract_measurements_from_json,
    get_file_extension,
    get_normalized_type,
    get_samples_from_json,
    prepare_json_file_content,
    split_json_by_sample,
)

# ---------------------------------------------------------------------------
# split_json_by_sample -- core pipeline
# ---------------------------------------------------------------------------


def test_split_json_by_sample_returns_both_samples(fixture_json):
    result = split_json_by_sample(fixture_json)
    assert set(result.keys()) == {"JM434", "JM435"}


def test_split_json_by_sample_correct_measurement_ids(fixture_json):
    result = split_json_by_sample(fixture_json)
    assert result["JM434"]["measurements"] == ["JM434_1_fw", "JM434_1_rv"]
    assert result["JM435"]["measurements"] == ["JM435_2_fw"]


def test_split_json_by_sample_json_content_is_valid_utf8(fixture_json):
    result = split_json_by_sample(fixture_json)
    for sample_id, payload in result.items():
        parsed = json.loads(payload["json_content"].decode("utf-8"))
        assert parsed["parameters"] == fixture_json["parameters"]
        assert all(e["sample"] == sample_id for e in parsed["data"])


def test_split_json_by_sample_preserves_efficiency(fixture_json):
    result = split_json_by_sample(fixture_json)
    jm434_data = json.loads(result["JM434"]["json_content"].decode("utf-8"))["data"]
    efficiencies = {e["direction"]: e["efficiency"] for e in jm434_data}
    assert efficiencies["fw"] == 15.2
    assert efficiencies["rv"] == 14.9


def test_split_json_by_sample_empty_input():
    assert split_json_by_sample({}) == {}
    assert split_json_by_sample(None) == {}
    assert split_json_by_sample({"data": []}) == {}


def test_split_json_by_sample_missing_data_key():
    assert split_json_by_sample({"parameters": {}}) == {}


# ---------------------------------------------------------------------------
# get_samples_from_json / extract_measurements_from_json
# ---------------------------------------------------------------------------


def test_get_samples_from_json_returns_sorted_unique(fixture_json):
    samples = get_samples_from_json(fixture_json)
    assert samples == ["JM434", "JM435"]


def test_extract_measurements_from_json_keys(fixture_json):
    meas = extract_measurements_from_json(fixture_json)
    assert "JM434_1_fw" in meas
    assert "JM435_2_fw" in meas
    assert len(meas) == 3


def test_extract_measurements_from_json_empty():
    assert extract_measurements_from_json(None) == {}
    assert extract_measurements_from_json({"data": []}) == {}


# ---------------------------------------------------------------------------
# prepare_json_file_content
# ---------------------------------------------------------------------------


def test_prepare_json_file_content_from_bytes(fixture_json):
    raw = json.dumps(fixture_json).encode("utf-8")
    parsed, valid = prepare_json_file_content(raw, "test.json")
    assert valid is True
    assert parsed["parameters"] == fixture_json["parameters"]


def test_prepare_json_file_content_invalid_returns_false():
    _, valid = prepare_json_file_content(b"not json at all {{{", "bad.json")
    assert valid is False


# ---------------------------------------------------------------------------
# get_normalized_type
# ---------------------------------------------------------------------------


def test_get_normalized_type_jv():
    assert get_normalized_type("JV_data_run1.txt") == "jv"


def test_get_normalized_type_eqe():
    assert get_normalized_type("EQE_measurement.csv") == "eqe"


def test_get_normalized_type_pes_aliases():
    for alias in ["nups", "he-ups", "cfsys", "xps"]:
        assert get_normalized_type(f"sample_{alias}_scan.txt") == "pes"


def test_get_normalized_type_unknown_returns_hy():
    assert get_normalized_type("randomfile.dat") == "hy"


# ---------------------------------------------------------------------------
# categorize_files
# ---------------------------------------------------------------------------


def test_categorize_files_splits_recognised_and_unrecognised():
    from data_manager import MEASUREMENT_TYPES

    filenames = ["jv_run1.txt", "eqe_run2.csv", "unknown_data.bin"]
    recognized, unrecognized, with_dots = categorize_files(filenames, MEASUREMENT_TYPES)
    assert "jv_run1.txt" in recognized
    assert "eqe_run2.csv" in recognized
    assert "unknown_data.bin" in unrecognized
    assert with_dots == []


def test_categorize_files_flags_dots_in_basename():
    from data_manager import MEASUREMENT_TYPES

    filenames = ["my.file.jv.txt"]
    _, _, with_dots = categorize_files(filenames, MEASUREMENT_TYPES)
    assert "my.file.jv.txt" in with_dots


# ---------------------------------------------------------------------------
# create_nomad_filename / get_file_extension
# ---------------------------------------------------------------------------


def test_create_nomad_filename():
    result = create_nomad_filename("JM434", "JV_run1", "jv", "txt")
    assert result == "JM434.JV_run1.jv.txt"


def test_get_file_extension():
    assert get_file_extension("sample.jv.txt") == "txt"


# ---------------------------------------------------------------------------
# extract_filenames_from_vuetify
# ---------------------------------------------------------------------------


def test_extract_filenames_from_vuetify():
    data = [{"name": "file1.txt", "size": 100}, {"name": "file2.csv", "size": 200}]
    assert extract_filenames_from_vuetify(data) == ["file1.txt", "file2.csv"]


def test_extract_filenames_from_vuetify_skips_bad_entries():
    data = [{"name": "ok.txt"}, "not-a-dict", {"size": 50}]
    assert extract_filenames_from_vuetify(data) == ["ok.txt"]


# ---------------------------------------------------------------------------
# AppState
# ---------------------------------------------------------------------------


def test_appstate_add_and_remove_files(fresh_state):
    fresh_state.set_sample_files("S001", [])
    fresh_state.add_files_to_sample("S001", ["a.txt", "b.csv"])
    assert fresh_state.sample_files_dict["S001"] == ["a.txt", "b.csv"]

    fresh_state.remove_files_from_sample("S001", ["a.txt"])
    assert fresh_state.sample_files_dict["S001"] == ["b.csv"]


def test_appstate_set_and_get_file_type(fresh_state):
    fresh_state.set_file_type("S001", "run1.txt", "jv")
    assert fresh_state.get_file_type("S001", "run1.txt") == "jv"
    assert fresh_state.get_file_type("S001", "missing.txt") == "hy"


def test_appstate_reset_clears_upload_state(fresh_state):
    fresh_state.add_files_to_sample("S001", ["file.txt"])
    fresh_state.set_file_type("S001", "file.txt", "eqe")
    fresh_state.reset_upload()
    assert fresh_state.sample_files_dict == {}
    assert fresh_state.file_type_dict == {}
    assert fresh_state.uploaded_files_data == {}
