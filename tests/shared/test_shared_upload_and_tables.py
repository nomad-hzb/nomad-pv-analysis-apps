"""Shared upload/lookup helpers (api_calls) and the pivot helper (table_utils)."""

from unittest.mock import MagicMock

import pandas as pd
import pytest

from hysprint_utils import api_calls
from hysprint_utils.table_utils import pivot_by_group


def test_pivot_keeps_every_measurement_of_every_group():
    data = pd.DataFrame(
        {"group": ["a", "a", "b", "b", "b", "b", None], "v": [1, 2, 3, 4, 5, 6, 7.0]}
    )
    pivot = pivot_by_group(data, "v", "group")
    assert list(pivot.columns) == ["a", "b", "(none)"]
    assert pivot["b"].tolist() == [3, 4, 5, 6]
    assert pivot["a"].dropna().tolist() == [1, 2]
    assert pivot["(none)"].dropna().tolist() == [7.0]


def test_pivot_of_an_empty_frame_is_empty():
    assert pivot_by_group(pd.DataFrame({"g": [], "v": []}), "v", "g").empty


def test_one_query_finds_every_samples_upload(monkeypatch):
    calls = []

    def fake_query_all(url, token, endpoint, query, timeout=None):
        calls.append((endpoint, query))
        return [
            {"upload_id": "u1", "results": {"eln": {"lab_ids": ["S1", "other"]}}},
            {"upload_id": "u2", "results": {"eln": {"lab_ids": ["S2"]}}},
        ]

    monkeypatch.setattr(api_calls, "_query_all", fake_query_all)
    found = api_calls.get_upload_ids_for_samples("https://x/api/v1", "tok", ["S1", "S2", "S3"])
    assert found == {"S1": "u1", "S2": "u2"}
    assert len(calls) == 1
    assert api_calls.get_upload_ids_for_samples("https://x/api/v1", "tok", []) == {}


def _ok(payload=None):
    response = MagicMock()
    response.json.return_value = payload
    return response


@pytest.fixture
def http(monkeypatch):
    put, post, get = MagicMock(return_value=_ok()), MagicMock(return_value=_ok()), MagicMock()
    monkeypatch.setattr(api_calls.requests, "put", put)
    monkeypatch.setattr(api_calls.requests, "post", post)
    monkeypatch.setattr(api_calls.requests, "get", get)
    monkeypatch.setattr(api_calls.time, "sleep", lambda s: None)
    return put, post, get


def test_upload_waits_for_processing_with_one_process_request(http):
    put, post, get = http
    get.side_effect = [
        _ok({"data": {"process_running": True}}),
        _ok({"data": {"process_running": False}}),
    ]
    polls = []
    api_calls.upload_raw_file_and_wait(
        "https://x/api/v1",
        "tok",
        "up1",
        "a.xlsx",
        b"x",
        "application/zip",
        on_poll=lambda waited, total: polls.append(waited),
    )
    assert put.call_args.kwargs["files"]["file"] == ("a.xlsx", b"x", "application/zip")
    assert put.call_args.kwargs["timeout"] == api_calls.REQUEST_TIMEOUT
    assert post.call_count == 1 and len(polls) == 2


def test_a_failed_put_stops_before_processing(http):
    put, post, _get = http
    bad = MagicMock()
    bad.raise_for_status.side_effect = RuntimeError("401")
    put.return_value = bad
    with pytest.raises(RuntimeError, match="401"):
        api_calls.upload_raw_file_and_wait("u", "t", "up1", "a", b"x", "m")
    post.assert_not_called()


def test_failed_processing_and_a_stuck_upload_raise(http):
    _put, _post, get = http
    get.return_value = _ok(
        {
            "data": {
                "process_running": False,
                "process_status": "FAILURE",
                "last_status_message": "bad",
            }
        }
    )
    with pytest.raises(RuntimeError, match="bad"):
        api_calls.upload_raw_file_and_wait("u", "t", "up1", "a", b"x", "m")
    get.return_value = _ok({"data": {"process_running": True}})
    with pytest.raises(TimeoutError):
        api_calls.upload_raw_file_and_wait(
            "u", "t", "up1", "a", b"x", "m", poll_interval=1, max_wait=3
        )
