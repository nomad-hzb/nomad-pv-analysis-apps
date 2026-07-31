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
    EXPERIMENT_INFO_COMPUTED_KEYS,
    NUMERIC_CONFIG_FIELDS,
    PIXEL_FIELD_KEYS,
    ExperimentState,
    NomadSessionCache,
    NudgeItem,
    ProcessFieldSpec,
    ProcessInstance,
    apply_process_override,
    apply_variation_template,
    apply_whole_experiment_template,
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
    find_forbidden_characters,
    generate_full_workbook,
    iter_varying_fields,
    list_process_occurrences,
    preview_value_for_field,
    progress_band,
    rebuild_field_specs,
    relevant_field_specs,
    set_field_manual,
    set_field_varies,
    steps_for_process_type,
    update_variation_column,
    upload_experiment_excel,
    workbook_to_bytes,
)

logger = logging.getLogger(__name__)

# Field keys that get a quick-fill button in _build_field_row - "Today"/"Now" for
# date-like fields (format matches sheet_experiment.py's own make_label examples for each
# key), "Me" for Operator (reads the same NOMAD_CLIENT_USER env var
# hysprint_utils.access_token.log_notebook_usage() already uses to attribute app usage,
# rather than an extra NOMAD /users/me API round trip this app doesn't otherwise need).
_DATE_FIELD_FORMATS = {"Date": "%d-%m-%Y", "Datetime": "%d.%m.%Y %H:%M:%S"}


def _current_user_name() -> str:
    return os.environ.get("NOMAD_CLIENT_USER", "").strip() or "Unknown User"


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
    (see _DATE_FIELD_FORMATS - "%d.%m.%Y %H:%M:%S" legitimately needs colons, and neither
    field ever feeds into compute_nomad_id/build_experiment_filename anyway, so there's
    nothing downstream for a colon to break here). Rejects (does not persist) any value
    containing a data_manager.FORBIDDEN_VALUE_CHARACTERS character: shows a red border +
    warning message instead of calling on_valid, so nothing downstream (Excel generation,
    Nomad ID) ever sees it. The widget still shows whatever the user typed - only the
    underlying state write is skipped - so typing isn't fought mid-keystroke."""

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


def _build_field_row(
    field_key: str,
    spec: ProcessFieldSpec,
    on_varies_change,
    on_value_change,
    preview_value=None,
) -> widgets.Widget:
    """Shared by ProcessFieldsPanel and ExperimentInfoPanel: a 'varies' checkbox, the
    field label (with a trailing '*' when required_for_progress), a value input (with a
    quick-fill button for Date/Datetime/Operator fields), and an 'outlier' flag when
    flagged. Non-varying fields are edited here directly; once a field is marked varying,
    its value moves to VaryingFieldsMatrix instead (edited per-sample there). Every
    autofilled field stays editable here, per the product requirement that autofill never
    locks a field.

    `preview_value`, when the field is still empty, is shown as the input's placeholder
    (native greyed-out text, not an official value) - a hint of what the active source
    batch would supply if adopted; falls back to a generic "value" placeholder when no
    preview is available.

    required_for_progress is no longer editable from this row (see
    config/required_fields.json) - it's shown as a '*' after the label instead of a
    checkbox, per the product ask to keep "what's required" out of the day-to-day UI."""
    varies_checkbox = widgets.Checkbox(
        value=spec.varies, indent=False, layout=widgets.Layout(width="24px")
    )
    varies_checkbox.observe(
        lambda change, key=field_key: on_varies_change(key, change["new"]), names="value"
    )

    label_text = f"{field_key} *" if spec.required_for_progress else field_key
    label = widgets.Label(value=label_text, layout=widgets.Layout(width="220px"))

    quick_fill_button = None
    warning_html = widgets.HTML(value="")
    if spec.varies:
        value_widget = widgets.HTML(value="<i>varies - see matrix</i>")
    else:
        placeholder = "value" if preview_value is None else str(preview_value)
        value_widget = widgets.Text(
            value="" if spec.value is None else str(spec.value),
            placeholder=placeholder,
            layout=widgets.Layout(width="200px"),
            # continuous_update=False: on_value_change ultimately triggers a full panel
            # re-render (see _notify_change), which discards and rebuilds this very
            # widget. With the ipywidgets default (True, fires on every keystroke), that
            # rebuild raced with the browser's own IME/typing state on every character -
            # reported as "typing lags, and often only the first character or two of a
            # fast-typed word survive." Committing on blur/Enter instead avoids the
            # mid-keystroke rebuild entirely.
            continuous_update=False,
        )
        if field_key in _DATE_FIELD_FORMATS:
            # Exempt: colons in "HH:MM:SS" are legitimate here, and this field never
            # feeds into an ID/filename - see _guard_forbidden_characters' docstring.
            value_widget.observe(
                lambda change, key=field_key: on_value_change(key, change["new"]), names="value"
            )
        else:
            _guard_forbidden_characters(
                value_widget,
                warning_html,
                lambda new_value, key=field_key: on_value_change(key, new_value),
            )

        date_format = _DATE_FIELD_FORMATS.get(field_key)
        if date_format is not None:

            def _fill_today(_button, widget=value_widget, fmt=date_format):
                widget.value = datetime.now().strftime(fmt)

            quick_fill_button = widgets.Button(
                description="Today", layout=widgets.Layout(width="55px")
            )
            quick_fill_button.on_click(_fill_today)
        elif field_key == "Operator":

            def _fill_operator(_button, widget=value_widget):
                widget.value = _current_user_name()

            quick_fill_button = widgets.Button(
                description="Me", layout=widgets.Layout(width="45px")
            )
            quick_fill_button.on_click(_fill_operator)

    row_children = [varies_checkbox, label, value_widget]
    if quick_fill_button is not None:
        row_children.append(quick_fill_button)
    row_children.append(_outlier_flag_html(spec))
    row_children.append(warning_html)

    return widgets.HBox(row_children, layout=widgets.Layout(align_items="center", margin="1px 0"))


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
        super().__init__([])
        self._render()

    def _notify_change(self) -> None:
        update_variation_column(self.state)
        self._render()
        if self.on_change:
            self.on_change()

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
        self.children = [
            _provenance_summary_html(visible_specs.values()),
            *(
                _build_field_row(
                    field_key,
                    spec,
                    self._on_varies_change,
                    self._on_value_change,
                    preview_value=self._preview_for(field_key, spec),
                )
                for field_key, spec in visible_specs.items()
            ),
        ]

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
    generate_full_workbook), and the pixel-specific fields (Number of pixels / Pixel
    area, which vary per CHILD row and are edited via SampleSetupPanel's per-sample
    table instead)."""

    def __init__(self, state: ExperimentState, on_change=None):
        self.state = state
        self.on_change = on_change
        super().__init__([])
        self._render()

    def _notify_change(self) -> None:
        update_variation_column(self.state)
        self._render()
        if self.on_change:
            self.on_change()

    def _render(self) -> None:
        relevant = {
            field_key: spec
            for field_key, spec in self.state.experiment_info_fields.items()
            if field_key not in EXPERIMENT_INFO_COMPUTED_KEYS and field_key not in PIXEL_FIELD_KEYS
        }
        self.children = [
            _provenance_summary_html(relevant.values()),
            *(
                _build_field_row(field_key, spec, self._on_varies_change, self._on_value_change)
                for field_key, spec in relevant.items()
            ),
        ]

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
            # widgets from scratch (_render_set_inputs) - see _build_field_row's
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
        """Gate `run` behind the nudge flow unless skip_nudge_checkbox is checked."""
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


class VaryingFieldsMatrix(widgets.VBox):
    """One column per currently-varying field, one row per sample, plus a leading
    Subbatch column (the sample's variation_group_index from Sample Setup, shown 1-based
    to match the Excel "Subbatch" value - see data_manager.subbatch_for_sample) and a
    trailing (always-last) computed Variation column. Cells are directly editable; the
    Variation cell is too (a manual edit there is respected by no-clobber going
    forward)."""

    def __init__(self, state: ExperimentState, on_change=None):
        self.state = state
        self.on_change = on_change
        super().__init__([])
        self._render()

    def refresh(self) -> None:
        self._render()

    def hard_refresh(self) -> None:
        """Clears children before rebuilding, instead of replacing them in place - for
        large datasets (many samples x many varying fields), the frontend has been
        reported to sometimes not finish rendering a big .children replacement; forcing
        an empty state first, then repopulating, is a common ipywidgets workaround for
        that class of stuck render. Wired to the 'Refresh Table' button in app.py."""
        self.children = []
        self._render()

    def _notify_change(self) -> None:
        update_variation_column(self.state)
        self._render()
        if self.on_change:
            self.on_change()

    def _render(self) -> None:
        varying_fields = iter_varying_fields(self.state)
        sample_numbers = self.state.sample_numbers()

        if not varying_fields or not sample_numbers:
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
            widgets.HTML(
                value=(
                    f"<div style='width:180px; text-align:center;'>{process_part}"
                    f"<br>{field_part}</div>"
                )
            )
            for process_part, field_part in (
                _split_varying_field_label(label) for label, _spec in varying_fields
            )
        )
        header_cells.append(
            widgets.HTML(value="<div style='width:180px; text-align:center;'>Variation</div>")
        )

        set_by_sample = {s.sample_number: s.variation_group_index for s in self.state.samples}
        rows = [widgets.HBox(header_cells)]
        variation_spec = self.state.experiment_info_fields.get("Variation")
        for sample_number in sample_numbers:
            rows.append(
                self._build_sample_row(
                    sample_number, set_by_sample.get(sample_number), varying_fields, variation_spec
                )
            )
        self.children = rows

    def _build_sample_row(
        self, sample_number, set_index, varying_fields, variation_spec
    ) -> widgets.HBox:
        # One shared warning line for the whole row (space is tight, one column per
        # varying field) - an invalid cell also gets its own red border, so which cell is
        # bad stays visible even after the message itself is superseded by a later edit.
        row_warning = widgets.HTML(value="")
        cells = [
            widgets.Label(value=str(sample_number), layout=widgets.Layout(width="70px")),
            widgets.Label(
                value="" if set_index is None else str(set_index + 1),
                layout=widgets.Layout(width="70px"),
            ),
        ]
        for _label, spec in varying_fields:
            value = spec.per_sample_values.get(sample_number)
            cell = widgets.Text(
                value="" if value is None else str(value),
                layout=widgets.Layout(width="180px"),
                # continuous_update=False - see _build_field_row's value_widget for why.
                # Here the cost is much worse: a per-keystroke change rebuilds the ENTIRE
                # matrix (every sample x every varying column), which is very likely the
                # real cause behind "the table sometimes doesn't appear" - large-matrix
                # re-renders were being triggered on every character typed into any cell.
                continuous_update=False,
            )
            _guard_forbidden_characters(
                cell,
                row_warning,
                lambda new_value, s=spec, sn=sample_number: self._on_cell_change(s, sn, new_value),
            )
            cells.append(cell)

        variation_value = ""
        if variation_spec is not None:
            variation_value = variation_spec.per_sample_values.get(sample_number) or ""
        variation_cell = widgets.Text(
            value=str(variation_value),
            layout=widgets.Layout(width="180px"),
            continuous_update=False,
        )
        _guard_forbidden_characters(
            variation_cell,
            row_warning,
            lambda new_value, sn=sample_number: self._on_variation_cell_change(sn, new_value),
        )
        cells.append(variation_cell)
        cells.append(row_warning)
        return widgets.HBox(cells)

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
    to."""

    def __init__(self, state: ExperimentState, on_change=None):
        self.state = state
        self.on_change = on_change

        self.template_input = widgets.Text(
            value=state.variation_template or "",
            placeholder=r"e.g. Den=\1_Sol-\2_SubTemp=\3 - leave blank for the automatic label",
            layout=widgets.Layout(width="420px"),
        )
        self.apply_button = widgets.Button(description="Apply", button_style="primary")
        self.apply_button.on_click(self._on_apply)
        self.status = widgets.HTML(value="")
        self.legend = widgets.HTML(value="")

        caption = widgets.HTML(
            value=(
                "<i style='color:#7f8c8d; font-size:11px;'>Custom Variation format "
                "(optional). Reference a varying column by position with "
                "<code>\\1</code>, <code>\\2</code>, <code>\\3</code>... in the same order "
                "as the legend below - you don't have to use every column. If a "
                "referenced column has no value for a given sample, it's simply left "
                "blank for that sample, not an error. Click Apply to (re)generate the "
                "Variation column under the new format; leave the box empty and click "
                "Apply to go back to the automatic label.</i>"
            )
        )

        super().__init__(
            [
                caption,
                widgets.HBox([self.template_input, self.apply_button]),
                self.status,
                self.legend,
            ]
        )
        self.refresh()

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


class ProcessSequenceBuilder(widgets.VBox):
    """Row-based process sequence editor: one row per process (Experiment Info always
    first and fixed, then each real ProcessInstance), a dropdown to pick the process type
    (Excel_creator-style), inline config controls (solvents/solutes/spinsteps/... +
    checkboxes), add/remove buttons, a collapsible ProcessFieldsPanel with a completion
    percentage next to its title, a one-click 'adopt from template batch' action, and a
    per-process override picker for adopting from a different batch entirely. Mirrors
    Excel_creator's row UX (dropdown + add/remove), but writes into an ExperimentState
    instead of a raw dict list, and calls rebuild_field_specs() after every edit so
    field_specs/pixel_fields stay in sync with the actual generated Excel column layout.
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
        # Last "adopt from template batch" / "override from batch" result per
        # sequence_index, so it survives the _notify_change() re-render that follows a
        # successful action (which discards and rebuilds the row's status widgets).
        self._adopt_status: dict[int, str] = {}
        self._override_status: dict[int, str] = {}
        self.experiment_info_box = widgets.VBox([])
        self.rows_box = widgets.VBox([])
        rebuild_field_specs(self.state)
        super().__init__([self.experiment_info_box, self.rows_box])
        self._render()

    def _notify_change(self) -> None:
        rebuild_field_specs(self.state)
        update_variation_column(self.state)
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
        self.experiment_info_box.children = [self._build_experiment_info_row()]
        self.rows_box.children = [
            self._build_row(process) for process in self.state.process_sequence
        ]

    def _on_toggle(self, sequence_index: int) -> None:
        self._expanded[sequence_index] = not self._expanded.get(sequence_index, True)
        self._render()

    # -- Experiment Info row (always first, never removable/re-typeable) ------

    def _build_experiment_info_row(self) -> widgets.Widget:
        is_expanded = self._expanded.get(0, True)
        toggle_button = widgets.Button(
            icon="chevron-down" if is_expanded else "chevron-right",
            layout=widgets.Layout(width="28px"),
        )
        toggle_button.on_click(lambda b: self._on_toggle(0))

        index_label = widgets.Label(value="0.", layout=widgets.Layout(width="25px"))
        # A (disabled) dropdown, not a plain label, so this row matches the visual shape
        # of every other process row - but Experiment Info itself can never change type.
        process_dropdown = widgets.Dropdown(
            options=["Experiment Info"],
            value="Experiment Info",
            disabled=True,
            layout=widgets.Layout(width="180px"),
        )

        filled, total = compute_experiment_info_progress(self.state)
        progress_label = widgets.HTML(value=_progress_html(filled, total))

        add_button = widgets.Button(
            icon="plus", button_style="success", layout=widgets.Layout(width="30px")
        )
        add_button.on_click(lambda b: self._add_after(0))

        main_row = widgets.HBox(
            [toggle_button, index_label, process_dropdown, progress_label, add_button],
            layout=widgets.Layout(
                margin="1px 0", padding="5px", border="1px solid #e0e0e0", align_items="center"
            ),
        )

        rows: list[widgets.Widget] = [main_row]
        if is_expanded:
            rows.append(_field_row_caption())
            rows.append(ExperimentInfoPanel(self.state, on_change=self.on_change))
        return widgets.VBox(
            rows, layout=widgets.Layout(margin="2px 0", border="1px solid #ccc", padding="4px")
        )

    # -- real process rows -----------------------------------------------------

    def _build_row(self, process: ProcessInstance) -> widgets.Widget:
        is_expanded = self._expanded.get(process.sequence_index, True)
        toggle_button = widgets.Button(
            icon="chevron-down" if is_expanded else "chevron-right",
            layout=widgets.Layout(width="28px"),
        )
        toggle_button.on_click(lambda b, seq=process.sequence_index: self._on_toggle(seq))

        index_label = widgets.Label(
            value=f"{process.sequence_index}.", layout=widgets.Layout(width="25px")
        )

        process_dropdown = widgets.Dropdown(
            options=_REAL_PROCESS_TYPES,
            value=process.process_type,
            layout=widgets.Layout(width="180px"),
        )
        process_dropdown.observe(
            lambda change, seq=process.sequence_index: self._on_process_type_change(
                seq, change["new"]
            ),
            names="value",
        )

        filled, total = compute_process_progress(process)
        progress_label = widgets.HTML(value=_progress_html(filled, total))

        numeric_controls, checkbox_controls = self._build_config_controls(process)

        add_button = widgets.Button(
            icon="plus", button_style="success", layout=widgets.Layout(width="30px")
        )
        add_button.on_click(lambda b, seq=process.sequence_index: self._add_after(seq))

        remove_button = widgets.Button(
            icon="minus", button_style="danger", layout=widgets.Layout(width="30px")
        )
        remove_button.on_click(lambda b, seq=process.sequence_index: self._remove(seq))

        main_row = widgets.HBox(
            [
                toggle_button,
                index_label,
                process_dropdown,
                progress_label,
                *numeric_controls,
                add_button,
                remove_button,
            ],
            layout=widgets.Layout(
                margin="1px 0", padding="5px", border="1px solid #e0e0e0", align_items="center"
            ),
        )

        rows: list[widgets.Widget] = [main_row]
        if checkbox_controls:
            rows.append(
                widgets.HBox(
                    checkbox_controls,
                    layout=widgets.Layout(
                        margin="0", padding="5px 5px 5px 210px", align_items="center"
                    ),
                )
            )
        rows.append(self._build_adopt_section(process))
        rows.append(self._build_override_section(process))
        if is_expanded:
            rows.append(_field_row_caption())
            rows.append(
                ProcessFieldsPanel(self.state, process, cache=self.cache, on_change=self.on_change)
            )

        return widgets.VBox(
            rows, layout=widgets.Layout(margin="2px 0", border="1px solid #ccc", padding="4px")
        )

    def _build_adopt_section(self, process: ProcessInstance) -> widgets.Widget:
        """One-click adoption from the batch already picked in the Whole-experiment
        Template picker (state.whole_experiment_template_batch_id), scoped to this one
        process. If that batch has more than one step of this process type (e.g. several
        Spin Coating layers), lets the user pick which one by the material it deposited
        before confirming - see list_process_occurrences."""
        button = widgets.Button(
            description="Adopt from template batch", layout=widgets.Layout(width="200px")
        )
        status = widgets.HTML(value=self._adopt_status.get(process.sequence_index, ""))
        picker_area = widgets.VBox([])
        caption = widgets.HTML(
            value=(
                "<i style='color:#7f8c8d; font-size:11px;'>Pulls this process's values "
                "from the batch picked above in Whole-experiment Template, for this "
                "process only.</i>"
            )
        )

        def on_click(_button):
            picker_area.children = []
            if not (self.url and self.token and self.cache):
                status.value = "<span style='color:#c0392b'>No NOMAD session available.</span>"
                return
            template_batch_id = self.state.whole_experiment_template_batch_id
            if not template_batch_id:
                status.value = (
                    "<span style='color:#c0392b'>Pick a whole-experiment template batch "
                    "above first.</span>"
                )
                return
            status.value = "<i>Working...</i>"
            try:
                occurrences = list_process_occurrences(
                    self.url, self.token, self.cache, template_batch_id, process.process_type
                )
            except Exception as exc:
                status.value = f"<span style='color:#c0392b'>Failed: {exc}</span>"
                return
            if not occurrences:
                status.value = (
                    f"<span style='color:#c0392b'>Batch {template_batch_id} has no "
                    f"{process.process_type} step.</span>"
                )
                return
            if len(occurrences) == 1:
                self._apply_adopt(
                    process.sequence_index, template_batch_id, occurrences[0][0], status
                )
                return
            status.value = ""
            occurrence_dropdown = widgets.Dropdown(
                options=[(label, idx) for idx, label in occurrences],
                description="Material:",
                style={"description_width": "initial"},
            )
            confirm_button = widgets.Button(description="Confirm", button_style="primary")
            confirm_button.on_click(
                lambda b: self._apply_adopt(
                    process.sequence_index, template_batch_id, occurrence_dropdown.value, status
                )
            )
            picker_area.children = [occurrence_dropdown, confirm_button]

        button.on_click(on_click)
        return widgets.VBox([widgets.HBox([button, status]), caption, picker_area])

    def _apply_adopt(
        self, sequence_index: int, batch_id: str, occurrence: int, status: widgets.HTML
    ) -> None:
        status.value = "<i>Working...</i>"
        try:
            process = self.state.get_process(sequence_index)
            written = apply_process_override(
                self.state, process, self.url, self.token, self.cache, batch_id, occurrence
            )
        except Exception as exc:
            status.value = f"<span style='color:#c0392b'>Failed: {exc}</span>"
            return
        # _notify_change() re-renders this row from scratch, discarding `status` - stash
        # the message so the freshly-built status widget picks it up (see
        # _build_adopt_section's initial value).
        self._adopt_status[sequence_index] = (
            f"<span style='color:#2c7a4b'>Filled {written} field(s) from Batch {batch_id}.</span>"
        )
        self._notify_change()

    def _build_config_controls(self, process: ProcessInstance):
        numeric_controls: list[widgets.Widget] = []
        checkbox_controls: list[widgets.Widget] = []
        config = process.config

        atmospheric_checkbox = widgets.Checkbox(
            value=bool(config.get(ATMOSPHERIC_CONFIG_KEY, False)),
            description="Add Atmospheric Values",
            style={"description_width": "initial"},
            layout=widgets.Layout(width="190px"),
        )
        atmospheric_checkbox.observe(
            lambda change, seq=process.sequence_index: self._on_config_change(
                seq, ATMOSPHERIC_CONFIG_KEY, change["new"]
            ),
            names="value",
        )
        checkbox_controls.append(atmospheric_checkbox)

        if process.process_type not in CONFIGURABLE_PROCESS_TYPES:
            return numeric_controls, checkbox_controls

        for key, label, applicable_types, min_val, max_val in NUMERIC_CONFIG_FIELDS:
            if process.process_type not in applicable_types:
                continue
            control = widgets.BoundedIntText(
                value=config.get(key, min_val),
                min=min_val,
                max=max_val,
                description=f"{label}:",
                style={"description_width": "initial"},
                layout=widgets.Layout(width="120px"),
                # continuous_update=False - see _build_field_row's value_widget for why.
                # This one is the worst case in the app: _on_config_change triggers a full
                # rebuild_field_specs() PLUS a re-render of every row in the whole
                # ProcessSequenceBuilder, not just this process - firing that per
                # keystroke made typing here the most visibly broken spot.
                continuous_update=False,
            )
            control.observe(
                lambda change, seq=process.sequence_index, k=key: self._on_config_change(
                    seq, k, change["new"]
                ),
                names="value",
            )
            numeric_controls.append(control)

        for key, label, applicable_types in BOOLEAN_CONFIG_FIELDS:
            if process.process_type not in applicable_types:
                continue
            checkbox = widgets.Checkbox(
                value=bool(config.get(key, False)),
                description=label,
                style={"description_width": "initial"},
                layout=widgets.Layout(width="140px"),
            )
            checkbox.observe(
                lambda change, seq=process.sequence_index, k=key: self._on_config_change(
                    seq, k, change["new"]
                ),
                names="value",
            )
            checkbox_controls.append(checkbox)

        return numeric_controls, checkbox_controls

    def _build_override_section(self, process: ProcessInstance) -> widgets.Widget:
        if process.source_override_batch_id is not None:
            detail = self._override_status.get(process.sequence_index, "")
            label = widgets.HTML(
                value=(
                    f"<span style='color:#2c7a4b'>Overridden from batch "
                    f"{process.source_override_batch_id}{detail}</span>"
                )
            )
            clear_button = widgets.Button(
                description="Clear override", layout=widgets.Layout(width="120px")
            )
            clear_button.on_click(lambda b, seq=process.sequence_index: self._clear_override(seq))
            return widgets.HBox([label, clear_button], layout=widgets.Layout(align_items="center"))

        toggle = widgets.ToggleButton(
            description="Override from batch...", layout=widgets.Layout(width="160px")
        )
        container = widgets.VBox([])

        def on_toggle(change, seq=process.sequence_index):
            container.children = [self._build_override_picker(seq)] if change["new"] else []

        toggle.observe(on_toggle, names="value")
        return widgets.VBox([toggle, container])

    def _build_override_picker(self, sequence_index: int) -> widgets.Widget:
        if not (self.url and self.token and self.cache):
            return widgets.HTML(
                value="<span style='color:#c0392b'>No NOMAD session available.</span>"
            )

        def on_load(batch_id):
            process = self.state.get_process(sequence_index)
            written = apply_process_override(
                self.state, process, self.url, self.token, self.cache, batch_id
            )
            # _notify_change() below re-renders this row, discarding the picker/status
            # widget _create_batch_picker would otherwise show its returned message on -
            # stash it so _build_override_section's "Overridden from batch X" label can
            # show it instead (see that method).
            self._override_status[sequence_index] = f" - filled {written} field(s)"
            self._notify_change()
            return None

        return _create_batch_picker(self.cache, self.url, self.token, "Override batch", on_load)

    def _clear_override(self, sequence_index: int) -> None:
        process = self.state.get_process(sequence_index)
        clear_process_override(self.state, process)
        self._override_status.pop(sequence_index, None)
        self._notify_change()

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
