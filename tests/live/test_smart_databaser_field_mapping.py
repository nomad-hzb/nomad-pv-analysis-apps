"""
Live verification for smart_databaser's NOMAD field-path mapping
(apps/smart_databaser/data_manager.py: PROCESS_TYPE_FIELD_PATHS).

The mapping was built by inspecting real archive data from batch HZB_MMB_12_10 during
implementation. This test re-queries the same batch and asserts the mapped paths still
resolve, so a NOMAD schema change on the server shows up as a test failure here instead
of a silent autofill regression.

Requires a running NOMAD server. Skipped unless NOMAD_URL and NOMAD_TOKEN env vars are
set.

Run with:
    NOMAD_URL=https://... NOMAD_TOKEN=... pytest tests/live/ -m live -v
"""

import os
import sys
from pathlib import Path

import pytest

NOMAD_URL = os.environ.get("NOMAD_URL", "")
NOMAD_TOKEN = os.environ.get("NOMAD_TOKEN", "")
KNOWN_BATCH_ID = "HZB_MMB_12_10"

pytestmark = pytest.mark.live

_SHARED_DIR = Path(__file__).parent.parent.parent / "shared"
_EXCEL_CREATOR_DIR = Path(__file__).parent.parent.parent / "apps" / "Excel_creator"
_APP_DIR = Path(__file__).parent.parent.parent / "apps" / "smart_databaser"
for _dir in (_SHARED_DIR, _EXCEL_CREATOR_DIR, _APP_DIR):
    if str(_dir) not in sys.path:
        sys.path.insert(0, str(_dir))


def _skip_if_no_credentials():
    if not NOMAD_URL or not NOMAD_TOKEN:
        pytest.skip("NOMAD_URL and NOMAD_TOKEN env vars required for live tests")


@pytest.mark.live
def test_spin_coating_field_mapping_still_resolves():
    _skip_if_no_credentials()
    from data_manager import NomadSessionCache, fetch_process_field_values

    cache = NomadSessionCache()
    values, source_sample_id = fetch_process_field_values(
        NOMAD_URL, NOMAD_TOKEN, cache, KNOWN_BATCH_ID, "Spin Coating"
    )

    assert source_sample_id, "expected a source sample id for the matched step"
    for expected_key in ["Material name", "Layer type", "Solvent 1 name"]:
        assert expected_key in values, f"{expected_key} no longer resolves - schema drift?"


@pytest.mark.live
def test_evaporation_field_mapping_still_resolves():
    _skip_if_no_credentials()
    from data_manager import NomadSessionCache, fetch_process_field_values

    cache = NomadSessionCache()
    values, source_sample_id = fetch_process_field_values(
        NOMAD_URL, NOMAD_TOKEN, cache, KNOWN_BATCH_ID, "Evaporation"
    )

    assert source_sample_id, "expected a source sample id for the matched step"
    assert "Material name" in values
    assert "Layer type" in values


@pytest.mark.live
def test_session_cache_avoids_redundant_calls_against_real_server():
    """Same assertion as the mocked unit test, but against the real API - confirms the
    cache genuinely skips the second network round trip, not just the mock."""
    _skip_if_no_credentials()
    import time

    from data_manager import NomadSessionCache

    cache = NomadSessionCache()
    start = time.monotonic()
    cache.get_processing_steps(NOMAD_URL, NOMAD_TOKEN, KNOWN_BATCH_ID)
    first_call_seconds = time.monotonic() - start

    start = time.monotonic()
    cache.get_processing_steps(NOMAD_URL, NOMAD_TOKEN, KNOWN_BATCH_ID)
    second_call_seconds = time.monotonic() - start

    assert second_call_seconds < first_call_seconds
