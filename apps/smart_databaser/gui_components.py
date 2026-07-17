# gui_components.py
# All ipywidgets code. No NOMAD/API calls or Excel generation logic lives here - it all
# funnels through data_manager.py, which owns ExperimentState and never imports a widget
# library.

import base64
import logging
import random

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
    apply_whole_experiment_template,
    build_experiment_filename,
    build_missing_fields_summary,
    build_nudge_queue,
    clear_process_override,
    compute_experiment_info_progress,
    compute_experiment_progress,
    compute_process_progress,
    compute_sample_set_split,
    default_config_for,
    generate_full_workbook,
    iter_varying_fields,
    list_process_occurrences,
    preview_value_for_field,
    progress_band,
    rebuild_field_specs,
    set_field_manual,
    set_field_required_for_progress,
    set_field_varies,
    update_variation_column,
    upload_experiment_excel,
    workbook_to_bytes,
)

logger = logging.getLogger(__name__)


def _provenance_html(spec: ProcessFieldSpec) -> widgets.HTML:
    if spec.provenance is None or spec.provenance.source == "manual":
        return widgets.HTML(value="")
    tag = f"from Batch {spec.provenance.source_batch_id}"
    if spec.provenance.source_sample_id:
        tag += f", Sample {spec.provenance.source_sample_id}"
    color = "#c0392b" if spec.is_outlier else "#7f8c8d"
    return widgets.HTML(value=f"<span style='color:{color}; font-size:11px;'>{tag}</span>")


def _build_field_row(
    field_key: str,
    spec: ProcessFieldSpec,
    on_varies_change,
    on_value_change,
    on_required_change,
    preview_value=None,
) -> widgets.Widget:
    """Shared by ProcessFieldsPanel and ExperimentInfoPanel: a 'varies' checkbox, the
    field label, a value input, a provenance tag when autofilled, and a trailing
    'Required' checkbox. Non-varying fields are edited here directly; once a field is
    marked varying, its value moves to VaryingFieldsMatrix instead (edited per-sample
    there). Every autofilled field stays editable here, per the product requirement that
    autofill never locks a field.

    `preview_value`, when the field is still empty, is shown as the input's placeholder
    (native greyed-out text, not an official value) - a hint of what the active source
    batch would supply if adopted; falls back to a generic "value" placeholder when no
    preview is available.

    The 'Required' checkbox (checked by default) is unrelated to Excel generation - it
    only controls whether this field counts toward the completion bar/nudge review (see
    data_manager.set_field_required_for_progress), per the product ask to let users
    exclude fields that "aren't really important" from the count without having to fill
    them just to make the number look right. Appended at the END of the row (not
    inserted earlier) so existing code that indexes into a row's children by position
    (e.g. row.children[1] for the label) keeps working unchanged."""
    varies_checkbox = widgets.Checkbox(
        value=spec.varies, indent=False, layout=widgets.Layout(width="24px")
    )
    varies_checkbox.observe(
        lambda change, key=field_key: on_varies_change(key, change["new"]), names="value"
    )

    label = widgets.Label(value=field_key, layout=widgets.Layout(width="220px"))

    if spec.varies:
        value_widget = widgets.HTML(value="<i>varies - see matrix</i>")
    else:
        placeholder = "value" if preview_value is None else str(preview_value)
        value_widget = widgets.Text(
            value="" if spec.value is None else str(spec.value),
            placeholder=placeholder,
            layout=widgets.Layout(width="200px"),
        )
        value_widget.observe(
            lambda change, key=field_key: on_value_change(key, change["new"]), names="value"
        )

    required_checkbox = widgets.Checkbox(
        value=spec.required_for_progress,
        description="Required",
        indent=False,
        layout=widgets.Layout(width="90px"),
        style={"description_width": "initial"},
    )
    required_checkbox.observe(
        lambda change, key=field_key: on_required_change(key, change["new"]), names="value"
    )

    return widgets.HBox(
        [varies_checkbox, label, value_widget, _provenance_html(spec), required_checkbox],
        layout=widgets.Layout(align_items="center", margin="1px 0"),
    )


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
        self.children = [
            _build_field_row(
                field_key,
                spec,
                self._on_varies_change,
                self._on_value_change,
                self._on_required_change,
                preview_value=self._preview_for(field_key, spec),
            )
            for field_key, spec in self.process.field_specs.items()
        ]

    def _on_varies_change(self, field_key: str, varies: bool) -> None:
        spec = self.process.field_specs[field_key]
        set_field_varies(spec, varies, self.state.sample_numbers())
        self._notify_change()

    def _on_value_change(self, field_key: str, new_value) -> None:
        spec = self.process.field_specs[field_key]
        set_field_manual(spec, new_value)
        self._notify_change()

    def _on_required_change(self, field_key: str, required: bool) -> None:
        spec = self.process.field_specs[field_key]
        set_field_required_for_progress(spec, required)
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
        self.children = [
            _build_field_row(
                field_key,
                spec,
                self._on_varies_change,
                self._on_value_change,
                self._on_required_change,
            )
            for field_key, spec in self.state.experiment_info_fields.items()
            if field_key not in EXPERIMENT_INFO_COMPUTED_KEYS and field_key not in PIXEL_FIELD_KEYS
        ]

    def _on_varies_change(self, field_key: str, varies: bool) -> None:
        spec = self.state.experiment_info_fields[field_key]
        set_field_varies(spec, varies, self.state.sample_numbers())
        self._notify_change()

    def _on_value_change(self, field_key: str, new_value) -> None:
        spec = self.state.experiment_info_fields[field_key]
        set_field_manual(spec, new_value)
        self._notify_change()

    def _on_required_change(self, field_key: str, required: bool) -> None:
        spec = self.state.experiment_info_fields[field_key]
        set_field_required_for_progress(spec, required)
        self._notify_change()


class SampleSetupPanel(widgets.VBox):
    """Setup-time sample/set configuration - distinct from the auto-computed Variation
    LABEL in VaryingFieldsMatrix (see the addendum: 'Number of samples' / 'Number of
    variations' are setup-time inputs, not the same concept). Internally, a "set" is still
    ExperimentState/SamplePlan's `variation_group_index` - only the UI-facing wording
    changed (product ask: 'group' reads as confusing, call it 'set'). 'Apply Sample Setup'
    only ADDS samples up to each set's requested count; it never removes existing samples,
    so re-clicking after adjusting counts never destroys already-configured per-sample
    data - matching this app's no-clobber philosophy elsewhere. Per-sample child-row
    (diced pixel) configuration is intentionally not exposed here for now - it only
    applies to a minority of experiments and was confusing alongside set assignment;
    SamplePlan.child_count still exists and defaults to 0. The per-sample list/remove-
    button table was removed too, per the same "confusing, doesn't make sense here"
    feedback - individual samples still exist on ExperimentState.samples and remain
    removable programmatically (ExperimentState.remove_sample), just not from this
    panel."""

    def __init__(self, state: ExperimentState, on_change=None):
        self.state = state
        self.on_change = on_change
        self.set_count_input = widgets.BoundedIntText(
            value=1,
            min=1,
            max=50,
            description="Variation sets:",
            style={"description_width": "initial"},
        )
        self.total_samples_input = widgets.BoundedIntText(
            value=0,
            min=0,
            max=1000,
            description="Total samples:",
            style={"description_width": "initial"},
        )
        self.sets_inputs_box = widgets.VBox([])
        self.apply_button = widgets.Button(description="Apply Sample Setup", button_style="primary")

        self.set_count_input.observe(self._on_settings_change, names="value")
        self.total_samples_input.observe(self._on_settings_change, names="value")
        self.apply_button.on_click(self._on_apply)

        caption = widgets.HTML(
            value=(
                "<i style='color:#7f8c8d; font-size:11px;'>Set how many variation sets you "
                "have and the total sample count, then Apply - samples are split as evenly "
                "as possible across sets (e.g. 15 samples / 4 sets &rarr; 4, 4, 4, 3). "
                "Adjust an individual set's count below before re-applying if you want a "
                "different split.</i>"
            )
        )

        super().__init__(
            [
                caption,
                self.set_count_input,
                self.total_samples_input,
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
                description=f"Set {set_index} samples:",
                style={"description_width": "initial"},
                layout=widgets.Layout(margin="0 0 0 20px"),
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
        f'<a download="{filename}" href="data:{mime};base64,{b64_data}">Download {filename}</a>'
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
    """One column per currently-varying field, one row per sample, plus a leading Set
    column (the sample's variation_group_index from Sample Setup) and a trailing
    (always-last) computed Variation column. Cells are directly editable; the Variation
    cell is too (a manual edit there is respected by no-clobber going forward)."""

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
            widgets.Label(value="Set", layout=widgets.Layout(width="50px")),
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
        cells = [
            widgets.Label(value=str(sample_number), layout=widgets.Layout(width="70px")),
            widgets.Label(
                value="" if set_index is None else str(set_index),
                layout=widgets.Layout(width="50px"),
            ),
        ]
        for _label, spec in varying_fields:
            value = spec.per_sample_values.get(sample_number)
            cell = widgets.Text(
                value="" if value is None else str(value), layout=widgets.Layout(width="180px")
            )
            cell.observe(
                lambda change, s=spec, sn=sample_number: self._on_cell_change(s, sn, change["new"]),
                names="value",
            )
            cells.append(cell)

        variation_value = ""
        if variation_spec is not None:
            variation_value = variation_spec.per_sample_values.get(sample_number) or ""
        variation_cell = widgets.Text(
            value=str(variation_value), layout=widgets.Layout(width="180px")
        )
        variation_cell.observe(
            lambda change, sn=sample_number: self._on_variation_cell_change(sn, change["new"]),
            names="value",
        )
        cells.append(variation_cell)
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
            "<i style='color:#7f8c8d; font-size:11px;'>Check 'varies' if a field's value "
            "differs per sample - it moves into the Varying Fields matrix below and stays "
            "editable there. Uncheck 'Required' for fields that aren't really important - "
            "they're excluded from the completion count and nudge review below, but are "
            "still written to the output Excel if you fill them in.</i>"
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
