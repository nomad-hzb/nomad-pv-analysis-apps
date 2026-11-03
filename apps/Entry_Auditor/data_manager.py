# data_manager.py
# Zero widget imports. NOMAD entry fetching/flattening, inconsistency detection (via
# hysprint_utils.consistency), and the raw-file correction/re-upload mechanism.

from __future__ import annotations

import json
import logging
import posixpath
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
import yaml
from pydantic import BaseModel

from hysprint_utils.api_calls import (
    _query_all as query_all,  # the shared paginated POST; public name pending (audit B1)
)
from hysprint_utils.api_calls import get_sample_entry_links
from hysprint_utils.config import ENTRY_TYPES
from hysprint_utils.consistency import (
    DEFAULT_EXCLUDE_COLUMNS,
    get_string_columns,
    summarize_field_values,
)

try:
    from hysprint_utils.config import API_ENDPOINT, URL_BASE
except ImportError:
    URL_BASE = "https://nomad-hzb-se.helmholtz-berlin.de"
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
    "Annealing": "HySprint_Annealing",
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
    # Plotly figures stored on the entry (NOMAD PlotSection "figures", e.g. the JV
    # history plots of a Sample or Batch) and a Sample's per-scan "jv_history_*" lists.
    # The plugin recomputes both from the JV measurements on every processing, so a
    # correction would not stick; and every plot point is a column of its own (over
    # 10,000 for one batch), which stalled the results view (issue #167).
    re.compile(r"(^|\.)figures\."),
    re.compile(r"^jv_history_"),
)


# ---------------------------------------------------------------------------
# Batch/sample resolution
# ---------------------------------------------------------------------------


def get_ids_in_batch_tolerant(url: str, token: str, batch_ids: list[str]) -> list[str]:
    """Like hysprint_utils.api_calls.get_ids_in_batch, but an audit tool also reports
    duplicate batch lab_ids (duplicate/legacy batch names) by name and returns each
    sample once. Logs duplicates instead of raising."""
    if not batch_ids:
        return []
    query: dict[str, Any] = {
        "required": {"data": "*"},
        "owner": "visible",
        "query": {"results.eln.lab_ids:any": batch_ids, "entry_type": ENTRY_TYPES["batch"]},
        "pagination": {"page_size": 100},
    }
    all_data = query_all(url, token, "entries/archive/query", query)

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


# ---------------------------------------------------------------------------
# Generic entry loading (flatten arbitrary archive data into audit-table columns)
# ---------------------------------------------------------------------------

_REF_PATTERN = re.compile(r"archive/([A-Za-z0-9_\-]+)(?:#|$)")


def _is_number(value: Any) -> bool:
    """int/float leaf (a bool is a flag, not a value to audit)."""
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _number_from_text(text: str, like: Any) -> int | float | None:
    """`text` as a number of the same kind as `like` (an int stays an int when it can),
    or None when it is not a number."""
    try:
        if isinstance(like, int):
            return int(text)
    except ValueError:
        pass
    try:
        return float(text)
    except ValueError:
        return None


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
    elif _is_number(obj):
        out[prefix] = str(obj)


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
    chunks = [sample_ids[i : i + chunk_size] for i in range(0, len(sample_ids), chunk_size)]
    all_sample_entry_ids: list[str] = []
    for chunk in chunks:
        data = query_all(
            url,
            token,
            "entries/query",
            {
                "required": {"include": ["entry_id"]},
                "owner": "visible",
                "query": {"results.eln.lab_ids:any": chunk},
                "pagination": {"page_size": 10000},
            },
        )
        all_sample_entry_ids.extend(entry["entry_id"] for entry in data)
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
    chunks = [sample_ids[i : i + chunk_size] for i in range(0, len(sample_ids), chunk_size)]
    ref_ids: set[str] = set()
    for chunk in chunks:
        data = query_all(
            url,
            token,
            "entries/archive/query",
            {
                "required": {"data": "*"},
                "owner": "visible",
                "query": {"results.eln.lab_ids:any": chunk},
                "pagination": {"page_size": 10000},
            },
        )
        for entry in data:
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
    chunks = [sample_ids[i : i + chunk_size] for i in range(0, len(sample_ids), chunk_size)]
    sample_entry_ids: list[str] = []
    entry_types: set[str] = set()

    for chunk in chunks:
        data = query_all(
            url,
            token,
            "entries/query",
            {
                "required": {"include": ["entry_id", "entry_type"]},
                "owner": "visible",
                "query": {"results.eln.lab_ids:any": chunk},
                "pagination": {"page_size": 10000},
            },
        )
        for entry in data:
            sample_entry_ids.append(entry["entry_id"])
            if entry.get("entry_type"):
                entry_types.add(entry["entry_type"])

    id_chunks = [
        sample_entry_ids[i : i + chunk_size] for i in range(0, len(sample_entry_ids), chunk_size)
    ]
    for id_chunk in id_chunks:
        data = query_all(
            url,
            token,
            "entries/query",
            {
                "required": {"include": ["entry_type"]},
                "owner": "visible",
                "query": {"entry_references.target_entry_id:any": id_chunk},
                "pagination": {"page_size": 10000},
            },
        )
        entry_types.update(entry["entry_type"] for entry in data if entry.get("entry_type"))

    ref_ids = _resolve_reference_ids(url, token, sample_ids, chunk_size)
    ref_id_chunks = [list(ref_ids)[i : i + chunk_size] for i in range(0, len(ref_ids), chunk_size)]
    for ref_chunk in ref_id_chunks:
        data = query_all(
            url,
            token,
            "entries/query",
            {
                "required": {"include": ["entry_type"]},
                "owner": "visible",
                "query": {"entry_id:any": ref_chunk},
                "pagination": {"page_size": 10000},
            },
        )
        entry_types.update(entry["entry_type"] for entry in data if entry.get("entry_type"))

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
        return query_all(
            url,
            token,
            "entries/archive/query",
            {
                "required": {"data": "*", "metadata": "*"},
                "owner": "visible",
                "query": {**query_filter, "entry_type": entry_type},
                "pagination": {"page_size": 10000},
            },
        )

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
            data = query_all(
                url,
                token,
                "entries/archive/query",
                {
                    "required": {"data": "*", "metadata": "*"},
                    "owner": "visible",
                    "query": {"entry_id:any": ref_chunk, "entry_type": entry_type},
                    "pagination": {"page_size": 10000},
                },
            )
            process(data)

    return pd.DataFrame(rows) if rows else None


# ---------------------------------------------------------------------------
# Correction mechanism - the downloaded archive file is parsed (JSON or YAML), exactly ONE
# value is changed at the exact path the audited column names, and the file is written back.
# A raw-text regex on the last key segment (the earlier approach) rewrote every field that
# shared that leaf name (issue #56). The edit follows the same path rules as _flatten, so a
# column always maps to one place in the file; anything ambiguous is refused, never guessed.
# ---------------------------------------------------------------------------


def _parse_archive_text(text: str, mainfile: str) -> Any:
    """Parsed content of an archive file, or None when it is not valid JSON/YAML."""
    try:
        if mainfile.endswith(".json"):
            return json.loads(text)
        return yaml.safe_load(text)
    except (ValueError, yaml.YAMLError):
        logger.warning("Could not parse %s", mainfile)
        return None


def _dump_archive_text(data: Any, mainfile: str, original_text: str) -> str:
    """Serialise back, keeping key order; JSON keeps the original indentation style."""
    if mainfile.endswith(".json"):
        lines = original_text.splitlines()
        indent: int | None = None
        if len(lines) > 1:
            leading = len(lines[1]) - len(lines[1].lstrip(" "))
            indent = leading or None
        text = json.dumps(data, indent=indent, ensure_ascii=False)
        return text + ("\n" if original_text.endswith("\n") else "")
    return yaml.safe_dump(data, sort_keys=False, allow_unicode=True, default_flow_style=False)


def _set_at_flat_path(
    obj: Any, parts: list[str], old_value: str, new_value: str
) -> tuple[Any, int]:
    """Replace the string (a number is written back as a number) at the flattened path
    `parts` when it equals old_value; returns (obj, n_changed) with n_changed 0 or 1.
    Mirrors _flatten: a single-item list is
    transparent (consumes no path part), a longer list consumes its 1-based index."""
    if isinstance(obj, list):
        if len(obj) == 1:
            obj[0], changed = _set_at_flat_path(obj[0], parts, old_value, new_value)
            return obj, changed
        if len(obj) > 1 and parts and parts[0].isdigit():
            index = int(parts[0]) - 1
            if 0 <= index < len(obj):
                obj[index], changed = _set_at_flat_path(obj[index], parts[1:], old_value, new_value)
                return obj, changed
        return obj, 0
    if isinstance(obj, dict):
        if parts and parts[0] in obj:
            obj[parts[0]], changed = _set_at_flat_path(
                obj[parts[0]], parts[1:], old_value, new_value
            )
            return obj, changed
        return obj, 0
    if isinstance(obj, str) and not parts and obj == old_value:
        return new_value, 1
    if _is_number(obj) and not parts and str(obj) == old_value:
        number = _number_from_text(new_value, obj)
        return (obj, 0) if number is None else (number, 1)
    return obj, 0


def _data_root(parsed: Any) -> Any:
    """The part of a parsed archive file the audit table was built from.

    The table is flattened from the entry's `data` section, but the raw .archive.json/.yaml wraps
    that section in a top-level "data" key, so a column path starts one level below the file root.
    A file without the wrapper is treated as its own data section."""
    if isinstance(parsed, dict) and isinstance(parsed.get("data"), dict):
        return parsed["data"]
    return parsed


def get_value_at_flat_path(file_text: str, mainfile: str, column: str) -> str | None:
    """The string value the flattened `column` points at in this file, or None."""
    data = _parse_archive_text(file_text, mainfile)
    if data is None:
        return None
    flat: dict[str, str] = {}
    _flatten(_data_root(data), "", flat)
    return flat.get(column)


def modify_file_field(
    file_text: str, mainfile: str, column: str, old_value: str, new_value: str
) -> tuple[str, int]:
    """Change the one value at `column` (a flattened dot path) from old_value to new_value
    in the archive file's text. Works for .archive.json and .archive.yaml. Returns
    (new_text, 1) on success, or (file_text unchanged, 0) when the file does not parse, the
    path does not exist, or the value there is not old_value."""
    data = _parse_archive_text(file_text, mainfile)
    if data is None:
        return file_text, 0
    root = _data_root(data)
    root, changed = _set_at_flat_path(root, column.split("."), str(old_value), str(new_value))
    if root is not data and isinstance(data, dict):
        data["data"] = root
    else:
        data = root
    logger.debug(
        "modify_file_field: column=%s old=%s new=%s changed=%d file=%s",
        column,
        old_value,
        new_value,
        changed,
        mainfile,
    )
    if not changed:
        return file_text, 0
    return _dump_archive_text(data, mainfile, file_text), changed


def fetch_entry_files(
    url: str, token: str, sample_ids: list[str], entry_type: str
) -> list[tuple[str, str, str]]:
    """[(entry_id, upload_id, mainfile), ...] for entries of entry_type linked to
    sample_ids. Used when the audited DataFrame doesn't already carry
    _entry_id/_upload_id/_mainfile columns."""
    if not sample_ids:
        return []

    data = query_all(
        url,
        token,
        "entries/query",
        {
            "required": {"include": ["entry_id"]},
            "owner": "visible",
            "query": {"results.eln.lab_ids:any": sample_ids},
            "pagination": {"page_size": 10000},
        },
    )
    sample_entry_ids = [entry["entry_id"] for entry in data]
    if not sample_entry_ids:
        return []

    data = query_all(
        url,
        token,
        "entries/query",
        {
            "required": {"include": ["entry_id", "upload_id", "mainfile"]},
            "owner": "visible",
            "query": {
                "entry_references.target_entry_id:any": sample_entry_ids,
                "entry_type": entry_type,
            },
            "pagination": {"page_size": 10000},
        },
    )

    result: list[tuple[str, str, str]] = []
    for entry in data:
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


OUTCOME_VERIFIED = "verified"  # processed successfully and the new value is at the path
OUTCOME_UNVERIFIED = "unverified"  # written, but processing timed out or could not be read back
OUTCOME_FAILED = "failed"  # processing failed, or the file does not hold the new value


def _raw_url(url: str, upload_id: str, mainfile: str) -> str:
    return f"{url}/uploads/{upload_id}/raw/{quote(mainfile, safe='/')}"


def upload_corrected_file(
    url: str,
    token: str,
    upload_id: str,
    mainfile: str,
    content: str,
    column: str | None = None,
    new_value: str | None = None,
) -> str:
    """PUT the corrected file back into the folder it came from (a file sent to the upload
    root would become a second entry), wait for NOMAD to process it, then read it back.

    Returns OUTCOME_VERIFIED only when processing ended in SUCCESS and the file holds
    new_value at `column`; OUTCOME_FAILED when processing failed or the stored value is not
    the new one; OUTCOME_UNVERIFIED when processing timed out or the file could not be read
    back. Raises UploadPublishedError for a published upload, and requests errors when a
    request itself fails."""
    headers = {"Authorization": f"Bearer {token}"}

    state_response = requests.get(f"{url}/uploads/{upload_id}", headers=headers, timeout=15)
    state_response.raise_for_status()
    if state_response.json().get("data", {}).get("publish_time"):
        raise UploadPublishedError(f"Upload {upload_id} is published; cannot edit.")

    folder = posixpath.dirname(mainfile)
    target = f"{url}/uploads/{upload_id}/raw/" + (f"{quote(folder, safe='/')}/" if folder else "")
    content_type = "application/json" if mainfile.endswith(".json") else "application/x-yaml"
    put_response = requests.put(
        target,
        headers=headers,
        data={"wait_for_processing": False},
        files={"file": (posixpath.basename(mainfile), content.encode("utf-8"), content_type)},
        timeout=30,
    )
    put_response.raise_for_status()

    status = wait_for_processing(url, token, upload_id)
    if status is None:
        logger.warning("Processing of %s did not finish in time", mainfile)
        return OUTCOME_UNVERIFIED
    if status != "SUCCESS":
        logger.error("Processing of %s ended with status %s", mainfile, status)
        return OUTCOME_FAILED

    verify_response = requests.get(_raw_url(url, upload_id, mainfile), headers=headers, timeout=15)
    if not verify_response.ok or column is None or new_value is None:
        logger.warning("Could not read back %s for verification", mainfile)
        return OUTCOME_UNVERIFIED
    stored = get_value_at_flat_path(verify_response.text, mainfile, column)
    if stored == str(new_value):
        logger.info("Verified: %s = %s in %s", column, new_value, mainfile)
        return OUTCOME_VERIFIED
    logger.error("Verification FAILED: %s holds %r in %s", column, stored, mainfile)
    return OUTCOME_FAILED


# ---------------------------------------------------------------------------
# Correction log - local, append-only file next to this module. In a multi-user Voila
# deployment this is best-effort history, not an audit-grade record: concurrent writes
# from different user sessions are not locked/serialized, and if this app runs in an
# ephemeral per-session container, the log does not persist across sessions at all.
# Accepted tradeoff for v1 - if this needs to be durable/shared, it should move to a
# real backend, not a repo-relative file.
# ---------------------------------------------------------------------------

CORRECTION_LOG_PATH = Path(__file__).parent / "entry_auditor_correction_log.txt"
BACKUP_DIR = Path(__file__).parent / "entry_auditor_backups"
"""Original file text of every entry before it is changed, as
<upload_id>/<mainfile path>.<timestamp>, so a wrong correction can be put back by hand."""


def save_backup(
    upload_id: str, mainfile: str, original_text: str, backup_dir: Path = BACKUP_DIR
) -> Path:
    """Write the original file text under backup_dir and return its path. Raises OSError
    when it cannot be written, in which case the caller must not change the entry."""
    stamp = datetime.now().strftime("%Y%m%dT%H%M%S")
    path = backup_dir / upload_id / f"{mainfile}.{stamp}"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(original_text, encoding="utf-8")
    return path


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
            if len(parts) < 2:
                continue
            correct, wrong = parts[0], parts[1]
            corrections.setdefault(correct, [])
            if wrong not in corrections[correct]:
                corrections[correct].append(wrong)
    return corrections


class CorrectionResult(BaseModel):
    success: int = 0  # verified: processed successfully and read back with the new value
    unverified: int = 0  # written, but processing timed out or could not be confirmed
    failed: int = 0
    skipped: int = 0
    succeeded_entry_ids: list[str] = []
    unverified_entry_ids: list[str] = []

    @property
    def total(self) -> int:
        return self.success + self.unverified + self.failed + self.skipped


def _correction_targets(
    url: str,
    token: str,
    df: pd.DataFrame,
    column: str,
    old_value: str,
    entry_type: str,
    only_entry_id: str | None,
) -> list[tuple[str, str, str]]:
    """[(entry_id, upload_id, mainfile)] of the entries a correction would touch."""
    affected_rows = df[df[column] == old_value]
    if only_entry_id and "_entry_id" in affected_rows.columns:
        affected_rows = affected_rows[affected_rows["_entry_id"] == only_entry_id]

    if "_entry_id" in df.columns:
        return [
            (row["_entry_id"], row["_upload_id"], row["_mainfile"])
            for _, row in affected_rows.iterrows()
            if row.get("_entry_id") and row.get("_upload_id") and row.get("_mainfile")
        ]
    affected_sample_ids = list(affected_rows["sample_id"].unique())
    return fetch_entry_files(url, token, affected_sample_ids, entry_type)


def preview_correction(
    url: str,
    token: str,
    df: pd.DataFrame,
    column: str,
    old_value: str,
    new_value: str,
    entry_type: str,
    only_entry_id: str | None = None,
    progress_callback: Callable[[int, int], None] | None = None,
) -> list[dict[str, Any]]:
    """What apply_correction would do, without writing anything: one dict per entry with
    entry_id, upload_id, mainfile, and status "change" (the value at `column` is old_value
    and would become new_value), "no_match" (not at that path) or "error" (with `detail`).
    Downloads only."""
    entry_files = _correction_targets(url, token, df, column, old_value, entry_type, only_entry_id)
    preview: list[dict[str, Any]] = []
    total = len(entry_files)
    for index, (entry_id, upload_id, mainfile) in enumerate(entry_files, start=1):
        if progress_callback is not None:
            progress_callback(index, total)
        item = {
            "entry_id": entry_id,
            "upload_id": upload_id,
            "mainfile": mainfile,
            "before": old_value,
            "after": new_value,
        }
        try:
            file_text = download_file(url, token, upload_id, mainfile)
            _, changed = modify_file_field(file_text, mainfile, column, old_value, new_value)
            item["status"] = "change" if changed else "no_match"
        except Exception as exc:  # noqa: BLE001
            logger.exception("Preview failed for entry %s", entry_id)
            item["status"] = "error"
            item["detail"] = str(exc)
        preview.append(item)
    return preview


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
    backup_dir: Path = BACKUP_DIR,
) -> CorrectionResult:
    """Change the value at `column` from old_value to new_value in every matching entry:
    download the entry's raw file, save a backup of it, change exactly that one value, PUT
    it back into its own folder, and read it back. An entry counts as updated (and is
    logged) only when NOMAD processed it successfully and it holds the new value; a timeout
    or unreadable result is counted as unverified, a failed processing or any error as
    failed, and a file where the value is not at that path as skipped. Never raises on a
    per-entry failure, so one bad entry does not abort the batch. Uses df's own
    _entry_id/_upload_id/_mainfile columns when present, else resolves them via
    fetch_entry_files. If only_entry_id is given, only that entry is touched.
    progress_callback is invoked as (index, total) before each entry, so the GUI can drive
    a progress bar without this module importing a widget library."""
    entry_files = _correction_targets(url, token, df, column, old_value, entry_type, only_entry_id)

    result = CorrectionResult()
    total = len(entry_files)
    for index, (entry_id, upload_id, mainfile) in enumerate(entry_files, start=1):
        if progress_callback is not None:
            progress_callback(index, total)
        try:
            file_text = download_file(url, token, upload_id, mainfile)
            modified_text, n_changed = modify_file_field(
                file_text, mainfile, column, old_value, new_value
            )
            if n_changed == 0:
                logger.warning("%s is not %r in entry %s", column, old_value, entry_id)
                result.skipped += 1
                continue
            save_backup(upload_id, mainfile, file_text, backup_dir)
            outcome = upload_corrected_file(
                url, token, upload_id, mainfile, modified_text, column=column, new_value=new_value
            )
            if outcome == OUTCOME_VERIFIED:
                logger.info("Corrected entry %s", entry_id)
                result.success += 1
                result.succeeded_entry_ids.append(entry_id)
            elif outcome == OUTCOME_UNVERIFIED:
                result.unverified += 1
                result.unverified_entry_ids.append(entry_id)
            else:
                result.failed += 1
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
                auditable = len(self.auditable_columns(label))
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
        # Drop the noise columns before get_string_columns, not after: its per-column
        # checks are the slow part when an entry carries thousands of plot-point columns.
        noise = {
            column
            for column in df.columns
            if any(pattern.search(column) for pattern in _NOISE_COLUMN_PATTERNS)
        }
        return get_string_columns(df, exclude_columns=DEFAULT_EXCLUDE_COLUMNS | noise)

    def field_summary(self, label: str, column: str) -> list[dict]:
        df = self.datasets.get(label)
        if df is None:
            return []
        # Only this column: summarize_field_values copies the frame it gets once per value,
        # which takes seconds per field when an entry carries thousands of plot columns.
        return summarize_field_values(df[[column]], column)

    def field_overview(self, label: str) -> list[dict]:
        """One entry per auditable column, for the always-visible summary table:
        {"column", "summary" (per-unique-value rows from field_summary), "is_varied"}."""
        overview = []
        for column in self.auditable_columns(label):
            summary = self.field_summary(label, column)
            overview.append({"column": column, "summary": summary, "is_varied": len(summary) > 1})
        return overview
