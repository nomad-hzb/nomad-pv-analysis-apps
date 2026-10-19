# nomad_prefill.py
# Zero widget imports. The samples of one NOMAD upload, as Experiment Info rows for the
# Experiment Data sheet. The app only calls this from its hidden "Prefill from NOMAD" panel;
# without it the app never talks to NOMAD.

import logging
import re
from dataclasses import dataclass, field

from hysprint_utils.api_calls import get_all_uploads, get_samples_with_substrates
from hysprint_utils.auth_manager import AuthenticationManager
from hysprint_utils.process_specs import build_field_paths, build_field_value_multipliers

try:
    from hysprint_utils.config import API_ENDPOINT, URL_BASE
except ImportError:
    URL_BASE = "https://nomad-hzb-se.helmholtz-berlin.de"
    API_ENDPOINT = "/nomad-oasis/api/v1"
    logging.getLogger(__name__).warning(
        "hysprint_utils.config not found; using hardcoded URL fallback"
    )

logger = logging.getLogger(__name__)

# How many of the user's newest uploads the dropdown offers.
UPLOAD_LIMIT = 100

# Experiment Info column -> archive paths into {"sample": ..., "substrate": ...}, and the
# confirmed unit factors, both from process_specs (the single source of truth). Columns
# without a path there (Date, Project_Name, Batch, ...) are never filled from NOMAD.
INFO_FIELD_PATHS = {
    key: paths for key, (paths, _unit_verified) in build_field_paths()["Experiment Info"].items()
}
INFO_MULTIPLIERS = build_field_value_multipliers().get("Experiment Info", {})

# The sheet's Nomad ID formula builds HZB_<Project_Name>_<Batch>_<Subbatch>_C-<Sample>
# (sheet_experiment.py); this reads a lab_id back into those columns. Batch, Subbatch and
# Sample are taken without underscores from the right and the project gets the rest, so the
# parts always rebuild exactly the same lab_id, also for a project name with underscores.
_LAB_ID_RE = re.compile(
    r"^HZB_(?P<Project_Name>.+)_(?P<Batch>[^_]+)_(?P<Subbatch>[^_]+)_C-(?P<Sample>[^_]+)$"
)
LAB_ID_COLUMNS = ("Project_Name", "Batch", "Subbatch", "Sample")


@dataclass(frozen=True)
class PrefillSample:
    """One sample row of the sheet: its lab_id (the Nomad ID) and the other Experiment Info
    columns NOMAD has a value for."""

    lab_id: str
    fields: dict = field(default_factory=dict)

    def as_row(self) -> dict:
        """{column header: value}, the form add_experiment_sheet takes."""
        return {"Nomad ID": self.lab_id, **self.fields}


def connect() -> tuple[str, str]:
    """(API url, token) for the configured Oasis, with the token of the NORTH container
    (NOMAD_CLIENT_ACCESS_TOKEN). Raises ValueError when there is none."""
    auth = AuthenticationManager(URL_BASE, API_ENDPOINT)
    return auth.url, auth.authenticate_with_token()


def upload_choices(uploads: list[dict]) -> list[tuple[str, str]]:
    """(label, upload_id) for a dropdown, in the order given (NOMAD returns newest first).
    The label is the upload name, or the id for an upload without one; names that occur
    more than once get the id appended, so the user can tell them apart."""
    names = [u.get("upload_name") or u["upload_id"] for u in uploads]
    choices = []
    for name, upload in zip(names, uploads, strict=True):
        label = f"{name} ({upload['upload_id']})" if names.count(name) > 1 else name
        choices.append((label, upload["upload_id"]))
    return choices


def _value_at(source, path):
    current = source
    for key in path:
        if isinstance(key, int):
            if not isinstance(current, list) or not -len(current) <= key < len(current):
                return None
            current = current[key]
        elif isinstance(current, dict):
            current = current.get(key)
        else:
            return None
    return current


def info_fields(source: dict) -> dict:
    """The Experiment Info columns that have a value in source ({"sample": ...,
    "substrate": ...}). The first path that gives a value wins; only plain values (text,
    numbers) are taken, with process_specs' confirmed unit factor applied."""
    values = {}
    for key, paths in INFO_FIELD_PATHS.items():
        for path in paths:
            value = _value_at(source, path)
            if isinstance(value, bool) or not isinstance(value, str | int | float):
                continue
            if isinstance(value, str) and not value.strip():
                continue
            if key in INFO_MULTIPLIERS and not isinstance(value, str):
                value = value * INFO_MULTIPLIERS[key]
            values[key] = value
            break
    return values


def parse_lab_id(lab_id: str) -> dict:
    """{Project_Name, Batch, Subbatch, Sample} of a lab_id made by the Nomad ID formula, or
    {} for one that does not follow it (then those columns stay for the user)."""
    match = _LAB_ID_RE.match(lab_id)
    return match.groupdict() if match else {}


def samples_from_sources(sources: list[dict]) -> list[PrefillSample]:
    """PrefillSamples sorted by lab_id; sources without a lab_id are skipped."""
    samples = []
    for source in sources:
        lab_id = (source.get("sample") or {}).get("lab_id")
        if lab_id:
            lab_id = str(lab_id)
            fields = {**parse_lab_id(lab_id), **info_fields(source)}
            samples.append(PrefillSample(lab_id, fields))
    return sorted(samples, key=lambda s: s.lab_id)


def filled_columns(samples: list[PrefillSample]) -> list[str]:
    """The columns at least one sample fills, in sheet order."""
    present = {key for s in samples for key in s.fields} | {"Nomad ID"}
    order = [*LAB_ID_COLUMNS, "Nomad ID", *INFO_FIELD_PATHS]
    return [key for key in order if key in present]


def fetch_uploads(url: str, token: str, limit: int = UPLOAD_LIMIT) -> list[dict]:
    """The user's own newest uploads."""
    return get_all_uploads(url, token, number_of_uploads=limit)


def fetch_samples_in_upload(url: str, token: str, upload_id: str) -> list[PrefillSample]:
    """Every sample of the upload, with what NOMAD knows of it and of its substrate."""
    samples = samples_from_sources(get_samples_with_substrates(url, token, upload_id))
    logger.info("Upload %s has %d samples", upload_id, len(samples))
    return samples
