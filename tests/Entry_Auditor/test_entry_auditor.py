"""Entry_Auditor: unit tests for the data_manager layer -- never hits the real API."""

import json

import data_manager as dm
import pandas as pd
from conftest import FIXTURE_PATH

# ---------------------------------------------------------------------------
# modify_file_field -- raw-text regex correction mechanism
# ---------------------------------------------------------------------------


def test_modify_file_field_json_replaces_value():
    file_text = '{"name": "Cleaning", "location": "HySpinbox", "other": "HySpinbox"}'
    modified, count = dm.modify_file_field(
        file_text, "entry.archive.json", "location", "HySpinbox", "HySpinBox"
    )
    assert count == 1
    assert '"location": "HySpinBox"' in modified
    assert '"other": "HySpinbox"' in modified  # only the matched key is touched


def test_modify_file_field_json_no_match_returns_zero_count():
    file_text = '{"location": "HySpinBox"}'
    modified, count = dm.modify_file_field(
        file_text, "entry.archive.json", "location", "NotPresent", "New"
    )
    assert count == 0
    assert modified == file_text


def test_modify_file_field_yaml_replaces_value():
    file_text = "name: Cleaning\nlocation: HySpinbox\nother: HySpinbox\n"
    modified, count = dm.modify_file_field(
        file_text, "entry.archive.yaml", "location", "HySpinbox", "HySpinBox"
    )
    assert count == 1
    assert "location: HySpinBox" in modified
    assert "other: HySpinbox" in modified


def test_modify_file_field_uses_column_to_json_key_mapping():
    file_text = '{"annealing": {"atmosphere": "N2"}}'
    modified, count = dm.modify_file_field(
        file_text, "entry.archive.json", "annealing_atmosphere", "N2", "Nitrogen"
    )
    assert count == 1
    assert '"atmosphere": "Nitrogen"' in modified


# ---------------------------------------------------------------------------
# _flatten -- recursive archive-data flattening used by load_generic_data
# ---------------------------------------------------------------------------


def test_flatten_nested_dict_produces_dot_path_keys():
    out: dict = {}
    dm._flatten({"annealing": {"atmosphere": "N2"}}, "", out)
    assert out == {"annealing.atmosphere": "N2"}


def test_flatten_list_of_dicts_keeps_shared_prefix():
    out: dict = {}
    dm._flatten({"layer": [{"layer_type": "ETL"}]}, "", out)
    assert out == {"layer.layer_type": "ETL"}


def test_flatten_skips_blank_and_non_string_leaves():
    out: dict = {}
    dm._flatten({"a": "", "b": None, "c": 5, "d": "kept"}, "", out)
    assert out == {"d": "kept"}


# ---------------------------------------------------------------------------
# get_ids_in_batch_tolerant -- duplicate-tolerant replacement for the shared,
# asserting hysprint_utils.api_calls.get_ids_in_batch
# ---------------------------------------------------------------------------


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


def test_get_ids_in_batch_tolerant_dedupes_and_warns_on_duplicates(monkeypatch, caplog):
    payload = {
        "data": [
            {
                "archive": {
                    "data": {
                        "lab_id": "Batch1",
                        "entities": [{"lab_id": "S1"}, {"lab_id": "S2"}],
                    }
                }
            },
            {
                "archive": {
                    "data": {
                        "lab_id": "Batch1",
                        "entities": [{"lab_id": "S2"}, {"lab_id": "S3"}],
                    }
                }
            },
        ],
        "pagination": {},
    }
    monkeypatch.setattr(dm.requests, "post", lambda *a, **k: _FakeResponse(payload))

    with caplog.at_level("WARNING"):
        result = dm.get_ids_in_batch_tolerant("https://example.test/api/v1", "tok", ["Batch1"])

    assert result == ["S1", "S2", "S3"]
    assert any("duplicate" in message.lower() for message in caplog.messages)


def test_get_ids_in_batch_tolerant_returns_empty_for_no_batch_ids():
    assert dm.get_ids_in_batch_tolerant("https://example.test/api/v1", "tok", []) == []


# ---------------------------------------------------------------------------
# Correction log persistence
# ---------------------------------------------------------------------------


def test_append_and_build_corrections_dict_round_trip(tmp_path):
    log_path = tmp_path / "log.txt"
    dm.append_correction_to_log(
        "location", "HySprint_Cleaning", "HySpinBox", "HySpinbox", 2, log_path=log_path
    )
    dm.append_correction_to_log(
        "location", "HySprint_Cleaning", "HySpinBox", "hyspinbox", 1, log_path=log_path
    )

    corrections = dm.build_corrections_dict(log_path=log_path)

    assert corrections == {"HySpinBox": ["HySpinbox", "hyspinbox"]}


def test_build_corrections_dict_missing_file_returns_empty(tmp_path):
    assert dm.build_corrections_dict(log_path=tmp_path / "missing.txt") == {}


# ---------------------------------------------------------------------------
# EntryAuditSession -- offline/demo mode + inconsistency detection
# ---------------------------------------------------------------------------


def test_load_offline_returns_true_and_populates_datasets(fresh_session):
    assert fresh_session.load_offline(FIXTURE_PATH) is True
    assert fresh_session.is_loaded
    assert set(fresh_session.datasets) == {"Cleaning", "Substrate"}
    assert len(fresh_session.sample_ids) == 3


def test_load_offline_returns_false_for_empty_fixture(tmp_path, fresh_session):
    fixture = tmp_path / "empty.json"
    fixture.write_text(json.dumps({"sample_links": {}, "datasets": {}}))
    assert fresh_session.load_offline(fixture) is False
    assert not fresh_session.is_loaded


def test_auditable_columns_finds_inconsistent_location_field(fresh_session):
    fresh_session.load_offline(FIXTURE_PATH)
    assert "location" in fresh_session.auditable_columns("Cleaning")


def test_field_summary_reports_typo_split(fresh_session):
    fresh_session.load_offline(FIXTURE_PATH)
    summary = fresh_session.field_summary("Cleaning", "location")
    values = {row["value"]: row["count"] for row in summary}
    assert values == {"HySpinBox": 2, "HySpinbox": 1}


def test_consistent_dataset_field_has_single_value(fresh_session):
    fresh_session.load_offline(FIXTURE_PATH)
    assert "substrate" in fresh_session.auditable_columns("Substrate")
    summary = fresh_session.field_summary("Substrate", "substrate")
    assert len(summary) == 1
    assert summary[0]["count"] == 3


# ---------------------------------------------------------------------------
# apply_correction -- corrects every occurrence and logs only on success
# ---------------------------------------------------------------------------


def _cleaning_df():
    with open(FIXTURE_PATH, encoding="utf-8") as f:
        fixture = json.load(f)
    return pd.DataFrame(fixture["datasets"]["Cleaning"])


def test_apply_correction_success_logs_and_counts(monkeypatch, tmp_path):
    df = _cleaning_df()
    log_path = tmp_path / "log.txt"

    monkeypatch.setattr(dm, "download_file", lambda *a, **k: '{"location": "HySpinbox"}')
    monkeypatch.setattr(dm, "upload_corrected_file", lambda *a, **k: True)
    monkeypatch.setattr(dm.time, "sleep", lambda *_a, **_k: None)

    result = dm.apply_correction(
        "https://example.test/api/v1",
        "tok",
        df,
        "location",
        "HySpinbox",
        "HySpinBox",
        "HySprint_Cleaning",
        log_path=log_path,
    )

    assert result.success == 1
    assert result.failed == 0
    assert result.skipped == 0
    assert dm.build_corrections_dict(log_path=log_path) == {"HySpinBox": ["HySpinbox"]}


def test_apply_correction_skips_when_value_not_found_in_file(monkeypatch, tmp_path):
    df = _cleaning_df()
    log_path = tmp_path / "log.txt"

    monkeypatch.setattr(dm, "download_file", lambda *a, **k: '{"location": "SomethingElse"}')
    monkeypatch.setattr(dm.time, "sleep", lambda *_a, **_k: None)

    result = dm.apply_correction(
        "https://example.test/api/v1",
        "tok",
        df,
        "location",
        "HySpinbox",
        "HySpinBox",
        "HySprint_Cleaning",
        log_path=log_path,
    )

    assert result.skipped == 1
    assert result.success == 0
    assert not log_path.exists()


def test_apply_correction_counts_failures_without_aborting(monkeypatch, tmp_path):
    df = _cleaning_df()
    log_path = tmp_path / "log.txt"

    def _raise_download(*_a, **_k):
        raise dm.requests.exceptions.RequestException("network error")

    monkeypatch.setattr(dm, "download_file", _raise_download)
    monkeypatch.setattr(dm.time, "sleep", lambda *_a, **_k: None)

    result = dm.apply_correction(
        "https://example.test/api/v1",
        "tok",
        df,
        "location",
        "HySpinbox",
        "HySpinBox",
        "HySprint_Cleaning",
        log_path=log_path,
    )

    assert result.failed == 1
    assert result.total == 1


def test_correction_result_total_sums_all_outcomes():
    result = dm.CorrectionResult(success=2, failed=1, skipped=3)
    assert result.total == 6


def test_modify_file_field_does_not_partial_match_substrings():
    # "HySpinbox" must not match inside "HySpinboxes" -- guards against the regex
    # accidentally corrupting an unrelated, longer value that merely contains it.
    file_text = '{"location": "HySpinboxes"}'
    _modified, count = dm.modify_file_field(
        file_text, "entry.archive.json", "location", "HySpinbox", "HySpinBox"
    )
    assert count == 0
