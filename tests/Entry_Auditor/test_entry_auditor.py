"""Entry_Auditor: unit tests for the data_manager layer -- never hits the real API."""

import json
from pathlib import Path

import data_manager as dm
import gui_components as gc
import pandas as pd

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "sample_batch.json"

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


def test_modify_file_field_has_no_leaf_name_aliases_any_more():
    """The old COLUMN_TO_JSON_KEY mapping edited by leaf name; edits are path-exact now."""
    assert not hasattr(dm, "COLUMN_TO_JSON_KEY")


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


def test_flatten_skips_blank_none_and_bool_leaves_but_keeps_numbers():
    out: dict = {}
    dm._flatten({"a": "", "b": None, "c": 5, "d": "kept", "e": 1.42, "f": True}, "", out)
    assert out == {"c": "5", "d": "kept", "e": "1.42"}


def test_flatten_keeps_a_varying_solute_concentration():
    out: dict = {}
    data = {"solution": [{"solution_details": {"solute": [{"concentration_mol": 1.42}]}}]}
    dm._flatten(data, "", out)
    assert out == {"solution.solution_details.solute.concentration_mol": "1.42"}


def test_modify_file_field_writes_a_number_back_as_a_number():
    file_text = '{"data": {"solute": [{"concentration_mol": 1.42}, {"concentration_mol": 2}]}}'
    modified, count = dm.modify_file_field(
        file_text, "entry.archive.json", "solute.1.concentration_mol", "1.42", "1.5"
    )
    assert count == 1
    assert '"concentration_mol": 1.5' in modified
    assert '"1.5"' not in modified
    # an integer stays an integer when the new value is one
    modified, count = dm.modify_file_field(
        file_text, "entry.archive.json", "solute.2.concentration_mol", "2", "3"
    )
    assert count == 1
    assert '"concentration_mol": 3}' in modified


def test_modify_file_field_refuses_text_for_a_number():
    file_text = '{"data": {"conc": 1.42}}'
    modified, count = dm.modify_file_field(file_text, "e.archive.json", "conc", "1.42", "abc")
    assert count == 0
    assert modified == file_text


def test_flatten_multi_item_list_numbers_each_item_instead_of_overwriting():
    out: dict = {}
    dm._flatten(
        {
            "solvent": [
                {"name": "DMF 0.01 milliliter"},
                {"name": "DMF 0.02 milliliter"},
            ]
        },
        "",
        out,
    )
    assert out == {
        "solvent.1.name": "DMF 0.01 milliliter",
        "solvent.2.name": "DMF 0.02 milliliter",
    }


def test_flatten_three_item_list_numbers_all_three():
    out: dict = {}
    dm._flatten({"layer": [{"layer_type": "A"}, {"layer_type": "B"}, {"layer_type": "C"}]}, "", out)
    assert out == {
        "layer.1.layer_type": "A",
        "layer.2.layer_type": "B",
        "layer.3.layer_type": "C",
    }


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
# discover_present_entry_types -- lightweight, entry_type-agnostic reconnaissance that
# lets EntryAuditSession.load skip load_generic_data entirely for schemas with nothing
# for a given sample set, instead of running its full per-type queries to find that out
# ---------------------------------------------------------------------------


def test_discover_present_entry_types_covers_all_three_match_strategies(monkeypatch):
    def fake_post(url, headers=None, json=None, timeout=None):
        query = json.get("query", {})
        if url.endswith("/entries/archive/query"):
            # _resolve_reference_ids: full archive fetch for reference-id extraction.
            return _FakeResponse(
                {"data": [{"archive": {"data": {"note": "../uploads/X/archive/REF1#/data"}}}]}
            )
        if "entry_references.target_entry_id:any" in query:
            return _FakeResponse({"data": [{"entry_type": "TypeB"}]})
        if "entry_id:any" in query:
            return _FakeResponse({"data": [{"entry_type": "TypeC"}]})
        if "results.eln.lab_ids:any" in query:
            return _FakeResponse(
                {
                    "data": [
                        {"entry_id": "e1", "entry_type": "HySprint_Sample"},
                        {"entry_id": "e2", "entry_type": "HySprint_Sample"},
                    ]
                }
            )
        raise AssertionError(f"unexpected query: {json}")

    monkeypatch.setattr(dm.requests, "post", fake_post)

    sample_entry_ids, ref_ids, entry_types = dm.discover_present_entry_types(
        "https://example.test/api/v1", "tok", ["S1", "S2"]
    )

    assert sample_entry_ids == ["e1", "e2"]
    assert ref_ids == {"REF1"}
    assert entry_types == {"HySprint_Sample", "TypeB", "TypeC"}


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


def test_field_overview_flags_varied_and_consistent_columns(fresh_session):
    fresh_session.load_offline(FIXTURE_PATH)
    overview = {entry["column"]: entry for entry in fresh_session.field_overview("Cleaning")}
    assert overview["location"]["is_varied"] is True
    assert len(overview["location"]["summary"]) == 2
    assert overview["name"]["is_varied"] is False
    assert len(overview["name"]["summary"]) == 1


def test_field_overview_matches_auditable_columns(fresh_session):
    fresh_session.load_offline(FIXTURE_PATH)
    overview_columns = {entry["column"] for entry in fresh_session.field_overview("Substrate")}
    assert overview_columns == set(fresh_session.auditable_columns("Substrate"))


def _sample_with_jv_plots() -> dict:
    """A Sample's data as recent nomad-baseclasses stores it: Plotly figures and per-scan
    jv_history_* lists, both recomputed from the JV measurements on every processing."""
    return {
        "name": "S1",
        "description": "spin coated",
        "jv_history_efficiency": [14.7, 21.5],
        "jv_history_cell_name": ["a_rev", "b_rev"],
        "figures": [
            {
                "label": "JV History",
                "figure": {"data": [{"x": [1, 2, 3], "y": [14.7, 21.5, 20.1], "name": "rev"}]},
            },
            {"label": "Best Pixel", "figure": {"data": [{"x": [0.1, 0.2], "y": [5, 6]}]}},
        ],
    }


def test_auditable_columns_skip_plot_figures_and_jv_history(fresh_session):
    """Issue #167: every plot point became an auditable field (over 10,000 for one batch),
    which stalled the results view."""
    rows = []
    for name in ("S1", "S2"):
        row: dict = {"sample_id": name}
        data = _sample_with_jv_plots()
        data["name"] = name
        dm._flatten(data, "", row)
        rows.append(row)
    fresh_session.datasets["Sample"] = pd.DataFrame(rows)
    columns = fresh_session.auditable_columns("Sample")
    assert "name" in columns and "description" in columns
    assert not [c for c in columns if c.startswith(("figures", "jv_history_"))]


def test_noise_patterns_match_nested_figures_but_not_similar_names():
    def noise(column):
        return any(pattern.search(column) for pattern in dm._NOISE_COLUMN_PATTERNS)

    assert noise("figures.1.figure.data.x.2")
    assert noise("results.figures.label")
    assert noise("jv_history_efficiency.3")
    assert not noise("figures_note")
    assert not noise("my_jv_history_note")


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
    monkeypatch.setattr(dm, "upload_corrected_file", lambda *a, **k: dm.OUTCOME_VERIFIED)
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
        backup_dir=tmp_path / "backups",
    )

    assert result.success == 1
    assert result.failed == 0
    assert result.skipped == 0
    assert dm.build_corrections_dict(log_path=log_path) == {"HySpinBox": ["HySpinbox"]}


def test_apply_correction_reports_progress_per_entry(monkeypatch, tmp_path):
    df = _cleaning_df()
    log_path = tmp_path / "log.txt"

    monkeypatch.setattr(dm, "download_file", lambda *a, **k: '{"location": "HySpinbox"}')
    monkeypatch.setattr(dm, "upload_corrected_file", lambda *a, **k: dm.OUTCOME_VERIFIED)
    monkeypatch.setattr(dm.time, "sleep", lambda *_a, **_k: None)

    events = []
    dm.apply_correction(
        "https://example.test/api/v1",
        "tok",
        df,
        "location",
        "HySpinbox",
        "HySpinBox",
        "HySprint_Cleaning",
        log_path=log_path,
        progress_callback=lambda index, total: events.append((index, total)),
    )

    assert events == [(1, 1)]


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


def test_apply_correction_only_entry_id_targets_single_entry(monkeypatch, tmp_path):
    df = _cleaning_df()
    log_path = tmp_path / "log.txt"

    monkeypatch.setattr(dm, "download_file", lambda *a, **k: '{"location": "HySpinBox"}')
    monkeypatch.setattr(dm, "upload_corrected_file", lambda *a, **k: dm.OUTCOME_VERIFIED)
    monkeypatch.setattr(dm.time, "sleep", lambda *_a, **_k: None)

    # location=="HySpinBox" matches entry1 and entry2 - only_entry_id must narrow to entry2.
    result = dm.apply_correction(
        "https://example.test/api/v1",
        "tok",
        df,
        "location",
        "HySpinBox",
        "HySpinBoxV2",
        "HySprint_Cleaning",
        log_path=log_path,
        only_entry_id="entry2",
        backup_dir=tmp_path / "backups",
    )

    assert result.total == 1
    assert result.success == 1


def test_apply_correction_only_entry_id_no_match_corrects_nothing(monkeypatch, tmp_path):
    df = _cleaning_df()
    log_path = tmp_path / "log.txt"

    monkeypatch.setattr(dm, "download_file", lambda *a, **k: '{"location": "HySpinBox"}')
    monkeypatch.setattr(dm, "upload_corrected_file", lambda *a, **k: dm.OUTCOME_VERIFIED)
    monkeypatch.setattr(dm.time, "sleep", lambda *_a, **_k: None)

    result = dm.apply_correction(
        "https://example.test/api/v1",
        "tok",
        df,
        "location",
        "HySpinBox",
        "HySpinBoxV2",
        "HySprint_Cleaning",
        log_path=log_path,
        only_entry_id="entry_not_present",
    )

    assert result.total == 0


def test_mainfile_label_strips_archive_suffix():
    assert gc._mainfile_label("11_0_spin_coating_Perovskite.archive.json") == (
        "11_0_spin_coating_Perovskite"
    )
    assert gc._mainfile_label("cleaning.archive.yaml") == "cleaning"


def test_mainfile_label_leaves_non_matching_names_untouched():
    assert gc._mainfile_label("") == ""
    assert gc._mainfile_label("no_suffix_here") == "no_suffix_here"


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


# ---------------------------------------------------------------------------
# Corrections are enabled, behind a preview + confirm step (issue #56)
# ---------------------------------------------------------------------------


def test_field_audit_panel_offers_preview_then_confirm(fresh_session):
    assert gc.CORRECTIONS_ENABLED is True
    assert fresh_session.load_offline(FIXTURE_PATH)
    label = next(iter(fresh_session.datasets))
    panel = gc.FieldAuditPanel(fresh_session, label, url="https://example.org", token="t")
    assert panel.dropdown is not None
    assert not hasattr(panel, "correct_button")  # no one-click write any more
    assert panel.confirm_button.layout.display == "none"  # nothing to confirm yet
    assert panel.cancel_button.layout.display == "none"


def test_sample_dropdown_follows_the_table_column_order(fresh_session):
    assert fresh_session.load_offline(FIXTURE_PATH)
    label = next(iter(fresh_session.datasets))
    panel = gc.FieldAuditPanel(fresh_session, label, url="https://example.org", token="t")
    df = panel.entries_df
    table_order = [str(df.loc[i].get("_entry_id", "")) for i in panel.entry_indices]
    shown = [value for _label, value in panel.sample_dropdown.options if value is not None]
    assert shown == [e for e in table_order if e in shown]


def test_field_audit_panel_offline_has_no_correction_controls(fresh_session):
    assert fresh_session.load_offline(FIXTURE_PATH)
    label = next(iter(fresh_session.datasets))
    panel = gc.FieldAuditPanel(fresh_session, label, url=None, token=None)
    assert panel.dropdown is None


# ---------------------------------------------------------------------------
# 5.1 safe corrections: path-exact edit (C1), escaping (H1/H2), upload folder (C2),
# verified outcome (C3), backup + preview (H3), HTML escaping (H4), refresh (H5)
# ---------------------------------------------------------------------------

_MULTI = {
    "name": "DMF",
    "solution": [
        {
            "solvent": [
                {"chemical_2": {"name": "DMF"}},
                {"chemical_2": {"name": "DMSO"}},
            ],
            "solute": [{"chemical_2": {"name": "DMF"}}],
        }
    ],
}


def _flat(text, mainfile="e.archive.json"):
    data = dm._parse_archive_text(text, mainfile)
    out: dict[str, str] = {}
    dm._flatten(data, "", out)
    return out


def test_correction_changes_only_the_audited_path_not_every_same_leaf_name():
    """Reproduces C1: three fields share the leaf name 'name' (and two the value DMF)."""
    text = json.dumps(_MULTI)
    column = "solution.solvent.1.chemical_2.name"
    assert _flat(text)[column] == "DMF"

    modified, count = dm.modify_file_field(text, "e.archive.json", column, "DMF", "N,N-DMF")

    assert count == 1
    flat = _flat(modified)
    assert flat[column] == "N,N-DMF"
    assert flat["solution.solvent.2.chemical_2.name"] == "DMSO"
    assert flat["solution.solute.chemical_2.name"] == "DMF"  # same value, other field
    assert flat["name"] == "DMF"  # the entry's own name


def test_correction_follows_single_item_lists_and_numbered_lists():
    text = json.dumps(_MULTI)
    modified, count = dm.modify_file_field(
        text, "e.archive.json", "solution.solute.chemical_2.name", "DMF", "X"
    )
    assert count == 1 and _flat(modified)["solution.solute.chemical_2.name"] == "X"
    modified, count = dm.modify_file_field(
        text, "e.archive.json", "solution.solvent.2.chemical_2.name", "DMSO", "Y"
    )
    assert count == 1 and _flat(modified)["solution.solvent.2.chemical_2.name"] == "Y"


def test_correction_refuses_a_path_that_is_missing_or_holds_another_value():
    text = json.dumps(_MULTI)
    for column, old in (
        ("solution.solvent.3.chemical_2.name", "DMF"),  # no third solvent
        ("solution.solvent.2.chemical_2.name", "DMF"),  # holds DMSO
        ("name.extra", "DMF"),  # beyond a leaf
        ("solution.solvent", "DMF"),  # not a leaf
    ):
        modified, count = dm.modify_file_field(text, "e.archive.json", column, old, "X")
        assert count == 0 and modified == text, column


def test_correction_survives_quotes_backslashes_newlines_and_unicode_in_the_new_value():
    text = '{"location": "HySpinbox", "unit": "\\u00b0C"}'
    for new in ['say "hi"', "back\\1slash", "line1\nline2", "N,N-DMF °C", "a: b # c"]:
        modified, count = dm.modify_file_field(text, "e.archive.json", "location", "HySpinbox", new)
        assert count == 1
        assert json.loads(modified)["location"] == new  # still valid JSON, exact value
        assert json.loads(modified)["unit"] == "°C"


def test_correction_matches_values_stored_json_escaped_or_yaml_quoted():
    escaped = '{"unit": "\\u00b0C"}'  # the file holds the escape, the audit table the character
    modified, count = dm.modify_file_field(escaped, "e.archive.json", "unit", "°C", "degC")
    assert count == 1 and json.loads(modified)["unit"] == "degC"
    quoted = 'location: "HySpinbox"\nother: "HySpinbox"\n'
    modified, count = dm.modify_file_field(quoted, "e.archive.yaml", "location", "HySpinbox", "Box")
    assert count == 1
    assert dm._parse_archive_text(modified, "e.archive.yaml") == {
        "location": "Box",
        "other": "HySpinbox",
    }


def test_correction_refuses_a_file_that_does_not_parse():
    modified, count = dm.modify_file_field("{not json", "e.archive.json", "a", "x", "y")
    assert count == 0 and modified == "{not json"


def test_correction_keeps_key_order_and_json_indentation():
    text = '{\n  "b": "1",\n  "a": "2"\n}\n'
    modified, count = dm.modify_file_field(text, "e.archive.json", "a", "2", "3")
    assert count == 1
    assert modified == '{\n  "b": "1",\n  "a": "3"\n}\n'


class _Resp:
    def __init__(self, payload=None, text="", ok=True):
        self._payload, self.text, self.ok = payload or {}, text, ok

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


def _fake_nomad(monkeypatch, status="SUCCESS", stored_text=None, publish_time=None):
    """Record every request; the upload reports `status`, the raw file reads back stored_text."""
    calls = []

    def get(url, **kwargs):
        calls.append(("GET", url, kwargs))
        if "/raw/" in url:
            return _Resp(text=stored_text if stored_text is not None else "{}")
        return _Resp({"data": {"process_status": status, "publish_time": publish_time}})

    def put(url, **kwargs):
        calls.append(("PUT", url, kwargs))
        return _Resp()

    monkeypatch.setattr(dm.requests, "get", get)
    monkeypatch.setattr(dm.requests, "put", put)
    monkeypatch.setattr(dm.time, "sleep", lambda *_a, **_k: None)
    return calls


def test_corrected_file_goes_back_into_its_own_folder_not_the_upload_root():
    """C2: PUT to the upload root would create a second entry next to the unchanged one."""
    import pytest

    stored = json.dumps({"location": "New"})
    for mainfile, expected in (
        ("batch_01/sub dir/3_spin.archive.json", "/uploads/u1/raw/batch_01/sub%20dir/"),
        ("3_spin.archive.json", "/uploads/u1/raw/"),
    ):
        with pytest.MonkeyPatch.context() as mp:
            calls = _fake_nomad(mp, stored_text=stored)
            outcome = dm.upload_corrected_file(
                "https://e.test/api/v1",
                "tok",
                "u1",
                mainfile,
                stored,
                column="location",
                new_value="New",
            )
        put = next(c for c in calls if c[0] == "PUT")
        assert put[1].endswith(expected), put[1]
        assert put[2]["files"]["file"][0] == mainfile.rsplit("/", 1)[-1]
        assert outcome == dm.OUTCOME_VERIFIED


def test_outcome_is_verified_only_when_processing_succeeded_and_the_value_reads_back(monkeypatch):
    new = json.dumps({"location": "New"})
    args = ("https://e.test/api/v1", "tok", "u1", "e.archive.json", new)
    kwargs = {"column": "location", "new_value": "New"}

    _fake_nomad(monkeypatch, status="SUCCESS", stored_text=new)
    assert dm.upload_corrected_file(*args, **kwargs) == dm.OUTCOME_VERIFIED

    _fake_nomad(monkeypatch, status="FAILURE", stored_text=new)
    assert dm.upload_corrected_file(*args, **kwargs) == dm.OUTCOME_FAILED

    _fake_nomad(monkeypatch, status="SUCCESS", stored_text=json.dumps({"location": "Old"}))
    assert dm.upload_corrected_file(*args, **kwargs) == dm.OUTCOME_FAILED  # old value still there

    # "New" is a substring of other content but not at the path: not verified.
    _fake_nomad(monkeypatch, status="SUCCESS", stored_text=json.dumps({"location": "Newer"}))
    assert dm.upload_corrected_file(*args, **kwargs) == dm.OUTCOME_FAILED

    monkeypatch.setattr(dm, "wait_for_processing", lambda *a, **k: None)  # timed out
    _fake_nomad(monkeypatch, status="RUNNING", stored_text=new)
    monkeypatch.setattr(dm, "wait_for_processing", lambda *a, **k: None)
    assert dm.upload_corrected_file(*args, **kwargs) == dm.OUTCOME_UNVERIFIED


def test_published_upload_is_never_written(monkeypatch):
    import pytest

    calls = _fake_nomad(monkeypatch, publish_time="2026-01-01")
    with pytest.raises(dm.UploadPublishedError):
        dm.upload_corrected_file(
            "https://e.test/api/v1", "tok", "u1", "e.archive.json", "{}", column="a", new_value="b"
        )
    assert not any(c[0] == "PUT" for c in calls)


def _apply(monkeypatch, tmp_path, outcome, text='{"location": "HySpinbox"}'):
    monkeypatch.setattr(dm, "download_file", lambda *a, **k: text)
    monkeypatch.setattr(dm, "upload_corrected_file", lambda *a, **k: outcome)
    monkeypatch.setattr(dm.time, "sleep", lambda *_a, **_k: None)
    log_path = tmp_path / "log.txt"
    result = dm.apply_correction(
        "https://e.test/api/v1",
        "tok",
        _cleaning_df(),
        "location",
        "HySpinbox",
        "HySpinBox",
        "HySprint_Cleaning",
        log_path=log_path,
        backup_dir=tmp_path / "backups",
    )
    return result, log_path


def test_only_verified_corrections_count_and_reach_the_log(monkeypatch, tmp_path):
    """C3: a timeout or failed processing used to be counted as updated and logged."""
    result, log_path = _apply(monkeypatch, tmp_path, dm.OUTCOME_VERIFIED)
    assert (result.success, result.unverified, result.failed) == (1, 0, 0)
    assert log_path.exists() and result.succeeded_entry_ids

    result, log_path = _apply(monkeypatch, tmp_path / "b", dm.OUTCOME_UNVERIFIED)
    assert (result.success, result.unverified, result.failed) == (0, 1, 0)
    assert result.unverified_entry_ids and not log_path.exists()

    result, log_path = _apply(monkeypatch, tmp_path / "c", dm.OUTCOME_FAILED)
    assert (result.success, result.unverified, result.failed) == (0, 0, 1)
    assert not log_path.exists()


def test_the_original_file_is_backed_up_before_it_is_changed(monkeypatch, tmp_path):
    original = '{"location": "HySpinbox"}'
    result, _ = _apply(monkeypatch, tmp_path, dm.OUTCOME_VERIFIED, text=original)
    backups = list((tmp_path / "backups").rglob("*.archive.json.*"))
    assert len(backups) == result.total
    assert all(b.read_text(encoding="utf-8") == original for b in backups)


def test_nothing_is_written_when_the_backup_cannot_be_saved(monkeypatch, tmp_path):
    uploaded = []
    monkeypatch.setattr(dm, "download_file", lambda *a, **k: '{"location": "HySpinbox"}')
    monkeypatch.setattr(dm, "upload_corrected_file", lambda *a, **k: uploaded.append(1))
    monkeypatch.setattr(dm.time, "sleep", lambda *_a, **_k: None)

    def broken(*_a, **_k):
        raise OSError("disk full")

    monkeypatch.setattr(dm, "save_backup", broken)
    result = dm.apply_correction(
        "https://e.test/api/v1",
        "tok",
        _cleaning_df(),
        "location",
        "HySpinbox",
        "HySpinBox",
        "HySprint_Cleaning",
        log_path=tmp_path / "log.txt",
        backup_dir=tmp_path / "b",
    )
    assert uploaded == [] and result.failed == 1 and result.success == 0


def test_preview_reports_what_would_change_and_writes_nothing(monkeypatch):
    writes = []
    monkeypatch.setattr(dm, "download_file", lambda *a, **k: '{"location": "HySpinbox"}')
    monkeypatch.setattr(dm, "upload_corrected_file", lambda *a, **k: writes.append(1))
    monkeypatch.setattr(dm, "save_backup", lambda *a, **k: writes.append(1))
    preview = dm.preview_correction(
        "https://e.test/api/v1",
        "tok",
        _cleaning_df(),
        "location",
        "HySpinbox",
        "HySpinBox",
        "HySprint_Cleaning",
    )
    assert preview and all(item["status"] == "change" for item in preview)
    assert writes == []

    monkeypatch.setattr(dm, "download_file", lambda *a, **k: '{"location": "Other"}')
    preview = dm.preview_correction(
        "https://e.test/api/v1",
        "tok",
        _cleaning_df(),
        "location",
        "HySpinbox",
        "HySpinBox",
        "HySprint_Cleaning",
    )
    assert all(item["status"] == "no_match" for item in preview)


def test_field_values_from_nomad_are_html_escaped_in_the_table(fresh_session):
    assert fresh_session.load_offline(FIXTURE_PATH)
    label = next(iter(fresh_session.datasets))
    df = fresh_session.datasets[label]
    column = next(c for c in df.columns if not c.startswith("_") and c != "sample_id")
    df.loc[df.index[0], column] = "<img src=x onerror=alert(1)>"
    panel = gc.FieldAuditPanel(fresh_session, label, url=None, token=None)
    cells = [c.value for cells in panel._value_cells.values() for c in cells]
    assert any("&lt;img src=x onerror=alert(1)&gt;" in v for v in cells)
    assert not any("<img" in v for v in cells)
    assert gc._esc("<a title='x'>") == "&lt;a title=&#x27;x&#x27;&gt;"


def test_confirm_flow_changes_the_table_after_a_verified_correction(monkeypatch, tmp_path):
    """H5 plus the preview/confirm gate: nothing is written until Confirm, and afterwards
    the table shows the new value."""
    fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    session = dm.EntryAuditSession()
    assert session.load_offline(FIXTURE_PATH)
    label = "Cleaning"
    df = session.datasets[label]
    column, old = "location", "HySpinbox"
    assert (df[column] == old).any(), "fixture must contain the value to correct"

    writes = []
    monkeypatch.setattr(dm, "download_file", lambda *a, **k: json.dumps({column: old}))
    monkeypatch.setattr(
        dm, "upload_corrected_file", lambda *a, **k: writes.append(a) or dm.OUTCOME_VERIFIED
    )
    monkeypatch.setattr(dm, "save_backup", lambda *a, **k: tmp_path)
    monkeypatch.setattr(dm, "append_correction_to_log", lambda *a, **k: None)
    monkeypatch.setattr(dm.time, "sleep", lambda *_a, **_k: None)
    monkeypatch.setattr(gc, "preview_correction", dm.preview_correction)
    monkeypatch.setattr(gc, "apply_correction", dm.apply_correction)

    panel = gc.FieldAuditPanel(session, label, url="https://e.test/api/v1", token="t")
    panel.dropdown.value = column
    panel.from_dropdown.value = old
    panel.to_input.value = "HySpinBox"

    panel._on_preview_click(None)
    assert writes == []  # a preview writes nothing
    assert panel.confirm_button.layout.display is None  # confirmation is now offered
    assert "will change" in panel.correct_out.value

    panel._on_confirm_click(None)
    assert writes, "confirm performs the write"
    assert "updated and verified" in panel.correct_out.value
    assert not (session.datasets[label][column] == old).any()  # H5: table data refreshed
    assert (session.datasets[label][column] == "HySpinBox").any()
    assert panel.confirm_button.layout.display == "none"
    del fixture


def test_changing_the_selection_after_a_preview_withdraws_the_confirmation(monkeypatch):
    session = dm.EntryAuditSession()
    assert session.load_offline(FIXTURE_PATH)
    monkeypatch.setattr(dm, "download_file", lambda *a, **k: json.dumps({"location": "HySpinbox"}))
    monkeypatch.setattr(gc, "preview_correction", dm.preview_correction)
    panel = gc.FieldAuditPanel(session, "Cleaning", url="https://e.test/api/v1", token="t")
    panel.dropdown.value = "location"
    panel.from_dropdown.value = "HySpinbox"
    panel.to_input.value = "Other"
    panel._on_preview_click(None)
    assert panel.confirm_button.layout.display is None
    panel.to_input.value = "Different"
    assert panel._pending is None and panel.confirm_button.layout.display == "none"


def _wrapped_archive():
    """The shape of a real .archive.json: the entry's fields sit under a top-level "data"."""
    return {
        "data": {
            "m_def": "nomad_hysprint.schema_packages.hysprint_package.HySprint_SpinCoating",
            "name": "spin coating X",
            "description": "Process notes",
            "location": "HZB-HySprintBox",
            "samples": [{"lab_id": "S1", "reference": "../uploads/u/archive/e#data"}],
            "solution": [{"solvent": [{"name": "DMF"}, {"name": "DMSO"}]}],
        }
    }


def test_correction_works_on_a_file_with_the_data_wrapper():
    """Real archive files wrap the audited fields in "data"; a path-exact edit that started at the
    file root found nothing ("0 will change") so no correction could ever be confirmed."""
    text = json.dumps(_wrapped_archive(), indent=2)
    modified, count = dm.modify_file_field(
        text, "e.archive.json", "location", "HZB-HySprintBox", "HySpinBox"
    )
    assert count == 1
    result = json.loads(modified)
    assert result["data"]["location"] == "HySpinBox"
    assert result["data"]["name"] == "spin coating X"  # nothing else touched
    assert set(result) == {"data"}


def test_wrapped_file_numbered_lists_and_read_back():
    text = json.dumps(_wrapped_archive())
    modified, count = dm.modify_file_field(
        text, "e.archive.json", "solution.solvent.2.name", "DMSO", "N,N-DMF"
    )
    assert count == 1
    assert (
        dm.get_value_at_flat_path(modified, "e.archive.json", "solution.solvent.2.name")
        == "N,N-DMF"
    )
    assert dm.get_value_at_flat_path(modified, "e.archive.json", "solution.solvent.1.name") == "DMF"
    assert dm.get_value_at_flat_path(modified, "e.archive.json", "samples.lab_id") == "S1"


def test_wrapped_yaml_file():
    text = "data:\n  location: Box\n  other: Box\n"
    modified, count = dm.modify_file_field(text, "e.archive.yaml", "location", "Box", "New")
    assert count == 1
    assert dm._parse_archive_text(modified, "e.archive.yaml") == {
        "data": {"location": "New", "other": "Box"}
    }


def test_a_wrong_path_still_changes_nothing_in_a_wrapped_file():
    text = json.dumps(_wrapped_archive())
    modified, count = dm.modify_file_field(text, "e.archive.json", "data.location", "x", "y")
    assert count == 0 and modified == text


def test_load_generic_data_keeps_a_field_that_only_some_entries_have(monkeypatch):
    from hysprint_utils.consistency import get_string_columns

    def entry(entry_id, solutes):
        return {
            "archive": {
                "metadata": {"entry_id": entry_id, "upload_id": "u", "mainfile": entry_id},
                "data": {
                    "samples": [{"lab_id": "s1"}],
                    "solution": [{"solution_details": {"solute": solutes}}],
                },
            }
        }

    entries = [
        entry("e1", [{"concentration_mol": 0.1}, {"concentration_mol": 0.2}]),
        entry("e2", [{"concentration_mol": 0.1}]),
    ]

    class _Response:
        def raise_for_status(self):
            pass

        def json(self):
            return {"data": entries}

    monkeypatch.setattr(dm.requests, "post", lambda *a, **k: _Response())
    monkeypatch.setattr(dm, "_resolve_sample_entry_ids", lambda *a, **k: [])

    df = dm.load_generic_data("http://x/api/v1", "t", ["s1"], "HySprint_SpinCoating")

    column = "solution.solution_details.solute.2.concentration_mol"
    assert column in get_string_columns(df)
    assert df[column].dropna().tolist() == ["0.2"]
