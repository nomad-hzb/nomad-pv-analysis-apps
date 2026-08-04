"""
gui_components.py
------------------
All ipywidgets code for the LCC Calculator lives here. The primary review
surface is read-only in-app tables (ResultsPanel) - Excel export is a
secondary download of the same already-computed numbers.
"""

from __future__ import annotations

import logging

import ipywidgets as widgets
from data_manager import LABOR_ROLES
from IPython.display import HTML, clear_output, display
from natsort import natsorted

from hysprint_utils.api_calls import get_batch_ids_with_authors
from hysprint_utils.plotting_utils import WidgetFactory

logger = logging.getLogger(__name__)


def _show_xlsx_download_link(
    output: widgets.Output, filename: str, b64_data: str, note: str = ""
) -> None:
    note_html = f'<span style="font-size: 0.9em; color: #155724;">{note}</span><br>' if note else ""
    with output:
        clear_output()
        display(
            HTML(
                '<div style="padding: 12px; background-color: #d4edda; '
                'border: 1px solid #c3e6cb; border-radius: 6px; margin: 10px 0;">'
                "<strong>Workbook ready</strong><br>"
                f"{note_html}"
                '<a href="data:application/vnd.openxmlformats-officedocument.'
                f'spreadsheetml.sheet;base64,{b64_data}" download="{filename}" '
                'style="display:inline-block; padding:8px 16px; '
                "background-color:#28a745; color:white; text-decoration:none; "
                'border-radius:4px; font-weight:bold; margin-top:8px;">'
                f"Download {filename}</a></div>"
            )
        )


def _show_download_error(output: widgets.Output, message: str) -> None:
    with output:
        clear_output()
        print(f"Error: {message}")  # noqa: T201 - legitimate Output() display


def _fmt_cost(value: float | None, verified: bool) -> str:
    if value is None:
        return "-"
    return f"{value:.2f}" if verified else f"{value:.2f} ⚠"


def _build_html_table(headers: list[str], rows: list[list], bold_last_row: bool = False) -> str:
    header_cells = "".join(
        "<th style='padding:4px 10px; border-bottom:2px solid #2E86AB; "
        f"text-align:left; white-space:nowrap;'>{header}</th>"
        for header in headers
    )
    body_rows = []
    for index, row in enumerate(rows):
        row_style = (
            "font-weight:bold; border-top:2px solid #333;"
            if bold_last_row and index == len(rows) - 1
            else ""
        )
        cells = "".join(
            f"<td style='padding:4px 10px; border-bottom:1px solid #eee;'>{cell}</td>"
            for cell in row
        )
        body_rows.append(f"<tr style='{row_style}'>{cells}</tr>")
    return (
        "<table style='border-collapse:collapse; font-size:0.9em;'>"
        f"<thead><tr>{header_cells}</tr></thead>"
        f"<tbody>{''.join(body_rows)}</tbody>"
        "</table>"
    )


class BatchSelectionPanel:
    """ "Select batches" tool: filter-by-user dropdown + search box + multi-select,
    following Global_analyzer's pattern (not the plain
    hysprint_utils.batch_selection.create_batch_selection helper, which has no
    author filter) - see plan notes for why this is app-local, not shared, code.
    """

    def __init__(self, url: str, token: str) -> None:
        batch_records = get_batch_ids_with_authors(url, token)

        # Collapse subbatch duplicates: keep only the top-level batch id.
        all_lab_ids = [record["lab_id"] for record in batch_records]
        records_by_lab_id = {}
        for record in batch_records:
            lab_id = record["lab_id"]
            if "_".join(lab_id.split("_")[:-1]) in all_lab_ids:
                continue
            records_by_lab_id[lab_id] = record
        self._batch_records = [records_by_lab_id[lab_id] for lab_id in natsorted(records_by_lab_id)]
        batch_ids_all = [record["lab_id"] for record in self._batch_records]

        author_names = sorted({record["author_name"] for record in self._batch_records})
        self.author_filter = widgets.Dropdown(
            options=["All"] + author_names,
            value="All",
            description="Filter by user:",
            style={"description_width": "initial"},
            layout=widgets.Layout(width="300px"),
        )
        self.search_box = widgets.Text(description="Search Batch")
        self.batch_selector = widgets.SelectMultiple(
            options=batch_ids_all,
            description="Batches",
            layout=widgets.Layout(width="400px", height="200px"),
        )
        self.load_button = WidgetFactory.create_button(
            description="Load Data", button_style="primary"
        )

        def _apply_filters(*_args):
            search_term = self.search_box.value.strip().lower()
            author = self.author_filter.value
            filtered = [
                record["lab_id"]
                for record in self._batch_records
                if (author == "All" or record["author_name"] == author)
                and (not search_term or search_term in record["lab_id"].lower())
            ]
            self.batch_selector.options = natsorted(filtered)

        self.search_box.observe(_apply_filters, names="value")
        self.author_filter.observe(_apply_filters, names="value")

        self.widget = widgets.VBox(
            [self.author_filter, self.search_box, self.batch_selector, self.load_button]
        )

    def connect_load_callback(self, handler) -> None:
        self.load_button.on_click(handler)

    @property
    def selected_batch_ids(self) -> list[str]:
        return list(self.batch_selector.value)


class ResultsPanel:
    """Read-only in-app tables (Processes, Materials, Summary) plus a role +
    hours input per loaded batch for Labor cost - this is the primary way
    to review a batch's cost breakdown. Excel export is a secondary,
    read-only download of these same already-computed numbers.
    """

    def __init__(self) -> None:
        self.status_output = widgets.Output(
            layout={"border": "1px solid #ddd", "padding": "10px", "min_height": "40px"}
        )
        self.processes_output = widgets.Output()
        self.materials_output = widgets.Output()
        self.labor_box = widgets.VBox()
        self.summary_output = widgets.Output()
        self._labor_widgets: dict[str, tuple[widgets.Dropdown, widgets.BoundedFloatText]] = {}

        self.widget = widgets.VBox(
            [
                self.status_output,
                widgets.HTML(
                    "<h3 style='color: #A23B72;'>Processes</h3>"
                    "<p style='color:#888; font-size:0.85em;'>⚠ = not yet verified "
                    "in cost_reference.xlsx</p>"
                ),
                self.processes_output,
                widgets.HTML("<h3 style='color: #A23B72;'>Materials</h3>"),
                self.materials_output,
                widgets.HTML("<h3 style='color: #A23B72;'>Labor</h3>"),
                widgets.HTML(
                    "<p style='color:#666;'>NOMAD doesn't record who ran a process, so pick "
                    "a role and enter estimated hours per batch below.</p>"
                ),
                self.labor_box,
                widgets.HTML("<h3 style='color: #A23B72;'>Summary</h3>"),
                self.summary_output,
            ]
        )

    def show_status(self, message: str) -> None:
        with self.status_output:
            clear_output()
            print(message)  # noqa: T201 - legitimate Output() display, not debug logging

    def setup_labor_inputs(self, batch_ids: list[str], on_change) -> None:
        """Rebuild one Role dropdown + Hours input row per batch.
        on_change(batch_id, role, hours) fires whenever either widget changes.
        """
        self._labor_widgets = {}
        rows = []
        for batch_id in batch_ids:
            role_dropdown = widgets.Dropdown(
                options=LABOR_ROLES,
                value=LABOR_ROLES[0],
                description=batch_id,
                style={"description_width": "180px"},
                layout=widgets.Layout(width="340px"),
            )
            hours_input = widgets.BoundedFloatText(
                value=0.0,
                min=0.0,
                max=500.0,
                step=0.5,
                description="Hours:",
                layout=widgets.Layout(width="150px"),
            )

            def _handle_change(
                _change, batch_id=batch_id, role_dropdown=role_dropdown, hours_input=hours_input
            ):
                on_change(batch_id, role_dropdown.value, hours_input.value)

            role_dropdown.observe(_handle_change, names="value")
            hours_input.observe(_handle_change, names="value")
            self._labor_widgets[batch_id] = (role_dropdown, hours_input)
            rows.append(widgets.HBox([role_dropdown, hours_input]))
        self.labor_box.children = rows

    def get_labor_selections(self) -> dict[str, tuple[str, float]]:
        return {
            batch_id: (role_dropdown.value, hours_input.value)
            for batch_id, (role_dropdown, hours_input) in self._labor_widgets.items()
        }

    def show_processes(self, rows: list) -> None:
        headers = [
            "Batch",
            "Process",
            "Steps",
            "Location(s)",
            "Process Cost",
            "Equipment Cost",
            "Total",
        ]
        table_rows = [
            [
                row.batch_id,
                row.process_type,
                row.step_count,
                ", ".join(row.locations) or "-",
                _fmt_cost(row.process_cost, row.process_cost_verified),
                _fmt_cost(row.equipment_cost, row.equipment_cost_verified),
                _fmt_cost(
                    row.total_cost, row.process_cost_verified and row.equipment_cost_verified
                ),
            ]
            for row in rows
        ]
        self._render_table(
            self.processes_output,
            headers,
            table_rows,
            "No processes found for the selected batch(es).",
        )

    def show_materials(self, rows: list) -> None:
        headers = [
            "Batch",
            "Material",
            "Role(s)",
            "Used",
            "CAS",
            "Quantity (g)",
            "Source",
            "€/g",
            "Total",
        ]
        table_rows = [
            [
                row.batch_id,
                row.material_name,
                ", ".join(row.roles),
                row.usage_count,
                row.cas_number or "-",
                f"{row.quantity_grams:.3g}" if row.quantity_grams is not None else "-",
                row.quantity_source,
                f"{row.price_per_gram:.2f}" if row.price_per_gram is not None else "-",
                _fmt_cost(row.total_cost, row.verified),
            ]
            for row in rows
        ]
        self._render_table(
            self.materials_output,
            headers,
            table_rows,
            "No materials found for the selected batch(es).",
        )

    def show_summary(self, totals: list) -> None:
        headers = [
            "Batch",
            "Samples",
            "Materials",
            "Processes",
            "Equipment",
            "Labor",
            "Grand Total",
            "Per Sample",
            "Unverified",
        ]
        table_rows = [
            [
                total.batch_id,
                total.num_samples,
                f"{total.material_total:.2f}",
                f"{total.process_total:.2f}",
                f"{total.equipment_total:.2f}",
                f"{total.labor_total:.2f}",
                f"{total.grand_total:.2f}",
                f"{total.per_sample:.2f}" if total.per_sample is not None else "-",
                total.unverified_count,
            ]
            for total in totals
        ]
        if totals:
            table_rows.append(
                [
                    "TOTAL (all selected)",
                    sum(total.num_samples for total in totals),
                    "",
                    "",
                    "",
                    "",
                    f"{sum(total.grand_total for total in totals):.2f}",
                    "",
                    "",
                ]
            )
        self._render_table(
            self.summary_output,
            headers,
            table_rows,
            "Load batches to see a summary.",
            bold_last_row=bool(totals),
        )

    def _render_table(
        self,
        output: widgets.Output,
        headers: list[str],
        rows: list[list],
        empty_message: str,
        bold_last_row: bool = False,
    ) -> None:
        with output:
            clear_output()
            if not rows:
                print(empty_message)  # noqa: T201 - legitimate Output() display
                return
            display(HTML(_build_html_table(headers, rows, bold_last_row)))


class ExportPanel:
    """Export-to-Excel button + browser download link (base64 data URI, no
    server-side file write - same pattern as MPPT_Analysis/gui_components.py).

    Costs are carried forward automatically from the shared admin-maintained
    cost_reference.xlsx (see data_manager.load_default_cost_reference) - no
    upload step for the user, that file is the single source of truth. The
    downloaded file is a read-only snapshot of the same numbers already
    shown in ResultsPanel above.
    """

    def __init__(self) -> None:
        self.export_button = WidgetFactory.create_button(
            description="Download Report", button_style="success"
        )
        self.download_output = widgets.Output()
        self.widget = widgets.VBox([self.export_button, self.download_output])

    def connect_export_callback(self, handler) -> None:
        self.export_button.on_click(handler)

    def show_download_link(self, filename: str, b64_data: str, cost_reference_note: str) -> None:
        _show_xlsx_download_link(self.download_output, filename, b64_data, cost_reference_note)

    def show_error(self, message: str) -> None:
        _show_download_error(self.download_output, message)


class AdminPanel:
    """Admin tool: generate a cost_reference.xlsx template pre-filled with
    the real Material/Process/Item names found in whatever batches are
    currently loaded (select a broad/complete batch selection first for
    full coverage). Save the downloaded file as
    apps/LCC_Calculator/cost_reference.xlsx (data_manager.DEFAULT_COST_REFERENCE_PATH)
    to make it the shared source of truth every user's session reads
    automatically.
    """

    def __init__(self) -> None:
        self.generate_button = WidgetFactory.create_button(
            description="Generate Cost Reference Template", button_style="info"
        )
        self.download_output = widgets.Output()
        self.widget = widgets.VBox(
            [
                widgets.HTML(
                    "<p style='color:#666;'><b>Admin tool</b> - select a broad/complete "
                    "set of batches above and Load, then generate a cost reference "
                    "template pre-filled with the real material/process/item names "
                    "found. Save the downloaded file as "
                    "<code>apps/LCC_Calculator/cost_reference.xlsx</code> to make it the "
                    "shared source of truth every user's session reads automatically.</p>"
                ),
                self.generate_button,
                self.download_output,
            ]
        )

    def connect_generate_callback(self, handler) -> None:
        self.generate_button.on_click(handler)

    def show_download_link(self, filename: str, b64_data: str) -> None:
        _show_xlsx_download_link(self.download_output, filename, b64_data)

    def show_error(self, message: str) -> None:
        _show_download_error(self.download_output, message)
