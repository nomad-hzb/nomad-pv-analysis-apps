"""Single-entry lookups raise EntryLookupError (not a bare assert that python -O skips)."""

import pytest

from hysprint_utils import api_calls
from hysprint_utils.api_calls import EntryLookupError

ENTRY = {"entry_id": "e1", "upload_id": "u1", "archive": {"data": {"lab_id": "S1"}}}


@pytest.fixture
def answer(monkeypatch):
    """Make every query_all call return the list given to answer(...)."""

    def set_answer(data):
        monkeypatch.setattr(api_calls, "query_all", lambda *args, **kwargs: data)

    return set_answer


@pytest.mark.parametrize(
    ("call", "expected"),
    [
        (lambda: api_calls.get_entry_data("u", "t", "e1"), {"lab_id": "S1"}),
        (lambda: api_calls.get_entryid("u", "t", "S1"), "e1"),
        (lambda: api_calls.get_nomad_ids_of_entry("u", "t", "S1"), ("e1", "u1")),
        (lambda: api_calls.get_entry_meta_data("u", "t", "e1"), ENTRY),
    ],
)
def test_one_entry_is_returned_as_before(answer, call, expected):
    answer([ENTRY])
    assert call() == expected


@pytest.mark.parametrize(
    "call",
    [
        lambda: api_calls.get_entry_data("u", "t", "e1"),
        lambda: api_calls.get_entryid("u", "t", "S1"),
        lambda: api_calls.get_nomad_ids_of_entry("u", "t", "S1"),
        lambda: api_calls.get_entry_meta_data("u", "t", "e1"),
    ],
)
@pytest.mark.parametrize(("data", "found"), [([], "no entry"), ([ENTRY, ENTRY], "2 entries")])
def test_none_or_several_entries_raise_a_named_lookup_error(answer, call, data, found):
    answer(data)
    with pytest.raises(EntryLookupError, match=f"NOMAD returned {found} for "):
        call()


def test_the_error_is_still_caught_by_old_assertion_handlers(answer):
    answer([])
    with pytest.raises(AssertionError):
        api_calls.get_entryid("u", "t", "S1")
    assert issubclass(EntryLookupError, LookupError)


def test_setup_environment_and_samples_raise_when_missing(monkeypatch):
    monkeypatch.setattr(api_calls, "get_information", lambda *args: [])
    with pytest.raises(EntryLookupError, match="setup of entry 'e1'"):
        api_calls.get_setup("u", "t", "e1")
    with pytest.raises(EntryLookupError, match="environment of entry 'e1'"):
        api_calls.get_environment("u", "t", "e1")
    with pytest.raises(EntryLookupError, match="no samples for entry 'e1'"):
        api_calls.get_samples("u", "t", "e1")
    monkeypatch.setattr(api_calls, "get_information", lambda *args: [{"s": 1}, {"s": 2}])
    assert api_calls.get_samples("u", "t", "e1") == [{"s": 1}, {"s": 2}]
    with pytest.raises(EntryLookupError, match="2 entries for the setup"):
        api_calls.get_setup("u", "t", "e1")
