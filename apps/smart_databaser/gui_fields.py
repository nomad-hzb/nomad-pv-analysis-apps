# gui_components.py
# All ipywidgets code. No NOMAD/API calls or Excel generation logic lives here - it all
# funnels through data_manager.py, which owns ExperimentState and never imports a widget
# library.

import html
import logging
import os
from datetime import datetime

import ipywidgets as widgets
from data_manager import (
    AVAILABLE_PROCESSES,
    DATE_FIELD_FORMATS,
    EXPERIMENT_INFO_COMPUTED_KEYS,
    ExperimentState,
    NomadSessionCache,
    ProcessFieldSpec,
    ProcessInstance,
    find_forbidden_characters,
    preview_value_for_field,
    relevant_field_specs,
    set_field_manual,
    set_field_varies,
)

logger = logging.getLogger(__name__)


def _current_user_name() -> str:
    return os.environ.get("NOMAD_CLIENT_USER", "").strip() or "Unknown User"


def _quick_fill_button_for(field_key: str, value_widget: widgets.Text) -> widgets.Button | None:
    """Shared by _FieldRow (non-varying fields) and VaryingFieldsMatrix's
    per-sample cells (varying fields moved into the matrix) - a "Today" button for
    Date/Datetime fields (see data_manager.DATE_FIELD_FORMATS), a "Me" button for
    Operator. Writes straight into value_widget.value, which fires the same observe chain
    a real keystroke would (forbidden-character guard, on_value_change, ...). Returns
    None (no button) for every other field key."""
    date_format = DATE_FIELD_FORMATS.get(field_key)
    if date_format is not None:

        def _fill_today(_button, widget=value_widget, fmt=date_format):
            widget.value = datetime.now().strftime(fmt)

        button = widgets.Button(description="Today", layout=widgets.Layout(width="55px"))
        button.on_click(_fill_today)
        return button

    if field_key == "Operator":

        def _fill_operator(_button, widget=value_widget):
            widget.value = _current_user_name()

        button = widgets.Button(description="Me", layout=widgets.Layout(width="45px"))
        button.on_click(_fill_operator)
        return button

    return None


def _provenance_summary_html(specs) -> widgets.HTML:
    """One 'Sourced from Batch X, Sample Y' summary line for the whole panel, instead of
    repeating the same tag on every autofilled row - in practice every field in one
    process/Experiment Info panel shares the same source (one process instance sources
    from one batch/occurrence at a time), so a per-row repeat was pure noise. Picks the
    first non-manual provenance found among the given specs."""
    for spec in specs:
        if spec.provenance is not None and spec.provenance.source != "manual":
            tag = f"Sourced from Batch {html.escape(str(spec.provenance.source_batch_id))}"
            if spec.provenance.source_sample_id:
                tag += f", Sample {html.escape(str(spec.provenance.source_sample_id))}"
            return widgets.HTML(value=f"<span style='color:#7f8c8d; font-size:11px;'>{tag}</span>")
    return widgets.HTML(value="")


def _outlier_flag_html(spec: ProcessFieldSpec) -> widgets.HTML:
    if not spec.is_outlier:
        return widgets.HTML(value="")
    return widgets.HTML(
        value=(
            "<span style='color:#c0392b; font-size:11px;' "
            "title='Autofilled value differs substantially from other samples at this "
            "same step - see the legend above.'>&#9888; outlier</span>"
        )
    )


def _forbidden_chars_message(forbidden: list) -> str:
    chars = " ".join(forbidden)
    return (
        f"<span style='color:#c0392b; font-size:11px;'>Not saved - "
        f"<code>{chars}</code> not allowed here (breaks IDs/file names downstream).</span>"
    )


def _guard_forbidden_characters(text_widget: widgets.Text, warning_html: widgets.HTML, on_valid):
    """Shared by every data-value Text widget in this app (field rows, matrix cells) -
    NOT the Variation template pattern (needs a backslash) and NOT Date/Datetime fields
    (see DATE_FIELD_FORMATS - "%d.%m.%Y %H:%M:%S" legitimately needs colons, and neither
    field ever feeds into compute_nomad_id/build_experiment_filename anyway, so there's
    nothing downstream for a colon to break here). Rejects (does not persist) any value
    containing a data_manager.FORBIDDEN_VALUE_CHARACTERS character: shows a red border +
    warning message instead of calling on_valid, so nothing downstream (Excel generation,
    Nomad ID) ever sees it. The widget still shows whatever the user typed - only the
    underlying state write is skipped - so typing isn't fought mid-keystroke.

    Returns the observer callback so a caller that later needs to write into
    text_widget.value programmatically (e.g. _FieldRow syncing from external state) can
    unobserve/reobserve around that write instead of looping back through on_valid."""

    def _on_change(change):
        new_value = change["new"]
        forbidden = find_forbidden_characters(new_value)
        if forbidden:
            text_widget.layout.border = "2px solid #c0392b"
            warning_html.value = _forbidden_chars_message(forbidden)
            return
        text_widget.layout.border = ""
        warning_html.value = ""
        on_valid(new_value)

    text_widget.observe(_on_change, names="value")
    return _on_change


def _sync_widget_value(widget: widgets.Widget, observer, new_value) -> None:
    """Writes widget.value only if it actually differs from new_value, unobserving/
    reobserving `observer` (whatever the widget's own observe("value") callback was)
    around the write. Used for any persistent widget - Text (_FieldRow, matrix cells),
    Dropdown, BoundedIntText, Checkbox (_ProcessRow) - that needs to be brought back in
    sync with state that changed some other way than this exact widget's own edit -
    without the unobserve/reobserve, the write would loop back through the same on_valid/
    on_change chain a second time for a value that has already been persisted."""
    if widget.value == new_value:
        return
    if observer is not None:
        widget.unobserve(observer, names="value")
    widget.value = new_value
    if observer is not None:
        widget.observe(observer, names="value")


class _FieldRow(widgets.HBox):
    """Shared by ProcessFieldsPanel and ExperimentInfoPanel: a 'varies' checkbox, the
    field label (with a trailing '*' when required_for_progress), a value input (with a
    quick-fill button for Date/Datetime/Operator fields), and an 'outlier' flag when
    flagged. Non-varying fields are edited here directly; once a field is marked varying,
    its value moves to VaryingFieldsMatrix instead (edited per-sample there). Every
    autofilled field stays editable here, per the product requirement that autofill never
    locks a field.

    Built once per field_key and refreshed in place via update() afterwards, instead of
    being torn down and rebuilt on every edit. The panels used to call a plain
    `_build_field_row()` function inside their `_render()`, which - since editing any one
    field re-renders the whole panel - discarded and recreated every row's Checkbox/Text
    widgets on every keystroke-commit. That destroyed the DOM element the user had just
    clicked/tabbed into out from under them (needing a second click, dropping the first
    characters typed into the next field) and left tab order to whatever order the
    recreated widgets happened to re-attach in. Keeping the same widget instances alive
    and only mutating the traits that actually changed avoids both.

    required_for_progress is no longer editable from this row (see
    config/required_fields.json) - it's shown as a '*' after the label instead of a
    checkbox, per the product ask to keep "what's required" out of the day-to-day UI."""

    def __init__(self, field_key: str, spec: ProcessFieldSpec, on_varies_change, on_value_change):
        self.field_key = field_key
        self._on_varies_change = on_varies_change
        self._on_value_change = on_value_change
        self._varies = spec.varies

        self.varies_checkbox = widgets.Checkbox(
            value=spec.varies, indent=False, layout=widgets.Layout(width="24px")
        )
        # Not in the Tab cycle: with one checkbox ahead of every value input, leaving it
        # tabbable meant Tab-ing out of one field landed on the NEXT field's checkbox
        # instead of the next field itself. Still reachable by click or Shift+Tab.
        self.varies_checkbox.tabbable = False
        self.varies_checkbox.observe(self._handle_varies_change, names="value")

        self.label = widgets.Label(layout=widgets.Layout(width="220px"))
        self.outlier_html = widgets.HTML(value="")
        self.warning_html = widgets.HTML(value="")
        self.value_widget: widgets.Widget | None = None
        self.quick_fill_button: widgets.Button | None = None
        self._value_observer = None

        super().__init__([], layout=widgets.Layout(align_items="center", margin="1px 0"))
        self.update(spec)

    def _handle_varies_change(self, change) -> None:
        self._on_varies_change(self.field_key, change["new"])

    def _handle_value_change(self, new_value) -> None:
        self._on_value_change(self.field_key, new_value)

    def update(self, spec: ProcessFieldSpec, preview_value=None) -> None:
        """`preview_value`, when the field is still empty, is shown as the input's
        placeholder (native greyed-out text, not an official value) - a hint of what the
        active source batch would supply if adopted; falls back to a generic "value"
        placeholder when no preview is available."""
        self.label.value = f"{self.field_key} *" if spec.required_for_progress else self.field_key
        self.outlier_html.value = _outlier_flag_html(spec).value
        if self.varies_checkbox.value != spec.varies:
            self.varies_checkbox.value = spec.varies

        if self.value_widget is None or spec.varies != self._varies:
            self._varies = spec.varies
            self._rebuild_value_cell(spec, preview_value)
        elif not spec.varies:
            self._sync_value_widget(spec, preview_value)

        row_children = [self.varies_checkbox, self.label, self.value_widget]
        if self.quick_fill_button is not None:
            row_children.append(self.quick_fill_button)
        row_children.append(self.outlier_html)
        row_children.append(self.warning_html)
        self.children = row_children

    def _rebuild_value_cell(self, spec: ProcessFieldSpec, preview_value) -> None:
        self.warning_html.value = ""
        self._value_observer = None
        if spec.varies:
            self.value_widget = widgets.HTML(value="<i>varies - see matrix</i>")
            self.quick_fill_button = None
            return

        placeholder = "value" if preview_value is None else str(preview_value)
        self.value_widget = widgets.Text(
            value="" if spec.value is None else str(spec.value),
            placeholder=placeholder,
            layout=widgets.Layout(width="200px"),
            # continuous_update=False: on_value_change writes into state and refreshes
            # the panel's rows; committing on blur/Enter instead of every keystroke keeps
            # that from firing (and racing the browser's own typing/IME state) on every
            # character - see the class docstring for what that broke.
            continuous_update=False,
        )
        if self.field_key in DATE_FIELD_FORMATS:
            # Exempt: colons in "HH:MM:SS" are legitimate here, and this field never
            # feeds into an ID/filename - see _guard_forbidden_characters' docstring.
            def _observer(change):
                self._handle_value_change(change["new"])

            self.value_widget.observe(_observer, names="value")
            self._value_observer = _observer
        else:
            self._value_observer = _guard_forbidden_characters(
                self.value_widget, self.warning_html, self._handle_value_change
            )

        self.quick_fill_button = _quick_fill_button_for(self.field_key, self.value_widget)

    def _sync_value_widget(self, spec: ProcessFieldSpec, preview_value) -> None:
        placeholder = "value" if preview_value is None else str(preview_value)
        if self.value_widget.placeholder != placeholder:
            self.value_widget.placeholder = placeholder
        new_value = "" if spec.value is None else str(spec.value)
        _sync_widget_value(self.value_widget, self._value_observer, new_value)


_REAL_PROCESS_TYPES = [p for p in AVAILABLE_PROCESSES if p != "Experiment Info"]


class ProcessFieldsPanel(widgets.VBox):
    """Renders every field of one ProcessInstance: a 'varies' checkbox, the field label,
    a value input, and a provenance tag when autofilled. Non-varying fields are edited
    here directly; once a field is marked varying, its value moves to
    VaryingFieldsMatrix instead (edited per-sample there) - this panel just shows a
    placeholder for it. Every autofilled field stays editable here, per the product
    requirement that autofill never locks a field."""

    def __init__(
        self,
        state: ExperimentState,
        process: ProcessInstance,
        cache: NomadSessionCache | None = None,
        on_change=None,
    ):
        self.state = state
        self.process = process
        self.cache = cache
        self.on_change = on_change
        self._rows: dict[str, _FieldRow] = {}
        self._provenance_widget = widgets.HTML(value="")
        super().__init__([])
        self._render()

    def _notify_change(self) -> None:
        self._render()
        if self.on_change:
            self.on_change()

    def refresh(self) -> None:
        """Re-renders from the current state without treating it as a local edit (no
        on_change) - call when ProcessSequenceBuilder reuses this same panel instance
        across its own re-renders, so it still picks up state changed by something other
        than this panel's own rows (e.g. rebuild_field_specs adding a column after a
        process-type change)."""
        self._render()

    def _preview_for(self, field_key: str, spec: ProcessFieldSpec):
        if spec.is_filled() or self.cache is None:
            return None
        return preview_value_for_field(self.state, self.process, field_key, self.cache)

    def _render(self) -> None:
        # relevant_field_specs, not self.process.field_specs directly: field_specs is
        # additive-only (a checkbox-gated field never gets deleted just because the
        # checkbox was unchecked again - see that function's docstring), so this filters
        # back down to only what the process's CURRENT config actually has a column for.
        visible_specs = relevant_field_specs(self.process)
        self._provenance_widget.value = _provenance_summary_html(visible_specs.values()).value

        # Row widgets are kept alive across renders (see _FieldRow) - only the field set
        # actually changing (added/removed field) touches self.children; a plain value or
        # varies edit just updates the existing rows' traits in place.
        for field_key in list(self._rows):
            if field_key not in visible_specs:
                del self._rows[field_key]
        for field_key, spec in visible_specs.items():
            row = self._rows.get(field_key)
            if row is None:
                row = _FieldRow(field_key, spec, self._on_varies_change, self._on_value_change)
                self._rows[field_key] = row
            row.update(spec, preview_value=self._preview_for(field_key, spec))

        self.children = [self._provenance_widget, *(self._rows[key] for key in visible_specs)]

    def _on_varies_change(self, field_key: str, varies: bool) -> None:
        spec = self.process.field_specs[field_key]
        set_field_varies(spec, varies, self.state.sample_numbers())
        self._notify_change()

    def _on_value_change(self, field_key: str, new_value) -> None:
        spec = self.process.field_specs[field_key]
        set_field_manual(spec, new_value)
        self._notify_change()


class ExperimentInfoPanel(widgets.VBox):
    """Same shape as ProcessFieldsPanel but for state.experiment_info_fields. Skips
    "Variation" (computed only, edited via VaryingFieldsMatrix), "Nomad ID" and "Sample"
    (always auto-derived from sample_number/child_index at Excel-generation time - see
    generate_full_workbook). "Number of pixels"/"Pixel area" are ordinary fields here
    like any other - they used to be gated behind a separate per-CHILD-row mechanism, but
    that had no UI to actually edit it (the per-sample child-row table was removed in an
    earlier round) and, per a real exported file, both fields are in practice a single
    constant value applying to the whole batch, not something that varies per diced
    pixel - see data_manager's git history around PixelFieldSpec's removal."""

    def __init__(self, state: ExperimentState, on_change=None):
        self.state = state
        self.on_change = on_change
        self._rows: dict[str, _FieldRow] = {}
        self._provenance_widget = widgets.HTML(value="")
        super().__init__([])
        self._render()

    def _notify_change(self) -> None:
        self._render()
        if self.on_change:
            self.on_change()

    def refresh(self) -> None:
        """See ProcessFieldsPanel.refresh - re-renders without treating it as a local
        edit, for when ProcessSequenceBuilder reuses this same panel instance."""
        self._render()

    def _render(self) -> None:
        relevant = {
            field_key: spec
            for field_key, spec in self.state.experiment_info_fields.items()
            if field_key not in EXPERIMENT_INFO_COMPUTED_KEYS
        }
        self._provenance_widget.value = _provenance_summary_html(relevant.values()).value

        # See ProcessFieldsPanel._render: rows are kept alive across renders so a plain
        # value/varies edit never tears down and rebuilds every field's widgets.
        for field_key in list(self._rows):
            if field_key not in relevant:
                del self._rows[field_key]
        for field_key, spec in relevant.items():
            row = self._rows.get(field_key)
            if row is None:
                row = _FieldRow(field_key, spec, self._on_varies_change, self._on_value_change)
                self._rows[field_key] = row
            row.update(spec)

        self.children = [self._provenance_widget, *(self._rows[key] for key in relevant)]

    def _on_varies_change(self, field_key: str, varies: bool) -> None:
        spec = self.state.experiment_info_fields[field_key]
        set_field_varies(spec, varies, self.state.sample_numbers())
        self._notify_change()

    def _on_value_change(self, field_key: str, new_value) -> None:
        spec = self.state.experiment_info_fields[field_key]
        set_field_manual(spec, new_value)
        self._notify_change()


def _create_batch_picker(
    cache: NomadSessionCache,
    url: str,
    token: str,
    description: str,
    on_load,
    button_label: str = "Apply",
):
    """Mirrors hysprint_utils.batch_selection.create_batch_selection's shape (searchable
    SelectMultiple + load button via WidgetFactory) - not reused directly since
    batch_selection.py must not be edited and this app needs single-batch-selection
    semantics (whole-experiment template, per-process override) rather than that helper's
    multi-batch load-and-visualize flow. Uses NomadSessionCache.get_batch_ids() so several
    pickers open in one session share one get_batch_ids() call."""
    from natsort import natsorted

    from hysprint_utils.plotting_utils import WidgetFactory

    batch_ids_list = natsorted(cache.get_batch_ids(url, token))

    selector = widgets.SelectMultiple(
        options=batch_ids_list,
        description=description,
        layout=widgets.Layout(width="320px", height="120px"),
    )
    search_field = widgets.Text(description="Search")
    load_button = WidgetFactory.create_button(description=button_label, button_style="primary")
    status = widgets.HTML(value="")

    def on_search(change):
        filtered = natsorted(
            [b for b in batch_ids_list if search_field.value.strip().lower() in b.lower()]
        )
        selector.options = filtered

    search_field.observe(on_search, names="value")

    def on_click(_button):
        if not selector.value:
            status.value = "<span style='color:#c0392b'>Pick one batch first.</span>"
            return
        batch_id = selector.value[0]
        warning = (
            f"<span style='color:#c0392b'>Multiple selected - using {batch_id} only.</span><br>"
            if len(selector.value) > 1
            else ""
        )
        # Set BEFORE the (possibly slow, network-bound) on_load call below, not after -
        # ipywidgets flushes this to the browser immediately even though the rest of this
        # handler runs synchronously and blocks the kernel until on_load returns.
        status.value = warning + "<i>Working...</i>"
        try:
            result_message = on_load(batch_id)
        except Exception as exc:
            status.value = (
                warning + f"<span style='color:#c0392b'>Failed: {html.escape(str(exc))}</span>"
            )
            return
        status.value = warning + (result_message or "<span style='color:#2c7a4b'>Done.</span>")

    load_button.on_click(on_click)

    return widgets.VBox([search_field, selector, load_button, status])


def _progress_html(filled: int, total: int) -> str:
    pct = round(100 * filled / total) if total else 0
    return f"<span style='color:#7f8c8d; font-size:12px;'>{pct}% ({filled}/{total})</span>"


def _field_row_caption() -> widgets.HTML:
    return widgets.HTML(
        value=(
            "<i style='color:#7f8c8d; font-size:11px;'>"
            "Check 'varies' if a field's value differs per sample - it moves into the "
            "Varying Fields matrix below and stays editable there.<br>"
            "<b>*</b> after a field name = required (counts toward the completion "
            "bar/nudge review below - edit config/required_fields.json to change this, "
            "there's no in-app toggle).<br>"
            "<span style='color:#c0392b'>&#9888; outlier</span> = an autofilled value "
            "differs substantially from other samples at the same step - worth a second "
            "look, not necessarily wrong."
            "</i>"
        )
    )
