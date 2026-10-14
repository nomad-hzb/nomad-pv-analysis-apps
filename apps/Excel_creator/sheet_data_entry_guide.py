import re

from hysprint_utils.process_specs import ATMOSPHERIC_FIELDS, PROCESSES

_UNIT_IN_LABEL = re.compile(r"\[([^\]]+)\]\s*$")


def _guide_row(label, test):
    """[Field Name, Description, Data Format, Units, Example] for one catalogue column."""
    unit = _UNIT_IN_LABEL.search(label)
    name = _UNIT_IN_LABEL.sub("", label).strip()
    if label == "Datetime":
        data_format, unit_text = "DD.MM.YYYY HH:MM:SS", "DD.MM.YYYY HH:MM:SS"
    else:
        unit_text = unit.group(1) if unit else ""
        if isinstance(test, bool):
            data_format = "Boolean"
        elif isinstance(test, (int, float)):
            data_format = "Number"
        else:
            data_format = "Text"
    return [label, name, data_format, unit_text, "" if test is None else str(test)]


def _test_value(spec_entry, n=1):
    test = spec_entry.get("test")
    return test(n) if callable(test) else test


def _guide_rows(process_name, atmospheric=False):
    """Guide table rows for one process type (or the atmospheric block), in catalogue order.

    Indexed groups (solvents, solutes, spin steps, ...) contribute their first item only."""
    if atmospheric:
        return [_guide_row(label, _test_value(spec)) for label, spec in ATMOSPHERIC_FIELDS.items()]
    spec = PROCESSES[process_name]
    rows = [
        _guide_row(label, _test_value(field)) for label, field in spec.get("fields", {}).items()
    ]
    for group in spec.get("indexed", {}).values():
        for entry in group:
            rows.append(_guide_row(entry["excel_key"].format(n=1), _test_value(entry)))
    return rows


# Method for adding a sheet with information on how to fill up the columns
def add_guide_sheet(workbook):
    guide_ws = workbook.create_sheet(title="Data Entry Guide")
    row = 1

    # 1. Introduction (multi-line text)
    intro_lines = [
        "Perovskite Solar Cell Fabrication Sequence (version Jan 2026)",
        "Data Entry Guide",
        "",
        "1. Introduction",
        "This guide provides instructions for filling out the spreadsheet that tracks the fabrication sequence of perovskite solar cells, supporting automated data upload to NOMAD.",  # noqa: E501
        "• Note: This guide is a reference. For specific questions or custom spreadsheet requests, please contact a Data Steward.",  # noqa: E501
        "• Customization: Each scientist may follow different fabrication steps. Data Stewards can provide a tailored spreadsheet for your workflow.",  # noqa: E501
        "• Coverage: Most Hysprint and IRIS lab processes are included. If you need to track additional information, contact a Data Steward.",  # noqa: E501
        "• Important: Do not add columns to the spreadsheet, as they will not be parsed.",
        "",
        "Example Fabrication Sequence:",
        "• Cleaning: 4 steps, UV-Ozone (ITO substrates)",
        "• Spin Coating: 1 solvent, 1 solute, 1 step (SAM)",
        "• Spin Coating: 2 solvents, 5 solutes, 2 steps, with antisolvent (Perovskite)",
        "• Evaporation: C60, BCP, Copper",
        "",
        "2. Detailed Field Descriptions",
        "Upload Name: Choose a descriptive upload name (e.g., project name + batch).",
        "",
    ]
    for line in intro_lines:
        guide_ws.cell(row=row, column=1, value=line)
        row += 1

    # Helper to write a table
    def write_table(ws, start_row, title, table_data):
        ws.cell(row=start_row, column=1, value=title)
        start_row += 1
        headers = ["Field Name", "Description", "Data Format", "Units", "Example"]
        for col, header in enumerate(headers, 1):
            ws.cell(row=start_row, column=col, value=header)
        for r, entry in enumerate(table_data, start_row + 1):
            for c, val in enumerate(entry, 1):
                ws.cell(row=r, column=c, value=val)
        return start_row + len(table_data) + 2  # leave a blank row after table

    # Every table below is generated from hysprint_utils.process_specs, the same catalogue
    # that builds the sheet's real columns, so the guide cannot drift from them. Examples are
    # the catalogue's test values; the first solvent/solute/step stands for the repeated ones.
    row = write_table(guide_ws, row, "Experiment Info", _guide_rows("Experiment Info"))
    for title, process_name in (
        ("Step 1: Cleaning (UV-Ozone)", "Cleaning UV-Ozone"),
        ("Step 2: Spin Coating", "Spin Coating"),
        ("Step 3: Evaporation", "Evaporation"),
        ("Step 4: ALD (Atomic Layer Deposition)", "ALD"),
        ("Step 5: Sputtering", "Sputtering"),
    ):
        row = write_table(guide_ws, row, title, _guide_rows(process_name))
    row = write_table(guide_ws, row, "Step 6: Atmospheric", _guide_rows(None, atmospheric=True))

    # 3. Data Entry Best Practices
    best_practices = [
        "",
        "3. Data Entry Best Practices",
        "• Decimal Points: Use a dot or comma as appropriate for your Excel/language settings.",
        "• Consistency: Use consistent names for materials, processes, and equipment.",
        "• Completeness: Record as many parameters as possible for each step.",
        "",
        "4. File Naming Conventions",
        "• Standard Format: Each measurement file should be saved as Nomad_id.comment.measurement_type.file_format",  # noqa: E501
        "  Example: DG_MMB_24_0_C-19.jv.txt",
    ]
    for line in best_practices:
        guide_ws.cell(row=row, column=1, value=line)
        row += 1

    # Add hyperlinks for Voila Dashboard and How-to-guide
    voila_row = row  # current row for Voila Dashboard
    guide_row = row + 1  # next row for How-to-guide

    guide_ws.cell(row=voila_row, column=1, value="• File Uploader Voila Dashboard")
    guide_ws.cell(
        row=voila_row, column=1
    ).hyperlink = "https://nomad-hzb-se.helmholtz-berlin.de/nomad-oasis/gui/search/voila"
    guide_ws.cell(row=voila_row, column=1).style = "Hyperlink"

    guide_ws.cell(
        row=guide_row,
        column=1,
        value="The Voila notebook automatically formats measurement files, so manual renaming is not required. We recommend using this method from now on. For how-to-guide, click here",  # noqa: E501
    )
    guide_ws.cell(
        row=guide_row, column=1
    ).hyperlink = (
        "https://scribehow.com/viewer/How_to_Work_on_the_HZB_Nomad_Oasis__bRbhHOaCR2S3dBIeQLYw8A"
    )
    guide_ws.cell(row=guide_row, column=1).style = "Hyperlink"

    # Set column widths for readability
    for col in "ABCDE":
        guide_ws.column_dimensions[col].width = 28
