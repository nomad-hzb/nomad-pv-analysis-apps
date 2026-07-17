from hysprint_utils.config import API_ENDPOINT, ENTRY_TYPES, URL_BASE


def test_url_base_no_trailing_slash():
    assert not URL_BASE.endswith("/"), "URL_BASE must not end with '/'"


def test_api_endpoint_no_trailing_slash():
    assert not API_ENDPOINT.endswith("/"), "API_ENDPOINT must not end with '/'"


def test_url_base_is_https():
    assert URL_BASE.startswith("https://"), "URL_BASE should use https"


def test_entry_types_all_present_and_non_empty():
    required_keys = {"batch", "jv", "eqe", "mppt", "abspl", "xrd", "trpl", "nmr"}
    missing = required_keys - set(ENTRY_TYPES.keys())
    assert not missing, "Missing ENTRY_TYPES keys: %s" % missing
    for key, value in ENTRY_TYPES.items():
        assert value, "ENTRY_TYPES[%r] must not be empty" % key


def test_entry_types_values_are_strings():
    for key, value in ENTRY_TYPES.items():
        assert isinstance(value, str), "ENTRY_TYPES[%r] must be a string" % key


def test_combined_url_valid():
    combined = URL_BASE + API_ENDPOINT
    assert "://" in combined
    assert not combined.endswith("/")
