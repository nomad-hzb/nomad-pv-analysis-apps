"""
gui_components.py
------------------
All ipywidgets code for the LCC Calculator lives here.
"""

from __future__ import annotations

import logging

import ipywidgets as widgets
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


class ReviewPanel:
    """Status line + per-batch line-item count chart, shown after a Load."""

    def __init__(self) -> None:
        self.status_output = widgets.Output(
            layout={"border": "1px solid #ddd", "padding": "10px", "min_height": "60px"}
        )
        self.plot_output = widgets.Output()
        self.widget = widgets.VBox([self.status_output, self.plot_output])

    def show_status(self, message: str) -> None:
        with self.status_output:
            clear_output()
            print(message)  # noqa: T201 - legitimate Output() display, not debug logging

    def show_figure(self, figure) -> None:
        with self.plot_output:
            clear_output()
            display(figure)


class ExportPanel:
    """Export-to-Excel button + browser download link (base64 data URI, no
    server-side file write - same pattern as MPPT_Analysis/gui_components.py).

    Costs are carried forward automatically from the shared admin-maintained
    cost_reference.xlsx (see data_manager.load_default_cost_reference) - no
    upload step for the user, that file is the single source of truth.
    """

    def __init__(self) -> None:
        self.export_button = WidgetFactory.create_button(
            description="Export to Excel", button_style="success"
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
    the real Material/Process/Operator/Item names found in whatever batches
    are currently loaded (select a broad/complete batch selection first for
    full coverage). Save the downloaded file as
    apps/LCC_Calculator/cost_reference.xlsx (data_manager.DEFAULT_COST_REFERENCE_PATH)
    to make it the shared source of truth every user's export reads
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
                    "template pre-filled with the real material/process/operator/item "
                    "names found. Save the downloaded file as "
                    "<code>apps/LCC_Calculator/cost_reference.xlsx</code> to make it the "
                    "shared source of truth every user's export reads automatically.</p>"
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
