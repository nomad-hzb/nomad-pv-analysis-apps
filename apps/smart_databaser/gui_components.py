# gui_components.py
# All ipywidgets code. No NOMAD/API calls or Excel generation logic lives here - it all
# funnels through data_manager.py, which owns ExperimentState and never imports a widget
# library.

import base64
import html
import json
import logging
import random

import ipywidgets as widgets
from data_manager import (
    ExperimentState,
    NomadSessionCache,
    NudgeItem,
    ProcessFieldSpec,
    apply_whole_experiment_template,
    build_experiment_filename,
    build_missing_fields_summary,
    build_nudge_queue,
    compute_experiment_progress,
    compute_sample_set_split,
    fill_all_date_and_operator_fields,
    generate_full_workbook,
    missing_critical_fields,
    progress_band,
    set_field_manual,
    upload_experiment_excel,
    workbook_to_bytes,
)
from gui_fields import (  # noqa: F401
    _REAL_PROCESS_TYPES,
    ExperimentInfoPanel,
    ProcessFieldsPanel,
    _create_batch_picker,
    _current_user_name,
    _field_row_caption,
    _FieldRow,
    _forbidden_chars_message,
    _guard_forbidden_characters,
    _outlier_flag_html,
    _progress_html,
    _provenance_summary_html,
    _quick_fill_button_for,
    _sync_widget_value,
)
from gui_matrix import (  # noqa: F401
    VariationTemplatePanel,
    VaryingFieldsMatrix,
    _MatrixCell,
    _MatrixColumn,
    _split_varying_field_label,
)
from gui_sequence import (  # noqa: F401
    BatchFieldMappingDebugPanel,
    ProcessSequenceBuilder,
    _debug_report_to_html,
    _ProcessRow,
)
from IPython.display import Javascript, display

logger = logging.getLogger(__name__)


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


class SampleSetupPanel(widgets.VBox):
    """Setup-time sample/Subbatch configuration - distinct from the auto-computed
    Variation LABEL in VaryingFieldsMatrix (see the addendum: 'Number of samples' /
    'Number of variations' are setup-time inputs, not the same concept). Internally, a
    "Subbatch" is still ExperimentState/SamplePlan's `variation_group_index` - only the
    UI-facing wording changed (product ask: first 'group' -> 'set' since 'group' read as
    confusing, then 'set' -> 'Subbatch' since the Subbatch Excel column is always exactly
    this value, 1-based - see data_manager.subbatch_for_sample). 'Apply Sample Setup'
    reconciles each Subbatch's sample count to exactly match its input - adding samples
    when raised, removing the highest-numbered (most recently added) ones first when
    lowered - so it supports growing AND shrinking to any size, in either order. Per-sample
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
            default_value = split[set_index] if set_index < len(split) else 0
            count_input = widgets.BoundedIntText(
                value=default_value,
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
        until a user noticed and clicked the button themselves.

        Reconciles every configured Subbatch's sample count to exactly match its input
        (adds OR removes, unlike the old add-only behavior that could never shrink a
        batch back down once grown) - excess samples are dropped from the END of that
        Subbatch (highest sample_number first), so already-configured earlier samples
        survive a later shrink. Also removes any sample belonging to a Subbatch that's no
        longer configured at all (Variation Subbatch count lowered), so the total sample
        count always matches what's currently shown, in both directions.

        All removals run before any additions: ExperimentState.add_sample numbers a new
        sample from the highest sample_number across the WHOLE state (not just its own
        Subbatch), so removing first keeps that numbering contiguous-ish instead of a
        newly-added sample jumping to a number well past ones being removed in the same
        Apply click (live-verified: growing one Subbatch while shrinking another to 0 in
        a single click produced e.g. sample 17 instead of 5 before this ordering fix)."""
        configured_indices = {
            count_input._set_index for count_input in self.sets_inputs_box.children
        }
        targets = {
            count_input._set_index: count_input.value
            for count_input in self.sets_inputs_box.children
        }
        for sample in list(self.state.samples):
            if sample.variation_group_index not in configured_indices:
                self.state.remove_sample(sample.sample_number)
        for set_index, target in targets.items():
            existing = sorted(
                (s for s in self.state.samples if s.variation_group_index == set_index),
                key=lambda s: s.sample_number,
            )
            if len(existing) > target:
                for sample in existing[target:]:
                    self.state.remove_sample(sample.sample_number)
        for set_index, target in targets.items():
            existing_count = sum(
                1 for s in self.state.samples if s.variation_group_index == set_index
            )
            for _ in range(max(0, target - existing_count)):
                self.state.add_sample(variation_group_index=set_index)
        if self.on_change:
            self.on_change()


def _build_download_link_html(state: ExperimentState) -> tuple[str, bytes, str]:
    """(link_html, excel_bytes, filename) - shared by create_download_button and
    create_finish_section so the base64 download-link logic (matching Excel_creator's own
    voila_experiment_app.py _create_download_link pattern) isn't duplicated."""
    workbook = generate_full_workbook(state)
    data = workbook_to_bytes(workbook)
    filename = build_experiment_filename(state)
    b64_data = base64.b64encode(data).decode()
    mime = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    link_html = (
        f'<a download="{filename}" href="data:{mime};base64,{b64_data}">'
        f"Click here to download the experiment file ({filename})</a>"
    )
    return link_html, data, filename


def _trigger_browser_download(js_output: widgets.Output, data: bytes, filename: str) -> None:
    """Auto-starts the real browser download instead of leaving the user to find and click
    a plain data-URI link buried in a status message - product feedback that the old
    'click Download only -> click Continue -> click the actual link' flow was too many
    steps for what should be one action. Mirrors App_dashboard's app.py::setup_app
    js_output pattern (see CLAUDE.md's 'display() inside a widget callback needs an
    Output() under Voila' gotcha): a bare display(Javascript(...)) from inside a button
    callback is silently dropped under Voila, since the callback fires from a comm
    message with no current output area - routing it through a real Output() widget that
    stays part of the displayed tree is what actually renders (and runs) it. Caller must
    keep js_output in the displayed widget tree."""
    mime = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    b64_data = base64.b64encode(data).decode()
    script = (
        "(function(){"
        "var a = document.createElement('a');"
        f"a.href = 'data:{mime};base64,{b64_data}';"
        f"a.download = {json.dumps(filename)};"
        "document.body.appendChild(a);"
        "a.click();"
        "document.body.removeChild(a);"
        "})();"
    )
    with js_output:
        js_output.clear_output(wait=True)
        display(Javascript(script))


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

    Either action (immediate, or 'Continue' after the nudge flow) that produces a file
    auto-starts the actual browser download via _trigger_browser_download - product
    feedback that the old flow ('Download only' -> 'Continue with Download' -> then find
    and click a plain-text link) was one click too many for what should already be the
    file. status_output still shows a fallback link for the rare case the browser blocks
    the automatic download (e.g. a popup/download blocker).

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
    # Hidden Output() that _trigger_browser_download routes its Javascript through - must
    # stay part of the returned widget tree (see that function's docstring). Zero-size so
    # it never visibly disturbs the layout.
    download_js_output = widgets.Output(
        layout=widgets.Layout(width="0px", height="0px", overflow="hidden")
    )

    def do_upload(data: bytes, filename: str) -> bool:
        if not upload_dropdown.value:
            status_output.value += (
                "<br><span style='color:#c0392b'>Pick a target upload first.</span>"
            )
            return False
        try:
            upload_experiment_excel(url, token, upload_dropdown.value, filename, data)
            status_output.value += (
                f"<br><span style='color:#2c7a4b'>Uploaded {html.escape(filename)} to "
                f"{html.escape(str(upload_dropdown.value))}.</span>"
            )
            return True
        except Exception as exc:
            status_output.value += (
                f"<br><span style='color:#c0392b'>Upload failed: {html.escape(str(exc))}</span>"
            )
            return False

    def run_download_only():
        link_html, data, filename = _build_download_link_html(state)
        _trigger_browser_download(download_js_output, data, filename)
        status_output.value = (
            f"<span style='color:#2c7a4b'>Downloading {filename} - it should start "
            f"automatically.</span> If it doesn't, {link_html}"
        )

    def run_upload_only():
        status_output.value = ""
        _link_html, data, filename = _build_download_link_html(state)
        do_upload(data, filename)

    def run_download_and_upload():
        link_html, data, filename = _build_download_link_html(state)
        _trigger_browser_download(download_js_output, data, filename)
        status_output.value = (
            f"<span style='color:#2c7a4b'>Downloading {filename} - it should start "
            f"automatically.</span> If it doesn't, {link_html}"
        )
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
            download_js_output,
        ]
    )
    return widgets.VBox(children)


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
            tag = f"from Batch {html.escape(str(spec.provenance.source_batch_id))}"
            if spec.provenance.source_sample_id:
                tag += f", Sample {html.escape(str(spec.provenance.source_sample_id))}"
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
