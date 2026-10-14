"""
data_manager.py
----------------
Pure Python / Pydantic layer for the LCC (Life Cycle Costing) Calculator.
No widget imports. Fetches processes/materials for selected batches from
NOMAD, and computes cost line items/totals in Python so the same numbers
feed both the in-app table (gui_components.py) and the exported workbook
(excel_export.py).
"""

from __future__ import annotations

import io
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

import openpyxl
import requests
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Domain models
# ---------------------------------------------------------------------------

# Fixed labor role tiers - NOMAD has no field tracking who (or what role)
# ran a process (confirmed against live data: `operator` is populated on
# roughly half of process entries and is only ever a free-text name, never
# a role), so labor cost cannot be auto-extracted per process instance.
# Instead a batch's labor cost is entered manually per role (hours worked),
# with the hourly rate coming from the shared cost reference file.
LABOR_ROLES = ["PhD Researcher", "Postdoc", "Engineer", "HiWi"]

# Canonical glovebox/tool names, as given by the lab (not derived from
# NOMAD's `location` field, which is free text typed by whoever ran the
# process - confirmed against live data to have many inconsistent variants
# of the same physical box, e.g. "HySpinBox"/"HySpin GB"/"Hyspin"/"hyspin").
# Used only as the Capital_Overhead_Disposal Location dropdown's option
# list - not matched automatically against the raw NOMAD text.
KNOWN_LOCATIONS = [
    "HyWeighBox",
    "HySolveBox",
    "HySpinBox",
    "HyPeroSpinBox",
    "HyALDBox",
    "HyVapBox",
    "HyPeroVapBox",
    "HyMessBox",
    "HySnPbBox",
    "ProtoSolveBox",
    "ProtoVapBox",
    "TinSpinBox",
    "TinVapBox",
    "TinHallBox",
    "InkCoatBox",
    "InkRollBox",
    "InkVapBox",
    "InkPatternBox",
]


class ProcessStepRow(BaseModel):
    batch_id: str
    process_type: str
    location: str = ""  # raw NOMAD text, informational only - see KNOWN_LOCATIONS note above
    position_in_plan: float | None = None
    step_index: int = 0
    step_label: str = ""
    duration_value: float | None = None
    duration_unit: str = ""
    rate_value: float | None = None
    rate_unit: str = ""
    num_samples_covered: int = 1
    sample_ids: list[str] = Field(default_factory=list)


class MaterialRow(BaseModel):
    batch_id: str
    process_type: str
    material_name: str
    role: str
    quantity_value: float | None = None
    quantity_unit: str = ""
    cas_number: str | None = None
    molar_mass_g_per_mol: float | None = None
    price_per_gram_est: float | None = None
    num_samples_covered: int = 1
    sample_ids: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Static chemical reference table
# ---------------------------------------------------------------------------
# No price data exists anywhere in this repo (confirmed by search), and live
# NOMAD data almost never has cas_number/molar_mass populated on chemical
# references either (checked against real entries: the fields exist in the
# schema but come back empty). CAS numbers below are real, well-established
# chemistry (safe to trust); price_per_gram_est is a rough general-knowledge
# estimate, NOT a live supplier lookup - every row using it is written to
# Excel with Verified=FALSE and a note asking colleagues to confirm.

# (name, cas_number, molar_mass_g_per_mol, price_per_gram_est)
_CHEMICAL_REFERENCE_ROWS: list[tuple[str, str, float, float]] = [
    ("PbI2", "10101-63-0", 461.01, 3.0),
    ("PbBr2", "10031-22-8", 367.01, 3.0),
    ("MAI", "14965-49-2", 158.97, 15.0),
    ("MABr", "18617-60-8", 111.97, 15.0),
    ("FAI", "879643-71-7", 186.99, 20.0),
    ("FABr", "1197196-79-2", 153.99, 20.0),
    ("MACl", "593-51-1", 67.52, 5.0),
    ("CsI", "7789-17-5", 259.81, 2.0),
    ("Cs2CO3", "534-17-8", 325.82, 3.0),
    ("Spiro-OMeTAD", "741909-64-2", 1225.44, 400.0),
    ("Li-TFSI", "90076-65-6", 287.09, 10.0),
    ("4-tert-Butylpyridine", "3978-81-2", 135.21, 1.0),
    ("DMF", "68-12-2", 73.09, 0.1),
    ("DMSO", "67-68-5", 78.13, 0.1),
    ("Chlorobenzene", "108-90-7", 112.56, 0.1),
    ("GBL", "96-48-0", 86.09, 0.2),
    ("IPA", "67-63-0", 60.10, 0.05),
    ("Toluene", "108-88-3", 92.14, 0.05),
    ("PCBM", "160848-22-6", 910.88, 100.0),
    ("C60", "99685-96-8", 720.66, 50.0),
]

CHEMICAL_REFERENCE: dict[str, dict] = {
    name: {"cas_number": cas, "molar_mass_g_per_mol": molar_mass, "price_per_gram_est": price}
    for name, cas, molar_mass, price in _CHEMICAL_REFERENCE_ROWS
}

CHEMICAL_REFERENCE_NOTE = (
    "Rough estimate based on general market knowledge, not a live supplier "
    "lookup - please confirm against your actual supplier/contract price."
)

# ---------------------------------------------------------------------------
# Generic flattening (adapted from Global_analyzer's _flatten_process_entry;
# reimplemented locally since apps don't import each other's app-local
# modules - see plan notes)
# ---------------------------------------------------------------------------


def flatten_entry(entry: dict, prefix: str = "") -> dict:
    """Recursively flatten a nested dict/list into dot-path keys.

    Single-item lists are unwrapped in place; multi-item lists get numeric
    ``.1``, ``.2``, ... suffixes so repeated sub-structures (e.g. recipe
    steps) become distinguishable keys instead of colliding.
    """
    out: dict = {}
    for key, value in entry.items():
        path = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            out.update(flatten_entry(value, path))
        elif isinstance(value, list):
            if not value:
                continue
            if len(value) == 1:
                item = value[0]
                if isinstance(item, dict):
                    out.update(flatten_entry(item, path))
                else:
                    out[path] = item
            else:
                for index, item in enumerate(value, start=1):
                    if isinstance(item, dict):
                        out.update(flatten_entry(item, f"{path}.{index}"))
                    else:
                        out[f"{path}.{index}"] = item
        elif isinstance(value, (str, int, float, bool)) or value is None:
            out[path] = value
    return out


_STEP_INDEX_RE = re.compile(r"^(?P<prefix>.+)\.(?P<index>\d+)\.(?P<field>.+)$")

_TIME_KEY_HINTS = ("time", "duration")
_RATE_KEY_HINTS = ("rate", "speed", "frequency")
_STEP_LIST_NAME_HINTS = ("step",)
_STEP_LIST_ALLOWLIST = {"cleaning", "cleaning_uv", "organic_evaporation"}

_SKIP_TOP_LEVEL_KEYS = {
    "samples",
    "m_def",
    "positon_in_experimental_plan",
    "datetime",
    "name",
    "description",
    "location",
    "operator",
    "lab_id",
}


def _group_into_steps(flat: dict) -> dict[tuple[str, int], dict]:
    """Group flattened dot-path keys by their list-index segment.

    Keys with no numeric list-index segment (e.g. a single-step process)
    fall under the sentinel key ("", 0).
    """
    steps: dict[tuple[str, int], dict] = {}
    for key, value in flat.items():
        match = _STEP_INDEX_RE.match(key)
        if match:
            step_key = (match.group("prefix"), int(match.group("index")))
            step_field = match.group("field")
        else:
            step_key = ("", 0)
            step_field = key
        steps.setdefault(step_key, {})[step_field] = value
    return steps


def _is_step_list_prefix(prefix: str) -> bool:
    if not prefix:
        return False
    last_segment = prefix.rsplit(".", 1)[-1].lower()
    return (
        any(hint in last_segment for hint in _STEP_LIST_NAME_HINTS)
        or last_segment in _STEP_LIST_ALLOWLIST
    )


def _first_numeric_match(fields: dict, hints: tuple[str, ...]) -> tuple[str, float] | None:
    for key, value in fields.items():
        if isinstance(value, bool):
            continue
        if isinstance(value, (int, float)) and any(hint in key.lower() for hint in hints):
            return key, float(value)
    return None


def extract_process_step_rows(
    process_data: dict,
    process_type: str,
    batch_id: str,
    num_samples_covered: int,
    sample_ids: list[str],
) -> list[ProcessStepRow]:
    """One row for the process itself (step_index 0), plus one row per
    detected step-like sub-list (e.g. recipe_steps, cleaning) - not every
    multi-item list, since solute/solvent lists belong to Materials, not
    Processes. Duration/rate/location only - no cost here. Cost is looked up
    per process type (and per location, for equipment) later, by
    compute_process_cost_rows, against the shared cost reference.
    """
    relevant = {k: v for k, v in process_data.items() if k not in _SKIP_TOP_LEVEL_KEYS}
    flat = flatten_entry(relevant)
    grouped = _group_into_steps(flat)
    position = process_data.get("positon_in_experimental_plan")
    location = str(process_data.get("location") or "").strip()

    rows: list[ProcessStepRow] = []
    for (prefix, index), fields in sorted(grouped.items(), key=lambda item: item[0]):
        if prefix and not _is_step_list_prefix(prefix):
            continue
        duration = _first_numeric_match(fields, _TIME_KEY_HINTS)
        rate = _first_numeric_match(fields, _RATE_KEY_HINTS)
        rows.append(
            ProcessStepRow(
                batch_id=batch_id,
                process_type=process_type,
                location=location,
                position_in_plan=position,
                step_index=index,
                step_label=prefix or process_type,
                duration_value=duration[1] if duration else None,
                duration_unit="as provided by NOMAD" if duration else "",
                rate_value=rate[1] if rate else None,
                rate_unit="as provided by NOMAD" if rate else "",
                num_samples_covered=num_samples_covered,
                sample_ids=list(sample_ids),
            )
        )
    return rows


# ---------------------------------------------------------------------------
# Material extraction (known NOMAD field shapes, see plan research notes)
# ---------------------------------------------------------------------------


def extract_material_rows(
    process_data: dict,
    process_type: str,
    batch_id: str,
    num_samples_covered: int,
    sample_ids: list[str],
) -> list[MaterialRow]:
    rows: list[MaterialRow] = []

    def add(
        material_name,
        role: str,
        quantity_value,
        quantity_unit: str,
        chemical: dict | None = None,
    ):
        if not material_name or not str(material_name).strip():
            return
        name = str(material_name).strip()
        static_ref = CHEMICAL_REFERENCE.get(name)

        # A real cas_number/molar_mass straight from NOMAD (when a chemist
        # actually ran the PubChem lookup for this reference) always wins
        # over the static guess table - it's authoritative, not an estimate.
        chemical = chemical or {}
        static_cas = static_ref["cas_number"] if static_ref else None
        static_molar_mass = static_ref["molar_mass_g_per_mol"] if static_ref else None
        cas_number = chemical.get("cas_number") or static_cas
        molar_mass = chemical.get("molar_mass") or static_molar_mass

        rows.append(
            MaterialRow(
                batch_id=batch_id,
                process_type=process_type,
                material_name=name,
                role=role,
                quantity_value=quantity_value,
                quantity_unit=quantity_unit,
                cas_number=cas_number,
                molar_mass_g_per_mol=molar_mass,
                price_per_gram_est=static_ref["price_per_gram_est"] if static_ref else None,
                num_samples_covered=num_samples_covered,
                sample_ids=list(sample_ids),
            )
        )

    layers = process_data.get("layer") or []
    if layers and isinstance(layers[0], dict):
        add(layers[0].get("layer_material_name"), "layer", None, "")

    solution_list = process_data.get("solution") or []
    if solution_list and isinstance(solution_list[0], dict):
        details = solution_list[0].get("solution_details") or {}
        for solute in details.get("solute") or []:
            if not isinstance(solute, dict):
                continue
            chemical = solute.get("chemical_2") or {}
            add(
                chemical.get("name"),
                "solute",
                solute.get("concentration_mol"),
                "mol (as provided)",
                chemical,
            )
        for solvent in details.get("solvent") or []:
            if not isinstance(solvent, dict):
                continue
            chemical = solvent.get("chemical_2") or {}
            add(
                chemical.get("name"),
                "solvent",
                solvent.get("chemical_volume"),
                "volume (as provided)",
                chemical,
            )

    for evap in process_data.get("organic_evaporation") or []:
        if not isinstance(evap, dict):
            continue
        chemical = evap.get("chemical_2") or {}
        add(
            chemical.get("name"),
            "evaporant",
            evap.get("thickness"),
            "thickness (as provided)",
            chemical,
        )

    substrate = process_data.get("substrate_data") or {}
    conducting = substrate.get("conducting_material")
    if isinstance(conducting, list) and conducting:
        add(", ".join(str(c) for c in conducting), "substrate", None, "")

    return rows


# ---------------------------------------------------------------------------
# NOMAD API access
# ---------------------------------------------------------------------------


def fetch_samples_per_batch(url: str, token: str, batch_ids: list[str]) -> dict[str, list[str]]:
    """Map each batch id to its own sample ids.

    hysprint_utils.api_calls.get_ids_in_batch returns one flat list across
    all requested batches, which loses the per-batch grouping this app
    needs (batch sample counts, per-sample cost allocation) - so batches
    are queried one at a time here instead. Confirmed against a full scan
    of every real batch on this instance that a handful of batches trip
    get_ids_in_batch up in more than one way - an AssertionError (its
    "exactly one batch record" check failing on a stale/unusual batch
    entry) and a KeyError (an "entities" item missing "lab_id" entirely,
    from malformed/legacy batch data). Either would otherwise crash the
    whole scan over one unrelated bad batch - such a batch is skipped
    (logged), not fatal.
    """
    from hysprint_utils.api_calls import get_ids_in_batch

    result: dict[str, list[str]] = {}
    for batch_id in batch_ids:
        try:
            result[batch_id] = get_ids_in_batch(url, token, [batch_id])
        except (AssertionError, KeyError):
            logger.warning("Skipping batch %s - could not resolve its samples via NOMAD.", batch_id)
    return result


# NOMAD's search backend caps how many terms an :any query clause can hold
# (confirmed against a live full-instance scan of ~400 batches / ~6000
# samples: a single unchunked query raised "400 Bad Request"). Queries
# built from an arbitrary-length sample/entry id list are chunked to this
# size and the results merged, so a broad admin scan doesn't crash the way
# a normal few-batch selection never would.
_QUERY_CHUNK_SIZE = 300

# Seconds: a stalled NOMAD request must not block the kernel (and the "Loading..." status)
# forever.
_REQUEST_TIMEOUT = 60


def _chunked(items: list[str], size: int = _QUERY_CHUNK_SIZE) -> list[list[str]]:
    return [items[i : i + size] for i in range(0, len(items), size)]


def _fetch_entry_ids_for_samples(
    url: str, token: str, headers: dict, sample_ids: list[str]
) -> list[str]:
    entry_ids: list[str] = []
    for chunk in _chunked(sample_ids):
        query = {
            "required": {"metadata": "*"},
            "owner": "visible",
            "query": {"results.eln.lab_ids:any": chunk},
            "pagination": {"page_size": 10000},
        }
        response = requests.post(
            f"{url}/entries/query", headers=headers, json=query, timeout=_REQUEST_TIMEOUT
        )
        response.raise_for_status()
        entry_ids.extend(entry["entry_id"] for entry in response.json()["data"])
    return entry_ids


def fetch_process_entries(
    url: str, token: str, sample_ids: list[str], process_type: str = "baseclasses.BaseProcess"
) -> list[tuple[dict, str]]:
    """Fetch every process entry linked to sample_ids, keeping the full
    ``samples`` list on each entry (hysprint_utils.api_calls.get_processing_steps
    and get_all_eqe only keep samples[0] - not reusable here since knowing how
    many samples a single process instance actually covers is exactly what
    lets 'one evaporation run for 16 samples' cost 1x per batch and 1/16th
    per sample instead of a guess).

    Returns a list of (process_data, entry_type) tuples, sorted by
    positon_in_experimental_plan (NOMAD's field name, not a typo introduced
    here).
    """
    headers = {"Authorization": f"Bearer {token}"}
    entry_ids = _fetch_entry_ids_for_samples(url, token, headers, sample_ids)

    entries = []
    seen_entry_ids: set[str] = set()
    for chunk in _chunked(entry_ids):
        process_query = {
            "required": {"data": "*", "metadata": "*"},
            "owner": "visible",
            "query": {
                "entry_references.target_entry_id:any": chunk,
                "section_defs.definition_qualified_name": process_type,
            },
            "pagination": {"page_size": 10000},
        }
        response = requests.post(
            f"{url}/entries/archive/query",
            headers=headers,
            json=process_query,
            timeout=_REQUEST_TIMEOUT,
        )
        response.raise_for_status()

        for entry in response.json()["data"]:
            # A process that references several samples comes back from every chunk that
            # holds one of them; count it once (its steps and materials were doubled before).
            entry_id = (entry.get("archive", {}).get("metadata") or {}).get(
                "entry_id"
            ) or entry.get("entry_id")
            if entry_id is not None:
                if entry_id in seen_entry_ids:
                    continue
                seen_entry_ids.add(entry_id)
            archive = entry["archive"]
            process_data = archive.get("data") or {}
            if "positon_in_experimental_plan" not in process_data:
                continue
            entry_type = (archive.get("metadata") or {}).get("entry_type") or process_data.get(
                "name", "Unknown Process"
            )
            entries.append((process_data, entry_type))

    entries.sort(key=lambda item: item[0]["positon_in_experimental_plan"])
    return entries


# entry types that are structural (the batch/sample records themselves), not
# a process or measurement someone would want in a cost catalog.
_EXCLUDED_SCHEMA_TYPES = {"HySprint_Batch", "HySprint_Sample"}


def discover_entry_types(url: str, token: str, sample_ids: list[str]) -> list[str]:
    """Every distinct schema (process AND measurement, e.g. HySprint_SpinCoating,
    HySprint_JVmeasurement) actually linked to these samples, via NOMAD's
    aggregation API - no hardcoded list of measurement types needed.
    Measurement schemas don't declare baseclasses.BaseMeasurement in
    section_defs the way process schemas declare baseclasses.BaseProcess
    (confirmed against live data: querying by that qualified name returns
    zero measurements), so this uses a plain entry_type aggregation instead,
    which works for anything.
    """
    headers = {"Authorization": f"Bearer {token}"}
    entry_ids = _fetch_entry_ids_for_samples(url, token, headers, sample_ids)
    if not entry_ids:
        return []

    found_types: set[str] = set()
    for chunk in _chunked(entry_ids):
        aggregation_query = {
            "owner": "visible",
            "query": {"entry_references.target_entry_id:any": chunk},
            "aggregations": {"entry_type_agg": {"terms": {"quantity": "entry_type", "size": 200}}},
            "pagination": {"page_size": 0},
        }
        response = requests.post(
            f"{url}/entries/query",
            headers=headers,
            json=aggregation_query,
            timeout=_REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        terms = response.json().get("aggregations", {}).get("entry_type_agg", {}).get("terms", {})
        found_types.update(entry["value"] for entry in terms.get("data", []))

    return sorted(
        entry_type for entry_type in found_types if entry_type not in _EXCLUDED_SCHEMA_TYPES
    )


# ---------------------------------------------------------------------------
# The shared cost reference file - single source of truth for cost figures
# ---------------------------------------------------------------------------
# An admin maintains one workbook (see DEFAULT_COST_REFERENCE_PATH below)
# with real prices/rates, marks them Verified, and saves it in place. Every
# user's export automatically reads that same file and carries forward
# anything that matches by name - no upload step, nothing for a regular
# user to configure. No cost ranges (Low/Est/High) anymore - one figure per
# line, kept simple per explicit feedback.


ALLOCATION_PER_BATCH = "per batch"
ALLOCATION_PER_SAMPLE = "per sample"
ALLOCATION_PER_HOUR = "per hour"


@dataclass
class CostReference:
    process_costs: dict[str, dict] = field(default_factory=dict)  # by Process_Type
    material_prices: dict[str, dict] = field(default_factory=dict)  # by Material_Name
    labor_rates: dict[str, dict] = field(default_factory=dict)  # by Role (LABOR_ROLES)
    overhead_costs: dict[str, dict] = field(default_factory=dict)  # by Item
    location_costs: dict[str, dict] = field(
        default_factory=dict
    )  # by Location, subset of overhead_costs
    problems: list[str] = field(default_factory=list)
    """Cells that could not be used (text where a number belongs, a sheet without its key
    column), as readable sentences for the user. Such a cell counts as a missing cost."""

    @property
    def total_entries(self) -> int:
        return (
            len(self.process_costs)
            + len(self.material_prices)
            + len(self.labor_rates)
            + len(self.overhead_costs)
        )

    @property
    def has_any_cost(self) -> bool:
        """True when at least one cost figure is actually filled in."""
        figures = [entry.get("cost_est") for entry in self.process_costs.values()]
        figures += [entry.get("price_per_gram_est") for entry in self.material_prices.values()]
        figures += [entry.get("hourly_rate_est") for entry in self.labor_rates.values()]
        figures += [entry.get("cost_est") for entry in self.overhead_costs.values()]
        return any(figure is not None for figure in figures)


def _header_index_map(ws) -> dict[str, int]:
    return {cell.value: index for index, cell in enumerate(ws[1]) if cell.value}


def _to_float_or_none(value, where: str, problems: list[str]) -> float | None:
    """A cost cell as a number, or None when it is blank. Text such as "TBD", "12 EUR" or an
    unevaluated formula (the workbook is read with data_only=False) is not a number: it is
    reported in `problems` and treated as missing instead of crashing the load later."""
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        problems.append(f"{where}: {value!r} is not a number")
        return None
    if isinstance(value, (int, float)):
        return float(value)
    problems.append(f"{where}: {value!r} is not a number")
    return None


def _cell(row, idx: dict[str, int], name: str):
    position = idx.get(name)
    return row[position] if position is not None and position < len(row) else None


def parse_cost_reference_workbook(file_bytes: bytes) -> CostReference:
    """Read an LCC workbook's manually-entered cost columns, keyed for reuse
    in a fresh export. Works on either the lean admin cost-reference template
    (excel_export.build_cost_reference_template) or a full per-batch export -
    both use the same header names, looked up by name rather than fixed
    position. Only reads literal, non-formula columns - Price_per_Gram_Est is
    recomputed here from Price/Grams_on_Bottle in Python rather than trusting
    whatever Excel last cached, since openpyxl can't evaluate formulas itself.

    A cost cell that is not a number does not abort the load: it is recorded in
    CostReference.problems and counts as a missing cost. A sheet without its key column
    (Process_Type, Material_Name, Role, Item) is skipped and reported the same way.
    """
    workbook = openpyxl.load_workbook(io.BytesIO(file_bytes), data_only=False)
    reference = CostReference()
    problems = reference.problems

    def sheet_rows(sheet_name: str, key_column: str):
        """(row, idx) pairs of a sheet, or nothing when the sheet or its key column is missing."""
        if sheet_name not in workbook.sheetnames:
            return
        ws = workbook[sheet_name]
        idx = _header_index_map(ws)
        if key_column not in idx:
            problems.append(f"Sheet {sheet_name}: no {key_column} column, sheet ignored")
            return
        for row in ws.iter_rows(min_row=2, values_only=True):
            if _cell(row, idx, key_column):
                yield row, idx

    if "Processes" in workbook.sheetnames:
        idx = _header_index_map(workbook["Processes"])
        if "Cost" in idx:  # a full per-batch export has no Cost column on this sheet
            for row, idx in sheet_rows("Processes", "Process_Type"):
                process_type = str(_cell(row, idx, "Process_Type")).strip()
                reference.process_costs[process_type] = {
                    "cost_est": _to_float_or_none(
                        _cell(row, idx, "Cost"), f"Processes / {process_type} / Cost", problems
                    ),
                    "verified": bool(_cell(row, idx, "Verified")),
                    "notes": _cell(row, idx, "Notes") or "",
                }

    for row, idx in sheet_rows("Materials", "Material_Name"):
        name = str(_cell(row, idx, "Material_Name")).strip()
        where = f"Materials / {name}"
        price = _to_float_or_none(_cell(row, idx, "Price"), f"{where} / Price", problems)
        grams_on_bottle = _to_float_or_none(
            _cell(row, idx, "Grams_on_Bottle"), f"{where} / Grams_on_Bottle", problems
        )
        if price is not None and grams_on_bottle:
            price_per_gram_est = price / grams_on_bottle
        else:
            price_per_gram_est = _to_float_or_none(
                _cell(row, idx, "Price_per_Gram_Est"), f"{where} / Price_per_Gram_Est", problems
            )
        reference.material_prices[name] = {
            "cas_number": _cell(row, idx, "CAS_Number") or None,
            "price_per_gram_est": price_per_gram_est,
            "average_quantity_grams": _to_float_or_none(
                _cell(row, idx, "Average_Quantity_Grams"),
                f"{where} / Average_Quantity_Grams",
                problems,
            ),
            "verified": bool(_cell(row, idx, "Verified")),
            "notes": _cell(row, idx, "Notes") or "",
        }

    for row, idx in sheet_rows("Labor", "Role"):
        role = str(_cell(row, idx, "Role")).strip()
        reference.labor_rates[role] = {
            "hourly_rate_est": _to_float_or_none(
                _cell(row, idx, "Hourly_Rate_Est"), f"Labor / {role} / Hourly_Rate_Est", problems
            ),
            "verified": bool(_cell(row, idx, "Verified")),
        }

    for row, idx in sheet_rows("Capital_Overhead_Disposal", "Item"):
        item = str(_cell(row, idx, "Item")).strip()
        allocation = str(_cell(row, idx, "Allocation_Method") or "").strip().lower()
        entry = {
            "cost_est": _to_float_or_none(
                _cell(row, idx, "Cost"), f"Capital_Overhead_Disposal / {item} / Cost", problems
            ),
            "verified": bool(_cell(row, idx, "Verified")),
            "notes": _cell(row, idx, "Notes") or "",
            "category": _cell(row, idx, "Category") or "",
            "allocation_method": allocation or ALLOCATION_PER_BATCH,
        }
        reference.overhead_costs[item] = entry
        location = _cell(row, idx, "Location")
        if location:
            reference.location_costs[str(location).strip()] = entry

    return reference


# ---------------------------------------------------------------------------
# Cost computation (pure Python - the same numbers feed the in-app table and
# the exported workbook, so there is exactly one place this math happens)
# ---------------------------------------------------------------------------


@dataclass
class ProcessCostRow:
    batch_id: str
    process_type: str
    step_count: int
    locations: list[str]
    process_cost: float | None
    process_cost_verified: bool
    equipment_cost: float | None
    equipment_cost_verified: bool
    num_samples: int
    equipment_missing: int = 0
    """Locations of this row whose equipment cost is not in the reference (or not a number)
    and that this row is responsible for; each counts as a missing cost."""

    @property
    def process_cost_missing(self) -> bool:
        return self.process_cost is None

    @property
    def total_cost(self) -> float | None:
        parts = [c for c in (self.process_cost, self.equipment_cost) if c is not None]
        return sum(parts) if parts else None


@dataclass
class MaterialCostRow:
    batch_id: str
    material_name: str
    roles: list[str]
    usage_count: int
    cas_number: str | None
    quantity_grams: float | None
    quantity_source: str  # "average (reference)" or "unknown - not in cost reference yet"
    price_per_gram: float | None
    total_cost: float | None
    verified: bool
    notes: str

    @property
    def missing(self) -> bool:
        return self.total_cost is None


@dataclass
class BatchTotal:
    batch_id: str
    num_samples: int
    material_total: float
    process_total: float
    equipment_total: float
    labor_total: float
    unverified_count: int
    overhead_total: float = 0.0
    missing_count: int = 0
    """Cost items of this batch that are unknown (blank or unusable in the reference). The
    totals above leave them out, so a batch with missing items is a LOWER BOUND, not a
    complete cost: it used to read 0.00 / Unverified 0, like a verified free batch."""

    @property
    def is_complete(self) -> bool:
        return self.missing_count == 0

    @property
    def grand_total(self) -> float:
        return (
            self.material_total
            + self.process_total
            + self.equipment_total
            + self.overhead_total
            + self.labor_total
        )

    @property
    def per_sample(self) -> float | None:
        return self.grand_total / self.num_samples if self.num_samples else None


def _allocated(
    entry: dict, num_samples: int, labor_hours: float | None
) -> tuple[float | None, bool]:
    """(cost, verified) of a capital/overhead entry for ONE batch, by its Allocation_Method:
    per batch = the cost once, per sample = cost x the batch's samples, per hour = cost x the
    labour hours entered for the batch (unknown until hours are entered -> None). A blank
    cost is None."""
    cost = entry.get("cost_est")
    if cost is None:
        return None, bool(entry.get("verified"))
    method = entry.get("allocation_method") or ALLOCATION_PER_BATCH
    if method == ALLOCATION_PER_SAMPLE:
        factor: float | None = float(num_samples)
    elif method == ALLOCATION_PER_HOUR:
        factor = labor_hours if labor_hours else None
    else:
        factor = 1.0
    if factor is None:
        return None, bool(entry.get("verified"))
    return cost * factor, bool(entry.get("verified"))


def compute_process_cost_rows(
    process_rows: list[ProcessStepRow],
    batch_sample_counts: dict[str, int],
    cost_reference: CostReference | None,
    labor_hours: dict[str, float] | None = None,
) -> list[ProcessCostRow]:
    """One row per (batch, process type), aggregating every step/instance of
    that type found in the batch. Process cost and equipment cost are kept
    separate (not summed into one blended figure) since they come from two
    different reference sheets and mean different things.

    Process cost is the reference's flat Cost for the process type (per batch, as the Guide
    says). Equipment cost belongs to a LOCATION, not to a process type, and counts ONCE per
    (batch, location) however many process types ran there (spin coating, annealing and
    quenching in the same box used to each carry the full amount): the first process-type
    row that used the location carries it, scaled by the location's Allocation_Method.
    """
    labor_hours = labor_hours or {}
    grouped: dict[tuple[str, str], list[ProcessStepRow]] = {}
    for row in process_rows:
        grouped.setdefault((row.batch_id, row.process_type), []).append(row)

    results = []
    charged_locations: set[tuple[str, str]] = set()
    for (batch_id, process_type), rows in sorted(grouped.items()):
        locations = sorted({row.location for row in rows if row.location})
        num_samples = batch_sample_counts.get(batch_id, 0)

        process_ref = cost_reference.process_costs.get(process_type) if cost_reference else None
        process_cost = process_ref["cost_est"] if process_ref else None
        process_verified = bool(process_ref["verified"]) if process_ref else False

        equipment_parts: list[tuple[float, bool]] = []
        equipment_missing = 0
        for location in locations:
            if (batch_id, location) in charged_locations:
                continue
            charged_locations.add((batch_id, location))
            entry = cost_reference.location_costs.get(location) if cost_reference else None
            cost, verified = (
                _allocated(entry, num_samples, labor_hours.get(batch_id))
                if entry
                else (None, False)
            )
            if cost is None:
                equipment_missing += 1
            else:
                equipment_parts.append((cost, verified))
        equipment_cost = sum(c for c, _ in equipment_parts) if equipment_parts else None
        equipment_verified = all(v for _, v in equipment_parts) if equipment_parts else False

        results.append(
            ProcessCostRow(
                batch_id=batch_id,
                process_type=process_type,
                step_count=len(rows),
                locations=locations,
                process_cost=process_cost,
                process_cost_verified=process_verified,
                equipment_cost=equipment_cost,
                equipment_cost_verified=equipment_verified,
                num_samples=num_samples,
                equipment_missing=equipment_missing,
            )
        )
    return sorted(results, key=lambda row: (row.batch_id, row.process_type))


def compute_overhead_cost(
    batch_id: str,
    num_samples: int,
    cost_reference: CostReference | None,
    labor_hours: float | None,
) -> tuple[float, int, bool]:
    """(total, missing, verified) of the batch's overhead: reference rows with no Location
    (rent, disposal, ...), allocated by their Allocation_Method. Rows tied to a location are
    equipment and are charged with the process rows instead. A row whose cost is blank, or
    per hour with no hours entered yet, counts as missing."""
    if cost_reference is None:
        return 0.0, 0, True
    location_entries = {id(entry) for entry in cost_reference.location_costs.values()}
    total, missing, verified = 0.0, 0, True
    for entry in cost_reference.overhead_costs.values():
        if id(entry) in location_entries:
            continue
        cost, entry_verified = _allocated(entry, num_samples, labor_hours)
        if cost is None:
            missing += 1
            continue
        total += cost
        verified = verified and entry_verified
    return total, missing, verified


def compute_material_cost_rows(
    material_rows: list[MaterialRow],
    cost_reference: CostReference | None,
) -> list[MaterialCostRow]:
    """One row per (batch, material name), aggregating every time that
    material was used across the batch's processes. The quantity is the reference file's
    Average_Quantity_Grams ONCE per batch: the admin Guide defines it as "how many grams a
    batch typically consumes", and multiplying it by the number of process entries that
    mention the material (as this used to) overstated the cost for materials that appear in
    several entries. NOMAD only gives concentration/volume/thickness for these materials,
    never a directly usable gram amount, so an "actual" grams figure is never available."""
    grouped: dict[tuple[str, str], list[MaterialRow]] = {}
    for row in material_rows:
        grouped.setdefault((row.batch_id, row.material_name), []).append(row)

    results = []
    for (batch_id, material_name), rows in grouped.items():
        ref = cost_reference.material_prices.get(material_name) if cost_reference else None
        price = ref.get("price_per_gram_est") if ref else None
        if price is None:
            price = next((row.price_per_gram_est for row in rows if row.price_per_gram_est), None)
        average_quantity = ref.get("average_quantity_grams") if ref else None

        usage_count = len(rows)
        if average_quantity is not None:
            quantity_grams = average_quantity
            quantity_source = "average per batch (reference)"
        else:
            quantity_grams = None
            quantity_source = "unknown - not in cost reference yet"

        total_cost = (
            quantity_grams * price if quantity_grams is not None and price is not None else None
        )
        cas_number = (ref.get("cas_number") if ref else None) or next(
            (row.cas_number for row in rows if row.cas_number), None
        )
        if ref and ref.get("notes"):
            notes = ref["notes"]
        elif price is not None and not ref_price_from_reference(ref):
            # only a price from the static table is a "rough estimate"; one the admin entered
            # in the reference file is theirs (and may be verified)
            notes = CHEMICAL_REFERENCE_NOTE
        else:
            notes = ""

        results.append(
            MaterialCostRow(
                batch_id=batch_id,
                material_name=material_name,
                roles=sorted({row.role for row in rows}),
                usage_count=usage_count,
                cas_number=cas_number,
                quantity_grams=quantity_grams,
                quantity_source=quantity_source,
                price_per_gram=price,
                total_cost=total_cost,
                verified=bool(ref["verified"]) if ref else False,
                notes=notes,
            )
        )
    return sorted(results, key=lambda row: (row.batch_id, row.material_name))


def ref_price_from_reference(ref: dict | None) -> bool:
    """True when the price of this material came from the admin's cost reference file."""
    return bool(ref) and ref.get("price_per_gram_est") is not None


def compute_labor_cost(
    role: str, hours: float | None, cost_reference: CostReference | None
) -> tuple[float | None, bool]:
    """hours x the role's hourly rate from the shared cost reference file."""
    if not hours or not role:
        return None, False
    ref = cost_reference.labor_rates.get(role) if cost_reference else None
    rate = ref.get("hourly_rate_est") if ref else None
    if rate is None:
        return None, False
    return hours * rate, bool(ref.get("verified"))


def compute_batch_totals(
    process_cost_rows: list[ProcessCostRow],
    material_cost_rows: list[MaterialCostRow],
    batch_sample_counts: dict[str, int],
    labor_costs: dict[str, tuple[float | None, bool]],  # batch_id -> (cost, verified)
    cost_reference: CostReference | None = None,
    labor_hours: dict[str, float] | None = None,
) -> list[BatchTotal]:
    """One row per batch, plus a grand total is just sum(BatchTotal.grand_total)
    across the returned list - "total cost of everything selected".

    Items whose cost is unknown (blank in the reference) add nothing to a total, and are
    counted in `missing_count`, so a total with missing items is shown as incomplete instead
    of passing for a complete, verified cost. Labour needs no entry: no hours chosen means no
    labour was claimed."""
    labor_hours = labor_hours or {}
    totals: dict[str, BatchTotal] = {
        batch_id: BatchTotal(
            batch_id=batch_id,
            num_samples=num_samples,
            material_total=0.0,
            process_total=0.0,
            equipment_total=0.0,
            labor_total=0.0,
            unverified_count=0,
        )
        for batch_id, num_samples in batch_sample_counts.items()
    }

    for row in process_cost_rows:
        total = totals.get(row.batch_id)
        if total is None:
            continue
        if row.process_cost is not None:
            total.process_total += row.process_cost
            if not row.process_cost_verified:
                total.unverified_count += 1
        else:
            total.missing_count += 1
        if row.equipment_cost is not None:
            total.equipment_total += row.equipment_cost
            if not row.equipment_cost_verified:
                total.unverified_count += 1
        total.missing_count += row.equipment_missing

    for row in material_cost_rows:
        total = totals.get(row.batch_id)
        if total is None:
            continue
        if row.total_cost is not None:
            total.material_total += row.total_cost
            if not row.verified:
                total.unverified_count += 1
        else:
            total.missing_count += 1

    for batch_id, (labor_cost, labor_verified) in labor_costs.items():
        total = totals.get(batch_id)
        if total is None:
            continue
        if labor_cost is None:
            if labor_hours.get(batch_id):
                total.missing_count += 1  # hours entered but the role's rate is not known
            continue
        total.labor_total += labor_cost
        if not labor_verified:
            total.unverified_count += 1

    for batch_id, total in totals.items():
        overhead, missing, verified = compute_overhead_cost(
            batch_id, total.num_samples, cost_reference, labor_hours.get(batch_id)
        )
        total.overhead_total = overhead
        total.missing_count += missing
        if overhead and not verified:
            total.unverified_count += 1

    return [totals[batch_id] for batch_id in sorted(totals)]


# The single source of truth: one admin-maintained workbook living alongside
# the app's own code. Every user's session reads this same file automatically
# (no upload step) - an admin edits it in place (via git, or directly through
# NOMAD's upload file browser if this app is deployed as a North tool, since
# the app's working directory sits inside that same mounted upload) and the
# update is live for everyone on their next export. Mirrors the existing
# repo-root secrets.py convention (see hysprint_utils.access_token), just
# scoped to this app's own folder instead of the repo root.
DEFAULT_COST_REFERENCE_PATH = Path(__file__).resolve().parent / "cost_reference.xlsx"


def load_default_cost_reference(path: Path | None = None) -> CostReference | None:
    """Read the shared master cost file if it exists. Returns None (not an
    error) when the file is missing - a fresh install has no admin-entered
    costs yet, and the app should still work, just with blank costs."""
    reference_path = path if path is not None else DEFAULT_COST_REFERENCE_PATH
    if not reference_path.is_file():
        logger.info("No cost reference file at %s; costs will start blank.", reference_path)
        return None
    try:
        return parse_cost_reference_workbook(reference_path.read_bytes())
    except Exception:
        logger.exception("Could not read cost reference file at %s", reference_path)
        return None


# ---------------------------------------------------------------------------
# State container
# ---------------------------------------------------------------------------


class LCCDataManager:
    """Holds the extracted cost line items for the currently loaded batches.
    No widget imports, no global state - one instance per app session."""

    def __init__(self) -> None:
        self.batch_sample_counts: dict[str, int] = {}
        self.process_rows: list[ProcessStepRow] = []
        self.material_rows: list[MaterialRow] = []
        self.all_sample_ids: list[str] = []

    @property
    def has_data(self) -> bool:
        return bool(self.process_rows or self.material_rows)

    def load_batches(self, url: str, token: str, batch_ids: list[str]) -> None:
        self.batch_sample_counts = {}
        self.process_rows = []
        self.material_rows = []
        self.all_sample_ids = []

        samples_per_batch = fetch_samples_per_batch(url, token, batch_ids)
        sample_to_batch: dict[str, str] = {}
        for batch_id, sample_ids in samples_per_batch.items():
            self.batch_sample_counts[batch_id] = len(sample_ids)
            for sample_id in sample_ids:
                sample_to_batch[sample_id] = batch_id

        all_sample_ids = list(sample_to_batch)
        self.all_sample_ids = all_sample_ids
        if not all_sample_ids:
            logger.warning("No samples found in selected batches: %s", batch_ids)
            return

        process_entries = fetch_process_entries(url, token, all_sample_ids)
        for process_data, entry_type in process_entries:
            covered_sample_ids = [
                sample.get("lab_id")
                for sample in (process_data.get("samples") or [])
                if isinstance(sample, dict) and sample.get("lab_id")
            ]
            if not covered_sample_ids:
                continue

            # A process instance normally covers samples from a single batch;
            # if it spans more than one (e.g. a shared oven run across
            # batches), it is attributed here to the first covered sample's
            # batch as a documented simplification (see Guide sheet).
            batch_id = next(
                (sample_to_batch[sid] for sid in covered_sample_ids if sid in sample_to_batch),
                None,
            )
            if batch_id is None:
                continue

            num_samples_covered = len(covered_sample_ids)

            self.process_rows.extend(
                extract_process_step_rows(
                    process_data, entry_type, batch_id, num_samples_covered, covered_sample_ids
                )
            )
            self.material_rows.extend(
                extract_material_rows(
                    process_data, entry_type, batch_id, num_samples_covered, covered_sample_ids
                )
            )

        logger.info(
            "Loaded %d process rows, %d material rows for %d batches.",
            len(self.process_rows),
            len(self.material_rows),
            len(batch_ids),
        )
