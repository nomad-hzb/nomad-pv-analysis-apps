"""get_mppt_batch_ids: the shared batch lookup first, then the chunked fallback, both through
the paginated query helpers (no first-page-only POSTs)."""

import sys

import pytest
from data_manager import DataManager


@pytest.fixture
def dm_module():
    return sys.modules[DataManager.__module__]


@pytest.fixture
def manager():
    return DataManager(url="http://mock", token="mock-token")


def test_fast_path_uses_the_shared_lookup_and_drops_empty_ids(monkeypatch, dm_module, manager):
    calls = []

    def fake_lookup(url, token, entry_type):
        calls.append((url, token, entry_type))
        return ["B2", "", "B1"]

    monkeypatch.setattr(dm_module, "get_all_batches_wth_data", fake_lookup)
    monkeypatch.setattr(dm_module, "query_all", lambda *a, **k: pytest.fail("no fallback"))
    assert manager.get_mppt_batch_ids() == ["B1", "B2"]
    assert calls == [("http://mock", "mock-token", dm_module.ENTRY_TYPES["mppt"])]


def test_fallback_reads_every_batch_page_and_checks_samples(monkeypatch, dm_module, manager):
    def failing_lookup(*args):
        raise RuntimeError("archive query failed")

    def fake_query_all(url, token, endpoint, query):
        assert endpoint == "entries/archive/query"
        return [
            {"archive": {"data": {"lab_id": "B1", "entities": [{"lab_id": "s1"}]}}},
            {"archive": {"data": {"lab_id": "B2", "entities": [{"lab_id": "s2"}]}}},
        ]

    monkeypatch.setattr(dm_module, "get_all_batches_wth_data", failing_lookup)
    monkeypatch.setattr(dm_module, "query_all", fake_query_all)
    monkeypatch.setattr(dm_module, "get_all_mppt", lambda url, token, ids: {"s2": {}})
    assert manager.get_mppt_batch_ids() == ["B2"]
