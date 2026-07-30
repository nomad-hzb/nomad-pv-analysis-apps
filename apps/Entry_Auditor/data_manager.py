# data_manager.py
# Zero widget imports. NOMAD entry fetching/flattening, inconsistency detection (via
# hysprint_utils.consistency), and the raw-file correction/re-upload mechanism.

from __future__ import annotations

import json
import logging
import re
import time
from collections import Counter
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

import pandas as pd
import requests
from pydantic import BaseModel

from hysprint_utils.api_calls import get_sample_entry_links
from hysprint_utils.consistency import get_string_columns, summarize_field_values

try:
    from hysprint_utils.config import API_ENDPOINT, URL_BASE
except ImportError:
    URL_BASE = "https://nomad-hzb-se.de"
    API_ENDPOINT = "/nomad-oasis/api/v1"
    logging.getLogger(__name__).warning(
        "hysprint_utils.config not found; using hardcoded URL fallback"
    )

logger = logging.getLogger(__name__)

URL_API = URL_BASE + API_ENDPOINT

# ---------------------------------------------------------------------------
# Entry-type catalog to audit - app-local (not a hysprint_utils concept). Every type is
# fetched generically via load_generic_data below; there is no per-type dedicated
# loader. entry_explorer's own most recent working notebook had already moved every
# entry away from dedicated per-type loaders in favor of the generic one, so none are
# ported here.
# ---------------------------------------------------------------------------

ENTRY_TYPES_TO_AUDIT: dict[str, str] = {
    "Batch": "HySprint_Batch",
    "Basic Sample": "HySprint_BasicSample",
    "ALD": "HySprint_AtomicLayerDeposition",
    "Blade Coating": "HySprint_BladeCoating",
    "Chemical": "HySprint_Chemical",
    "Cleaning": "HySprint_Cleaning",
    "Deposition": "HySprint_Deposition",
    "Dip Coating": "HySprint_DipCoating",
    "Electrode": "HySprint_Electrode",
    "Environment": "HySprint_Environment",
    "Evaporation": "HySprint_Evaporation",
    "Experimental Plan": "HySprint_ExperimentalPlan",
    "Ink": "HySprint_Ink",
    "Inkjet Printing": "HySprint_Inkjet_Printing",
    "Laser Scribing": "HySprint_LaserScribing",
    "Process": "HySprint_Process",
    "Sample": "HySprint_Sample",
    "Slot Die Coating": "HySprint_SlotDieCoating",
    "Solution": "HySprint_Solution",
    "Spin Coating": "HySprint_SpinCoating",
    "SpinCoating Recipe": "HySprint_SpinCoating_Recipe",
    "Storage": "HySprint_Storage",
    "Substrate": "HySprint_Substrate",
}

# App-local noise filters for auditable_columns, applied on top of
# hysprint_utils.consistency.get_string_columns/DEFAULT_EXCLUDE_COLUMNS (not a shared-
# code change - callers are meant to layer their own filtering on that generic base).
# Regex-based rather than an exact-name set, because the columns _flatten actually
# produces depend on how deeply an entry's data nests and how many list items it has -
# a fixed set of names can't anticipate every numbered variant.
_NOISE_COLUMN_PATTERNS = (
    # NOMAD's own schema-definition reference (the archiving Python class path and its
    # hash) at ANY nesting depth - identical for every entry of a type, and identical
    # again for every item for the same reason if it's inside a list (e.g. a Batch
    # entry's "entities.3.m_def"). Never meaningful data a user would audit/correct.
    re.compile(r"(^|\.)m_def(_id)?$"),
    # "samples.name"/"samples.lab_id" (and, for an entry linking >1 sample at once -
    # e.g. a batch-level cleaning record, or a Batch entry's own "entities" list - the
    # numbered variants "samples.1.name", "entities.16.lab_id", ...). This is just
    # restating which sample(s) an entry belongs to, already shown via each column's
    # own header/tooltip; for a many-sample entry it also explodes into dozens of
    # columns that are blank for every other (normal, single-sample) entry.
    re.compile(r"^(samples|entities)(\.\d+)?\."),
)


# ---------------------------------------------------------------------------
# Batch/sample resolution
# ---------------------------------------------------------------------------


def get_ids_in_batch_tolerant(url: str, token: str, batch_ids: list[str]) -> list[str]:
    """Paginated drop-in for hysprint_utils.api_calls.get_ids_in_batch that tolerates
    duplicate batch lab_ids - that function hard-asserts len(data) == len(batch_ids),
    which breaks on duplicate/legacy batch names. An audit tool needs to handle that
    case, not fail on it, so this is kept app-local rather than changing the shared
    function. Logs duplicates instead of raising."""
    if not batch_ids:
        return []
    headers = {"Authorization": f"Bearer {token}"}
    query: dict[str, Any] = {
        "required": {"data": "*"},
        "owner": "visible",
        "query": {"results.eln.lab_ids:any": batch_ids, "entry_type": "HySprint_Batch"},
        "pagination": {"page_size": 100},
    }
    all_data: list[dict] = []
    while True:
        response = requests.post(
            f"{url}/entries/archive/query", headers=headers, json=query, timeout=30
        )
        response.raise_for_status()
        payload = response.json()
        all_data.extend(payload.get("data", []))
        next_value = payload["pagination"].get("next_page_after_value")
        if not next_value:
            break
        query["pagination"]["page_after_value"] = next_value

    found_ids: list[str] = []
    for entry in all_data:
        lab_ids = entry["archive"]["data"].get("lab_id", [])
        found_ids.extend(lab_ids if isinstance(lab_ids, list) else [lab_ids])
    duplicates = [lab_id for lab_id, count in Counter(found_ids).items() if count > 1]
    if duplicates:
        logger.warning("Found %d duplicate batch name(s): %s", len(duplicates), duplicates)

    sample_ids: list[str] = []
    for entry in all_data:
        data = entry["archive"]["data"]
        if "entities" in data:
            sample_ids.extend(s["lab_id"] for s in data["entities"] if "lab_id" in s)
    return list(dict.fromkeys(sample_ids))


def get_sample_links_chunked(
    url: str, token: str, sample_ids: list[str], chunk_size: int = 200
) -> dict[str, str]:
    """Chunked wrapper around hysprint_utils.get_sample_entry_links to stay under
    NOMAD's per-request size limit for large batches."""
    result: dict[str, str] = {}
    for i in range(0, len(sample_ids), chunk_size):
        chunk = sample_ids[i : i + chunk_size]
        result.update(get_sample_entry_links(url, token, chunk))
    return result


def get_entry_links(url: str, token: str, sample_ids: list[str], entry_type: str) -> dict[str, str]:
    """{sample_id: gui_url} for entries of entry_type, mapped back to sample_ids via
    the entry's own 'samples' field."""
    if not sample_ids:
        return {}
    headers = {"Authorization": f"Bearer {token}"}
    base_url = url.split("/api/")[0]

    response = requests.post(
        f"{url}/entries/query",
        headers=headers,
        json={
            "required": {"include": ["entry_id"]},
            "owner": "visible",
            "query": {"results.eln.lab_ids:any": sample_ids},
            "pagination": {"page_size": 10000},
        },
        timeout=30,
    )
    response.raise_for_status()
    sample_entry_ids = [entry["entry_id"] for entry in response.json()["data"]]
    if not sample_entry_ids:
        return {}

    response = requests.post(
        f"{url}/entries/archive/query",
        headers=headers,
        json={
            "required": {"data": {"samples": "*"}, "metadata": "*"},
            "owner": "visible",
            "query": {
                "entry_references.target_entry_id:any": sample_entry_ids,
                "entry_type": entry_type,
            },
            "pagination": {"page_size": 10000},
        },
        timeout=30,
    )
    response.raise_for_status()

    result: dict[str, str] = {}
    for entry in response.json()["data"]:
        meta = entry.get("archive", {}).get("metadata", {})
        data = entry.get("archive", {}).get("data", {})
        entry_id = meta.get("entry_id", "")
        upload_id = meta.get("upload_id", "")
        gui_url = f"{base_url}/gui/user/uploads/upload/id/{upload_id}/entry/id/{entry_id}"
        samples = data.get("samples", [])
        if samples:
            lab_id = samples[0].get("lab_id", "")
            if lab_id in sample_ids:
                result[lab_id] = gui_url
    return result


# ---------------------------------------------------------------------------
# Generic entry loading (flatten arbitrary archive data into audit-table columns)
# ---------------------------------------------------------------------------

_REF_PATTERN = re.compile(r"archive/([A-Za-z0-9_\-]+)(?:#|$)")


def _flatten(obj: Any, prefix: str, out: dict[str, str]) -> None:
    """Recursively flattens dicts to dot-path keys and unwraps single-item lists onto
    the same path (e.g. NOMAD's common "0-or-1 items" repeatable subsections). A list
    with more than one item (e.g. a solution with two solvents) is numbered 1-based
    per item instead of sharing one path - matching the "Solvent 1"/"Solvent 2"
    convention Excel_creator/smart_databaser already use for these same NOMAD list
    fields - so every item survives as its own column instead of later items silently
    overwriting earlier ones at an identical key."""
    if isinstance(obj, dict):
        for key, value in obj.items():
            _flatten(value, f"{prefix}.{key}" if prefix else key, out)
    elif isinstance(obj, list):
        if len(obj) <= 1:
            for item in obj:
                _flatten(item, prefix, out)
        else:
            for index, item in enumerate(obj, start=1):
                _flatten(item, f"{prefix}.{index}", out)
    elif isinstance(obj, str) and obj.strip():
        out[prefix] = obj


def _extract_ref_ids(obj: Any, ref_ids: set[str]) -> None:
    if isinstance(obj, dict):
        for value in obj.values():
            _extract_ref_ids(value, ref_ids)
    elif isinstance(obj, list):
        for item in obj:
            _extract_ref_ids(item, ref_ids)
    elif isinstance(obj, str):
        for match in _REF_PATTERN.finditer(obj):
            ref_ids.add(match.group(1))


def _resolve_sample_entry_ids(
    url: str, token: str, sample_ids: list[str], chunk_size: int = 200
) -> list[str]:
    """Entry ids of the sample entries themselves - a pure function of sample_ids, used
    by load_generic_data's reference-based fallback strategy. Identical for every
    entry_type audited in one session, so callers should compute it once and pass it
    back in via load_generic_data's cache= param rather than recomputing per schema."""
    headers = {"Authorization": f"Bearer {token}"}
    chunks = [sample_ids[i : i + chunk_size] for i in range(0, len(sample_ids), chunk_size)]
    all_sample_entry_ids: list[str] = []
    for chunk in chunks:
        response = requests.post(
            f"{url}/entries/query",
            headers=headers,
            json={
                "required": {"include": ["entry_id"]},
                "owner": "visible",
                "query": {"results.eln.lab_ids:any": chunk},
                "pagination": {"page_size": 10000},
            },
            timeout=30,
        )
        response.raise_for_status()
        all_sample_entry_ids.extend(entry["entry_id"] for entry in response.json()["data"])
    return all_sample_entry_ids


def _resolve_reference_ids(
    url: str, token: str, sample_ids: list[str], chunk_size: int = 200
) -> set[str]:
    """Every archive-reference id reachable from the sample entries' own data - a pure
    function of sample_ids, used by load_generic_data's last-resort fallback strategy.
    Identical for every entry_type audited in one session (and by far the most
    expensive lookup, since it downloads full archive data for every sample), so
    callers should compute it once and pass it back in via load_generic_data's cache=
    param rather than recomputing per schema."""
    headers = {"Authorization": f"Bearer {token}"}
    chunks = [sample_ids[i : i + chunk_size] for i in range(0, len(sample_ids), chunk_size)]
    ref_ids: set[str] = set()
    for chunk in chunks:
        response = requests.post(
            f"{url}/entries/archive/query",
            headers=headers,
            json={
                "required": {"data": "*"},
                "owner": "visible",
                "query": {"results.eln.lab_ids:any": chunk},
                "pagination": {"page_size": 10000},
            },
            timeout=30,
        )
        response.raise_for_status()
        for entry in response.json().get("data", []):
            _extract_ref_ids(entry.get("archive", {}).get("data", {}), ref_ids)
    return ref_ids


def discover_present_entry_types(
    url: str, token: str, sample_ids: list[str], chunk_size: int = 200
) -> tuple[list[str], set[str], set[str]]:
    """Cheap, entry_type-agnostic reconnaissance for EntryAuditSession.load(): finds
    the set of entry_type values reachable from sample_ids via all three of
    load_generic_data's matching strategies (direct lab_id match, reference from
    sample entries, reference-following through sample archive data), using
    entries/query's lightweight {"include": ["entry_type"]} projection instead of
    fetching each candidate entry's full archive data and without an entry_type filter
    (so one pass covers every schema instead of one query set per schema). The
    dominant cost of auditing ~20 configured entry types is the majority that come
    back completely empty for a typical batch - this lets EntryAuditSession.load skip
    load_generic_data entirely for those instead of running its full per-type queries
    just to learn there's nothing there.

    Returns (sample_entry_ids, ref_ids, entry_types_present) so callers can seed
    load_generic_data's cache with the first two and avoid recomputing them."""
    headers = {"Authorization": f"Bearer {token}"}
    chunks = [sample_ids[i : i + chunk_size] for i in range(0, len(sample_ids), chunk_size)]
    sample_entry_ids: list[str] = []
    entry_types: set[str] = set()

    for chunk in chunks:
        response = requests.post(
            f"{url}/entries/query",
            headers=headers,
            json={
                "required": {"include": ["entry_id", "entry_type"]},
                "owner": "visible",
                "query": {"results.eln.lab_ids:any": chunk},
                "pagination": {"page_size": 10000},
            },
            timeout=30,
        )
        response.raise_for_status()
        for entry in response.json()["data"]:
            sample_entry_ids.append(entry["entry_id"])
            if entry.get("entry_type"):
                entry_types.add(entry["entry_type"])

    id_chunks = [
        sample_entry_ids[i : i + chunk_size] for i in range(0, len(sample_entry_ids), chunk_size)
    ]
    for id_chunk in id_chunks:
        response = requests.post(
            f"{url}/entries/query",
            headers=headers,
            json={
                "required": {"include": ["entry_type"]},
                "owner": "visible",
                "query": {"entry_references.target_entry_id:any": id_chunk},
                "pagination": {"page_size": 10000},
            },
            timeout=30,
        )
        response.raise_for_status()
        entry_types.update(
            entry["entry_type"] for entry in response.json()["data"] if entry.get("entry_type")
        )

    ref_ids = _resolve_reference_ids(url, token, sample_ids, chunk_size)
    ref_id_chunks = [list(ref_ids)[i : i + chunk_size] for i in range(0, len(ref_ids), chunk_size)]
    for ref_chunk in ref_id_chunks:
        response = requests.post(
            f"{url}/entries/query",
            headers=headers,
            json={
                "required": {"include": ["entry_type"]},
                "owner": "visible",
                "query": {"entry_id:any": ref_chunk},
                "pagination": {"page_size": 10000},
            },
            timeout=30,
        )
        response.raise_for_status()
        entry_types.update(
            entry["entry_type"] for entry in response.json()["data"] if entry.get("entry_type")
        )

    return sample_entry_ids, ref_ids, entry_types


def load_generic_data(
    url: str,
    token: str,
    sample_ids: list[str],
    entry_type: str,
    chunk_size: int = 200,
    cache: dict[str, Any] | None = None,
) -> pd.DataFrame | None:
    """Fetch and flatten every entry of entry_type reachable from sample_ids, via three
    fallback strategies (direct lab_id match, reference from sample entries, and
    reference-following through sample archive data). Returns a DataFrame with one row
    per entry: sample_id, correction-mechanism metadata
    (_entry_id/_upload_id/_mainfile/_gui_url), and one column per flattened string leaf
    in the entry's data (dot-path keys).

    cache is an optional dict shared across repeated calls for the same sample_ids
    (EntryAuditSession.load audits ~20 entry types per session.load() call) - the two
    lookups that only depend on sample_ids, not entry_type, are computed once and
    reused instead of being repeated for every entry type."""
    if not sample_ids:
        return None
    if cache is None:
        cache = {}
    headers = {"Authorization": f"Bearer {token}"}
    base_url = url.split("/api/")[0]
    seen: set[str] = set()
    rows: list[dict] = []

    chunks = [sample_ids[i : i + chunk_size] for i in range(0, len(sample_ids), chunk_size)]

    def process(entries: list[dict]) -> None:
        for entry in entries:
            meta = entry.get("archive", {}).get("metadata", {})
            entry_id = meta.get("entry_id", "")
            if not entry_id or entry_id in seen:
                continue
            seen.add(entry_id)
            upload_id = meta.get("upload_id", "")
            mainfile = meta.get("mainfile", "")
            data = entry.get("archive", {}).get("data", {})
            raw_samples = data.get("samples", [])
            if isinstance(raw_samples, dict):
                raw_samples = [raw_samples]
            sample_id = next(
                (
                    sample.get("lab_id")
                    for sample in raw_samples
                    if isinstance(sample, dict) and sample.get("lab_id") in sample_ids
                ),
                "N/A",
            )
            row: dict[str, Any] = {
                "sample_id": sample_id,
                "_entry_id": entry_id,
                "_upload_id": upload_id,
                "_mainfile": mainfile,
                "_gui_url": (
                    f"{base_url}/gui/user/uploads/upload/id/{upload_id}/entry/id/{entry_id}"
                ),
            }
            _flatten(data, "", row)
            rows.append(row)

    def archive_query(query_filter: dict) -> list[dict]:
        response = requests.post(
            f"{url}/entries/archive/query",
            headers=headers,
            json={
                "required": {"data": "*", "metadata": "*"},
                "owner": "visible",
                "query": {**query_filter, "entry_type": entry_type},
                "pagination": {"page_size": 10000},
            },
            timeout=30,
        )
        response.raise_for_status()
        return response.json().get("data", [])

    for chunk in chunks:
        process(archive_query({"results.eln.lab_ids:any": chunk}))

    if "sample_entry_ids" not in cache:
        cache["sample_entry_ids"] = _resolve_sample_entry_ids(url, token, sample_ids, chunk_size)
    all_sample_entry_ids = cache["sample_entry_ids"]

    id_chunks = [
        all_sample_entry_ids[i : i + chunk_size]
        for i in range(0, len(all_sample_entry_ids), chunk_size)
    ]
    for id_chunk in id_chunks:
        process(archive_query({"entry_references.target_entry_id:any": id_chunk}))

    if not rows:
        if "ref_ids" not in cache:
            cache["ref_ids"] = _resolve_reference_ids(url, token, sample_ids, chunk_size)
        ref_ids = cache["ref_ids"]

        ref_chunks = [list(ref_ids)[i : i + chunk_size] for i in range(0, len(ref_ids), chunk_size)]
        for ref_chunk in ref_chunks:
            response = requests.post(
                f"{url}/entries/archive/query",
                headers=headers,
                json={
                    "required": {"data": "*", "metadata": "*"},
                    "owner": "visible",
                    "query": {"entry_id:any": ref_chunk, "entry_type": entry_type},
                    "pagination": {"page_size": 10000},
                },
                timeout=30,
            )
            response.raise_for_status()
            process(response.json().get("data", []))

    return pd.DataFrame(rows) if rows else None


# ---------------------------------------------------------------------------
# Correction mechanism - raw-text regex replace on the downloaded archive file,
# deliberately not a JSON parse/dump, so NOMAD's unit/quantity wrapper structure and
# m_def references are never disturbed. Re-uploads the whole file and verifies the
# result.
# ---------------------------------------------------------------------------

# Maps flattened DataFrame column names to their actual key in the JSON/YAML file, for
# the (rare) cases where load_generic_data's dot-path flattening produces a compound
# name that doesn't match the raw key (e.g. "annealing.atmosphere" flattens fine, but a
# caller working from an already-merged/renamed column needs the real leaf key).
COLUMN_TO_JSON_KEY: dict[str, str] = {
    "annealing_atmosphere": "atmosphere",
    "annealing_temperature": "temperature",
    "annealing_time": "time",
}


def modify_file_field(
    file_text: str, mainfile: str, column_name: str, old_value: str, new_value: str
) -> tuple[str, int]:
    """Targeted string replacement on raw file text. Works for both .archive.json and
    .archive.yaml. Returns (modified_text, n_replacements)."""
    actual_key = COLUMN_TO_JSON_KEY.get(column_name, column_name.split(".")[-1])

    if mainfile.endswith(".json"):
        pattern = re.compile(
            r'("' + re.escape(actual_key) + r'"\s*:\s*")' + re.escape(str(old_value)) + r'"'
        )
        modified, count = pattern.subn(r"\g<1>" + str(new_value) + '"', file_text)
    else:
        pattern = re.compile(
            r"^(\s*" + re.escape(actual_key) + r"\s*:\s*)" + re.escape(str(old_value)) + r"\s*$",
            re.MULTILINE,
        )
        modified, count = pattern.subn(r"\g<1>" + str(new_value), file_text)

    logger.debug(
        "modify_file_field: key=%s old=%s new=%s matches=%d file=%s",
        actual_key,
        old_value,
        new_value,
        count,
        mainfile,
    )
    return modified, count


def fetch_entry_files(
    url: str, token: str, sample_ids: list[str], entry_type: str
) -> list[tuple[str, str, str]]:
    """[(entry_id, upload_id, mainfile), ...] for entries of entry_type linked to
    sample_ids. Used when the audited DataFrame doesn't already carry
    _entry_id/_upload_id/_mainfile columns."""
    if not sample_ids:
        return []
    headers = {"Authorization": f"Bearer {token}"}

    response = requests.post(
        f"{url}/entries/query",
        headers=headers,
        json={
            "required": {"include": ["entry_id"]},
            "owner": "visible",
            "query": {"results.eln.lab_ids:any": sample_ids},
            "pagination": {"page_size": 10000},
        },
        timeout=30,
    )
    response.raise_for_status()
    sample_entry_ids = [entry["entry_id"] for entry in response.json()["data"]]
    if not sample_entry_ids:
        return []

    response = requests.post(
        f"{url}/entries/query",
        headers=headers,
        json={
            "required": {"include": ["entry_id", "upload_id", "mainfile"]},
            "owner": "visible",
            "query": {
                "entry_references.target_entry_id:any": sample_entry_ids,
                "entry_type": entry_type,
            },
            "pagination": {"page_size": 10000},
        },
        timeout=30,
    )
    response.raise_for_status()

    result: list[tuple[str, str, str]] = []
    for entry in response.json()["data"]:
        entry_id = entry.get("entry_id")
        upload_id = entry.get("upload_id")
        mainfile = entry.get("mainfile")
        if entry_id and upload_id and mainfile:
            result.append((entry_id, upload_id, mainfile))
    return result


def download_file(url: str, token: str, upload_id: str, mainfile: str) -> str:
    response = requests.get(
        f"{url}/uploads/{upload_id}/raw/{quote(mainfile, safe='/')}",
        headers={"Authorization": f"Bearer {token}"},
        timeout=30,
    )
    response.raise_for_status()
    return response.text


def wait_for_processing(
    url: str, token: str, upload_id: str, timeout: float = 30, poll_interval: float = 1.5
) -> str | None:
    """Polls upload status until it leaves PENDING/RUNNING or timeout is reached."""
    headers = {"Authorization": f"Bearer {token}"}
    elapsed = 0.0
    while elapsed < timeout:
        response = requests.get(f"{url}/uploads/{upload_id}", headers=headers, timeout=15)
        response.raise_for_status()
        status = response.json().get("data", {}).get("process_status")
        if status not in ("PENDING", "RUNNING"):
            return status
        time.sleep(poll_interval)
        elapsed += poll_interval
    logger.warning("Timed out waiting for upload %s processing after %ss", upload_id, timeout)
    return None


class UploadPublishedError(Exception):
    """Raised when attempting to correct an entry belonging to an already-published
    upload."""


def upload_corrected_file(
    url: str,
    token: str,
    upload_id: str,
    mainfile: str,
    content: str,
    old_value: str | None = None,
    new_value: str | None = None,
) -> bool:
    """PUTs the corrected raw file back, waits for processing, then verifies the new
    value is present (or the old one is gone). Returns True if verification confirmed
    the new value; False if verification was inconclusive - a failed/inconclusive
    verification is logged, not raised, since it does not necessarily mean the write
    itself failed."""
    headers = {"Authorization": f"Bearer {token}"}

    state_response = requests.get(f"{url}/uploads/{upload_id}", headers=headers, timeout=15)
    state_response.raise_for_status()
    if state_response.json().get("data", {}).get("publish_time"):
        raise UploadPublishedError(f"Upload {upload_id} is published; cannot edit.")

    put_response = requests.put(
        f"{url}/uploads/{upload_id}/raw/",
        headers=headers,
        data={"wait_for_processing": False},
        files={"file": (Path(mainfile).name, content.encode("utf-8"), "application/json")},
        timeout=30,
    )
    put_response.raise_for_status()

    wait_for_processing(url, token, upload_id)

    verify_response = requests.get(
        f"{url}/uploads/{upload_id}/raw/{quote(mainfile, safe='/')}",
        headers=headers,
        timeout=15,
    )
    if not verify_response.ok:
        logger.warning(
            "Could not verify correction for upload %s: status %d",
            upload_id,
            verify_response.status_code,
        )
        return False
    if new_value and str(new_value) in verify_response.text:
        logger.info("Verification passed: %s confirmed in %s", new_value, mainfile)
        return True
    if old_value and str(old_value) in verify_response.text:
        logger.error("Verification FAILED: old value still present in %s", mainfile)
        return False
    logger.warning("Verification inconclusive for %s", mainfile)
    return False


# ---------------------------------------------------------------------------
# Correction log - local, append-only file next to this module. In a multi-user Voila
# deployment this is best-effort history, not an audit-grade record: concurrent writes
# from different user sessions are not locked/serialized, and if this app runs in an
# ephemeral per-session container, the log does not persist across sessions at all.
# Accepted tradeoff for v1 - if this needs to be durable/shared, it should move to a
# real backend, not a repo-relative file.
# ---------------------------------------------------------------------------

CORRECTION_LOG_PATH = Path(__file__).parent / "entry_auditor_correction_log.txt"


def append_correction_to_log(
    field: str,
    entry_type: str,
    correct_value: str,
    wrong_value: str,
    n_fixed: int,
    log_path: Path = CORRECTION_LOG_PATH,
) -> None:
    """Append one correction event. Format (pipe-separated):
    correct_value | wrong_value | field | entry_type | timestamp | n_fixed"""
    write_header = not log_path.exists()
    with open(log_path, "a", encoding="utf-8") as f:
        if write_header:
            f.write("# Entry Auditor correction log\n")
            f.write("# correct_value | wrong_value | field | entry_type | timestamp | n_fixed\n")
        timestamp = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
        f.write(
            f"{correct_value} | {wrong_value} | {field} | {entry_type} | {timestamp} | {n_fixed}\n"
        )


def build_corrections_dict(log_path: Path = CORRECTION_LOG_PATH) -> dict[str, list[str]]:
    """Read the correction log and return {correct_value: [wrong_value, ...]}."""
    if not log_path.exists():
        return {}
    corrections: dict[str, list[str]] = {}
    with open(log_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = [p.strip() for p in line.split("|")]
            correct, wrong = parts[0], parts[1]
            corrections.setdefault(correct, [])
            if wrong not in corrections[correct]:
                corrections[correct].append(wrong)
    return corrections


class CorrectionResult(BaseModel):
    success: int = 0
    failed: int = 0
    skipped: int = 0

    @property
    def total(self) -> int:
        return self.success + self.failed + self.skipped


def apply_correction(
    url: str,
    token: str,
    df: pd.DataFrame,
    column: str,
    old_value: str,
    new_value: str,
    entry_type: str,
    log_path: Path = CORRECTION_LOG_PATH,
    only_entry_id: str | None = None,
    progress_callback: Callable[[int, int], None] | None = None,
) -> CorrectionResult:
    """Corrects every occurrence of old_value in column across df's underlying NOMAD
    entries: downloads each entry's raw file, regex-replaces the value, re-uploads, and
    verifies. Uses df's own _entry_id/_upload_id/_mainfile columns when present (already
    resolved by load_generic_data); otherwise resolves them via fetch_entry_files from
    the affected rows' sample_ids. Logs successful corrections via
    append_correction_to_log. Never raises on a per-entry failure - failures are counted
    in the returned CorrectionResult instead, so one bad entry doesn't abort the batch.
    If only_entry_id is given, the correction is narrowed to that single entry instead
    of every row matching old_value - lets a user fix one occurrence without touching
    other entries that currently happen to share the same (otherwise consistent) value.
    progress_callback, if given, is invoked as (index, total) before each entry is
    processed - gui_components uses it to drive a progress bar without this module
    importing any widget library."""
    affected_rows = df[df[column] == old_value]
    if only_entry_id and "_entry_id" in affected_rows.columns:
        affected_rows = affected_rows[affected_rows["_entry_id"] == only_entry_id]

    if "_entry_id" in df.columns:
        entry_files = [
            (row["_entry_id"], row["_upload_id"], row["_mainfile"])
            for _, row in affected_rows.iterrows()
            if row.get("_entry_id") and row.get("_upload_id") and row.get("_mainfile")
        ]
    else:
        affected_sample_ids = list(affected_rows["sample_id"].unique())
        entry_files = fetch_entry_files(url, token, affected_sample_ids, entry_type)

    result = CorrectionResult()
    total = len(entry_files)
    for index, (entry_id, upload_id, mainfile) in enumerate(entry_files, start=1):
        if progress_callback is not None:
            progress_callback(index, total)
        try:
            file_text = download_file(url, token, upload_id, mainfile)
            modified_text, n_replacements = modify_file_field(
                file_text, mainfile, column, old_value, new_value
            )
            if n_replacements == 0:
                logger.warning("No match for %s=%s in entry %s", column, old_value, entry_id)
                result.skipped += 1
                continue
            upload_corrected_file(
                url,
                token,
                upload_id,
                mainfile,
                modified_text,
                old_value=old_value,
                new_value=new_value,
            )
            logger.info("Corrected entry %s (%d replacement(s))", entry_id, n_replacements)
            result.success += 1
        except Exception:
            logger.exception("Failed to correct entry %s", entry_id)
            result.failed += 1
        time.sleep(0.2)

    if result.success > 0:
        append_correction_to_log(
            column, entry_type, new_value, old_value, result.success, log_path=log_path
        )

    return result


# ---------------------------------------------------------------------------
# Session state - holds the datasets loaded for one audit run (one per entry type),
# plus the sample->GUI-link map. gui_components.py renders from this; it never talks to
# NOMAD directly.
# ---------------------------------------------------------------------------


class EntryAuditSession:
    def __init__(self) -> None:
        self.datasets: dict[str, pd.DataFrame] = {}
        self.sample_ids: list[str] = []
        self.sample_links: dict[str, str] = {}

    @property
    def is_loaded(self) -> bool:
        return bool(self.datasets)

    def load(
        self,
        url: str,
        token: str,
        batch_ids: list[str],
        progress_callback: Callable[[int, int, str], None] | None = None,
    ) -> dict[str, str]:
        """Fetch every ENTRY_TYPES_TO_AUDIT dataset for the samples in batch_ids.
        Returns {label: status_message} for the caller to display. progress_callback,
        if given, is invoked as (index, total, label) before each entry type is
        fetched - gui_components uses it to drive a progress bar without this module
        importing any widget library.

        Before the per-type loop, discover_present_entry_types finds which configured
        entry types actually have anything for this sample set - most configured
        types come back empty for a typical batch, so load_generic_data's full,
        expensive per-type queries are skipped entirely for those instead of being run
        just to learn there's nothing there. Its sample_entry_ids/ref_ids results seed
        load_generic_data's cache so the types that ARE present don't redo that work."""
        self.datasets = {}
        self.sample_ids = get_ids_in_batch_tolerant(url, token, batch_ids)
        self.sample_links = get_sample_links_chunked(url, token, self.sample_ids)

        sample_entry_ids, ref_ids, entry_types_present = discover_present_entry_types(
            url, token, self.sample_ids
        )
        cache: dict[str, Any] = {"sample_entry_ids": sample_entry_ids, "ref_ids": ref_ids}

        total = len(ENTRY_TYPES_TO_AUDIT)
        messages: dict[str, str] = {}
        for index, (label, entry_type) in enumerate(ENTRY_TYPES_TO_AUDIT.items(), start=1):
            if progress_callback is not None:
                progress_callback(index, total, label)
            if entry_type not in entry_types_present:
                messages[label] = "No entries"
                continue
            try:
                df = load_generic_data(url, token, self.sample_ids, entry_type, cache=cache)
            except Exception as exc:  # noqa: BLE001
                logger.exception("Failed to load %s", label)
                messages[label] = f"Skipped: {exc}"
                continue
            if df is not None and not df.empty:
                self.datasets[label] = df
                auditable = len(get_string_columns(df))
                messages[label] = f"Loaded {len(df)} entries, {auditable} auditable field(s)"
            else:
                messages[label] = "No entries"
        return messages

    def load_offline(self, fixture_path: Path) -> bool:
        """Load from a local fixture JSON (offline / demo mode). Fixture shape:
        {"sample_links": {...}, "datasets": {label: [row_dict, ...]}}."""
        with open(fixture_path, encoding="utf-8") as f:
            fixture = json.load(f)
        return self._build_from_raw(fixture.get("datasets", {}), fixture.get("sample_links", {}))

    def _build_from_raw(
        self, raw_datasets: dict[str, list[dict]], sample_links: dict[str, str]
    ) -> bool:
        self.datasets = {}
        for label, rows in raw_datasets.items():
            if rows:
                self.datasets[label] = pd.DataFrame(rows)
        self.sample_links = dict(sample_links)
        self.sample_ids = sorted(
            {
                sample_id
                for df in self.datasets.values()
                for sample_id in df.get("sample_id", pd.Series(dtype=str)).unique()
            }
        )
        return bool(self.datasets)

    def auditable_columns(self, label: str) -> list[str]:
        df = self.datasets.get(label)
        if df is None:
            return []
        columns = get_string_columns(df)
        return [
            column
            for column in columns
            if not any(pattern.search(column) for pattern in _NOISE_COLUMN_PATTERNS)
        ]

    def field_summary(self, label: str, column: str) -> list[dict]:
        df = self.datasets.get(label)
        if df is None:
            return []
        return summarize_field_values(df, column)

    def field_overview(self, label: str) -> list[dict]:
        """One entry per auditable column, for the always-visible summary table:
        {"column", "summary" (per-unique-value rows from field_summary), "is_varied"}."""
        overview = []
        for column in self.auditable_columns(label):
            summary = self.field_summary(label, column)
            overview.append({"column": column, "summary": summary, "is_varied": len(summary) > 1})
        return overview
