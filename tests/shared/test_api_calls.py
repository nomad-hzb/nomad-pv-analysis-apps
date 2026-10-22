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


# --- pagination, status checks and timeouts (S2) -------------------------------------------


class _PagedServer:
    """Fake NOMAD query endpoint: serves `rows` in pages and records every request."""

    def __init__(self, rows, page_size=2):
        self.rows, self.page_size, self.requests = rows, page_size, []

    def post(self, url, headers=None, json=None, timeout=None):
        self.requests.append({"url": url, "json": json, "timeout": timeout})
        start = int((json["pagination"].get("page_after_value")) or 0)
        page = self.rows[start : start + self.page_size]
        nxt = start + self.page_size
        payload = {"data": page, "pagination": {}}
        if nxt < len(self.rows):
            payload["pagination"]["next_page_after_value"] = str(nxt)

        class _Resp:
            def raise_for_status(self):
                pass

            def json(self):
                return payload

        return _Resp()


def test_query_all_follows_every_page(monkeypatch):
    from hysprint_utils import api_calls

    server = _PagedServer([{"i": n} for n in range(5)])
    monkeypatch.setattr(api_calls.requests, "post", server.post)
    query = {"query": {"x": 1}}
    data = api_calls._query_all("https://e.test/api", "tok", "entries/query", query)
    assert [d["i"] for d in data] == [0, 1, 2, 3, 4]
    assert len(server.requests) == 3
    assert query == {"query": {"x": 1}}  # caller's query untouched


def test_query_all_sets_default_page_size_and_timeout(monkeypatch):
    from hysprint_utils import api_calls

    server = _PagedServer([{"i": 1}], page_size=10)
    monkeypatch.setattr(api_calls.requests, "post", server.post)
    api_calls._query_all("https://e.test/api", "tok", "entries/query", {"query": {}})
    sent = server.requests[0]
    assert sent["json"]["pagination"]["page_size"] == api_calls.DEFAULT_PAGE_SIZE
    assert sent["timeout"] == api_calls.REQUEST_TIMEOUT


def test_query_all_stops_on_repeated_cursor(monkeypatch):
    from hysprint_utils import api_calls

    class _Loop:
        def raise_for_status(self):
            pass

        def json(self):
            return {"data": [{"i": 1}], "pagination": {"next_page_after_value": "same"}}

    monkeypatch.setattr(api_calls.requests, "post", lambda *a, **k: _Loop())
    data = api_calls._query_all("https://e.test/api", "tok", "entries/query", {"query": {}})
    assert len(data) == 2  # first page, then the repeated cursor is served once and stopped


def test_get_all_mppt_returns_entries_beyond_the_first_page(monkeypatch):
    from hysprint_utils import api_calls

    sample_entries = [{"entry_id": f"e{n}"} for n in range(3)]
    archive = [
        _linked(f"m{n}", [f"S{n}"], entry_type="HySprint_MPPTrackingMeasurement") for n in range(5)
    ]
    responses = {
        "entries/query": _PagedServer(sample_entries),
        "entries/archive/query": _PagedServer(archive),
    }

    def post(url, **kwargs):
        endpoint = "entries/archive/query" if url.endswith("archive/query") else "entries/query"
        return responses[endpoint].post(url, **kwargs)

    monkeypatch.setattr(api_calls.requests, "post", post)
    res = api_calls.get_all_mppt("https://e.test/api", "tok", ["S0"])
    assert set(res) == {f"S{n}" for n in range(5)}


def test_get_all_batches_wth_data_raises_on_http_error(monkeypatch):
    import pytest
    import requests

    from hysprint_utils import api_calls

    class _Bad:
        def raise_for_status(self):
            raise requests.HTTPError("401")

        def json(self):
            return {}

    monkeypatch.setattr(api_calls.requests, "post", lambda *a, **k: _Bad())
    with pytest.raises(requests.HTTPError):
        api_calls.get_all_batches_wth_data("https://e.test/api", "tok", "T")


def test_get_ids_in_batch_warns_instead_of_asserting(monkeypatch, caplog):
    from hysprint_utils import api_calls

    batch = {"archive": {"data": {"entities": [{"lab_id": "S1"}]}}}
    server = _PagedServer([batch], page_size=10)
    monkeypatch.setattr(api_calls.requests, "post", server.post)
    with caplog.at_level("WARNING"):
        ids = api_calls.get_ids_in_batch("https://e.test/api", "tok", ["B1", "B2"])
    assert ids == ["S1"]
    assert "asked for 2 batches" in caplog.text


# =============================================================================
# get_samples_with_substrates (Excel_creator's Prefill from NOMAD)
# =============================================================================


def _ref(entry_id, upload_id="u1"):
    return f"../uploads/{upload_id}/archive/{entry_id}#/data"


def _fake_query_all(responses, queries):
    """_query_all stand-in answering each call with the next response list."""
    answers = iter(responses)

    def fake(url, token, endpoint, query):
        queries.append((endpoint, query))
        return next(answers)

    return fake


def test_entry_id_from_reference():
    from hysprint_utils import api_calls

    assert api_calls.entry_id_from_reference(_ref("abc")) == "abc"
    assert api_calls.entry_id_from_reference("../upload/archive/xyz#data") == "xyz"
    for not_a_reference in (None, "", "plain text", {"m_def": "x"}, 5):
        assert api_calls.entry_id_from_reference(not_a_reference) is None


def test_get_samples_with_substrates_pairs_each_sample_with_its_substrate(monkeypatch):
    from hysprint_utils import api_calls

    samples = [
        {"archive": {"data": {"lab_id": "S1", "substrate": _ref("sub1")}}},
        {"archive": {"data": {"lab_id": "S2", "substrate": _ref("sub1")}}},
        {"archive": {"data": {"lab_id": "S3", "substrate": _ref("sub2", "other_upload")}}},
        {"archive": {"data": {"lab_id": "S4"}}},
        {"archive": {"data": {"lab_id": "S5", "substrate": _ref("gone")}}},
    ]
    substrates = [
        {"entry_id": "sub1", "archive": {"data": {"substrate": "Glass"}}},
        {"entry_id": "sub2", "archive": {"data": {"substrate": "FTO"}}},
    ]
    queries = []
    monkeypatch.setattr(api_calls, "_query_all", _fake_query_all([samples, substrates], queries))
    result = api_calls.get_samples_with_substrates("https://e.test/api", "tok", "up1")

    assert [(r["sample"]["lab_id"], r["substrate"]) for r in result] == [
        ("S1", {"substrate": "Glass"}),
        ("S2", {"substrate": "Glass"}),
        ("S3", {"substrate": "FTO"}),
        ("S4", {}),
        ("S5", {}),  # referenced substrate not found
    ]
    (_, sample_query), (_, substrate_query) = queries
    assert sample_query["query"] == {"upload_id": "up1", "entry_type": "HySprint_Sample"}
    assert sample_query["required"] == {"data": "*"}
    # one query for all substrates, each id once, whatever upload they are in
    assert substrate_query["query"] == {"entry_id:any": ["gone", "sub1", "sub2"]}


def test_get_samples_with_substrates_skips_the_second_query_without_references(monkeypatch):
    from hysprint_utils import api_calls

    queries = []
    samples = [{"archive": {"data": {"lab_id": "S1"}}}, {"archive": None}]
    monkeypatch.setattr(api_calls, "_query_all", _fake_query_all([samples], queries))
    result = api_calls.get_samples_with_substrates("https://e.test/api", "tok", "up1")
    assert result == [
        {"sample": {"lab_id": "S1"}, "substrate": {}},
        {"sample": {}, "substrate": {}},
    ]
    assert len(queries) == 1


def test_get_samples_with_substrates_follows_entry_types(monkeypatch):
    from hysprint_utils import api_calls

    queries = []
    monkeypatch.setattr(api_calls, "_query_all", _fake_query_all([[]], queries))
    api_calls.get_samples_with_substrates("u", "t", "up1", sample_type="Other_Sample")
    assert queries[0][1]["query"]["entry_type"] == "Other_Sample"


class _FakeResponse:
    def __init__(self, status=200, content=b""):
        self.status_code = status
        self.content = content

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests

            raise requests.HTTPError(f"{self.status_code} error")


def test_download_raw_file_quotes_path_and_returns_bytes(monkeypatch):
    from hysprint_utils import api_calls

    calls = []

    def fake_get(url, headers, timeout):
        calls.append((url, headers, timeout))
        return _FakeResponse(content=b"tiff-bytes")

    monkeypatch.setattr(api_calls.requests, "get", fake_get)
    data = api_calls.download_raw_file("https://e.test/api", "tok", "UP1", "sem data/VP 1.tif")
    assert data == b"tiff-bytes"
    url, headers, timeout = calls[0]
    assert url == "https://e.test/api/uploads/UP1/raw/sem%20data/VP%201.tif"
    assert headers == {"Authorization": "Bearer tok"}
    assert timeout == api_calls.REQUEST_TIMEOUT


def test_download_raw_file_raises_on_http_error(monkeypatch):
    import pytest
    import requests

    from hysprint_utils import api_calls

    monkeypatch.setattr(api_calls.requests, "get", lambda *a, **k: _FakeResponse(status=404))
    with pytest.raises(requests.HTTPError):
        api_calls.download_raw_file("https://e.test/api", "tok", "UP1", "missing.tif")


def test_entry_types_include_sem():
    from hysprint_utils.config import ENTRY_TYPES

    assert ENTRY_TYPES["sem"] == "HySprint_SEM"
