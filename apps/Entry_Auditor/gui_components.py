# gui_components.py
# All ipywidgets code. No NOMAD/API calls happen here directly - everything funnels
# through data_manager.py, which owns EntryAuditSession and never imports a widget
# library.

from __future__ import annotations

import base64
import logging
from pathlib import Path

import ipywidgets as widgets
import pandas as pd
from data_manager import (
    ENTRY_TYPES_TO_AUDIT,
    EntryAuditSession,
    apply_correction,
    build_corrections_dict,
)

from hysprint_utils.batch_selection import create_batch_selection

logger = logging.getLogger(__name__)


def _render_field_table_html(session: EntryAuditSession, label: str, column: str) -> str:
    summary = session.field_summary(label, column)
    is_inconsistent = len(summary) > 1
    color = "#c0392b" if is_inconsistent else "#27ae60"
    status = "inconsistent" if is_inconsistent else "consistent"
    df = session.datasets[label]

    rows = [
        f"<div style='font-weight:bold;color:{color};margin-bottom:6px'>"
        f"[{status}] <code>{column}</code> - {len(summary)} unique value(s)</div>",
        "<table style='border-collapse:collapse;font-size:13px'>",
        "<tr style='background:#f0f0f0'>"
        "<th style='text-align:left;padding:4px 14px'>Value</th>"
        "<th style='text-align:center;padding:4px 14px'>Count</th>"
        "<th style='text-align:left;padding:4px 14px'>Links</th></tr>",
    ]
    for entry in summary:
        link_tags = []
        for row_index in entry["row_indices"][:10]:
            row = df.loc[row_index]
            sample_id = row.get("sample_id", "")
            gui_url = row.get("_gui_url", "") or session.sample_links.get(sample_id, "")
            if gui_url:
                link_tags.append(f"<a href='{gui_url}' target='_blank'>open</a>")
        if len(entry["row_indices"]) > 10:
            remaining = len(entry["row_indices"]) - 10
            link_tags.append(f"<span style='color:#888'>+{remaining} more</span>")
        rows.append(
            "<tr>"
            f"<td style='padding:3px 14px'><b>{entry['value']}</b></td>"
            f"<td style='padding:3px 14px;text-align:center'>{entry['count']}</td>"
            f"<td style='padding:3px 14px'>{' '.join(link_tags) or '-'}</td>"
            "</tr>"
        )
    rows.append("</table>")
    return "".join(rows)


class FieldAuditPanel(widgets.VBox):
    """Field selector, value table, and correction section for one entry-type dataset.
    The correction section is only shown when url/token are both given - offline/demo
    data has no NOMAD entries to write back to."""

    def __init__(
        self,
        session: EntryAuditSession,
        label: str,
        url: str | None,
        token: str | None,
    ) -> None:
        self.session = session
        self.label = label
        self.url = url
        self.token = token
        self.entry_type = ENTRY_TYPES_TO_AUDIT[label]
        self._can_correct = url is not None and token is not None

        self.checkbox = widgets.Checkbox(
            value=False,
            description="Show consistent fields (1 unique value)",
            layout=widgets.Layout(width="340px"),
        )
        self.dropdown = widgets.Dropdown(
            options=self._field_options(False),
            description="Field:",
            layout=widgets.Layout(width="380px"),
        )
        self.table_out = widgets.HTML(value="")

        self.checkbox.observe(self._on_checkbox_change, names="value")
        self.dropdown.observe(self._on_field_change, names="value")

        df = session.datasets[label]
        entries = len(df)
        unique_samples = df["sample_id"].nunique() if "sample_id" in df.columns else 0
        header = widgets.HTML(
            value=(
                f"<h4 style='margin-bottom:2px'>{label}</h4>"
                f"<p style='margin-top:0;color:#555'>Entries: {entries} &nbsp;|&nbsp; "
                f"Unique samples: {unique_samples} &nbsp;|&nbsp; "
                f"Auditable fields: {len(self._field_options(True))}</p>"
            )
        )

        correct_section: widgets.Widget = widgets.VBox([])
        if self._can_correct:
            self.from_dropdown = widgets.Dropdown(
                description="Correct:", layout=widgets.Layout(width="320px")
            )
            self.to_input = widgets.Text(
                description="To:", placeholder="new value", layout=widgets.Layout(width="320px")
            )
            self.correct_button = widgets.Button(
                description="Correct all", button_style="warning", icon="pencil"
            )
            self.correct_out = widgets.HTML(value="")
            self.correct_button.on_click(self._on_correct_click)
            correct_section = widgets.VBox(
                [
                    widgets.HTML("<hr><b>Correct values</b>"),
                    widgets.HBox([self.from_dropdown, self.to_input, self.correct_button]),
                    self.correct_out,
                ]
            )

        super().__init__([header, self.checkbox, self.dropdown, self.table_out, correct_section])

        if self.dropdown.options:
            first_column = self.dropdown.options[0][1]
            self._render_table(first_column)
            if self._can_correct:
                self._refresh_from_options(first_column)
        else:
            self.table_out.value = (
                "<p style='color:#27ae60'>All fields are consistent for this selection. "
                "Tick the checkbox above to inspect individual values.</p>"
            )

    def _field_options(self, show_consistent: bool) -> list[tuple[str, str]]:
        options = []
        for column in self.session.auditable_columns(self.label):
            unique_count = len(self.session.field_summary(self.label, column))
            if show_consistent or unique_count > 1:
                options.append((f"{column}  ({unique_count} unique)", column))
        return options

    def _on_checkbox_change(self, change) -> None:
        self.dropdown.options = self._field_options(change["new"])

    def _on_field_change(self, change) -> None:
        if not change["new"]:
            return
        self._render_table(change["new"])
        if self._can_correct:
            self._refresh_from_options(change["new"])

    def _render_table(self, column: str) -> None:
        self.table_out.value = _render_field_table_html(self.session, self.label, column)

    def _refresh_from_options(self, column: str) -> None:
        summary = self.session.field_summary(self.label, column)
        self.from_dropdown.options = [row["value"] for row in summary]

    def _on_correct_click(self, _button) -> None:
        self.correct_out.value = "<i>Working...</i>"
        column = self.dropdown.value
        old_value = self.from_dropdown.value
        new_value = self.to_input.value.strip()

        if not new_value:
            self.correct_out.value = "<span style='color:#c0392b'>Enter a target value.</span>"
            return
        if new_value == old_value:
            self.correct_out.value = (
                "<span style='color:#c0392b'>Target is the same as source. Nothing to do.</span>"
            )
            return

        try:
            result = apply_correction(
                self.url,
                self.token,
                self.session.datasets[self.label],
                column,
                old_value,
                new_value,
                self.entry_type,
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("Correction failed for %s.%s", self.label, column)
            self.correct_out.value = f"<span style='color:#c0392b'>Failed: {exc}</span>"
            return

        self.correct_out.value = (
            f"Done - {result.success} updated, {result.skipped} skipped, {result.failed} failed."
        )


def create_audit_tab(
    session: EntryAuditSession, url: str, token: str, demo_fixture_path: Path
) -> widgets.VBox:
    log_out = widgets.HTML(value="")
    results_out = widgets.VBox([])

    def _show_results(url_for_panels: str | None, token_for_panels: str | None) -> None:
        results_out.children = [
            FieldAuditPanel(session, label, url_for_panels, token_for_panels)
            for label in session.datasets
        ]

    def _run_audit(batch_widget) -> None:
        batch_ids = list(batch_widget.value)
        results_out.children = []
        if not batch_ids:
            log_out.value = "No batches selected."
            return
        log_out.value = f"Resolving samples for {len(batch_ids)} batch(es)..."
        messages = session.load(url, token, batch_ids)
        log_out.value = f"Found {len(session.sample_ids)} samples.<br>" + "<br>".join(
            f"{label}: {message}" for label, message in messages.items()
        )
        _show_results(url, token)

    demo_button = widgets.Button(
        description="Load demo data", button_style="warning", icon="database"
    )

    def _on_demo_click(_button) -> None:
        results_out.children = []
        if not session.load_offline(demo_fixture_path):
            log_out.value = "Demo fixture contained no data."
            return
        log_out.value = f"Loaded demo data: {len(session.sample_ids)} samples."
        _show_results(None, None)

    demo_button.on_click(_on_demo_click)

    return widgets.VBox(
        [
            widgets.HTML("<h3 style='margin:4px 0'>Batch Selection</h3>"),
            demo_button,
            create_batch_selection(url, token, _run_audit),
            widgets.HTML("<b style='font-size:12px'>Log</b>"),
            log_out,
            widgets.HTML("<h3 style='margin:10px 0 4px 0'>Audit Results</h3>"),
            results_out,
        ]
    )


def _corrections_dataframe() -> pd.DataFrame:
    corrections = build_corrections_dict()
    rows = [
        {"correct_value": correct, "wrong_value": wrong}
        for correct, wrongs in corrections.items()
        for wrong in wrongs
    ]
    return pd.DataFrame(rows) if rows else pd.DataFrame(columns=["correct_value", "wrong_value"])


def create_corrections_tab() -> widgets.VBox:
    table_out = widgets.HTML(value="")
    download_out = widgets.HTML(value="")
    refresh_button = widgets.Button(description="Refresh", button_style="info", icon="refresh")
    export_button = widgets.Button(
        description="Export CSV", button_style="success", icon="download"
    )

    def _on_refresh(_button=None) -> None:
        df = _corrections_dataframe()
        if df.empty:
            table_out.value = "<p style='color:#888'>No corrections logged yet.</p>"
        else:
            table_out.value = df.to_html(index=False)
        download_out.value = ""

    def _on_export(_button) -> None:
        df = _corrections_dataframe()
        if df.empty:
            download_out.value = "Nothing to export."
            return
        b64_data = base64.b64encode(df.to_csv(index=False).encode()).decode()
        download_out.value = (
            f"<a href='data:text/csv;base64,{b64_data}' download='corrections.csv'>"
            "Download corrections.csv</a>"
        )

    refresh_button.on_click(_on_refresh)
    export_button.on_click(_on_export)
    _on_refresh()

    return widgets.VBox(
        [
            widgets.HTML("<h3 style='margin:4px 0'>Corrections Log</h3>"),
            widgets.HBox([refresh_button, export_button]),
            table_out,
            download_out,
        ]
    )


def create_entry_auditor_ui(url: str, token: str, demo_fixture_path: Path) -> widgets.Widget:
    session = EntryAuditSession()
    tabs = widgets.Tab(
        children=[
            create_audit_tab(session, url, token, demo_fixture_path),
            create_corrections_tab(),
        ]
    )
    tabs.set_title(0, "Audit")
    tabs.set_title(1, "Corrections")
    return tabs
