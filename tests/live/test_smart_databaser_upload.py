"""
Live verification for smart_databaser's upload mechanism
(apps/smart_databaser/data_manager.py: upload_experiment_excel).

This is the one live test in this suite that WRITES to the NOMAD server - it PUTs a real
generated .xlsx into an existing upload and triggers processing. It is gated behind an
EXTRA env var beyond NOMAD_URL/NOMAD_TOKEN specifically so it can never accidentally run
against a real, non-disposable upload: DISPOSABLE_UPLOAD_ID must be set to an upload_id
you have created for this purpose (via the NOMAD web GUI, per the manual "create the
upload first" step this app deliberately keeps) and are fine having test data written
into. Do not point this at a real experiment upload.

Requires a running NOMAD server and a disposable upload. Skipped unless NOMAD_URL,
NOMAD_TOKEN, and DISPOSABLE_UPLOAD_ID env vars are all set.

Run with:
    NOMAD_URL=https://... NOMAD_TOKEN=... DISPOSABLE_UPLOAD_ID=... \\
        pytest tests/live/test_smart_databaser_upload.py -m live -v -s

What to check after running:
    - The printed response bodies confirm the response shapes upload_experiment_excel
      assumes (particularly response.json()["data"]["process_running"] on the poll GET).
    - Open the disposable upload in the NOMAD web GUI afterward and confirm the Excel
      appears and was accepted (ideally parsed cleanly) by the experiment parser -
      this test only confirms the HTTP calls succeed, not that NOMAD's parser is happy
      with the file's content.
"""

import os
import sys
from pathlib import Path

import pytest

NOMAD_URL = os.environ.get("NOMAD_URL", "")
NOMAD_TOKEN = os.environ.get("NOMAD_TOKEN", "")
DISPOSABLE_UPLOAD_ID = os.environ.get("DISPOSABLE_UPLOAD_ID", "")

pytestmark = pytest.mark.live

_SHARED_DIR = Path(__file__).parent.parent.parent / "shared"
_EXCEL_CREATOR_DIR = Path(__file__).parent.parent.parent / "apps" / "Excel_creator"
_APP_DIR = Path(__file__).parent.parent.parent / "apps" / "smart_databaser"
for _dir in (_SHARED_DIR, _EXCEL_CREATOR_DIR, _APP_DIR):
    if str(_dir) not in sys.path:
        sys.path.insert(0, str(_dir))


def _skip_if_no_credentials():
    if not (NOMAD_URL and NOMAD_TOKEN and DISPOSABLE_UPLOAD_ID):
        pytest.skip(
            "NOMAD_URL, NOMAD_TOKEN, and DISPOSABLE_UPLOAD_ID env vars all required - "
            "DISPOSABLE_UPLOAD_ID must point at an upload you're fine having test data "
            "written into, never a real experiment upload"
        )


@pytest.mark.live
def test_target_upload_is_listed_and_reachable():
    """Sanity check before the write test: confirms get_all_uploads sees the disposable
    upload, and that the direct GET .../uploads/{id} endpoint upload_experiment_excel's
    poll loop depends on returns the expected shape."""
    _skip_if_no_credentials()
    import requests
    from data_manager import NomadSessionCache

    cache = NomadSessionCache()
    uploads = cache.get_uploads(NOMAD_URL, NOMAD_TOKEN)
    upload_ids = [u["upload_id"] for u in uploads]
    assert DISPOSABLE_UPLOAD_ID in upload_ids, (
        f"{DISPOSABLE_UPLOAD_ID} not found in get_all_uploads() result - double check the env var"
    )

    response = requests.get(
        f"{NOMAD_URL}/uploads/{DISPOSABLE_UPLOAD_ID}",
        headers={"Authorization": f"Bearer {NOMAD_TOKEN}"},
    )
    response.raise_for_status()
    print("\nGET /uploads/{id} response:", response.json())
    assert "process_running" in response.json()["data"]


@pytest.mark.live
def test_upload_experiment_excel_against_disposable_upload():
    """The real write test: builds a minimal ExperimentState, generates a real Excel via
    generate_full_workbook, and uploads it to DISPOSABLE_UPLOAD_ID via the exact function
    the Upload button calls. Confirms it completes without raising - check the printed
    output and the NOMAD GUI afterward for the rest."""
    _skip_if_no_credentials()
    from data_manager import (
        ExperimentState,
        build_experiment_filename,
        generate_full_workbook,
        rebuild_field_specs,
        upload_experiment_excel,
        workbook_to_bytes,
    )

    state = ExperimentState()
    state.add_process("Evaporation")
    rebuild_field_specs(state)
    state.experiment_info_fields["Project_Name"].value = "SmartDatabaserLiveTest"
    state.experiment_info_fields["Batch"].value = "0"
    state.add_sample(variation_group_index=0, sample_number=1)
    state.get_process(1).field_specs["Material name"].value = "TestMaterial"

    workbook = generate_full_workbook(state)
    excel_bytes = workbook_to_bytes(workbook)
    filename = build_experiment_filename()

    print(f"\nUploading {filename} ({len(excel_bytes)} bytes) to {DISPOSABLE_UPLOAD_ID}")
    upload_experiment_excel(NOMAD_URL, NOMAD_TOKEN, DISPOSABLE_UPLOAD_ID, filename, excel_bytes)
    print("upload_experiment_excel completed without raising.")
