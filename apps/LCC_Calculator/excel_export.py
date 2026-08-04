"""
excel_export.py
----------------
Builds openpyxl workbooks for the LCC Calculator: the per-batch cost report
(literal values only - the same numbers already computed in Python by
data_manager.py for the in-app table, just written to cells) and the
admin-maintained cost reference template. No widget imports.
"""

from __future__ import annotations

import logging

from data_manager import (
    CHEMICAL_REFERENCE,
    CHEMICAL_REFERENCE_NOTE,
    KNOWN_LOCATIONS,
    LABOR_ROLES,
    BatchTotal,
    CostReference,
    MaterialCostRow,
    ProcessCostRow,
    compute_labor_cost,
)
from openpyxl import Workbook
from openpyxl.formatting.rule import CellIsRule
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation
from openpyxl.worksheet.worksheet import Worksheet

logger = logging.getLogger(__name__)

MAX_DATA_ROW = 2000

HEADER_FILL = PatternFill(start_color="2E86AB", end_color="2E86AB", fill_type="solid")
HEADER_FONT = Font(color="FFFFFF", bold=True)
WARNING_FILL = PatternFill(start_color="F8D7DA", end_color="F8D7DA", fill_type="solid")
VERIFIED_FILL = PatternFill(start_color="D4EDDA", end_color="D4EDDA", fill_type="solid")

COST_CATEGORY_OPTIONS = ["Capital", "Maintenance", "Overhead", "End-of-Life"]
ALLOCATION_METHOD_OPTIONS = ["per batch", "per sample", "per hour"]


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _col(headers: list[str], name: str) -> int:
    return headers.index(name) + 1


def _letter(headers: list[str], name: str) -> str:
    return get_column_letter(_col(headers, name))


def _write_header(ws: Worksheet, headers: list[str]) -> None:
    for col_index, header in enumerate(headers, start=1):
        cell = ws.cell(row=1, column=col_index, value=header)
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.alignment = Alignment(horizontal="center", wrap_text=True)
    ws.freeze_panes = "A2"


def _add_bool_dropdown(ws: Worksheet, col_letter: str, last_row: int = MAX_DATA_ROW) -> None:
    dv = DataValidation(type="list", formula1='"TRUE,FALSE"', allow_blank=True)
    dv.error = "Please select TRUE or FALSE"
    dv.errorTitle = "Invalid Entry"
    ws.add_data_validation(dv)
    dv.add(f"{col_letter}2:{col_letter}{last_row}")


def _add_list_dropdown(
    ws: Worksheet, col_letter: str, options: list[str], last_row: int = MAX_DATA_ROW
) -> None:
    options_str = ",".join(options)
    dv = DataValidation(type="list", formula1=f'"{options_str}"', allow_blank=True)
    dv.error = "Please select from the dropdown list"
    dv.errorTitle = "Invalid Entry"
    ws.add_data_validation(dv)
    dv.add(f"{col_letter}2:{col_letter}{last_row}")


def _highlight_verified_column(
    ws: Worksheet, verified_col_letter: str, last_row: int = MAX_DATA_ROW
) -> None:
    """Red for FALSE (unverified), green for TRUE (confirmed)."""
    cell_range = f"{verified_col_letter}2:{verified_col_letter}{last_row}"
    ws.conditional_formatting.add(
        cell_range, CellIsRule(operator="equal", formula=["FALSE"], fill=WARNING_FILL)
    )
    ws.conditional_formatting.add(
        cell_range, CellIsRule(operator="equal", formula=["TRUE"], fill=VERIFIED_FILL)
    )


def _autosize_columns(ws: Worksheet, headers: list[str]) -> None:
    for col_index, header in enumerate(headers, start=1):
        letter = get_column_letter(col_index)
        ws.column_dimensions[letter].width = max(14, len(header) + 2)


# ---------------------------------------------------------------------------
# Guide sheet
# ---------------------------------------------------------------------------

_GUIDE_TEXT = [
    ("Life Cycle Costing (LCC) Calculator - Guide", True),
    ("", False),
    (
        "This is a computed report: every number here was already looked up "
        "against the shared cost reference file (cost_reference.xlsx) and "
        "calculated in the app before export - it is a read-only snapshot, "
        "not a live spreadsheet. To correct a value for future reports, edit "
        "cost_reference.xlsx itself, not this file.",
        False,
    ),
    ("", False),
    ("Processes sheet:", True),
    (
        "One row per process type per batch (e.g. all SpinCoating steps in "
        "a batch collapse into one row). Process_Cost and Equipment_Cost "
        "are shown separately, not combined - Process_Cost comes from the "
        "reference file's Processes sheet (a flat cost per process type); "
        "Equipment_Cost comes from the reference file's Capital_Overhead_"
        "Disposal sheet, matched by the physical box/tool (Location) the "
        "process actually ran in.",
        False,
    ),
    ("", False),
    ("Materials sheet:", True),
    (
        "One row per distinct material per batch, aggregated across every "
        "time it was used. Quantity_Grams is Average_Quantity_Grams (from "
        "the reference file) multiplied by how many times the material was "
        "used - NOMAD only records concentration/volume/thickness for these "
        "materials, never a directly usable gram amount, so the reference "
        "file's average figure is the only quantity source (Quantity_Source "
        "column says so explicitly).",
        False,
    ),
    ("", False),
    ("Labor sheet:", True),
    (
        "NOMAD does not record who ran a process or what role they hold, so "
        "this is entered manually per batch in the app (role + hours "
        "worked) before export. Cost = Hours x the role's hourly rate from "
        "the reference file.",
        False,
    ),
    ("", False),
    ("Summary sheet:", True),
    (
        "One row per batch (Grand_Total, Per_Sample), plus a final TOTAL "
        "row summing every selected batch - the overall cost of everything "
        "selected. Unverified_Count tallies how many line items behind that "
        "batch's total are not yet marked Verified=TRUE in the reference "
        "file.",
        False,
    ),
]


def _build_guide_sheet(wb: Workbook) -> None:
    ws = wb.active
    ws.title = "Guide"
    row = 1
    for text, bold in _GUIDE_TEXT:
        cell = ws.cell(row=row, column=1, value=text)
        if bold:
            cell.font = Font(bold=True, size=13 if row == 1 else 11)
        cell.alignment = Alignment(wrap_text=True, vertical="top")
        row += 1
    ws.column_dimensions["A"].width = 110


# ---------------------------------------------------------------------------
# Processes sheet (per-batch report)
# ---------------------------------------------------------------------------

PROCESSES_HEADERS = [
    "Batch_ID",
    "Process_Type",
    "Steps",
    "Locations",
    "Process_Cost",
    "Process_Cost_Verified",
    "Equipment_Cost",
    "Equipment_Cost_Verified",
    "Total_Cost",
]


def _build_processes_sheet(wb: Workbook, process_cost_rows: list[ProcessCostRow]) -> None:
    ws = wb.create_sheet("Processes")
    _write_header(ws, PROCESSES_HEADERS)

    for row_index, row in enumerate(process_cost_rows, start=2):
        ws.cell(row=row_index, column=_col(PROCESSES_HEADERS, "Batch_ID"), value=row.batch_id)
        ws.cell(
            row=row_index, column=_col(PROCESSES_HEADERS, "Process_Type"), value=row.process_type
        )
        ws.cell(row=row_index, column=_col(PROCESSES_HEADERS, "Steps"), value=row.step_count)
        ws.cell(
            row=row_index,
            column=_col(PROCESSES_HEADERS, "Locations"),
            value=", ".join(row.locations),
        )
        ws.cell(
            row=row_index, column=_col(PROCESSES_HEADERS, "Process_Cost"), value=row.process_cost
        )
        ws.cell(
            row=row_index,
            column=_col(PROCESSES_HEADERS, "Process_Cost_Verified"),
            value=row.process_cost_verified,
        )
        ws.cell(
            row=row_index,
            column=_col(PROCESSES_HEADERS, "Equipment_Cost"),
            value=row.equipment_cost,
        )
        ws.cell(
            row=row_index,
            column=_col(PROCESSES_HEADERS, "Equipment_Cost_Verified"),
            value=row.equipment_cost_verified,
        )
        ws.cell(row=row_index, column=_col(PROCESSES_HEADERS, "Total_Cost"), value=row.total_cost)

    _highlight_verified_column(ws, _letter(PROCESSES_HEADERS, "Process_Cost_Verified"))
    _highlight_verified_column(ws, _letter(PROCESSES_HEADERS, "Equipment_Cost_Verified"))
    _autosize_columns(ws, PROCESSES_HEADERS)


# ---------------------------------------------------------------------------
# Materials sheet (per-batch report)
# ---------------------------------------------------------------------------

MATERIALS_HEADERS = [
    "Batch_ID",
    "Material_Name",
    "Roles",
    "Usage_Count",
    "CAS_Number",
    "Quantity_Grams",
    "Quantity_Source",
    "Price_per_Gram",
    "Total_Cost",
    "Verified",
    "Notes",
]


def _build_materials_sheet(wb: Workbook, material_cost_rows: list[MaterialCostRow]) -> None:
    ws = wb.create_sheet("Materials")
    _write_header(ws, MATERIALS_HEADERS)

    for row_index, row in enumerate(material_cost_rows, start=2):
        ws.cell(row=row_index, column=_col(MATERIALS_HEADERS, "Batch_ID"), value=row.batch_id)
        ws.cell(
            row=row_index, column=_col(MATERIALS_HEADERS, "Material_Name"), value=row.material_name
        )
        ws.cell(row=row_index, column=_col(MATERIALS_HEADERS, "Roles"), value=", ".join(row.roles))
        ws.cell(row=row_index, column=_col(MATERIALS_HEADERS, "Usage_Count"), value=row.usage_count)
        ws.cell(row=row_index, column=_col(MATERIALS_HEADERS, "CAS_Number"), value=row.cas_number)
        ws.cell(
            row=row_index,
            column=_col(MATERIALS_HEADERS, "Quantity_Grams"),
            value=row.quantity_grams,
        )
        ws.cell(
            row=row_index,
            column=_col(MATERIALS_HEADERS, "Quantity_Source"),
            value=row.quantity_source,
        )
        ws.cell(
            row=row_index,
            column=_col(MATERIALS_HEADERS, "Price_per_Gram"),
            value=row.price_per_gram,
        )
        ws.cell(row=row_index, column=_col(MATERIALS_HEADERS, "Total_Cost"), value=row.total_cost)
        ws.cell(row=row_index, column=_col(MATERIALS_HEADERS, "Verified"), value=row.verified)
        ws.cell(row=row_index, column=_col(MATERIALS_HEADERS, "Notes"), value=row.notes)

    _highlight_verified_column(ws, _letter(MATERIALS_HEADERS, "Verified"))
    _autosize_columns(ws, MATERIALS_HEADERS)


# ---------------------------------------------------------------------------
# Labor sheet (per-batch report) - role + hours picked in the app, one row
# per batch (not per role - only the role actually selected is shown).
# ---------------------------------------------------------------------------

LABOR_HEADERS = ["Batch_ID", "Role", "Hours", "Hourly_Rate", "Cost", "Verified"]


def _build_labor_sheet(
    wb: Workbook,
    labor_selections: dict[str, tuple[str, float]],
    cost_reference: CostReference | None,
) -> None:
    ws = wb.create_sheet("Labor")
    _write_header(ws, LABOR_HEADERS)

    for row_index, (batch_id, (role, hours)) in enumerate(
        sorted(labor_selections.items()), start=2
    ):
        cost, verified = compute_labor_cost(role, hours, cost_reference)
        rate = (
            cost_reference.labor_rates.get(role, {}).get("hourly_rate_est")
            if cost_reference
            else None
        )
        ws.cell(row=row_index, column=_col(LABOR_HEADERS, "Batch_ID"), value=batch_id)
        ws.cell(row=row_index, column=_col(LABOR_HEADERS, "Role"), value=role)
        ws.cell(row=row_index, column=_col(LABOR_HEADERS, "Hours"), value=hours)
        ws.cell(row=row_index, column=_col(LABOR_HEADERS, "Hourly_Rate"), value=rate)
        ws.cell(row=row_index, column=_col(LABOR_HEADERS, "Cost"), value=cost)
        ws.cell(row=row_index, column=_col(LABOR_HEADERS, "Verified"), value=verified)

    _highlight_verified_column(ws, _letter(LABOR_HEADERS, "Verified"))
    _autosize_columns(ws, LABOR_HEADERS)


# ---------------------------------------------------------------------------
# Summary sheet (per-batch report)
# ---------------------------------------------------------------------------

SUMMARY_HEADERS = [
    "Batch_ID",
    "Num_Samples",
    "Material_Total",
    "Process_Total",
    "Equipment_Total",
    "Labor_Total",
    "Grand_Total",
    "Per_Sample",
    "Unverified_Count",
]


def _build_summary_sheet(wb: Workbook, batch_totals: list[BatchTotal]) -> None:
    ws = wb.create_sheet("Summary")
    _write_header(ws, SUMMARY_HEADERS)

    row_index = 2
    for total in batch_totals:
        ws.cell(row=row_index, column=_col(SUMMARY_HEADERS, "Batch_ID"), value=total.batch_id)
        ws.cell(row=row_index, column=_col(SUMMARY_HEADERS, "Num_Samples"), value=total.num_samples)
        ws.cell(
            row=row_index,
            column=_col(SUMMARY_HEADERS, "Material_Total"),
            value=total.material_total,
        )
        ws.cell(
            row=row_index, column=_col(SUMMARY_HEADERS, "Process_Total"), value=total.process_total
        )
        ws.cell(
            row=row_index,
            column=_col(SUMMARY_HEADERS, "Equipment_Total"),
            value=total.equipment_total,
        )
        ws.cell(row=row_index, column=_col(SUMMARY_HEADERS, "Labor_Total"), value=total.labor_total)
        ws.cell(row=row_index, column=_col(SUMMARY_HEADERS, "Grand_Total"), value=total.grand_total)
        ws.cell(row=row_index, column=_col(SUMMARY_HEADERS, "Per_Sample"), value=total.per_sample)
        ws.cell(
            row=row_index,
            column=_col(SUMMARY_HEADERS, "Unverified_Count"),
            value=total.unverified_count,
        )
        row_index += 1

    if batch_totals:
        ws.cell(
            row=row_index, column=_col(SUMMARY_HEADERS, "Batch_ID"), value="TOTAL (all selected)"
        )
        ws.cell(row=row_index, column=_col(SUMMARY_HEADERS, "Batch_ID")).font = Font(bold=True)
        ws.cell(
            row=row_index,
            column=_col(SUMMARY_HEADERS, "Num_Samples"),
            value=sum(total.num_samples for total in batch_totals),
        )
        ws.cell(
            row=row_index,
            column=_col(SUMMARY_HEADERS, "Material_Total"),
            value=sum(total.material_total for total in batch_totals),
        )
        ws.cell(
            row=row_index,
            column=_col(SUMMARY_HEADERS, "Process_Total"),
            value=sum(total.process_total for total in batch_totals),
        )
        ws.cell(
            row=row_index,
            column=_col(SUMMARY_HEADERS, "Equipment_Total"),
            value=sum(total.equipment_total for total in batch_totals),
        )
        ws.cell(
            row=row_index,
            column=_col(SUMMARY_HEADERS, "Labor_Total"),
            value=sum(total.labor_total for total in batch_totals),
        )
        ws.cell(
            row=row_index,
            column=_col(SUMMARY_HEADERS, "Grand_Total"),
            value=sum(total.grand_total for total in batch_totals),
        )
        ws.cell(
            row=row_index,
            column=_col(SUMMARY_HEADERS, "Unverified_Count"),
            value=sum(total.unverified_count for total in batch_totals),
        )

    _autosize_columns(ws, SUMMARY_HEADERS)


# ---------------------------------------------------------------------------
# Cost reference template - the admin-maintained single source of truth
# ---------------------------------------------------------------------------

_REFERENCE_GUIDE_TEXT = [
    ("LCC Cost Reference - Guide (for admins)", True),
    ("", False),
    (
        "This is the single source of truth for cost figures. Every user's "
        "LCC Calculator session reads this same file automatically when "
        "computing a batch's costs - there is nothing for them to upload or "
        "configure.",
        False,
    ),
    ("", False),
    (
        "To update a cost: edit the matching row's Cost (or Price/Average_"
        "Quantity_Grams on Materials) on the relevant sheet below, set "
        "Verified to TRUE, and save this file in place. The change is live "
        "for every user next time they load a batch.",
        False,
    ),
    ("", False),
    (
        "To add a new material/process/item: add a new row with a name "
        "that exactly matches what the app extracts from NOMAD (use the "
        "admin 'Generate Cost Reference Template' button in the app to get "
        "exact names automatically instead of typing them by hand) - "
        "matching is by exact text, so a typo means the row is silently "
        "ignored rather than applied. Labor is the exception: Role is "
        "always one of the 4 fixed tiers, no typos possible.",
        False,
    ),
    ("", False),
    (
        "Materials sheet - Price and Grams_on_Bottle: enter what you paid "
        "for a bottle/container (Price) and how many grams it holds "
        "(Grams_on_Bottle) - Price_per_Gram_Est is computed automatically. "
        "Average_Quantity_Grams is how many grams a batch typically "
        "consumes of this material - NOMAD does not give a usable gram "
        "amount for solution-based materials, so this average is the only "
        "quantity source the app has. Pre-seeded with rough starting price "
        "estimates for common perovskite-fab chemicals (Verified=FALSE) - "
        "replace with your actual supplier prices and typical usage, and "
        "mark Verified=TRUE as you confirm each one.",
        False,
    ),
    ("", False),
    (
        "Capital_Overhead_Disposal sheet - Location: pre-seeded with one "
        "equipment-depreciation placeholder per known glovebox/tool. A "
        "process's Equipment_Cost in the exported report only applies when "
        "the batch's raw NOMAD location text exactly matches a Location "
        "here - see the exported report's Guide sheet for why that text is "
        "often inconsistent.",
        False,
    ),
]

_REFERENCE_MATERIALS_HEADERS = [
    "Material_Name",
    "CAS_Number",
    "Price",
    "Grams_on_Bottle",
    "Price_per_Gram_Est",
    "Average_Quantity_Grams",
    "Verified",
    "Notes",
]
_REFERENCE_PROCESSES_HEADERS = ["Process_Type", "Cost", "Verified", "Notes"]
_REFERENCE_LABOR_HEADERS = ["Role", "Hourly_Rate_Est", "Verified"]
_REFERENCE_CAPITAL_HEADERS = [
    "Item",
    "Location",
    "Category",
    "Allocation_Method",
    "Cost",
    "Verified",
    "Notes",
]


def _write_reference_guide_sheet(wb: Workbook, generated_from_note: str) -> None:
    ws = wb.active
    ws.title = "Guide"
    lines = [
        *_REFERENCE_GUIDE_TEXT[:2],
        (f"Generated from: {generated_from_note}.", False),
        ("", False),
        *_REFERENCE_GUIDE_TEXT[2:],
    ]
    for row_index, (text, bold) in enumerate(lines, start=1):
        cell = ws.cell(row=row_index, column=1, value=text)
        if bold:
            cell.font = Font(bold=True, size=13 if row_index == 1 else 11)
        cell.alignment = Alignment(wrap_text=True, vertical="top")
    ws.column_dimensions["A"].width = 110


def _write_reference_materials_sheet(
    wb: Workbook, entries: list[tuple[str, str | None, float | None, str]]
) -> None:
    """entries: (material_name, cas_number, price_per_gram_est, notes). Price
    is seeded equal to price_per_gram_est with Grams_on_Bottle=1 so the
    formula-computed Price_per_Gram_Est matches today's static estimate
    exactly. Average_Quantity_Grams is never guessed - always left blank."""
    ws = wb.create_sheet("Materials")
    _write_header(ws, _REFERENCE_MATERIALS_HEADERS)
    price_col = _letter(_REFERENCE_MATERIALS_HEADERS, "Price")
    grams_col = _letter(_REFERENCE_MATERIALS_HEADERS, "Grams_on_Bottle")
    for row_index, (name, cas_number, price_per_gram, notes) in enumerate(entries, start=2):
        ws.cell(
            row=row_index, column=_col(_REFERENCE_MATERIALS_HEADERS, "Material_Name"), value=name
        )
        ws.cell(
            row=row_index, column=_col(_REFERENCE_MATERIALS_HEADERS, "CAS_Number"), value=cas_number
        )
        ws.cell(
            row=row_index, column=_col(_REFERENCE_MATERIALS_HEADERS, "Price"), value=price_per_gram
        )
        ws.cell(
            row=row_index,
            column=_col(_REFERENCE_MATERIALS_HEADERS, "Grams_on_Bottle"),
            value=1 if price_per_gram is not None else None,
        )
        ws.cell(
            row=row_index,
            column=_col(_REFERENCE_MATERIALS_HEADERS, "Price_per_Gram_Est"),
            value=(
                f'=IF(OR({price_col}{row_index}="",{grams_col}{row_index}=""),"",'
                f"{price_col}{row_index}/{grams_col}{row_index})"
            ),
        )
        # Average_Quantity_Grams left blank - never guessed, see Guide sheet.
        ws.cell(row=row_index, column=_col(_REFERENCE_MATERIALS_HEADERS, "Verified"), value=False)
        ws.cell(row=row_index, column=_col(_REFERENCE_MATERIALS_HEADERS, "Notes"), value=notes)
    verified_col = _letter(_REFERENCE_MATERIALS_HEADERS, "Verified")
    _add_bool_dropdown(ws, verified_col)
    _highlight_verified_column(ws, verified_col)
    _autosize_columns(ws, _REFERENCE_MATERIALS_HEADERS)


def _write_reference_processes_sheet(wb: Workbook, process_types: list[str]) -> None:
    ws = wb.create_sheet("Processes")
    _write_header(ws, _REFERENCE_PROCESSES_HEADERS)
    for row_index, process_type in enumerate(process_types, start=2):
        ws.cell(
            row=row_index,
            column=_col(_REFERENCE_PROCESSES_HEADERS, "Process_Type"),
            value=process_type,
        )
        ws.cell(row=row_index, column=_col(_REFERENCE_PROCESSES_HEADERS, "Verified"), value=False)
    verified_col = _letter(_REFERENCE_PROCESSES_HEADERS, "Verified")
    _add_bool_dropdown(ws, verified_col)
    _highlight_verified_column(ws, verified_col)
    _autosize_columns(ws, _REFERENCE_PROCESSES_HEADERS)


def _write_reference_labor_sheet(wb: Workbook) -> None:
    """Always the 4 fixed role tiers - see data_manager.LABOR_ROLES."""
    ws = wb.create_sheet("Labor")
    _write_header(ws, _REFERENCE_LABOR_HEADERS)
    for row_index, role in enumerate(LABOR_ROLES, start=2):
        ws.cell(row=row_index, column=_col(_REFERENCE_LABOR_HEADERS, "Role"), value=role)
        ws.cell(row=row_index, column=_col(_REFERENCE_LABOR_HEADERS, "Verified"), value=False)
    verified_col = _letter(_REFERENCE_LABOR_HEADERS, "Verified")
    _add_bool_dropdown(ws, verified_col)
    _highlight_verified_column(ws, verified_col)
    _autosize_columns(ws, _REFERENCE_LABOR_HEADERS)


def _write_reference_capital_sheet(wb: Workbook, entries: list[tuple[str, str, str, str]]) -> None:
    """entries: (item, location, category, allocation_method)."""
    ws = wb.create_sheet("Capital_Overhead_Disposal")
    _write_header(ws, _REFERENCE_CAPITAL_HEADERS)
    for row_index, (item, location, category, allocation) in enumerate(entries, start=2):
        ws.cell(row=row_index, column=_col(_REFERENCE_CAPITAL_HEADERS, "Item"), value=item)
        ws.cell(row=row_index, column=_col(_REFERENCE_CAPITAL_HEADERS, "Location"), value=location)
        ws.cell(row=row_index, column=_col(_REFERENCE_CAPITAL_HEADERS, "Category"), value=category)
        ws.cell(
            row=row_index,
            column=_col(_REFERENCE_CAPITAL_HEADERS, "Allocation_Method"),
            value=allocation,
        )
        ws.cell(row=row_index, column=_col(_REFERENCE_CAPITAL_HEADERS, "Verified"), value=False)
    verified_col = _letter(_REFERENCE_CAPITAL_HEADERS, "Verified")
    _add_list_dropdown(ws, _letter(_REFERENCE_CAPITAL_HEADERS, "Category"), COST_CATEGORY_OPTIONS)
    _add_list_dropdown(
        ws, _letter(_REFERENCE_CAPITAL_HEADERS, "Allocation_Method"), ALLOCATION_METHOD_OPTIONS
    )
    _add_list_dropdown(ws, _letter(_REFERENCE_CAPITAL_HEADERS, "Location"), [*KNOWN_LOCATIONS, ""])
    _add_bool_dropdown(ws, verified_col)
    _highlight_verified_column(ws, verified_col)
    _autosize_columns(ws, _REFERENCE_CAPITAL_HEADERS)


def _known_location_capital_entries() -> list[tuple[str, str, str, str]]:
    entries = [("Cleanroom / lab rent", "", "Overhead", "per hour")]
    entries.extend(
        (f"Equipment depreciation - {location}", location, "Capital", "per batch")
        for location in KNOWN_LOCATIONS
    )
    return entries


def build_cost_reference_template() -> Workbook:
    """A generic starting point for the admin-maintained master cost file
    (data_manager.DEFAULT_COST_REFERENCE_PATH) - Materials pre-seeded from
    the static CHEMICAL_REFERENCE table only (no NOMAD data involved),
    Capital_Overhead_Disposal pre-seeded from the fixed KNOWN_LOCATIONS
    list. Prefer build_cost_reference_template_from_data when real batch
    data is available - it guarantees exact-match material/process names
    instead of relying on manual typing.
    """
    wb = Workbook()
    _write_reference_guide_sheet(
        wb, "the static chemical reference list and known locations only (no NOMAD data scanned)"
    )
    materials_entries = [
        (name, info["cas_number"], info["price_per_gram_est"], CHEMICAL_REFERENCE_NOTE)
        for name, info in sorted(CHEMICAL_REFERENCE.items())
    ]
    _write_reference_materials_sheet(wb, materials_entries)
    _write_reference_processes_sheet(wb, [])
    _write_reference_labor_sheet(wb)
    _write_reference_capital_sheet(wb, _known_location_capital_entries())
    return wb


def build_cost_reference_template_from_data(
    process_types: list[str],
    material_names_with_cas: dict[str, str | None],
    batch_count: int,
    extra_schema_types: list[str] | None = None,
) -> Workbook:
    """Same shape as build_cost_reference_template, but Materials/Processes
    rows are seeded from every distinct Material_Name / Process_Type
    actually found in the scanned batches - guarantees exact-match names
    against what the app extracts from NOMAD, so an admin never has to
    hand-type (and risk mistyping) a name. Falls back to the static
    CHEMICAL_REFERENCE list for any common chemical not yet encountered.
    extra_schema_types (e.g. from data_manager.discover_entry_types) adds
    measurement/other schemas with no process-level cost concept but still
    worth having in the catalog for visibility.

    Labor and Capital_Overhead_Disposal locations are NOT derived from data
    - they're always the fixed role tiers / known locations, since those
    are stable lab facts independent of which batches happen to be
    selected. Intended for an admin to run over a broad/complete batch
    selection, then save the result as data_manager.DEFAULT_COST_REFERENCE_PATH.
    """
    wb = Workbook()
    _write_reference_guide_sheet(
        wb,
        f"{batch_count} selected batch(es) - re-run with a broader batch "
        "selection (ideally all batches) for fuller coverage",
    )

    all_material_names = sorted(set(material_names_with_cas) | set(CHEMICAL_REFERENCE.keys()))
    materials_entries = [
        (
            name,
            material_names_with_cas.get(name)
            or (CHEMICAL_REFERENCE[name]["cas_number"] if name in CHEMICAL_REFERENCE else None),
            CHEMICAL_REFERENCE[name]["price_per_gram_est"] if name in CHEMICAL_REFERENCE else None,
            CHEMICAL_REFERENCE_NOTE if name in CHEMICAL_REFERENCE else "",
        )
        for name in all_material_names
    ]
    _write_reference_materials_sheet(wb, materials_entries)

    all_process_types = sorted(set(process_types) | set(extra_schema_types or []))
    _write_reference_processes_sheet(wb, all_process_types)

    _write_reference_labor_sheet(wb)
    _write_reference_capital_sheet(wb, _known_location_capital_entries())

    return wb


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def build_workbook(
    process_cost_rows: list[ProcessCostRow],
    material_cost_rows: list[MaterialCostRow],
    batch_totals: list[BatchTotal],
    labor_selections: dict[str, tuple[str, float]],
    cost_reference: CostReference | None,
) -> Workbook:
    """A read-only computed report - every cell is a literal value already
    computed in Python (see data_manager.compute_*), not an Excel formula,
    so it always shows exactly what the in-app table showed at export time.
    """
    wb = Workbook()
    _build_guide_sheet(wb)
    _build_processes_sheet(wb, process_cost_rows)
    _build_materials_sheet(wb, material_cost_rows)
    _build_labor_sheet(wb, labor_selections, cost_reference)
    _build_summary_sheet(wb, batch_totals)
    logger.info("Built LCC report workbook: %s", wb.sheetnames)
    return wb
