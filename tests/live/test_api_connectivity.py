"""
Live smoke tests for NOMAD Oasis API connectivity.

These tests require a running NOMAD server. Skip them unless the environment
variables NOMAD_URL and NOMAD_TOKEN are set.

Run with:
    NOMAD_URL=https://... NOMAD_TOKEN=... pytest tests/live/ -m live -v
"""

import os

import pytest

NOMAD_URL = os.environ.get("NOMAD_URL", "")
NOMAD_TOKEN = os.environ.get("NOMAD_TOKEN", "")

pytestmark = pytest.mark.live


def _skip_if_no_credentials():
    if not NOMAD_URL or not NOMAD_TOKEN:
        pytest.skip("NOMAD_URL and NOMAD_TOKEN env vars required for live tests")


@pytest.mark.live
def test_api_reachable():
    """GET /info returns 200 OK."""
    _skip_if_no_credentials()
    import requests

    url = NOMAD_URL.rstrip("/") + "/info"
    resp = requests.get(url, timeout=10)
    assert resp.status_code == 200, "NOMAD /info returned %d" % resp.status_code


@pytest.mark.live
def test_token_authentication():
    """Authenticated request to /users/me succeeds."""
    _skip_if_no_credentials()
    import requests

    url = NOMAD_URL.rstrip("/") + "/users/me"
    resp = requests.get(url, headers={"Authorization": "Bearer " + NOMAD_TOKEN}, timeout=10)
    assert resp.status_code == 200, "Auth check returned %d" % resp.status_code


@pytest.mark.live
def test_get_ids_in_batch_returns_list():
    """get_ids_in_batch with a dummy batch returns a list (possibly empty)."""
    _skip_if_no_credentials()
    from hysprint_utils.api_calls import get_ids_in_batch

    result = get_ids_in_batch(NOMAD_URL, NOMAD_TOKEN, ["nonexistent_batch_xyz"])
    assert isinstance(result, (list, set)), "Expected list or set, got %s" % type(result)


@pytest.mark.live
def test_get_sample_description_returns_dict():
    """get_sample_description with empty list returns a dict."""
    _skip_if_no_credentials()
    from hysprint_utils.api_calls import get_sample_description

    result = get_sample_description(NOMAD_URL, NOMAD_TOKEN, [])
    assert isinstance(result, dict), "Expected dict, got %s" % type(result)
