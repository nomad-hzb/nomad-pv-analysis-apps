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
from IPython.display import display as ipydisplay

logger = logging.getLogger(__name__)


class LCCCalculatorApp:
    def __init__(self, url: str, token: str) -> None:
        self.url = url
        self.token = token
        self._dm = dm.LCCDataManager()
        self._cost_reference: dm.CostReference | None = None
        self._process_cost_rows: list[dm.ProcessCostRow] = []
        self._material_cost_rows: list[dm.MaterialCostRow] = []
        self._batch_totals: list[dm.BatchTotal] = []

        self._batch_panel = gui.BatchSelectionPanel(url, token)
        self._results_panel = gui.ResultsPanel()
        self._export_panel = gui.ExportPanel()
        self._admin_panel = gui.AdminPanel()

        self._batch_panel.connect_load_callback(self._on_load_batches)
        self._export_panel.connect_export_callback(self._on_export)
        self._admin_panel.connect_generate_callback(self._on_generate_reference_template)

    def _on_load_batches(self, _button) -> None:
        batch_ids = self._batch_panel.selected_batch_ids
        if not batch_ids:
            self._results_panel.show_status("Please select at least one batch.")
            return

        self._results_panel.show_status(f"Loading {len(batch_ids)} batch(es)...")
        try:
            self._dm.load_batches(self.url, self.token, batch_ids)
        except Exception as exc:  # noqa: BLE001 - surfaced to the user, not swallowed
            logger.exception("Error loading batches")
            self._results_panel.show_status(f"Error loading batches: {exc}")
            return

        if not self._dm.has_data:
            self._results_panel.show_status(
                "No process/material data found for the selected batch(es)."
            )
            return

        self._cost_reference = dm.load_default_cost_reference()
        self._process_cost_rows = dm.compute_process_cost_rows(
            self._dm.process_rows, self._dm.batch_sample_counts, self._cost_reference
        )
        self._material_cost_rows = dm.compute_material_cost_rows(
            self._dm.material_rows, self._cost_reference
        )
        self._results_panel.setup_labor_inputs(
            sorted(self._dm.batch_sample_counts), self._on_labor_change
        )

        if self._cost_reference is not None and self._cost_reference.total_entries:
            reference_note = (
                f"{self._cost_reference.total_entries} known cost entries applied from "
                "the shared cost reference file."
            )
        else:
            reference_note = (
                "No shared cost reference file found yet - costs will show as blank/unverified."
            )
        self._results_panel.show_status(
            f"Loaded {len(batch_ids)} batch(es): {len(self._process_cost_rows)} process type(s), "
            f"{len(self._material_cost_rows)} material(s). {reference_note}"
        )
        self._refresh_results()

    def _on_labor_change(self, _batch_id: str, _role: str, _hours: float) -> None:
        self._refresh_results()

    def _refresh_results(self) -> None:
        labor_selections = self._results_panel.get_labor_selections()
        labor_costs = {
            batch_id: dm.compute_labor_cost(role, hours, self._cost_reference)
            for batch_id, (role, hours) in labor_selections.items()
        }
        self._batch_totals = dm.compute_batch_totals(
            self._process_cost_rows,
            self._material_cost_rows,
            self._dm.batch_sample_counts,
            labor_costs,
        )
        self._results_panel.show_processes(self._process_cost_rows)
        self._results_panel.show_materials(self._material_cost_rows)
        self._results_panel.show_summary(self._batch_totals)

    def _on_export(self, _button) -> None:
        if not self._dm.has_data:
            self._export_panel.show_error("Load at least one batch with data first.")
            return

        try:
            labor_selections = self._results_panel.get_labor_selections()
            workbook = excel_export.build_workbook(
                self._process_cost_rows,
                self._material_cost_rows,
                self._batch_totals,
                labor_selections,
                self._cost_reference,
            )
            buffer = io.BytesIO()
            workbook.save(buffer)
            buffer.seek(0)
        except Exception as exc:  # noqa: BLE001 - surfaced to the user, not swallowed
            logger.exception("Error building report workbook")
            self._export_panel.show_error(str(exc))
            return

        b64_data = base64.b64encode(buffer.getvalue()).decode()
        filename = f"LCC_Calculator_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
        self._export_panel.show_download_link(
            filename, b64_data, "Read-only snapshot of the tables shown above."
        )

    def _on_generate_reference_template(self, _button) -> None:
        if not self._dm.has_data:
            self._admin_panel.show_error("Load at least one batch with data first.")
            return

        try:
            extra_schema_types = dm.discover_entry_types(
                self.url, self.token, self._dm.all_sample_ids
            )
            process_types = sorted({row.process_type for row in self._dm.process_rows})
            material_names_with_cas = {
                row.material_name: row.cas_number for row in self._dm.material_rows
            }
            workbook = excel_export.build_cost_reference_template_from_data(
                process_types,
                material_names_with_cas,
                len(self._dm.batch_sample_counts),
                extra_schema_types,
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
                self._results_panel.widget,
                self._export_panel.widget,
                admin_section,
            ],
            layout=widgets.Layout(padding="12px", gap="8px"),
        )
        ipydisplay(app_layout)
