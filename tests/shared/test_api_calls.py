from hysprint_utils.api_calls import _index_linked_data_by_sample, get_all_measurements_except_JV


def _linked(entry_id, sample_lab_ids, entry_type="HySprint_Annealing", extra_data=None):
    data = {"samples": [{"lab_id": lab_id} for lab_id in sample_lab_ids]}
    if extra_data:
        data.update(extra_data)
    return {
        "archive": {
            "data": data,
            "metadata": {"entry_id": entry_id, "entry_type": entry_type},
        }
    }


def test_index_linked_data_by_sample_single_sample_entry():
    linked_data = [_linked("e1", ["S1"])]
    res = _index_linked_data_by_sample(linked_data)
    assert list(res.keys()) == ["S1"]
    assert len(res["S1"]) == 1


def test_index_linked_data_by_sample_fans_out_to_every_referenced_sample():
    """Regression test for the samples[0]-only bug (issue #32): a single entry
    referencing multiple samples (e.g. several substrates annealed together in
    one oven run) must be indexed under every one of those samples, not just
    the first one listed."""
    linked_data = [_linked("e1", ["S1", "S2", "S3"])]
    res = _index_linked_data_by_sample(linked_data)
    assert set(res.keys()) == {"S1", "S2", "S3"}
    for lab_id in ("S1", "S2", "S3"):
        assert res[lab_id][0][0]["samples"][0]["lab_id"] == "S1"


def test_index_linked_data_by_sample_accumulates_multiple_entries_per_sample():
    linked_data = [_linked("e1", ["S1"]), _linked("e2", ["S1", "S2"])]
    res = _index_linked_data_by_sample(linked_data)
    assert len(res["S1"]) == 2
    assert len(res["S2"]) == 1


def test_index_linked_data_by_sample_skips_entries_with_no_samples():
    linked_data = [_linked("e1", [])]
    res = _index_linked_data_by_sample(linked_data)
    assert res == {}


def test_get_all_measurements_except_jv_fans_out_and_excludes_jv(monkeypatch):
    entries_response = {"data": [{"entry_id": "sample_entry"}]}
    archive_response = {
        "data": [
            _linked("anneal1", ["S1", "S2"], entry_type="HySprint_Annealing"),
            _linked("jv1", ["S1"], entry_type="HySprint_JVmeasurement"),
        ]
    }
    responses = iter([entries_response, archive_response])

    class _Resp:
        def __init__(self, payload):
            self._payload = payload

        def raise_for_status(self):
            pass

        def json(self):
            return self._payload

    def fake_post(*args, **kwargs):
        return _Resp(next(responses))

    monkeypatch.setattr("hysprint_utils.api_calls.requests.post", fake_post)

    res = get_all_measurements_except_JV("https://example.test/api/v1", "token", ["S1", "S2"])

    # The JV entry must be excluded, and the annealing entry must reach both samples.
    assert set(res.keys()) == {"S1", "S2"}
    assert len(res["S1"]) == 1
    assert len(res["S2"]) == 1
