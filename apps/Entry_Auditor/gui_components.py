# gui_components.py
# All ipywidgets code. No NOMAD/API calls happen here directly - everything funnels
# through data_manager.py, which owns EntryAuditSession and never imports a widget
# library.

from __future__ import annotations

import base64
import logging
import re
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


_MAINFILE_SUFFIX = re.compile(r"\.archive\.(json|yaml)$")


def _mainfile_label(mainfile: str) -> str:
    """Short, human-meaningful tag for one entry's underlying file - a sample can have
    several entries of the same schema (e.g. multiple Spin Coating steps), all sharing
    one sample_id, so the mainfile (which carries a sequence/step prefix in this lab's
    naming convention) is what actually tells them apart in the UI."""
    return _MAINFILE_SUFFIX.sub("", mainfile)


def _log_html(text: str) -> str:
    return (
        "<div style='max-height:220px;overflow-y:auto;font-size:12px;white-space:pre-wrap'>"
        f"{text}</div>"
    )


def _render_detail_table_html(session: EntryAuditSession, label: str, show_links: bool) -> str:
    """One row per (parameter, entry) - the full, untruncated detail view behind the
    'Expand' toggle. Rows belonging to a varied parameter are colored to match the
    summary table. show_links controls whether each value is wrapped in a hyperlink to
    its NOMAD GUI entry (opt-in, since resolving/rendering a link for every row adds up
    on large batches)."""
    df = session.datasets[label]
    overview = session.field_overview(label)

    rows = [
        "<table style='border-collapse:collapse;font-size:12px'>",
        "<tr style='background:#f0f0f0'>"
        "<th style='text-align:left;padding:4px 12px'>Parameter</th>"
        "<th style='text-align:left;padding:4px 12px'>Sample</th>"
        "<th style='text-align:left;padding:4px 12px'>Value</th></tr>",
    ]
    for entry in overview:
        column = entry["column"]
        color = "#c0392b" if entry["is_varied"] else "#1a1a1a"
        for value_row in entry["summary"]:
            value = value_row["value"]
            for row_index in value_row["row_indices"]:
                row = df.loc[row_index]
                sample_id = row.get("sample_id", "") or "N/A"
                # A sample can carry several entries of the same schema (e.g. multiple
                # Spin Coating steps) - the mainfile tag is what tells them apart.
                mainfile_label = _mainfile_label(row.get("_mainfile", "") or "")
                sample_cell = f"{sample_id} <span style='color:#888'>({mainfile_label})</span>"
                value_cell = str(value)
                if show_links:
                    gui_url = row.get("_gui_url", "") or session.sample_links.get(sample_id, "")
                    if gui_url:
                        value_cell = f"<a href='{gui_url}' target='_blank'>{value_cell}</a>"
                rows.append(
                    "<tr>"
                    f"<td style='padding:2px 12px;color:{color}'>{column}</td>"
                    f"<td style='padding:2px 12px'>{sample_cell}</td>"
                    f"<td style='padding:2px 12px;color:{color}'>{value_cell}</td>"
                    "</tr>"
                )
    rows.append("</table>")
    table_html = "".join(rows)
    return (
        "<div style='max-height:420px;overflow-y:auto;border:1px solid #ddd;padding:4px'>"
        f"{table_html}</div>"
    )


class FieldAuditPanel(widgets.VBox):
    """Always-visible parameter/value/variations summary, an opt-in detailed per-entry
    table, and a correction section for one entry-type dataset. The correction section
    is only shown when url/token are both given - offline/demo data has no NOMAD entries
    to write back to."""

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

        df = session.datasets[label]
        entries = len(df)
        unique_samples = df["sample_id"].nunique() if "sample_id" in df.columns else 0
        overview = session.field_overview(label)
        header = widgets.HTML(
            value=(
                f"<h4 style='margin-bottom:2px'>{label}</h4>"
                f"<p style='margin-top:0;color:#555'>Entries: {entries} &nbsp;|&nbsp; "
                f"Unique samples: {unique_samples} &nbsp;|&nbsp; "
                f"Auditable fields: {len(overview)}</p>"
            )
        )

        self.expand_toggle = widgets.ToggleButton(value=False, description="Expand", icon="expand")
        self.links_toggle = widgets.ToggleButton(
            value=False, description="Add NOMAD links", icon="link"
        )
        self.detail_out = widgets.HTML(value="")
        self.expand_toggle.observe(self._on_expand_change, names="value")
        self.links_toggle.observe(self._on_links_change, names="value")

        self.dropdown: widgets.Dropdown | None = None
        correct_section: widgets.Widget = widgets.VBox([])
        if self._can_correct:
            self.dropdown = widgets.Dropdown(
                options=list(session.auditable_columns(label)),
                description="Field:",
                layout=widgets.Layout(width="380px"),
            )
            self.from_dropdown = widgets.Dropdown(
                description="Change name:", layout=widgets.Layout(width="260px")
            )
            self.sample_dropdown = widgets.Dropdown(
                description="Sample:", layout=widgets.Layout(width="260px")
            )
            self.to_input = widgets.Text(
                description="To:", placeholder="new value", layout=widgets.Layout(width="260px")
            )
            self.correct_button = widgets.Button(
                description="Correct value(s)", button_style="warning", icon="pencil"
            )
            self.correct_out = widgets.HTML(value="")

            self.dropdown.observe(self._on_field_change, names="value")
            self.from_dropdown.observe(self._on_from_change, names="value")
            self.correct_button.on_click(self._on_correct_click)

            correct_section = widgets.VBox(
                [
                    widgets.HTML("<hr><b>Correct values</b>"),
                    widgets.HBox(
                        [
                            self.dropdown,
                            self.from_dropdown,
                            self.sample_dropdown,
                            self.to_input,
                            self.correct_button,
                        ]
                    ),
                    self.correct_out,
                ]
            )
            if self.dropdown.options:
                self._refresh_from_options(self.dropdown.options[0])

        summary_grid = self._build_summary_grid(overview)
        toolbar = widgets.HBox([self.expand_toggle, self.links_toggle])

        super().__init__([header, summary_grid, toolbar, self.detail_out, correct_section])

    def _build_summary_grid(self, overview: list[dict]) -> widgets.VBox:
        # Plain HBox/VBox rows rather than GridBox - GridBox leans on CSS grid support
        # that has been unreliable in some embedded ipywidgets renderers (e.g. VS
        # Code's Jupyter webview), whereas nested HBox/VBox is the oldest and most
        # broadly-supported ipywidgets layout pattern.
        name_width, value_width, variations_width = "240px", "200px", "100px"
        header_row = widgets.HBox(
            [
                widgets.HTML("<b>Parameter</b>", layout=widgets.Layout(width=name_width)),
                widgets.HTML("<b>Value</b>", layout=widgets.Layout(width=value_width)),
                widgets.HTML("<b>Variations</b>", layout=widgets.Layout(width=variations_width)),
            ]
        )
        rows: list[widgets.Widget] = [header_row]
        for entry in overview:
            column = entry["column"]
            summary = entry["summary"]
            is_varied = entry["is_varied"]
            color = "#c0392b" if is_varied else "#1a1a1a"
            value_display = "varied" if is_varied else (summary[0]["value"] if summary else "-")

            if self._can_correct:
                name_widget = widgets.Button(
                    description=column,
                    layout=widgets.Layout(width=name_width),
                    tooltip="Select this field in the correction controls below",
                )
                if is_varied:
                    name_widget.style.button_color = "#f5b7b1"
                name_widget.on_click(lambda _button, col=column: self._select_field(col))
            else:
                name_widget = widgets.HTML(
                    f"<code>{column}</code>", layout=widgets.Layout(width=name_width)
                )

            value_widget = widgets.HTML(
                f"<span style='color:{color}'>{value_display}</span>",
                layout=widgets.Layout(width=value_width),
            )
            variations_widget = widgets.HTML(
                f"<span style='color:{color}'>{len(summary)}</span>",
                layout=widgets.Layout(width=variations_width),
            )
            rows.append(widgets.HBox([name_widget, value_widget, variations_widget]))

        return widgets.VBox(rows, layout=widgets.Layout(max_height="360px", overflow_y="auto"))

    def _select_field(self, column: str) -> None:
        if self.dropdown is None:
            return
        if self.dropdown.value == column:
            self._refresh_from_options(column)
        else:
            self.dropdown.value = column

    def _on_expand_change(self, change) -> None:
        if change["new"]:
            self._render_detail_table()
        else:
            self.detail_out.value = ""

    def _on_links_change(self, _change) -> None:
        if self.expand_toggle.value:
            self._render_detail_table()

    def _render_detail_table(self) -> None:
        self.detail_out.value = _render_detail_table_html(
            self.session, self.label, self.links_toggle.value
        )

    def _on_field_change(self, change) -> None:
        column = change["new"]
        if not column:
            return
        self._refresh_from_options(column)

    def _refresh_from_options(self, column: str) -> None:
        summary = self.session.field_summary(self.label, column)
        options = tuple(row["value"] for row in summary)
        previous_value = self.from_dropdown.value
        self.from_dropdown.options = options
        new_value = options[0] if options else None
        self.from_dropdown.value = new_value
        if new_value == previous_value:
            # Assigning the same value back doesn't fire the "value" observer below,
            # so the sample dropdown would otherwise go stale - refresh explicitly.
            self._refresh_sample_options(column, new_value)

    def _on_from_change(self, change) -> None:
        old_value = change["new"]
        if old_value is None or self.dropdown is None:
            self.sample_dropdown.options = [("All", None)]
            return
        self._refresh_sample_options(self.dropdown.value, old_value)

    def _refresh_sample_options(self, column: str, old_value) -> None:
        summary = self.session.field_summary(self.label, column)
        matched = next((row for row in summary if row["value"] == old_value), None)
        if not matched:
            self.sample_dropdown.options = [("All", None)]
            return
        df = self.session.datasets[self.label]
        options = [(f"All matching entries ({len(matched['row_indices'])})", None)]
        for row_index in matched["row_indices"]:
            row = df.loc[row_index]
            sample_id = row.get("sample_id", "") or "N/A"
            entry_id = row.get("_entry_id", "")
            mainfile_label = _mainfile_label(row.get("_mainfile", "") or "")
            # A sample can carry several entries of the same schema (e.g. multiple
            # Spin Coating steps) - always show the mainfile tag, not just when a
            # duplicate is detected, so the option a user picks is unambiguous.
            label = f"{sample_id} ({mainfile_label})" if mainfile_label else str(sample_id)
            options.append((label, entry_id))
        self.sample_dropdown.options = options

    def _on_correct_click(self, _button) -> None:
        self.correct_out.value = "<i>Working...</i>"
        column = self.dropdown.value
        old_value = self.from_dropdown.value
        new_value = self.to_input.value.strip()
        only_entry_id = self.sample_dropdown.value

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
                only_entry_id=only_entry_id,
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
    # status_out is always visible - it's the only feedback the user gets for "nothing
    # selected"/"still loading"/errors, so it must never be hidden behind the collapsed
    # debug accordion below.
    status_out = widgets.HTML(value="")
    progress_bar = widgets.IntProgress(min=0, max=1, value=0, layout=widgets.Layout(width="380px"))
    progress_bar.layout.display = "none"
    log_out = widgets.HTML(value="")
    log_accordion = widgets.Accordion(children=[log_out], selected_index=None)
    log_accordion.set_title(0, "Debug log (per-schema entry counts)")
    results_out = widgets.VBox([])

    def _status(text: str) -> None:
        status_out.value = f"<p style='margin:4px 0'>{text}</p>"

    def _log(text: str) -> None:
        log_out.value = _log_html(text)

    def _show_results(url_for_panels: str | None, token_for_panels: str | None) -> None:
        results_out.children = [
            FieldAuditPanel(session, label, url_for_panels, token_for_panels)
            for label in session.datasets
        ]

    def _on_load_progress(index: int, total: int, label: str) -> None:
        progress_bar.max = total
        progress_bar.value = index - 1
        _status(f"Loading schema {index}/{total}: {label}...")

    def _run_audit(batch_widget) -> None:
        batch_ids = list(batch_widget.value)
        results_out.children = []
        log_out.value = ""
        if not batch_ids:
            _status(
                "No batches selected - highlight one or more batches in the list "
                "above (Ctrl/Cmd-click for multiple), then click Load Data."
            )
            return
        _status(f"Resolving samples for {len(batch_ids)} batch(es)...")
        progress_bar.value = 0
        progress_bar.layout.display = None
        try:
            messages = session.load(url, token, batch_ids, progress_callback=_on_load_progress)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Failed to load batches %s", batch_ids)
            _status(f"<span style='color:#c0392b'>Failed to load batches: {exc}</span>")
            return
        finally:
            progress_bar.layout.display = "none"
        _status(
            f"Loaded {len(session.sample_ids)} sample(s) across {len(session.datasets)} schema(s)."
        )
        _log("<br>".join(f"{label}: {message}" for label, message in messages.items()))
        _show_results(url, token)

    demo_button = widgets.Button(
        description="Load demo data", button_style="warning", icon="database"
    )

    def _on_demo_click(_button) -> None:
        results_out.children = []
        log_out.value = ""
        try:
            loaded = session.load_offline(demo_fixture_path)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Failed to load demo fixture %s", demo_fixture_path)
            _status(f"<span style='color:#c0392b'>Failed to load demo data: {exc}</span>")
            return
        if not loaded:
            _status("Demo fixture contained no data.")
            return
        _status(f"Loaded demo data: {len(session.sample_ids)} samples.")
        _show_results(None, None)

    demo_button.on_click(_on_demo_click)

    return widgets.VBox(
        [
            widgets.HTML("<h3 style='margin:4px 0'>Batch Selection</h3>"),
            demo_button,
            create_batch_selection(url, token, _run_audit),
            status_out,
            progress_bar,
            log_accordion,
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
