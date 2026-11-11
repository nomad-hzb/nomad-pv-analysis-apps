"""APIClient GUI links follow API_ENDPOINT instead of a hard-coded /nomad-oasis (A4)."""

import pytest

from hysprint_utils.auth_manager import APIClient


@pytest.mark.parametrize(
    ("endpoint", "gui"),
    [
        ("/nomad-oasis/api/v1", "https://o.test/nomad-oasis/gui"),
        ("/api/v1", "https://o.test/gui"),
        ("/other-oasis/api/v1", "https://o.test/other-oasis/gui"),
    ],
)
def test_entry_links_use_the_oasis_prefix_of_the_api(endpoint, gui):
    client = APIClient("https://o.test", endpoint)
    assert client.get_entry_data_url("abc") == f"{gui}/entry/id/abc/data/data"
    assert client.get_entry_image_preview_url("abc", 2) == (
        f"{gui}/entry/id/abc/data/data/images:2/image_preview/preview"
    )
    assert client.get_entry_url("abc", "HySprint_SEM") == client.get_entry_image_preview_url("abc")


def test_the_default_hzb_link_is_unchanged():
    client = APIClient("https://nomad-hzb-se.helmholtz-berlin.de", "/nomad-oasis/api/v1")
    assert client.get_entry_data_url("x") == (
        "https://nomad-hzb-se.helmholtz-berlin.de/nomad-oasis/gui/entry/id/x/data/data"
    )
