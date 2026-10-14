# gui_components.py
# All ipywidgets code. No NOMAD/API calls or Excel generation logic lives here - it all
# funnels through data_manager.py, which owns ExperimentState and never imports a widget
# library.

import html
import logging

import ipywidgets as widgets
from data_manager import (
    ATMOSPHERIC_CONFIG_KEY,
    AVAILABLE_PROCESSES,
    BOOLEAN_CONFIG_FIELDS,
    CONFIGURABLE_PROCESS_TYPES,
    NUMERIC_CONFIG_FIELDS,
    ExperimentState,
    NomadSessionCache,
    ProcessInstance,
    apply_process_override,
    build_field_mapping_debug_report,
    clear_process_override,
    compute_experiment_info_progress,
    compute_process_progress,
    default_config_for,
    list_process_occurrences,
    rebuild_field_specs,
    steps_for_process_type,
)
from gui_fields import (
    _REAL_PROCESS_TYPES,
    ExperimentInfoPanel,
    ProcessFieldsPanel,
    _create_batch_picker,
    _field_row_caption,
    _progress_html,
    _sync_widget_value,
)

logger = logging.getLogger(__name__)


class _ProcessRow(widgets.VBox):
    """One process's row in ProcessSequenceBuilder: toggle/index/type dropdown/progress/
    add-remove buttons, config controls, the adopt-from-template and override-from-batch
    sections, and (when expanded) the process's ProcessFieldsPanel. Built once per
    process (keyed by id(process) in ProcessSequenceBuilder._process_rows - sequence_index
    isn't a stable key, it shifts on every add/remove elsewhere in the sequence - see
    ExperimentState.renumber_sequence_indices) and refreshed in place afterwards.

    Needed for the same reason as _FieldRow/VaryingFieldsMatrix's cached cells:
    ProcessFieldsPanel itself stopped
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
            self._adopt_status.value = (
                f"<span style='color:#c0392b'>Failed: {html.escape(str(exc))}</span>"
            )
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
            self._adopt_status.value = (
                f"<span style='color:#c0392b'>Failed: {html.escape(str(exc))}</span>"
            )
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
            value_html = (
                "<i style='color:#c0392b'>not found</i>"
                if value is None
                else html.escape(str(value))
            )
            unverified = (
                ""
                if row["unit_verified"]
                else " <span style='color:#c0392b'>(unit unverified)</span>"
            )
            rows.append(
                f"<tr><td style='padding:2px 8px;'>{html.escape(str(row['excel_key']))}</td>"
                f"<td style='padding:2px 8px;'>{value_html}{unverified}</td>"
                f"<td style='padding:2px 8px; color:#7f8c8d;'>"
                f"{html.escape(', '.join(map(str, row['paths'])))}</td></tr>"
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
                f"<tr><td style='padding:2px 8px;'>{html.escape(str(row['path']))}</td>"
                f"<td style='padding:2px 8px;'>{html.escape(str(row['value']))}</td></tr>"
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
            self.report_output.value = (
                f"<span style='color:#c0392b'>Failed: {html.escape(str(exc))}</span>"
            )
            return
        report = build_field_mapping_debug_report(process_type, source)
        self.report_output.value = _debug_report_to_html(report, process_type, occurrence_label)
