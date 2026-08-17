# gui_components.py
# All ipywidgets code. No NOMAD/API calls or Excel generation logic lives here - it all
# funnels through data_manager.py, which owns ExperimentState and never imports a widget
# library.

import base64
import logging
import os
import random
from datetime import datetime

import ipywidgets as widgets
from data_manager import (
    ATMOSPHERIC_CONFIG_KEY,
    AVAILABLE_PROCESSES,
    BOOLEAN_CONFIG_FIELDS,
    CONFIGURABLE_PROCESS_TYPES,
    DATE_FIELD_FORMATS,
    EXPERIMENT_INFO_COMPUTED_KEYS,
    NUMERIC_CONFIG_FIELDS,
    ExperimentState,
    NomadSessionCache,
    NudgeItem,
    ProcessFieldSpec,
    ProcessInstance,
    apply_process_override,
    apply_variation_template,
    apply_whole_experiment_template,
    auto_fill_variation_column,
    build_experiment_filename,
    build_field_mapping_debug_report,
    build_missing_fields_summary,
    build_nudge_queue,
    clear_process_override,
    compute_experiment_info_progress,
    compute_experiment_progress,
    compute_process_progress,
    compute_sample_set_split,
    default_config_for,
    fill_all_date_and_operator_fields,
    find_forbidden_characters,
    generate_full_workbook,
    iter_varying_fields,
    list_process_occurrences,
    missing_critical_fields,
    populate_column_from_first,
    preview_value_for_field,
    progress_band,
    rebuild_field_specs,
    relevant_field_specs,
    set_field_manual,
    set_field_varies,
    steps_for_process_type,
    upload_experiment_excel,
    workbook_to_bytes,
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


def create_quick_fill_all_button(state: ExperimentState, on_change=None) -> widgets.VBox:
    """One bulk action covering every 'Today'/'Me' quick-fill button in the whole
    experiment at once - product ask: filling each Date/Datetime/Operator field one row
    at a time was tedious once there were several processes. Calls
    data_manager.fill_all_date_and_operator_fields with a single shared timestamp/name so
    every field ends up consistent, including per-sample slots on fields already marked
    varying. Always overwrites (same as the individual per-field buttons) - not a
    no-clobber autofill."""
    button = widgets.Button(
        description="Fill all Date/Operator fields",
        button_style="info",
        layout=widgets.Layout(width="220px"),
    )
    status = widgets.HTML(value="")

    def on_click(_button):
        date_count, operator_count = fill_all_date_and_operator_fields(state, _current_user_name())
        status.value = (
            f"<span style='color:#2c7a4b'>Filled {date_count} date field(s) and "
            f"{operator_count} operator field(s).</span>"
        )
        if on_change:
            on_change()

    button.on_click(on_click)
    return widgets.VBox([button, status])


def _provenance_summary_html(specs) -> widgets.HTML:
    """One 'Sourced from Batch X, Sample Y' summary line for the whole panel, instead of
    repeating the same tag on every autofilled row - in practice every field in one
    process/Experiment Info panel shares the same source (one process instance sources
    from one batch/occurrence at a time), so a per-row repeat was pure noise. Picks the
    first non-manual provenance found among the given specs."""
    for spec in specs:
        if spec.provenance is not None and spec.provenance.source != "manual":
            tag = f"Sourced from Batch {spec.provenance.source_batch_id}"
            if spec.provenance.source_sample_id:
                tag += f", Sample {spec.provenance.source_sample_id}"
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


class SampleSetupPanel(widgets.VBox):
    """Setup-time sample/Subbatch configuration - distinct from the auto-computed
    Variation LABEL in VaryingFieldsMatrix (see the addendum: 'Number of samples' /
    'Number of variations' are setup-time inputs, not the same concept). Internally, a
    "Subbatch" is still ExperimentState/SamplePlan's `variation_group_index` - only the
    UI-facing wording changed (product ask: first 'group' -> 'set' since 'group' read as
    confusing, then 'set' -> 'Subbatch' since the Subbatch Excel column is always exactly
    this value, 1-based - see data_manager.subbatch_for_sample). 'Apply Sample Setup' only
    ADDS samples up to each Subbatch's requested count; it never removes existing
    samples, so re-clicking after adjusting counts never destroys already-configured
    per-sample data - matching this app's no-clobber philosophy elsewhere. Per-sample
    child-row (diced pixel) configuration is intentionally not exposed here for now - it
    only applies to a minority of experiments and was confusing alongside Subbatch
    assignment; SamplePlan.child_count still exists and defaults to 0. The per-sample
    list/remove-button table was removed too, per the same "confusing, doesn't make sense
    here" feedback - individual samples still exist on ExperimentState.samples and remain
    removable programmatically (ExperimentState.remove_sample), just not from this
    panel."""

    def __init__(self, state: ExperimentState, on_change=None):
        self.state = state
        self.on_change = on_change
        self.total_samples_input = widgets.BoundedIntText(
            value=16,
            min=0,
            max=1000,
            description="Total samples:",
            style={"description_width": "initial"},
            # continuous_update=False: every change rebuilds sets_inputs_box's per-Subbatch
            # widgets from scratch (_render_set_inputs) - see _FieldRow's
            # value_widget for why firing that on every keystroke, not on blur/Enter,
            # caused typing lag/dropped digits.
            continuous_update=False,
        )
        self.set_count_input = widgets.BoundedIntText(
            value=4,
            min=1,
            max=50,
            description="Variation Subbatch:",
            style={"description_width": "initial"},
            continuous_update=False,
        )
        self.sets_inputs_box = widgets.VBox([])
        self.apply_button = widgets.Button(description="Apply Sample Setup", button_style="primary")

        self.set_count_input.observe(self._on_settings_change, names="value")
        self.total_samples_input.observe(self._on_settings_change, names="value")
        self.apply_button.on_click(self._on_apply)

        caption = widgets.HTML(
            value=(
                "<i style='color:#7f8c8d; font-size:11px;'>Set the total sample count and "
                "how many variation Subbatches you have, then Apply - samples are split as "
                "evenly as possible across Subbatches (e.g. 15 samples / 4 Subbatches "
                "&rarr; 4, 4, 4, 3). Adjust an individual Subbatch's count below before "
                "re-applying if you want a different split. Each sample's 'Subbatch' Excel "
                "value is always its Subbatch number (1-based) - never typed manually.</i>"
            )
        )

        super().__init__(
            [
                caption,
                self.total_samples_input,
                self.set_count_input,
                self.apply_button,
                self.sets_inputs_box,
            ]
        )
        self._render_set_inputs()

    def _render_set_inputs(self) -> None:
        split = compute_sample_set_split(self.total_samples_input.value, self.set_count_input.value)
        rows = []
        for set_index in range(self.set_count_input.value):
            existing_count = sum(
                1 for s in self.state.samples if s.variation_group_index == set_index
            )
            default_value = split[set_index] if set_index < len(split) else 0
            count_input = widgets.BoundedIntText(
                value=max(existing_count, default_value),
                min=0,
                max=200,
                description=f"Subbatch {set_index + 1} samples:",
                style={"description_width": "initial"},
                layout=widgets.Layout(margin="0 0 0 20px"),
                continuous_update=False,
            )
            count_input._set_index = set_index
            rows.append(count_input)
        self.sets_inputs_box.children = rows

    def _on_settings_change(self, change) -> None:
        self._render_set_inputs()

    def _on_apply(self, _button) -> None:
        self.apply_sample_setup()

    def apply_sample_setup(self) -> None:
        """The 'Apply Sample Setup' button's action, exposed as a public method so
        app.py can trigger the default sample set once on page load - product ask, since
        the Varying Fields table (and everything downstream) previously stayed empty
        until a user noticed and clicked the button themselves."""
        for count_input in self.sets_inputs_box.children:
            set_index = count_input._set_index
            existing = [s for s in self.state.samples if s.variation_group_index == set_index]
            needed = count_input.value - len(existing)
            for _ in range(max(0, needed)):
                self.state.add_sample(variation_group_index=set_index)
        if self.on_change:
            self.on_change()


def _build_download_link_html(state: ExperimentState) -> tuple[str, bytes, str]:
    """(link_html, excel_bytes, filename) - shared by create_download_button and
    create_finish_section so the base64 download-link logic (matching Excel_creator's own
    voila_experiment_app.py _create_download_link pattern) isn't duplicated."""
    workbook = generate_full_workbook(state)
    data = workbook_to_bytes(workbook)
    filename = build_experiment_filename()
    b64_data = base64.b64encode(data).decode()
    mime = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    link_html = (
        f'<a download="{filename}" href="data:{mime};base64,{b64_data}">'
        f"Click here to download the experiment file ({filename})</a>"
    )
    return link_html, data, filename


def create_download_button(state: ExperimentState) -> widgets.VBox:
    """Client-side base64 download link - no server-side filesystem write needed under
    Voila."""
    button = widgets.Button(description="Download Excel", button_style="success")
    output_area = widgets.HTML(value="")

    def on_click(_button):
        link_html, _data, _filename = _build_download_link_html(state)
        output_area.value = link_html

    button.on_click(on_click)
    return widgets.VBox([button, output_area])


def create_finish_section(
    state: ExperimentState,
    url: str,
    token: str,
    cache: NomadSessionCache,
    progress_bar: widgets.Widget | None = None,
) -> widgets.VBox:
    """Three explicit end-of-workflow actions, not one combined action, per the product
    requirement: 'Download only', 'Upload only', 'Download + Upload'. The upload target
    is picked from the user's own already-created NOMAD upload (get_all_uploads via
    NomadSessionCache.get_uploads) - this app never auto-creates an upload, keeping the
    manual 'create the upload in the NOMAD web GUI first' step.

    `progress_bar` (typically a ProgressBarWidget), if given, is displayed directly above
    the three action buttons - product ask: the completion bar reads better right where
    the user is about to finish, not up at the top of the page.

    By default, clicking any of the three finish buttons opens the nudge review flow
    first and the action itself only runs once the user clicks 'Continue' beneath it -
    the eventual intent is that nudge review is mandatory before finishing. The 'Skip
    nudge review' checkbox (unchecked by default) is a testing-only escape hatch back to
    the old immediate behavior.

    Batch/Project_Name are checked BEFORE any of that (data_manager.
    missing_critical_fields) and hard-block all three actions, unconditionally - not
    skippable via the nudge checkbox, since they're baked into every sample's Nomad ID
    (compute_nomad_id) and a missing one means the exported file's own ID scheme is
    already broken, whether it's downloaded or uploaded.

    IMPORTANT: upload_experiment_excel has not been verified against the real NOMAD API
    as of this writing - see tests/live/test_smart_databaser_upload.py, which must be run
    manually against a disposable upload before trusting this against a real one."""
    uploads = cache.get_uploads(url, token)
    upload_options = [("Select an upload...", None)] + [
        (f"{u.get('upload_name') or u['upload_id']} ({u['upload_id']})", u["upload_id"])
        for u in uploads
    ]
    upload_dropdown = widgets.Dropdown(
        options=upload_options,
        description="Target upload:",
        style={"description_width": "initial"},
        layout=widgets.Layout(width="420px"),
    )

    skip_nudge_checkbox = widgets.Checkbox(
        value=False, indent=False, description="Skip nudge review (testing only)"
    )
    skip_nudge_caption = widgets.HTML(
        value=(
            "<i style='color:#7f8c8d; font-size:11px;'>By default you'll be guided "
            "through any missing/outlier fields before finishing. Check this to skip "
            "straight to Download/Upload while testing.</i>"
        )
    )

    status_output = widgets.HTML(value="")
    nudge_area = widgets.VBox([])

    def do_upload(data: bytes, filename: str) -> bool:
        if not upload_dropdown.value:
            status_output.value += (
                "<br><span style='color:#c0392b'>Pick a target upload first.</span>"
            )
            return False
        try:
            upload_experiment_excel(url, token, upload_dropdown.value, filename, data)
            status_output.value += (
                f"<br><span style='color:#2c7a4b'>Uploaded {filename} to "
                f"{upload_dropdown.value}.</span>"
            )
            return True
        except Exception as exc:
            status_output.value += f"<br><span style='color:#c0392b'>Upload failed: {exc}</span>"
            return False

    def run_download_only():
        link_html, _data, _filename = _build_download_link_html(state)
        status_output.value = link_html

    def run_upload_only():
        status_output.value = ""
        _link_html, data, filename = _build_download_link_html(state)
        do_upload(data, filename)

    def run_download_and_upload():
        link_html, data, filename = _build_download_link_html(state)
        status_output.value = link_html
        do_upload(data, filename)

    def start_action(action_name: str, run) -> None:
        """Gate `run` behind the critical-fields check (always, cannot be skipped), then
        the nudge flow unless skip_nudge_checkbox is checked."""
        missing = missing_critical_fields(state)
        if missing:
            nudge_area.children = []
            fields = " and ".join(missing)
            verb = "is" if len(missing) == 1 else "are"
            pronoun = "it" if len(missing) == 1 else "them"
            status_output.value = (
                f"<div style='color:#c0392b; font-weight:bold; border:2px solid "
                f"#c0392b; padding:8px; margin:4px 0;'>&#9888; Cannot {action_name.lower()} "
                f"- {fields} {verb} missing from Experiment Info. {fields} {verb} baked "
                f"into every sample's Nomad ID, so the exported file would already be "
                f"broken - fill {pronoun} in above first.</div>"
            )
            return
        status_output.value = ""

        if skip_nudge_checkbox.value:
            nudge_area.children = []
            run()
            return

        flow = NudgePopupFlow(state)

        def on_continue(_button):
            nudge_area.children = []
            run()

        continue_button = widgets.Button(
            description=f"Continue with {action_name}", button_style="primary"
        )
        continue_button.on_click(on_continue)
        nudge_area.children = [flow, continue_button]

    def on_download_only(_button):
        start_action("Download", run_download_only)

    def on_upload_only(_button):
        start_action("Upload", run_upload_only)

    def on_download_and_upload(_button):
        start_action("Download + Upload", run_download_and_upload)

    download_button = widgets.Button(description="Download only", button_style="success")
    download_button.on_click(on_download_only)

    upload_button = widgets.Button(description="Upload only", button_style="info")
    upload_button.on_click(on_upload_only)

    download_and_upload_button = widgets.Button(
        description="Download + Upload", button_style="warning"
    )
    download_and_upload_button.on_click(on_download_and_upload)

    children = [
        skip_nudge_checkbox,
        skip_nudge_caption,
        upload_dropdown,
    ]
    if progress_bar is not None:
        children.append(progress_bar)
    children.extend(
        [
            widgets.HBox([download_button, upload_button, download_and_upload_button]),
            nudge_area,
            status_output,
        ]
    )
    return widgets.VBox(children)


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
            status.value = warning + f"<span style='color:#c0392b'>Failed: {exc}</span>"
            return
        status.value = warning + (result_message or "<span style='color:#2c7a4b'>Done.</span>")

    load_button.on_click(on_click)

    return widgets.VBox([search_field, selector, load_button, status])


def create_whole_experiment_template_picker(
    state: ExperimentState, url: str, token: str, cache: NomadSessionCache, on_change=None
) -> widgets.VBox:
    """Picking a batch here REPLACES the current process sequence: that batch's own steps
    are used to populate a full sequence here, fully filled in (see
    apply_whole_experiment_template) - re-picking replaces the sequence again, every
    time. When a sourced field varies across the batch's own samples, the first sample's
    value is used (see fetch_process_field_values's occurrence-based step lookup). This
    same batch is also what each process row's 'Adopt from template batch' button (see
    ProcessSequenceBuilder) pulls from for a single process.

    This is the slowest action in the app (one or more real HTTP calls, then autofill
    across every process in the replicated sequence) - shows a progress bar across the
    per-process autofill phase (see apply_whole_experiment_template's progress_callback),
    on top of _create_batch_picker's own "Working..." indicator for the initial batch
    fetch."""

    progress_bar = widgets.FloatProgress(
        min=0,
        max=1,
        value=0,
        bar_style="info",
        layout=widgets.Layout(width="300px", visibility="hidden"),
    )
    progress_label = widgets.Label(value="")

    def on_progress(done: int, total: int) -> None:
        progress_bar.layout.visibility = "visible"
        progress_bar.max = max(total, 1)
        progress_bar.value = done
        progress_label.value = f"{done} / {total} processes"

    def on_load(batch_id):
        progress_bar.value = 0
        written_by_process = apply_whole_experiment_template(
            state, url, token, cache, batch_id, progress_callback=on_progress
        )
        progress_bar.layout.visibility = "hidden"
        progress_label.value = ""
        if on_change:
            on_change()
        process_count = len(state.process_sequence)
        field_count = sum(written_by_process.values())
        return (
            f"<span style='color:#2c7a4b'>Replicated {process_count} process(es) from "
            f"Batch {batch_id}, filled {field_count} field(s).</span>"
        )

    header = widgets.HTML(value="<h4>Whole-experiment Template</h4>")
    caption = widgets.HTML(
        value=(
            "<i style='color:#7f8c8d; font-size:11px;'>Pick a past batch to REPLACE your "
            "current process sequence: its steps populate a full sequence here, fully "
            "filled in (if a value varied across that batch's samples, its first "
            "sample's value is used). Everything stays editable afterwards - re-picking "
            "replaces the sequence again. <b>This can take a while for batches with many "
            "steps - please be patient.</b></i>"
        )
    )
    return widgets.VBox(
        [
            header,
            caption,
            _create_batch_picker(
                cache, url, token, "Template batch", on_load, button_label="Replicate Experiment"
            ),
            widgets.HBox([progress_bar, progress_label]),
        ]
    )


def _split_varying_field_label(combined_label: str) -> tuple[str, str]:
    """iter_varying_fields() labels are always '<process label> - <field key>' (see its
    docstring); process labels never contain ' - ' themselves, so a first-occurrence split
    reliably separates them for the matrix's two-line header."""
    process_part, _, field_part = combined_label.partition(" - ")
    return (process_part, field_part) if field_part else ("", process_part)


class _MatrixCell:
    """One (sample, varying-field) cell in VaryingFieldsMatrix: a persistent Text input
    (+ optional quick-fill button, for a Date/Datetime/Operator field moved into the
    matrix - see _quick_fill_button_for's docstring for why it keeps the button), kept
    alive across matrix re-renders instead of rebuilt on every edit. Mirrors _FieldRow;
    see its class docstring for why. Here the win is much bigger: a per-keystroke change
    used to rebuild the ENTIRE matrix (every sample x every varying column), which was
    very likely the real cause behind "the table sometimes doesn't appear"."""

    def __init__(self, field_key: str, warning_html: widgets.HTML, on_change):
        self.text = widgets.Text(
            layout=widgets.Layout(width="180px"),
            # continuous_update=False - see _FieldRow's value_widget for why.
            continuous_update=False,
        )
        self._observer = _guard_forbidden_characters(self.text, warning_html, on_change)
        quick_fill_button = _quick_fill_button_for(field_key, self.text)
        self.widget: widgets.Widget = (
            self.text
            if quick_fill_button is None
            else widgets.HBox(
                [self.text, quick_fill_button], layout=widgets.Layout(align_items="center")
            )
        )

    def sync(self, value) -> None:
        _sync_widget_value(self.text, self._observer, "" if value is None else str(value))


class _MatrixRow(widgets.HBox):
    """One sample's row in VaryingFieldsMatrix: Sample/Subbatch labels, one _MatrixCell
    per currently-varying field, the Variation cell, and a shared warning line. Built
    once per sample_number and refreshed in place - see _MatrixCell and _FieldRow for why
    (this is the same "keep widgets alive across re-renders" fix, applied to the matrix's
    rows instead of a field panel's rows)."""

    def __init__(self, sample_number: int, on_cell_change, on_variation_change):
        self.sample_number = sample_number
        self._on_cell_change = on_cell_change
        self._on_variation_change = on_variation_change
        self.sample_label = widgets.Label(
            value=str(sample_number), layout=widgets.Layout(width="70px")
        )
        self.subbatch_label = widgets.Label(layout=widgets.Layout(width="70px"))
        # One shared warning line for the whole row (space is tight, one column per
        # varying field) - an invalid cell also gets its own red border, so which cell is
        # bad stays visible even after the message itself is superseded by a later edit.
        self.row_warning = widgets.HTML(value="")
        self._cells: dict[int, _MatrixCell] = {}
        self.variation_text = widgets.Text(
            layout=widgets.Layout(width="180px"), continuous_update=False
        )
        self._variation_observer = _guard_forbidden_characters(
            self.variation_text,
            self.row_warning,
            lambda new_value: self._on_variation_change(self.sample_number, new_value),
        )
        super().__init__([])

    def update(self, set_index, varying_fields, variation_spec: ProcessFieldSpec | None) -> None:
        self.subbatch_label.value = "" if set_index is None else str(set_index + 1)

        live_ids = {id(spec) for _label, spec in varying_fields}
        for key in list(self._cells):
            if key not in live_ids:
                del self._cells[key]

        cell_widgets = []
        for label, spec in varying_fields:
            cell = self._cells.get(id(spec))
            if cell is None:
                _process_part, field_part = _split_varying_field_label(label)
                cell = _MatrixCell(
                    field_part,
                    self.row_warning,
                    lambda new_value, s=spec: self._on_cell_change(
                        s, self.sample_number, new_value
                    ),
                )
                self._cells[id(spec)] = cell
            cell.sync(spec.per_sample_values.get(self.sample_number))
            cell_widgets.append(cell.widget)

        variation_value = ""
        if variation_spec is not None:
            variation_value = variation_spec.per_sample_values.get(self.sample_number) or ""
        _sync_widget_value(self.variation_text, self._variation_observer, str(variation_value))

        self.children = [
            self.sample_label,
            self.subbatch_label,
            *cell_widgets,
            self.variation_text,
            self.row_warning,
        ]


class VaryingFieldsMatrix(widgets.VBox):
    """One column per currently-varying field, one row per sample, plus a leading
    Subbatch column (the sample's variation_group_index from Sample Setup, shown 1-based
    to match the Excel "Subbatch" value - see data_manager.subbatch_for_sample) and a
    trailing (always-last) Variation column. Every cell is directly editable, including
    Variation - it is NOT auto-computed live anymore (see update_variation_column's
    docstring for why); use the "Auto-fill Variation" button above VariationTemplatePanel
    for an on-demand bulk fill. Every column header (including Variation) has a small
    arrow-down "populate" button that copies that column's first row down into every
    other row - a time-saver when most samples share one value."""

    def __init__(self, state: ExperimentState, on_change=None):
        self.state = state
        self.on_change = on_change
        self._rows: dict[int, _MatrixRow] = {}
        super().__init__([])
        self._render()

    def refresh(self) -> None:
        self._render()

    def hard_refresh(self) -> None:
        """Clears children AND the cached row widgets before rebuilding fresh, instead of
        the normal refresh()'s reuse-in-place - for large datasets (many samples x many
        varying fields), the frontend has been reported to sometimes not finish
        rendering a big .children replacement; forcing a genuinely empty state first,
        then repopulating with brand new widgets, is a common ipywidgets workaround for
        that class of stuck render (reusing the same, possibly-stuck widget models
        wouldn't help). Wired to the 'Refresh Table' button in app.py."""
        self.children = []
        self._rows = {}
        self._render()

    def _notify_change(self) -> None:
        self._render()
        if self.on_change:
            self.on_change()

    def _render(self) -> None:
        varying_fields = iter_varying_fields(self.state)
        sample_numbers = self.state.sample_numbers()

        if not varying_fields or not sample_numbers:
            self._rows = {}
            self.children = [
                widgets.HTML(
                    value="<i>Mark fields as varying, and add samples, to see the matrix.</i>"
                )
            ]
            return

        header_cells = [
            widgets.Label(value="Sample", layout=widgets.Layout(width="70px")),
            widgets.Label(value="Subbatch", layout=widgets.Layout(width="70px")),
        ]
        header_cells.extend(
            self._build_column_header(label, spec, sample_numbers) for label, spec in varying_fields
        )
        variation_spec = self.state.experiment_info_fields.get("Variation")
        header_cells.append(
            self._build_column_header(
                "Variation", variation_spec, sample_numbers, label_text="Variation"
            )
        )

        set_by_sample = {s.sample_number: s.variation_group_index for s in self.state.samples}

        live_samples = set(sample_numbers)
        for key in list(self._rows):
            if key not in live_samples:
                del self._rows[key]

        body_rows = []
        for sample_number in sample_numbers:
            row = self._rows.get(sample_number)
            if row is None:
                row = _MatrixRow(
                    sample_number, self._on_cell_change, self._on_variation_cell_change
                )
                self._rows[sample_number] = row
            row.update(set_by_sample.get(sample_number), varying_fields, variation_spec)
            body_rows.append(row)

        self.children = [widgets.HBox(header_cells), *body_rows]

    def _build_column_header(
        self, label: str, spec: ProcessFieldSpec | None, sample_numbers: list[int], label_text=None
    ) -> widgets.Widget:
        if label_text is None:
            process_part, field_part = _split_varying_field_label(label)
            label_text = f"{process_part}<br>{field_part}"
        text = widgets.HTML(
            value=f"<div style='width:180px; text-align:center;'>{label_text}</div>"
        )
        if spec is None:
            return text
        populate_button = widgets.Button(
            icon="arrow-down",
            tooltip="Copy the first row's value into every row below",
            layout=widgets.Layout(width="30px", margin="2px auto 0 auto"),
        )
        populate_button.on_click(
            lambda _button, s=spec, sns=sample_numbers: self._on_populate_column(s, sns)
        )
        return widgets.VBox([text, populate_button], layout=widgets.Layout(align_items="center"))

    def _on_cell_change(self, spec: ProcessFieldSpec, sample_number: int, new_value) -> None:
        set_field_manual(spec, new_value, sample_number=sample_number)
        self._notify_change()

    def _on_variation_cell_change(self, sample_number: int, new_value) -> None:
        variation_spec = self.state.experiment_info_fields.get("Variation")
        if variation_spec is not None:
            # Variation is always per-sample; force the scope before writing so a manual
            # edit lands in per_sample_values, not the (unused for this field) constant
            # value slot.
            variation_spec.varies = True
            set_field_manual(variation_spec, new_value, sample_number=sample_number)
        self._notify_change()

    def _on_populate_column(self, spec: ProcessFieldSpec, sample_numbers: list[int]) -> None:
        populate_column_from_first(spec, sample_numbers)
        self._notify_change()


class VariationTemplatePanel(widgets.VBox):
    """Optional custom format for the computed Variation column - e.g.
    'Den=\\1_Sol-\\2_SubTemp=\\3' instead of the automatic field-slug label. '\\N' (1-based)
    refers to the Nth currently-varying column, in the SAME order as the Varying Fields
    matrix's columns (a live '\\1 = ...' legend below the input shows exactly what that
    order is right now, since it shifts as fields are marked varying/un-varying
    elsewhere). Not every varying column has to be referenced by the template, and a
    referenced column left unfilled for a given sample just renders as empty for that
    sample - see data_manager.render_variation_template.

    Deliberately exempt from the forbidden-character guard every other Text input in
    this app uses (_guard_forbidden_characters) - this pattern legitimately needs a
    backslash, it's a control input, not sample/experiment data.

    Needs an explicit refresh() wired into app.py's refresh_all: the \\N legend depends on
    iter_varying_fields(state), which changes in response to OTHER widgets' actions
    (ProcessFieldsPanel/ExperimentInfoPanel's 'varies' checkboxes), not this panel's
    own. Hides itself entirely (same condition VaryingFieldsMatrix uses to show its own
    placeholder) whenever there's no actual matrix table to apply a Variation format
    to.

    Hosts two buttons side by side, color-coded to keep them visually distinct since
    they're easy to conflate: "Apply Formula" (blue/primary) SWITCHES the active format
    (the custom pattern typed above, or automatic if left blank) and refills under it;
    "Automatically fill up Variation" (green/success) just (re)computes under WHATEVER
    format is already active, without changing it - the one to reach for after editing
    varying-field values, since Variation is a plain, directly-editable matrix column now
    and is no longer filled in live as you type (see update_variation_column's
    docstring)."""

    def __init__(self, state: ExperimentState, on_change=None):
        self.state = state
        self.on_change = on_change

        self.template_input = widgets.Text(
            value=state.variation_template or "",
            placeholder=r"e.g. Den=\1_Sol-\2_SubTemp=\3 - leave blank for the automatic label",
            layout=widgets.Layout(width="420px"),
        )
        self.apply_button = widgets.Button(description="Apply Formula", button_style="primary")
        self.apply_button.on_click(self._on_apply)
        self.autofill_button = widgets.Button(
            description="Automatically fill up Variation", button_style="success"
        )
        self.autofill_button.on_click(self._on_autofill)
        self.status = widgets.HTML(value="")
        self.autofill_status = widgets.HTML(value="")
        self.legend = widgets.HTML(value="")

        caption = widgets.HTML(
            value=(
                "<i style='color:#7f8c8d; font-size:11px;'>Variation is a plain entry "
                "column - it is not filled in automatically as you type. Custom Variation "
                "format (optional): reference a varying column by position with "
                "<code>\\1</code>, <code>\\2</code>, <code>\\3</code>... in the same order "
                "as the legend below - you don't have to use every column, and a "
                "referenced column with no value for a given sample is simply left blank "
                "for that sample, not an error. <b>Apply Formula</b> switches to this "
                "format (or back to the automatic label if left blank) and refills "
                "immediately; <b>Automatically fill up Variation</b> just (re)fills under "
                "whichever format is already active, without changing it - a manually-"
                "typed Variation value is never overwritten by either.</i>"
            )
        )

        super().__init__(
            [
                caption,
                widgets.HBox([self.template_input, self.apply_button, self.autofill_button]),
                self.status,
                self.autofill_status,
                self.legend,
            ]
        )
        self.refresh()

    def _on_autofill(self, _button) -> None:
        written = auto_fill_variation_column(self.state)
        self.autofill_status.value = (
            f"<span style='color:#2c7a4b'>Filled {written} sample(s).</span>"
        )
        self.refresh()
        if self.on_change:
            self.on_change()

    def refresh(self) -> None:
        """Re-renders the \\N legend from the CURRENT varying fields - call whenever
        anything outside this panel changes which fields are marked varying. Hides the
        whole panel (same condition as VaryingFieldsMatrix's own placeholder) when
        there's no varying field, or no sample, for a Variation format to apply to."""
        varying_fields = iter_varying_fields(self.state)
        if not varying_fields or not self.state.sample_numbers():
            self.layout.display = "none"
            return
        self.layout.display = ""
        rows = [
            f"<code>\\{index}</code> = {label}"
            for index, (label, _spec) in enumerate(varying_fields, start=1)
        ]
        self.legend.value = (
            "<span style='color:#7f8c8d; font-size:11px;'>"
            + " &nbsp;|&nbsp; ".join(rows)
            + "</span>"
        )

    def _on_apply(self, _button) -> None:
        apply_variation_template(self.state, self.template_input.value)
        self.status.value = (
            "<span style='color:#2c7a4b'>Applied.</span>"
            if self.state.variation_template
            else "<span style='color:#2c7a4b'>Reverted to the automatic label.</span>"
        )
        self.refresh()
        if self.on_change:
            self.on_change()


_PROGRESS_BAR_STYLE_BY_BAND = {
    "red": "danger",
    "yellow": "warning",
    "blue": "info",
    "green": "success",
}

# 10 phrases per data_manager.progress_band result, keyed the same way - purely
# decorative copy, safe to edit/expand freely without touching any logic.
_PROGRESS_MESSAGES = {
    "red": [
        "Every great dataset starts with a single filled cell. Let's go!",
        "The fields are calling. Will you answer?",
        "Rome wasn't databased in a day, but you could start today.",
        "Somewhere, a Data Steward is hoping you'll fill in just one more field.",
        "This progress bar is lonely. Give it some company.",
        "Future You will thank Present You for filling this in now.",
        "Blank fields are just opportunities wearing a disguise.",
        "A journey of a thousand fields begins with a single click.",
        "The NOMAD archive believes in you. Do you believe in it?",
        "Warm-up lap complete. Now let's actually start the race.",
    ],
    "yellow": [
        "You're past the halfway warm-up - keep the momentum going!",
        "Solid progress! The finish line is starting to look real.",
        "Halfway to hero status. Don't stop now.",
        "This experiment is starting to look like science, not guesswork.",
        "Nice work - your metadata is no longer a cry for help.",
        "You're outrunning most spreadsheets right now.",
        "Progress detected. Keep it coming.",
        "The completion bar just smiled at you. Keep going.",
        "You're closer to 'done' than to 'oops, forgot everything'.",
        "Keep this up and you'll make it look easy.",
    ],
    "blue": [
        "Almost there - you can practically smell the finish line.",
        "This is the part where champions don't slow down.",
        "Your future self is already proud of you.",
        "The last stretch is always the sweetest.",
        "You're so close, even the progress bar is getting excited.",
        "Just a few more fields between you and greatness.",
        "This is what 'nearly there' looks like. Keep pushing.",
        "You've out-documented most of the lab already.",
        "The Data Steward is smiling somewhere. Probably at you.",
        "Home stretch! Don't let a few empty cells slow you down.",
    ],
    "green": [
        "Look at you, absolutely crushing it!",
        "This is what a fully-documented experiment looks like. Gorgeous.",
        "You've basically won the metadata Olympics.",
        "10/10, no notes (well, maybe just a few notes fields left).",
        "Chef's kiss. This dataset is *chef's kiss*.",
        "Future researchers will build their analyses on this beautifully filled sheet.",
        "You make good data entry look easy.",
        "This is the completion bar's favorite color for a reason.",
        "Somewhere, a meta-analysis just got easier because of you.",
        "Achievement unlocked: Metadata Perfectionist.",
    ],
}


class ProgressBarWidget(widgets.VBox):
    """Material-gated progress bar (data_manager.compute_experiment_progress), color-
    coded by data_manager.progress_band (red/yellow/blue/green) with a rotating
    encouraging message per band. Call .refresh() after any field edit elsewhere in the
    app."""

    def __init__(self, state: ExperimentState):
        self.state = state
        self.bar = widgets.FloatProgress(
            min=0, max=1, value=0, layout=widgets.Layout(width="400px")
        )
        self.label = widgets.Label(value="")
        self.message = widgets.HTML(value="")
        super().__init__([widgets.HBox([self.bar, self.label]), self.message])
        self.refresh()

    def refresh(self) -> None:
        filled, total = compute_experiment_progress(self.state)
        self.bar.max = max(total, 1)
        self.bar.value = filled
        self.label.value = f"{filled} / {total} fields"
        band = progress_band(filled, total)
        self.bar.bar_style = _PROGRESS_BAR_STYLE_BY_BAND[band]
        phrase = random.choice(_PROGRESS_MESSAGES[band])
        self.message.value = f"<i style='color:#7f8c8d;'>{phrase}</i>"


class NudgePopupFlow(widgets.VBox):
    """Guided popup sequence (data_manager.build_nudge_queue): missing fields first
    (worst-gap processes first), then outlier-flagged filled values, ending with a
    summary of remaining gaps per process - always the last popup, regardless of queue
    length. 'Confirm & Next' writes the shown value back via set_field_manual (so an
    outlier gets un-flagged once confirmed correct, and a filled-in missing field is
    accepted); 'Skip' just advances. The queue is a snapshot taken at construction time -
    if a field gets filled/edited elsewhere in the app while the flow is open, its item is
    silently skipped when reached, since it's no longer missing/outlier."""

    def __init__(self, state: ExperimentState, on_change=None, max_items: int | None = None):
        self.state = state
        self.on_change = on_change
        self.queue = build_nudge_queue(state, max_items=max_items)
        self.index = 0
        self.body = widgets.VBox([])
        super().__init__([self.body])
        self._render()

    def _current_spec(self, item: NudgeItem) -> ProcessFieldSpec | None:
        try:
            process = self.state.get_process(item.sequence_index)
        except KeyError:
            return None
        return process.field_specs.get(item.field_key)

    def _item_still_relevant(self, item: NudgeItem, spec: ProcessFieldSpec | None) -> bool:
        if spec is None or spec.varies:
            return False
        if item.kind == "missing":
            return not spec.is_filled()
        return spec.is_outlier and spec.is_filled()

    def _render(self) -> None:
        while self.index < len(self.queue):
            item = self.queue[self.index]
            if self._item_still_relevant(item, self._current_spec(item)):
                break
            self.index += 1

        if self.index >= len(self.queue):
            self.body.children = [self._build_summary()]
            return

        self.body.children = [self._build_item_widget(self.queue[self.index])]

    def _build_item_widget(self, item: NudgeItem) -> widgets.Widget:
        spec = self._current_spec(item)
        kind_label = "Missing field" if item.kind == "missing" else "Outlier flagged"
        header = widgets.HTML(
            value=(
                f"<b>{kind_label}</b> - {item.sequence_index}: {item.process_type} - "
                f"{item.field_key} ({self.index + 1} / {len(self.queue)})"
            )
        )

        value_input = widgets.Text(
            value="" if spec.value is None else str(spec.value),
            layout=widgets.Layout(width="260px"),
        )

        provenance_html = widgets.HTML(value="")
        if spec.provenance is not None and spec.provenance.source != "manual":
            tag = f"from Batch {spec.provenance.source_batch_id}"
            if spec.provenance.source_sample_id:
                tag += f", Sample {spec.provenance.source_sample_id}"
            provenance_html.value = f"<span style='color:#7f8c8d; font-size:11px;'>{tag}</span>"

        confirm_button = widgets.Button(description="Confirm & Next", button_style="success")
        confirm_button.on_click(lambda b: self._on_confirm(item, value_input.value))

        skip_button = widgets.Button(description="Skip")
        skip_button.on_click(lambda b: self._on_skip())

        return widgets.VBox(
            [
                header,
                widgets.HBox([value_input, provenance_html]),
                widgets.HBox([confirm_button, skip_button]),
            ]
        )

    def _on_confirm(self, item: NudgeItem, new_value: str) -> None:
        spec = self._current_spec(item)
        if spec is not None and new_value.strip():
            set_field_manual(spec, new_value)
        self.index += 1
        self._advance()

    def _on_skip(self) -> None:
        self.index += 1
        self._advance()

    def _advance(self) -> None:
        self._render()
        if self.on_change:
            self.on_change()

    def _build_summary(self) -> widgets.Widget:
        summary = build_missing_fields_summary(self.state)
        if not summary:
            return widgets.HTML(value="<b>All fields are filled.</b>")
        rows = ["<b>Still missing fields:</b><ul>"]
        rows.extend(
            f"<li>{process.sequence_index}: {process.process_type} - {count} missing</li>"
            for process, count in summary
        )
        rows.append("</ul>")
        return widgets.HTML(value="".join(rows))


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


class _ProcessRow(widgets.VBox):
    """One process's row in ProcessSequenceBuilder: toggle/index/type dropdown/progress/
    add-remove buttons, config controls, the adopt-from-template and override-from-batch
    sections, and (when expanded) the process's ProcessFieldsPanel. Built once per
    process (keyed by id(process) in ProcessSequenceBuilder._process_rows - sequence_index
    isn't a stable key, it shifts on every add/remove elsewhere in the sequence - see
    ExperimentState.renumber_sequence_indices) and refreshed in place afterwards.

    Needed for the same reason as _FieldRow/_MatrixRow: ProcessFieldsPanel itself stopped
    being rebuilt from scratch on every field edit, but it was still being reinserted
    under a brand new outer VBox every time (the old _build_row rebuilt everything around
    it too) - which still tore down its on-screen DOM (a fresh parent means a fresh
    frontend view for every descendant, even an unchanged child widget) and kept losing
    focus/scroll position on every keystroke-commit.

    update() runs for EVERY process row on EVERY edit anywhere in the form (so progress
    %/config displays everywhere stay current), not just the row actually being edited -
    so config controls (numeric/checkbox) AND the adopt-from-template/override-from-batch
    sections are all cached and synced/swapped in place too, exactly like _FieldRow/
    _MatrixCell. An earlier version rebuilt the adopt/override sections fresh every
    update() call (they used to need a separate ProcessSequenceBuilder._adopt_status/
    _override_status dict just to survive that rebuild) - which meant self.children
    differed from the previous render on EVERY SINGLE update() call, for every row,
    regardless of whether that row's own process actually changed, since two brand new
    widget objects were always in the list. That's what was still clearing an in-progress
    edit (and derailing tab order) in a numbered-process row whenever ANY field changed
    anywhere in the form - Experiment Info has no adopt/override section and was never
    affected, which is what pointed here."""

    def __init__(self, builder: "ProcessSequenceBuilder", process: ProcessInstance):
        self._builder = builder
        self.process = process
        self._numeric_controls: list[widgets.Widget] = []
        self._checkbox_controls: list[widgets.Widget] = []
        self._numeric_control_widgets: dict[str, widgets.Widget] = {}
        self._numeric_control_observers: dict[str, object] = {}
        self._checkbox_control_widgets: dict[str, widgets.Widget] = {}
        self._checkbox_control_observers: dict[str, object] = {}

        self.toggle_button = widgets.Button(layout=widgets.Layout(width="28px"))
        self.toggle_button.on_click(lambda _b: builder._on_toggle(self.process.sequence_index))

        self.index_label = widgets.Label(layout=widgets.Layout(width="25px"))

        self.process_dropdown = widgets.Dropdown(
            options=_REAL_PROCESS_TYPES, layout=widgets.Layout(width="180px")
        )
        self.process_dropdown.value = process.process_type
        self.process_dropdown.observe(self._handle_process_type_change, names="value")

        self.progress_label = widgets.HTML(value="")

        self.add_button = widgets.Button(
            icon="plus", button_style="success", layout=widgets.Layout(width="30px")
        )
        self.add_button.on_click(lambda _b: builder._add_after(self.process.sequence_index))

        self.remove_button = widgets.Button(
            icon="minus", button_style="danger", layout=widgets.Layout(width="30px")
        )
        self.remove_button.on_click(lambda _b: builder._remove(self.process.sequence_index))

        self.main_row = widgets.HBox(
            layout=widgets.Layout(
                margin="1px 0", padding="5px", border="1px solid #e0e0e0", align_items="center"
            )
        )
        self.checkbox_controls_row = widgets.HBox(
            layout=widgets.Layout(margin="0", padding="5px 5px 5px 210px", align_items="center")
        )
        self.caption = _field_row_caption()
        self.panel: ProcessFieldsPanel | None = None

        # -- Adopt-from-template section: persistent, updated in place - see class
        # docstring for why this used to be rebuilt fresh every update().
        self._adopt_button = widgets.Button(
            description="Adopt from template batch", layout=widgets.Layout(width="200px")
        )
        self._adopt_button.on_click(self._on_adopt_click)
        self._adopt_status = widgets.HTML(value="")
        self._adopt_picker_area = widgets.VBox([])
        self.adopt_section = widgets.VBox(
            [
                widgets.HBox([self._adopt_button, self._adopt_status]),
                widgets.HTML(
                    value=(
                        "<i style='color:#7f8c8d; font-size:11px;'>Pulls this process's "
                        "values from the batch picked above in Whole-experiment Template, "
                        "for this process only.</i>"
                    )
                ),
                self._adopt_picker_area,
            ]
        )

        # -- Override-from-batch section: two mutually exclusive layouts (already
        # overridden vs not) - both cached, swapped as a whole only when that actually
        # flips (see _sync_override_section), instead of the top-level shape being
        # rebuilt on every update() like the rest of this section used to be.
        self._override_detail = ""
        self._override_active_label = widgets.HTML(value="")
        override_clear_button = widgets.Button(
            description="Clear override", layout=widgets.Layout(width="120px")
        )
        override_clear_button.on_click(lambda _b: self._on_clear_override())
        self._override_active_view = widgets.HBox(
            [self._override_active_label, override_clear_button],
            layout=widgets.Layout(align_items="center"),
        )
        self._override_toggle = widgets.ToggleButton(
            description="Override from batch...", layout=widgets.Layout(width="160px")
        )
        self._override_container = widgets.VBox([])
        self._override_toggle.observe(self._on_override_toggle, names="value")
        self._override_inactive_view = widgets.VBox(
            [self._override_toggle, self._override_container]
        )
        self.override_section = widgets.VBox([])
        self._override_active: bool | None = None

        super().__init__(
            [], layout=widgets.Layout(margin="2px 0", border="1px solid #ccc", padding="4px")
        )
        self.update()

    def _handle_process_type_change(self, change) -> None:
        self._builder._on_process_type_change(self.process.sequence_index, change["new"])

    def update(self) -> None:
        process = self.process
        is_expanded = self._builder._expanded.get(process.sequence_index, True)
        self.toggle_button.icon = "chevron-down" if is_expanded else "chevron-right"
        self.index_label.value = f"{process.sequence_index}."
        _sync_widget_value(
            self.process_dropdown, self._handle_process_type_change, process.process_type
        )

        filled, total = compute_process_progress(process)
        self.progress_label.value = _progress_html(filled, total)

        self._sync_config_controls()
        self._sync_override_section()

        self.main_row.children = [
            self.toggle_button,
            self.index_label,
            self.process_dropdown,
            self.progress_label,
            *self._numeric_controls,
            self.add_button,
            self.remove_button,
        ]
        self.checkbox_controls_row.children = self._checkbox_controls

        rows: list[widgets.Widget] = [self.main_row]
        if self._checkbox_controls:
            rows.append(self.checkbox_controls_row)
        rows.append(self.adopt_section)
        rows.append(self.override_section)
        if is_expanded:
            rows.append(self.caption)
            if self.panel is None:
                self.panel = ProcessFieldsPanel(
                    self._builder.state,
                    process,
                    cache=self._builder.cache,
                    on_change=self._builder._dispatch_on_change,
                )
            else:
                self.panel.refresh()
            rows.append(self.panel)
        self.children = rows

    def _sync_config_controls(self) -> None:
        process = self.process
        config = process.config

        checkbox_keys = [ATMOSPHERIC_CONFIG_KEY]
        self._sync_checkbox_control(
            ATMOSPHERIC_CONFIG_KEY,
            "Add Atmospheric Values",
            "190px",
            bool(config.get(ATMOSPHERIC_CONFIG_KEY, False)),
        )

        numeric_keys: list[str] = []
        if process.process_type in CONFIGURABLE_PROCESS_TYPES:
            for key, label, applicable_types, min_val, max_val in NUMERIC_CONFIG_FIELDS:
                if process.process_type not in applicable_types:
                    continue
                self._sync_numeric_control(key, label, min_val, max_val, config.get(key, min_val))
                numeric_keys.append(key)

            for key, label, applicable_types in BOOLEAN_CONFIG_FIELDS:
                if process.process_type not in applicable_types:
                    continue
                self._sync_checkbox_control(key, label, "140px", bool(config.get(key, False)))
                checkbox_keys.append(key)

        for key in list(self._numeric_control_widgets):
            if key not in numeric_keys:
                del self._numeric_control_widgets[key]
                del self._numeric_control_observers[key]
        for key in list(self._checkbox_control_widgets):
            if key not in checkbox_keys:
                del self._checkbox_control_widgets[key]
                del self._checkbox_control_observers[key]

        self._numeric_controls = [self._numeric_control_widgets[key] for key in numeric_keys]
        self._checkbox_controls = [self._checkbox_control_widgets[key] for key in checkbox_keys]

    def _sync_numeric_control(
        self, key: str, label: str, min_val: int, max_val: int, value: int
    ) -> None:
        widget = self._numeric_control_widgets.get(key)
        if widget is None:
            widget = widgets.BoundedIntText(
                value=value,
                min=min_val,
                max=max_val,
                description=f"{label}:",
                style={"description_width": "initial"},
                layout=widgets.Layout(width="120px"),
                # continuous_update=False - see _FieldRow's value_widget for why. This one
                # used to be the worst case in the app: _on_config_change triggers a full
                # rebuild_field_specs() PLUS a re-render of every row in the whole
                # ProcessSequenceBuilder, not just this process.
                continuous_update=False,
            )

            def _observer(change, k=key):
                self._builder._on_config_change(self.process.sequence_index, k, change["new"])

            widget.observe(_observer, names="value")
            self._numeric_control_widgets[key] = widget
            self._numeric_control_observers[key] = _observer
            return
        _sync_widget_value(widget, self._numeric_control_observers[key], value)

    def _sync_checkbox_control(self, key: str, label: str, width: str, value: bool) -> None:
        widget = self._checkbox_control_widgets.get(key)
        if widget is None:
            widget = widgets.Checkbox(
                value=value,
                description=label,
                style={"description_width": "initial"},
                layout=widgets.Layout(width=width),
            )

            def _observer(change, k=key):
                self._builder._on_config_change(self.process.sequence_index, k, change["new"])

            widget.observe(_observer, names="value")
            self._checkbox_control_widgets[key] = widget
            self._checkbox_control_observers[key] = _observer
            return
        _sync_widget_value(widget, self._checkbox_control_observers[key], value)

    # -- adopt-from-template-batch ----------------------------------------------

    def _on_adopt_click(self, _button) -> None:
        """One-click adoption from the batch already picked in the Whole-experiment
        Template picker (state.whole_experiment_template_batch_id), scoped to this one
        process. If that batch has more than one step of this process type (e.g. several
        Spin Coating layers), lets the user pick which one by the material it deposited
        before confirming - see list_process_occurrences."""
        builder = self._builder
        process = self.process
        self._adopt_picker_area.children = []
        if not (builder.url and builder.token and builder.cache):
            self._adopt_status.value = (
                "<span style='color:#c0392b'>No NOMAD session available.</span>"
            )
            return
        template_batch_id = builder.state.whole_experiment_template_batch_id
        if not template_batch_id:
            self._adopt_status.value = (
                "<span style='color:#c0392b'>Pick a whole-experiment template batch "
                "above first.</span>"
            )
            return
        self._adopt_status.value = "<i>Working...</i>"
        try:
            occurrences = list_process_occurrences(
                builder.url, builder.token, builder.cache, template_batch_id, process.process_type
            )
        except Exception as exc:
            self._adopt_status.value = f"<span style='color:#c0392b'>Failed: {exc}</span>"
            return
        if not occurrences:
            self._adopt_status.value = (
                f"<span style='color:#c0392b'>Batch {template_batch_id} has no "
                f"{process.process_type} step.</span>"
            )
            return
        if len(occurrences) == 1:
            self._apply_adopt(template_batch_id, occurrences[0][0])
            return
        self._adopt_status.value = ""
        occurrence_dropdown = widgets.Dropdown(
            options=[(label, idx) for idx, label in occurrences],
            description="Material:",
            style={"description_width": "initial"},
        )
        confirm_button = widgets.Button(description="Confirm", button_style="primary")
        confirm_button.on_click(
            lambda b: self._apply_adopt(template_batch_id, occurrence_dropdown.value)
        )
        self._adopt_picker_area.children = [occurrence_dropdown, confirm_button]

    def _apply_adopt(self, batch_id: str, occurrence: int) -> None:
        builder = self._builder
        self._adopt_status.value = "<i>Working...</i>"
        try:
            written = apply_process_override(
                builder.state,
                self.process,
                builder.url,
                builder.token,
                builder.cache,
                batch_id,
                occurrence,
            )
        except Exception as exc:
            self._adopt_status.value = f"<span style='color:#c0392b'>Failed: {exc}</span>"
            return
        self._adopt_status.value = (
            f"<span style='color:#2c7a4b'>Filled {written} field(s) from Batch {batch_id}.</span>"
        )
        builder._notify_change()

    # -- override-from-batch ------------------------------------------------------

    def _sync_override_section(self) -> None:
        active = self.process.source_override_batch_id is not None
        if active:
            self._override_active_label.value = (
                f"<span style='color:#2c7a4b'>Overridden from batch "
                f"{self.process.source_override_batch_id}{self._override_detail}</span>"
            )
        if active != self._override_active:
            self._override_active = active
            self.override_section.children = (
                [self._override_active_view] if active else [self._override_inactive_view]
            )

    def _on_override_toggle(self, change) -> None:
        if change["new"]:
            self._override_container.children = [self._build_override_picker()]
        else:
            self._override_container.children = []

    def _build_override_picker(self) -> widgets.Widget:
        builder = self._builder
        if not (builder.url and builder.token and builder.cache):
            return widgets.HTML(
                value="<span style='color:#c0392b'>No NOMAD session available.</span>"
            )

        def on_load(batch_id):
            written = apply_process_override(
                builder.state, self.process, builder.url, builder.token, builder.cache, batch_id
            )
            self._override_detail = f" - filled {written} field(s)"
            builder._notify_change()
            return None

        return _create_batch_picker(
            builder.cache, builder.url, builder.token, "Override batch", on_load
        )

    def _on_clear_override(self) -> None:
        clear_process_override(self._builder.state, self.process)
        self._override_detail = ""
        self._builder._notify_change()


class ProcessSequenceBuilder(widgets.VBox):
    """Row-based process sequence editor: one row per process (Experiment Info always
    first and fixed, then each real ProcessInstance), a dropdown to pick the process type
    (Excel_creator-style), inline config controls (solvents/solutes/spinsteps/... +
    checkboxes), add/remove buttons, a collapsible ProcessFieldsPanel with a completion
    percentage next to its title, a one-click 'adopt from template batch' action, and a
    per-process override picker for adopting from a different batch entirely. Mirrors
    Excel_creator's row UX (dropdown + add/remove), but writes into an ExperimentState
    instead of a raw dict list, and calls rebuild_field_specs() after every edit so
    field_specs stay in sync with the actual generated Excel column layout.
    """

    def __init__(
        self,
        state: ExperimentState,
        url: str | None = None,
        token: str | None = None,
        cache: NomadSessionCache | None = None,
        on_change=None,
    ):
        self.state = state
        self.url = url
        self.token = token
        self.cache = cache
        self.on_change = on_change
        # Collapse/expand state per sequence_index (0 = Experiment Info); defaults to
        # expanded so nothing looks hidden on first load.
        self._expanded: dict[int, bool] = {}
        # Every row's whole widget tree (toggle/dropdown/progress/config controls/
        # ProcessFieldsPanel or ExperimentInfoPanel, wrapped in an outer VBox) used to be
        # rebuilt from scratch on every _render(), which fires on ANY field edit anywhere
        # (a field already re-renders itself locally - see ProcessFieldsPanel/
        # ExperimentInfoPanel._notify_change - but that still calls on_change, which
        # cascades up through app.py's refresh_all into this widget's own refresh()).
        # Even after ProcessFieldsPanel/ExperimentInfoPanel instances themselves started
        # being reused (see _process_rows/_info_panel below), reinserting that SAME
        # instance under a brand new outer VBox every time still tore down its on-screen
        # DOM - a fresh parent means a fresh frontend view for every descendant, even one
        # whose underlying widget model didn't change - which kept losing focus/scroll
        # position on every keystroke-commit. _ProcessRow (and the mirrored experiment-
        # info-row widgets below) keep that whole per-row tree alive and update it in
        # place instead, keyed by id(process) rather than sequence_index (which shifts on
        # every add/remove elsewhere in the sequence - see ExperimentState.
        # renumber_sequence_indices).
        self._process_rows: dict[int, _ProcessRow] = {}

        self._info_toggle_button = widgets.Button(layout=widgets.Layout(width="28px"))
        self._info_toggle_button.on_click(lambda _b: self._on_toggle(0))
        self._info_index_label = widgets.Label(value="0.", layout=widgets.Layout(width="25px"))
        # A (disabled) dropdown, not a plain label, so this row matches the visual shape
        # of every other process row - but Experiment Info itself can never change type.
        self._info_dropdown = widgets.Dropdown(
            options=["Experiment Info"],
            value="Experiment Info",
            disabled=True,
            layout=widgets.Layout(width="180px"),
        )
        self._info_progress_label = widgets.HTML(value="")
        self._info_add_button = widgets.Button(
            icon="plus", button_style="success", layout=widgets.Layout(width="30px")
        )
        self._info_add_button.on_click(lambda _b: self._add_after(0))
        self._info_main_row = widgets.HBox(
            [
                self._info_toggle_button,
                self._info_index_label,
                self._info_dropdown,
                self._info_progress_label,
                self._info_add_button,
            ],
            layout=widgets.Layout(
                margin="1px 0", padding="5px", border="1px solid #e0e0e0", align_items="center"
            ),
        )
        self._info_caption = _field_row_caption()
        self._info_row_widget = widgets.VBox(
            [], layout=widgets.Layout(margin="2px 0", border="1px solid #ccc", padding="4px")
        )
        self._info_panel: ExperimentInfoPanel | None = None

        self.experiment_info_box = widgets.VBox([])
        self.rows_box = widgets.VBox([])
        rebuild_field_specs(self.state)
        super().__init__([self.experiment_info_box, self.rows_box])
        self._render()

    def _dispatch_on_change(self) -> None:
        # A trampoline, not self.on_change passed by value: app.py constructs this widget
        # before it has built refresh_all, then assigns sequence_builder.on_change =
        # refresh_all afterwards. A cached child panel built during that window would
        # otherwise be handed a permanently-None callback and silently stop propagating
        # its edits to the progress bar / matrix / variation legend.
        if self.on_change:
            self.on_change()

    def _notify_change(self) -> None:
        rebuild_field_specs(self.state)
        self._render()
        if self.on_change:
            self.on_change()

    def refresh(self) -> None:
        """Re-renders from the current state without treating it as a local edit (no
        rebuild_field_specs/on_change) - call after something OUTSIDE this widget changes
        what should be displayed, e.g. the whole-experiment template picker replacing
        state.process_sequence wholesale. Without this, picking a template would update
        the data correctly but leave the on-screen rows stale, since this widget only
        otherwise re-renders in response to its own internal actions."""
        self._render()

    def _render(self) -> None:
        self.experiment_info_box.children = [self._update_experiment_info_row()]

        live_ids = {id(process) for process in self.state.process_sequence}
        for key in list(self._process_rows):
            if key not in live_ids:
                del self._process_rows[key]

        row_widgets = []
        for process in self.state.process_sequence:
            row = self._process_rows.get(id(process))
            if row is None:
                row = _ProcessRow(self, process)
                self._process_rows[id(process)] = row
            else:
                row.update()
            row_widgets.append(row)
        self.rows_box.children = row_widgets

    def _on_toggle(self, sequence_index: int) -> None:
        self._expanded[sequence_index] = not self._expanded.get(sequence_index, True)
        self._render()

    # -- Experiment Info row (always first, never removable/re-typeable) ------

    def _update_experiment_info_row(self) -> widgets.Widget:
        is_expanded = self._expanded.get(0, True)
        self._info_toggle_button.icon = "chevron-down" if is_expanded else "chevron-right"

        filled, total = compute_experiment_info_progress(self.state)
        self._info_progress_label.value = _progress_html(filled, total)

        rows: list[widgets.Widget] = [self._info_main_row]
        if is_expanded:
            rows.append(self._info_caption)
            if self._info_panel is None:
                self._info_panel = ExperimentInfoPanel(
                    self.state, on_change=self._dispatch_on_change
                )
            else:
                self._info_panel.refresh()
            rows.append(self._info_panel)
        self._info_row_widget.children = rows
        return self._info_row_widget

    # -- mutation handlers -----------------------------------------------------

    def _on_process_type_change(self, sequence_index: int, new_type: str) -> None:
        process = self.state.get_process(sequence_index)
        process.process_type = new_type
        process.config = default_config_for(new_type)
        process.field_specs = {}
        process.source_override_batch_id = None
        self._notify_change()

    def _on_config_change(self, sequence_index: int, key: str, value) -> None:
        process = self.state.get_process(sequence_index)
        process.config[key] = value
        self._notify_change()

    def _add_after(self, sequence_index: int) -> None:
        if sequence_index == 0:
            # Experiment Info isn't a real ProcessInstance (implicit index 0), so "add
            # after it" means inserting the very first real process.
            self.state.add_process("Generic Process", at_index=0)
            self._notify_change()
            return
        position = next(
            (
                i
                for i, p in enumerate(self.state.process_sequence)
                if p.sequence_index == sequence_index
            ),
            len(self.state.process_sequence) - 1,
        )
        self.state.add_process("Generic Process", at_index=position + 1)
        self._notify_change()

    def _remove(self, sequence_index: int) -> None:
        self.state.remove_process(sequence_index)
        self._notify_change()


def _debug_report_to_html(report: dict, process_type: str, occurrence_label: str) -> str:
    rows = [
        f"<h5 style='margin-bottom:2px;'>Mapped fields - {process_type} ({occurrence_label})</h5>"
    ]
    if not report["mapped"]:
        rows.append("<i>No field mappings configured for this process type.</i>")
    else:
        rows.append(
            "<table style='border-collapse:collapse; font-size:12px;'>"
            "<tr><th style='text-align:left; padding:2px 8px;'>Excel field</th>"
            "<th style='text-align:left; padding:2px 8px;'>Value</th>"
            "<th style='text-align:left; padding:2px 8px;'>Archive path</th></tr>"
        )
        for row in report["mapped"]:
            value = row["value"]
            value_html = "<i style='color:#c0392b'>not found</i>" if value is None else str(value)
            unverified = (
                ""
                if row["unit_verified"]
                else " <span style='color:#c0392b'>(unit unverified)</span>"
            )
            rows.append(
                f"<tr><td style='padding:2px 8px;'>{row['excel_key']}</td>"
                f"<td style='padding:2px 8px;'>{value_html}{unverified}</td>"
                f"<td style='padding:2px 8px; color:#7f8c8d;'>{', '.join(row['paths'])}</td></tr>"
            )
        rows.append("</table>")

    rows.append("<h5 style='margin-bottom:2px;'>Raw fields ignored by every mapping</h5>")
    if not report["ignored"]:
        rows.append("<i>None - every raw field on this step is claimed by a mapping.</i>")
    else:
        rows.append(
            "<table style='border-collapse:collapse; font-size:12px;'>"
            "<tr><th style='text-align:left; padding:2px 8px;'>Archive path</th>"
            "<th style='text-align:left; padding:2px 8px;'>Value</th></tr>"
        )
        for row in report["ignored"]:
            rows.append(
                f"<tr><td style='padding:2px 8px;'>{row['path']}</td>"
                f"<td style='padding:2px 8px;'>{row['value']}</td></tr>"
            )
        rows.append("</table>")
    return "".join(rows)


class BatchFieldMappingDebugPanel(widgets.VBox):
    """Diagnostic tool: pick a real batch, then a process type (including 'Experiment
    Info'), to see every configured Excel field mapping's resolved value (found or 'not
    found') alongside every raw archive field NOT claimed by any mapping. Answers 'what's
    taken from the database and what's ignored' directly against real data, so a real gap
    (wrong process-type disambiguation, a genuinely unmapped field, a config range too
    narrow) can be spotted and reported precisely instead of guessed at. Read-only - never
    writes into ExperimentState."""

    def __init__(self, url: str, token: str, cache: NomadSessionCache):
        self.url = url
        self.token = token
        self.cache = cache
        self._batch_id: str | None = None

        self.process_type_dropdown = widgets.Dropdown(
            options=AVAILABLE_PROCESSES,
            value="Experiment Info",
            description="Process type:",
            style={"description_width": "initial"},
            layout=widgets.Layout(width="280px"),
        )
        self.occurrence_dropdown = widgets.Dropdown(
            options=[],
            description="Occurrence:",
            style={"description_width": "initial"},
            layout=widgets.Layout(width="280px", visibility="hidden"),
        )
        self.report_output = widgets.HTML(value="")

        self.process_type_dropdown.observe(self._on_selection_change, names="value")
        self.occurrence_dropdown.observe(self._on_selection_change, names="value")

        batch_picker = _create_batch_picker(
            cache, url, token, "Batch", self._on_batch_loaded, button_label="Load"
        )

        super().__init__(
            [
                widgets.HTML(
                    value=(
                        "<i style='color:#7f8c8d; font-size:11px;'>Pick a batch, then a "
                        "process type, to see exactly what this app would copy from that "
                        "batch's real archive data versus every raw field left "
                        "unmapped.</i>"
                    )
                ),
                batch_picker,
                self.process_type_dropdown,
                self.occurrence_dropdown,
                self.report_output,
            ]
        )

    def _on_batch_loaded(self, batch_id: str) -> str:
        self._batch_id = batch_id
        self._refresh_occurrences()
        self._refresh_report()
        return f"<span style='color:#2c7a4b'>Loaded {batch_id}.</span>"

    def _on_selection_change(self, change) -> None:
        if change["name"] != "value":
            return
        self._refresh_occurrences()
        self._refresh_report()

    def _refresh_occurrences(self) -> None:
        process_type = self.process_type_dropdown.value
        if not self._batch_id or process_type == "Experiment Info":
            self.occurrence_dropdown.options = []
            self.occurrence_dropdown.layout.visibility = "hidden"
            return
        try:
            occurrences = list_process_occurrences(
                self.url, self.token, self.cache, self._batch_id, process_type
            )
        except Exception:
            occurrences = []
        if not occurrences:
            self.occurrence_dropdown.options = []
            self.occurrence_dropdown.layout.visibility = "hidden"
            return
        self.occurrence_dropdown.options = [(label, idx) for idx, label in occurrences]
        self.occurrence_dropdown.layout.visibility = "visible"

    def _refresh_report(self) -> None:
        if not self._batch_id:
            self.report_output.value = ""
            return
        process_type = self.process_type_dropdown.value
        try:
            if process_type == "Experiment Info":
                source = self.cache.get_experiment_info_source(self.url, self.token, self._batch_id)
                if source is None:
                    self.report_output.value = (
                        "<i>This batch has no samples with a resolvable substrate.</i>"
                    )
                    return
                occurrence_label = "first sample"
            else:
                steps = steps_for_process_type(
                    self.cache.get_processing_steps(self.url, self.token, self._batch_id),
                    process_type,
                )
                if not steps:
                    self.report_output.value = f"<i>Batch has no {process_type} step.</i>"
                    return
                occurrence = self.occurrence_dropdown.value or 0
                if occurrence >= len(steps):
                    occurrence = 0
                source = steps[occurrence]
                occurrence_label = f"occurrence {occurrence + 1} of {len(steps)}"
        except Exception as exc:
            self.report_output.value = f"<span style='color:#c0392b'>Failed: {exc}</span>"
            return
        report = build_field_mapping_debug_report(process_type, source)
        self.report_output.value = _debug_report_to_html(report, process_type, occurrence_label)
