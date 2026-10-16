"""
Live check of the SEM file layout the SEM_crystal_counter app relies on: a HySprint_SEM
entry's data.detector_data paths are relative to the upload's raw folder, so
download_raw_file(upload_id, path) returns the TIFF.

Run with (NOMAD_URL is the API base, e.g. https://<oasis>/nomad-oasis/api/v1):
    NOMAD_URL=... NOMAD_TOKEN=... pytest tests/live/test_sem_raw_download.py -m live -v
"""

import os
import re

import pytest

NOMAD_URL = os.environ.get("NOMAD_URL", "")
NOMAD_TOKEN = os.environ.get("NOMAD_TOKEN", "")

pytestmark = pytest.mark.live


@pytest.mark.live
def test_sem_detector_data_downloads_as_tiff():
    if not NOMAD_URL or not NOMAD_TOKEN:
        pytest.skip("NOMAD_URL and NOMAD_TOKEN env vars required for live tests")
    import requests

    from hysprint_utils.api_calls import download_raw_file
    from hysprint_utils.config import ENTRY_TYPES

    url = NOMAD_URL.rstrip("/")
    query = {
        "owner": "visible",
        "query": {"entry_type": ENTRY_TYPES["sem"]},
        "required": {"metadata": {"upload_id": "*"}, "data": {"detector_data": "*"}},
        "pagination": {"page_size": 20},
    }
    resp = requests.post(
        f"{url}/entries/archive/query",
        json=query,
        headers={"Authorization": f"Bearer {NOMAD_TOKEN}"},
        timeout=60,
    )
    resp.raise_for_status()
    entries = [
        e["archive"]
        for e in resp.json()["data"]
        if e["archive"].get("data", {}).get("detector_data")
    ]
    if not entries:
        pytest.skip("no visible HySprint_SEM entry with detector_data")
    archive = entries[0]
    path = archive["data"]["detector_data"][0]
    content = download_raw_file(url, NOMAD_TOKEN, archive["metadata"]["upload_id"], path)
    assert content[:4] in (b"II*\x00", b"MM\x00*"), f"{path} is not a TIFF"
    assert re.search(rb"Image Pixel Size = [0-9.]+ ?(pm|nm|\xb5m|um|mm)", content), (
        f"{path} has no pixel size in its metadata"
    )
