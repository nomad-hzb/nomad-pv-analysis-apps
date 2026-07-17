"""
Data management, state, and file-processing utilities for File_Uploader.

Covers: application state, JSON conversion, file categorisation, and
the chunked-read protocol for ipyvuetify FileInput widgets.
No widget imports in this module.
"""

import json
import logging
import os
from pathlib import Path

try:
    from hysprint_utils.config import API_ENDPOINT, URL_BASE
except ImportError:
    URL_BASE = "https://nomad-hzb-se.de"
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


# ---------------------------------------------------------------------------
# Application state
# ---------------------------------------------------------------------------
class AppState:
    """Centralised application state; all mutable data lives here."""

    def __init__(self):
        self.upload_files = []
        self.sample_id_buttons = []
        self.output_areas = {}
        self.sample_files_dict = {}
        self.file_type_dict = {}
        self.selected_sample_id = None
        self.raw_upload_data = None
        self.uploaded_files_data = {}
        self.file_input_widget = None

    def reset_upload(self):
        self.sample_id_buttons = []
        self.output_areas = {}
        self.sample_files_dict = {}
        self.file_type_dict = {}
        self.selected_sample_id = None
        self.uploaded_files_data = {}

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
def get_normalized_type(file_name):
    """Determine measurement type from filename; returns alias-resolved type."""
    file_lower = file_name.lower()
    for mtype in MEASUREMENT_TYPES:
        if mtype in file_lower:
            return "pes" if mtype in PES_ALIASES else mtype
    return "hy"


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
        if any(kw in filename.lower() for kw in measurement_types):
            recognized.append(filename)
        else:
            unrecognized.append(filename)
    return recognized, unrecognized, files_with_dots


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


def format_measurement_for_display(measurement_id, entry):
    return f"{measurement_id} (Card:{entry.get('card')}, Ch:{entry.get('channel')})"


# ---------------------------------------------------------------------------
# File-system loader (development / manual inspection only)
# ---------------------------------------------------------------------------
def load_json_file_sync(file_input_widget, filename):
    """Synchronously read a named JSON file from a FileInput widget."""
    try:
        if hasattr(file_input_widget, "get_files"):
            try:
                for f in file_input_widget.get_files():
                    if isinstance(f, dict) and f.get("name") == filename and f.get("file_obj"):
                        return f["file_obj"].read()
            except Exception:
                pass
        if hasattr(file_input_widget, "file_info"):
            for fi in file_input_widget.file_info:
                if fi.get("name") == filename and fi.get("file_obj"):
                    try:
                        return fi["file_obj"].read()
                    except Exception:
                        pass
        return None
    except Exception as exc:
        logger.error("Error loading JSON file %s: %s", filename, exc)
        return None


def load_json_from_path(file_path):
    """Load JSON from filesystem; returns (json_data, measurement_ids, is_valid)."""
    try:
        path = Path(file_path)
        if not path.exists():
            logger.error("File not found: %s", file_path)
            return None, {}, False
        file_content = path.read_bytes()
        logger.debug("Loaded %d bytes from %s", len(file_content), file_path)
        json_data, is_valid = prepare_json_file_content(file_content, path.name)
        if is_valid and json_data:
            measurements = extract_measurements_from_json(json_data)
            logger.debug(
                "Found %d measurements from %d samples",
                len(measurements),
                len(get_samples_from_json(json_data)),
            )
            return json_data, list(measurements.keys()), True
        return None, {}, False
    except Exception as exc:
        logger.error("Error loading JSON from %s: %s", file_path, exc)
        return None, {}, False
