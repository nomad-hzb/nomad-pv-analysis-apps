"""
app.py
------
Thin assembly layer for the LCC Calculator app.

Usage::

    app = LCCCalculatorApp(url, token)
    app.display()
"""

from __future__ import annotations

import base64
import io
import logging
from datetime import datetime

import data_manager as dm
import excel_export
import gui_components as gui
import ipywidgets as widgets
import plot_manager as pm
from IPython.display import display as ipydisplay

logger = logging.getLogger(__name__)


class LCCCalculatorApp:
    def __init__(self, url: str, token: str) -> None:
        self.url = url
        self.token = token
        self._dm = dm.LCCDataManager()

        self._batch_panel = gui.BatchSelectionPanel(url, token)
        self._review_panel = gui.ReviewPanel()
        self._export_panel = gui.ExportPanel()
        self._admin_panel = gui.AdminPanel()

        self._batch_panel.connect_load_callback(self._on_load_batches)
        self._export_panel.connect_export_callback(self._on_export)
        self._admin_panel.connect_generate_callback(self._on_generate_reference_template)

    def _on_load_batches(self, _button) -> None:
        batch_ids = self._batch_panel.selected_batch_ids
        if not batch_ids:
            self._review_panel.show_status("Please select at least one batch.")
            return

        self._review_panel.show_status(f"Loading {len(batch_ids)} batch(es)...")
        try:
            self._dm.load_batches(self.url, self.token, batch_ids)
        except Exception as exc:  # noqa: BLE001 - surfaced to the user, not swallowed
            logger.exception("Error loading batches")
            self._review_panel.show_status(f"Error loading batches: {exc}")
            return

        if not self._dm.has_data:
            self._review_panel.show_status(
                "No process/material data found for the selected batch(es)."
            )
            return

        self._review_panel.show_status(
            f"Loaded {len(self._dm.process_rows)} process step row(s) and "
            f"{len(self._dm.material_rows)} material row(s) across {len(batch_ids)} batch(es). "
            "Labor hours are entered manually per role in the exported workbook - "
            "see the Guide sheet."
        )
        self._review_panel.show_figure(pm.build_line_item_count_figure(self._dm))

    def _on_export(self, _button) -> None:
        if not self._dm.has_data:
            self._export_panel.show_error("Load at least one batch with data first.")
            return

        try:
            cost_reference = dm.load_default_cost_reference()
            workbook = excel_export.build_workbook(self._dm, cost_reference)
            buffer = io.BytesIO()
            workbook.save(buffer)
            buffer.seek(0)
        except Exception as exc:  # noqa: BLE001 - surfaced to the user, not swallowed
            logger.exception("Error building Excel workbook")
            self._export_panel.show_error(str(exc))
            return

        b64_data = base64.b64encode(buffer.getvalue()).decode()
        filename = f"LCC_Calculator_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
        if cost_reference is not None and cost_reference.total_entries:
            cost_reference_note = (
                f"Applied {cost_reference.total_entries} known cost entries from the "
                "shared cost reference file."
            )
        else:
            cost_reference_note = "No shared cost reference file found yet - all costs start blank."
        self._export_panel.show_download_link(filename, b64_data, cost_reference_note)

    def _on_generate_reference_template(self, _button) -> None:
        if not self._dm.has_data:
            self._admin_panel.show_error("Load at least one batch with data first.")
            return

        try:
            extra_schema_types = dm.discover_entry_types(
                self.url, self.token, self._dm.all_sample_ids
            )
            workbook = excel_export.build_cost_reference_template_from_data(
                self._dm, extra_schema_types
            )
            buffer = io.BytesIO()
            workbook.save(buffer)
            buffer.seek(0)
        except Exception as exc:  # noqa: BLE001 - surfaced to the user, not swallowed
            logger.exception("Error building cost reference template")
            self._admin_panel.show_error(str(exc))
            return

        b64_data = base64.b64encode(buffer.getvalue()).decode()
        self._admin_panel.show_download_link("cost_reference.xlsx", b64_data)

    def display(self) -> None:
        title = widgets.HTML("<h1 style='text-align: center; color: #2E86AB;'>LCC Calculator</h1>")
        admin_section = widgets.VBox(
            [
                widgets.HTML("<h3 style='color: #A23B72;'>Admin: Cost Reference Template</h3>"),
                self._admin_panel.widget,
            ]
        )
        app_layout = widgets.VBox(
            [
                title,
                self._batch_panel.widget,
                self._review_panel.widget,
                self._export_panel.widget,
                admin_section,
            ],
            layout=widgets.Layout(padding="12px", gap="8px"),
        )
        ipydisplay(app_layout)
