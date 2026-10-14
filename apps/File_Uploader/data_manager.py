"""
Data management, state, and file-processing utilities for File_Uploader.

Covers: application state, JSON conversion, file categorisation, and
the chunked-read protocol for ipyvuetify FileInput widgets.
No widget imports in this module.
"""

import json
import logging
import os
import re
from collections import defaultdict
from io import BytesIO
from zipfile import ZipFile

try:
    from hysprint_utils.config import API_ENDPOINT, URL_BASE
except ImportError:
    URL_BASE = "https://nomad-hzb-se.helmholtz-berlin.de"
    API_ENDPOINT = "/nomad-oasis/api/v1"

URL_API = URL_BASE + API_ENDPOINT

try:
    from hysprint_utils.access_token import get_token as _get_token

    TOKEN = _get_token(URL_API)
except Exception:
    TOKEN = os.environ.get("NOMAD_CLIENT_ACCESS_TOKEN", "")

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
MEASUREMENT_TYPES = ["hy"] + sorted(
    [
        "jv",
        "eqe",
        "mppt",
        "sem",
        "xrd",
        "xps",
        "nups",
        "he-ups",
        "cfsys",
        "abspl",
        "pes",
        "nmr",
        "trpl",
        "trspv",
        "pli",
    ]
)
PES_ALIASES = ["nups", "he-ups", "cfsys", "xps"]

# Marker sets used to identify a measurement type from file content when the
# filename gives no hint. A type matches if ALL markers in any one of its
# sets are found (case-insensitive) in the sniffed text. Covers different
# instrument/software export formats for the same measurement type (e.g. a
# Keithley IV-tester export and a SoSim PVcomB export both count as "jv").
CONTENT_TYPE_SIGNATURES = {
    "jv": (
        {"v_oc", "fill factor"},
        {"v_oc", "efficiency"},
    ),
}


# ---------------------------------------------------------------------------
# Application state
# ---------------------------------------------------------------------------
class AppState:
    """Centralised application state; all mutable data lives here."""

    def __init__(self):
        self.upload_files = []
        self.sample_id_buttons = []
        self.sample_buttons = {}
        self.output_areas = {}
        self.sample_files_dict = {}
        self.file_type_dict = {}
        self.selected_sample_id = None
        self.raw_upload_data = None
        self.uploaded_files_data = {}
        self.file_input_widget = None
        self.file_read_status = {}

    def reset_upload(self):
        self.sample_id_buttons = []
        self.sample_buttons = {}
        self.output_areas = {}
        self.sample_files_dict = {}
        self.file_type_dict = {}
        self.selected_sample_id = None
        self.uploaded_files_data = {}
        self.file_read_status = {}

    def set_sample_files(self, sample_id, files):
        self.sample_files_dict[sample_id] = files

    def add_files_to_sample(self, sample_id, files):
        if sample_id not in self.sample_files_dict:
            self.sample_files_dict[sample_id] = []
        self.sample_files_dict[sample_id].extend(files)

    def remove_files_from_sample(self, sample_id, files):
        if sample_id in self.sample_files_dict:
            self.sample_files_dict[sample_id] = [
                f for f in self.sample_files_dict[sample_id] if f not in files
            ]

    def set_file_type(self, sample_id, file_name, file_type):
        if sample_id not in self.file_type_dict:
            self.file_type_dict[sample_id] = {}
        self.file_type_dict[sample_id][file_name] = file_type

    def get_file_type(self, sample_id, file_name, default="hy"):
        if sample_id in self.file_type_dict and file_name in self.file_type_dict[sample_id]:
            return self.file_type_dict[sample_id][file_name]
        return default


state = AppState()


# ---------------------------------------------------------------------------
# File utility functions
# ---------------------------------------------------------------------------
_TYPE_TOKEN_SPLIT = re.compile(r"[._\s-]+")


def type_from_filename(file_name, measurement_types=None):
    """The measurement type a file name names, or None.

    The base name is split into tokens at ".", "_", "-" and spaces and a type must be a whole
    token (trailing digits allowed: "JV3"), so "HySprint_S1_jv.txt" is a jv file, "S2_hysteresis"
    and "anhydrous" name no type, and "xrd_assembly" is not "sem". The first token that names
    a type wins. The generic "hy" is the fallback, never matched."""
    types = [t for t in (measurement_types or MEASUREMENT_TYPES) if t != "hy"]
    base = os.path.splitext(file_name)[0].lower()
    tokens = [t for t in _TYPE_TOKEN_SPLIT.split(base) if t]
    for index, token in enumerate(tokens):
        candidates = {token, re.sub(r"\d+$", "", token)}
        if token == "he" and index + 1 < len(tokens):
            candidates.add(f"he-{re.sub(chr(92) + 'd+$', '', tokens[index + 1])}")
        for mtype in types:
            if mtype in candidates:
                return "pes" if mtype in PES_ALIASES else mtype
    return None


def get_normalized_type(file_name, file_content=None):
    """Determine measurement type from filename, falling back to content sniffing.

    Filename tokens take priority (see type_from_filename); when none names a type and
    `file_content` is available, the first bytes are checked against CONTENT_TYPE_SIGNATURES
    (handles files like Keithley JV exports that carry no type hint in the filename at all).
    """
    named = type_from_filename(file_name)
    if named:
        return named
    sniffed = detect_type_from_content(file_content)
    if sniffed:
        return sniffed
    return "hy"


def detect_type_from_content(file_content, sniff_bytes=4096):
    """Return a measurement type inferred from the start of `file_content`, or None."""
    if not file_content:
        return None
    try:
        text = file_content[:sniff_bytes].decode("utf-8", errors="ignore").lower()
    except Exception as exc:
        logger.debug("detect_type_from_content: decode failed: %s", exc)
        return None
    for mtype, marker_sets in CONTENT_TYPE_SIGNATURES.items():
        for markers in marker_sets:
            if all(marker in text for marker in markers):
                return mtype
    return None


def extract_filenames_from_vuetify(file_data_list):
    """Extract filenames from ipyvuetify FileInput data list."""
    return [fd["name"] for fd in file_data_list if isinstance(fd, dict) and "name" in fd]


def categorize_files(filenames, measurement_types):
    """Split filenames into recognised, unrecognised, and dot-containing groups."""
    recognized, unrecognized, files_with_dots = [], [], []
    for filename in filenames:
        base_name = os.path.splitext(filename)[0]
        if "." in base_name:
            files_with_dots.append(filename)
        if type_from_filename(filename, measurement_types):
            recognized.append(filename)
        else:
            unrecognized.append(filename)
    return recognized, unrecognized, files_with_dots


def natural_sort_key(text):
    """Sort key for human/natural ordering: 'S2' before 'S10', not after."""
    return [int(part) if part.isdigit() else part.lower() for part in re.split(r"(\d+)", text)]


def extract_trailing_number(text):
    """Return the last run of digits found in `text` as an int, or None."""
    matches = re.findall(r"\d+", text)
    return int(matches[-1]) if matches else None


def extract_file_sample_number(filename):
    """Return the sample number embedded in a filename.

    Prefers the number directly after a leading 'S'/'s' token (the common
    "S1", "S2", ... convention), since a trailing number elsewhere in the
    name -- an exposure time, a cell/pixel index, e.g. "S3_1min", "S1_2"
    -- is not the sample number. Falls back to the last run of digits in
    the name when no such token exists.
    """
    match = re.search(r"(?:^|[_\-\s])[Ss](\d+)", filename)
    if match:
        return int(match.group(1))
    return extract_trailing_number(filename)


def match_files_to_samples(filenames, sample_ids):
    """Match files to samples by number (e.g. S8.txt / S8_1.txt -> sample ID ending in 8).

    Returns (matches, unmatched):
        matches: {filename: sample_id} for unambiguous matches
        unmatched: {filename: reason} for files left for manual assignment
    """
    sample_numbers = defaultdict(list)
    for sample_id in sample_ids:
        number = extract_trailing_number(sample_id)
        if number is not None:
            sample_numbers[number].append(sample_id)

    matches = {}
    unmatched = {}
    for filename in filenames:
        number = extract_file_sample_number(filename)
        if number is None:
            unmatched[filename] = "no number found in filename"
            continue
        candidates = sample_numbers.get(number, [])
        if not candidates:
            unmatched[filename] = f"no sample ID ends with {number}"
        elif len(candidates) > 1:
            unmatched[filename] = f"ambiguous: {len(candidates)} sample IDs end with {number}"
        else:
            matches[filename] = candidates[0]
    return matches, unmatched


def create_nomad_filename(sample_id, original_filename, measurement_type, file_extension):
    """Return NOMAD-compliant filename: <sample>.<base>.<type>.<ext>"""
    return f"{sample_id}.{original_filename}.{measurement_type}.{file_extension}"


def get_file_extension(filename):
    return filename.split(".")[-1]


# ---------------------------------------------------------------------------
# Chunked file reader (ipyvuetify FileInput protocol -- no widget import needed)
# ---------------------------------------------------------------------------
def read_file_from_widget(
    file_input_widget,
    file_index,
    on_complete,
    on_error=None,
    chunk_size=512 * 1024,
    out_widget=None,
):
    """
    Non-blocking chunked read from an ipyvuetify FileInput widget.
    Calls on_complete(bytes) on success, on_error(str) on failure.
    """
    try:
        file_size = file_input_widget.file_info[file_index]["size"]
        file_name = file_input_widget.file_info[file_index]["name"]
        all_data = bytearray(file_size)
        offset = 0

        logger.debug("Starting read: %s (%d bytes)", file_name, file_size)

        def request_next_chunk():
            nonlocal offset
            if offset >= file_size:
                logger.debug("Read complete: %s", file_name)
                on_complete(bytes(all_data))
                return

            length = min(chunk_size, file_size - offset)

            class ChunkListener:
                def __init__(self):
                    self.version = file_input_widget.version

                def handle_chunk(self, content, buffer):
                    nonlocal offset
                    chunk_bytes = bytes(buffer)
                    chunk_offset = content["offset"]
                    all_data[chunk_offset : chunk_offset + len(chunk_bytes)] = chunk_bytes
                    offset += len(chunk_bytes)
                    logger.debug("%s: %d%%", file_name, int(offset / file_size * 100))
                    request_next_chunk()

            file_input_widget.chunk_listeners[file_index] = ChunkListener()
            file_input_widget.send(
                {
                    "method": "read",
                    "args": [
                        {
                            "file_index": file_index,
                            "offset": offset,
                            "length": length,
                            "id": file_index,
                        }
                    ],
                }
            )

        request_next_chunk()

    except Exception as exc:
        logger.error("read_file_from_widget failed: %s", exc)
        if on_error:
            on_error(str(exc))


# ---------------------------------------------------------------------------
# JSON processing
# ---------------------------------------------------------------------------
def prepare_json_file_content(file_content, file_name):
    """Parse raw bytes or str as JSON; returns (json_data, is_valid)."""
    try:
        text = file_content.decode("utf-8") if isinstance(file_content, bytes) else file_content
        return json.loads(text), True
    except Exception as exc:
        logger.error("Error parsing JSON %s: %s", file_name, exc)
        return None, False


def extract_measurements_from_json(json_data):
    """Return {sample_cell_direction: entry} dict from a JSON data block."""
    measurements = {}
    if not json_data or "data" not in json_data:
        return measurements
    for entry in json_data["data"]:
        if all(k in entry for k in ("sample", "cell", "direction")):
            mid = f"{entry['sample']}_{entry['cell']}_{entry['direction']}"
            measurements[mid] = entry
    return measurements


def get_samples_from_json(json_data):
    """Return sorted list of unique sample IDs from a JSON data block."""
    if not json_data or "data" not in json_data:
        return []
    return sorted({e["sample"] for e in json_data["data"] if "sample" in e})


def create_nomad_json_content(sample_name, measurement_entries, parameters):
    """Serialise per-sample measurements to UTF-8 JSON bytes."""
    payload = {"parameters": parameters, "data": measurement_entries}
    return json.dumps(payload, indent=2).encode("utf-8")


def split_json_by_sample(json_data):
    """Split a multi-sample JV JSON into one content blob per sample.

    Returns:
        {sample_id: {"json_content": bytes, "measurements": [str], "entries": [dict]}}
    """
    result = {}
    if not json_data or "data" not in json_data:
        return result
    parameters = json_data.get("parameters", {})
    for sample_id in get_samples_from_json(json_data):
        entries = [e for e in json_data["data"] if e.get("sample") == sample_id]
        meas_ids = sorted(
            f"{e['sample']}_{e['cell']}_{e['direction']}"
            for e in entries
            if all(k in e for k in ("sample", "cell", "direction"))
        )
        result[sample_id] = {
            "json_content": create_nomad_json_content(sample_id, entries, parameters),
            "measurements": meas_ids,
            "entries": entries,
        }
    return result


# ---------------------------------------------------------------------------
# Upload: look up the target uploads, build one ZIP per upload, PUT it and wait
# ---------------------------------------------------------------------------
ZIP_MIME_TYPE = "application/zip"


def unavailable_files(sample_files_dict, uploaded_files_data, file_read_status=None):
    """[(sample_id, file_name, reason)] for every assigned file whose content is not available
    (still reading, failed, timed out or never loaded). Uploading without them would silently
    leave them out."""
    file_read_status = file_read_status or {}
    missing = []
    for sample_id, file_names in sample_files_dict.items():
        for file_name in file_names:
            data = uploaded_files_data.get(file_name)
            if data is not None and data.get("file_content"):
                continue
            status = file_read_status.get(file_name)
            if data is None:
                reason = "not loaded"
            elif status and status != "done":
                reason = status
            else:
                reason = "no content"
            missing.append((sample_id, file_name, reason))
    return missing


def nomad_file_name(sample_id, file_name, file_data, measurement_type):
    """The name a file gets inside the upload archive."""
    if file_data.get("is_json"):
        return f"{sample_id}.{file_data['name']}"
    base_name = ".".join(file_name.split(".")[:-1])
    if measurement_type == "jv" and file_data.get("epoch_time"):
        base_name = f"{file_data['epoch_time']}_{base_name}"
    return create_nomad_filename(
        sample_id, base_name, measurement_type, get_file_extension(file_name)
    )


def build_archives(sample_files_dict, file_type_dict, uploaded_files_data, upload_id_by_sample):
    """({upload_id: zip bytes}, [sample_id without an upload]) for the assigned files.

    Every assigned file must have its content (check unavailable_files first); a sample whose
    upload could not be found is returned in the second list instead of being dropped."""
    buffers: dict[str, BytesIO] = {}
    no_upload = []
    for sample_id, file_names in sample_files_dict.items():
        if not file_names:
            continue
        upload_id = upload_id_by_sample.get(sample_id)
        if upload_id is None:
            no_upload.append(sample_id)
            continue
        buffer = buffers.setdefault(upload_id, BytesIO())
        for file_name in file_names:
            file_data = uploaded_files_data[file_name]
            measurement_type = file_type_dict.get(sample_id, {}).get(file_name, "hy")
            name = nomad_file_name(sample_id, file_name, file_data, measurement_type)
            with ZipFile(buffer, "a") as archive:
                archive.writestr(name, file_data["file_content"])
    return {upload_id: buffer.getvalue() for upload_id, buffer in buffers.items()}, no_upload
