# app.py
# Thin orchestrator: wires data_manager state + gui_components widgets together. No
# business logic lives here.

import logging

import ipywidgets as widgets
from data_manager import ExperimentState, NomadSessionCache, rebuild_field_specs
from gui_components import (
    BatchFieldMappingDebugPanel,
    NudgePopupFlow,
    ProcessSequenceBuilder,
    ProgressBarWidget,
    SampleSetupPanel,
    VariationTemplatePanel,
    VaryingFieldsMatrix,
    create_finish_section,
    create_whole_experiment_template_picker,
)

logger = logging.getLogger(__name__)

# Widgets created by the previous call to initialize_ui() are explicitly closed before
# building new ones, mirroring File_Uploader's app.py pattern: clear_output() only hides
# widgets from display, it doesn't destroy them, so stale on_click/observe handlers from
# prior cell re-runs would otherwise all fire simultaneously on one click.
_ui_widget_ids: set = set()


def initialize_ui(url: str, token: str) -> widgets.VBox:
    global _ui_widget_ids
    for widget_id in list(_ui_widget_ids):
        widget = widgets.Widget.widgets.get(widget_id)
        if widget is not None:
            try:
                widget.close()
            except Exception:
                pass
    _ui_widget_ids = set()
    ids_before = set(widgets.Widget.widgets.keys())

    state = ExperimentState()
    cache = NomadSessionCache()
    rebuild_field_specs(state)  # populate experiment_info_fields/pixel_fields up front

    progress_bar = ProgressBarWidget(state)
    matrix = VaryingFieldsMatrix(state)
    sequence_builder = ProcessSequenceBuilder(state, url, token, cache)
    variation_template_panel = VariationTemplatePanel(state, on_change=lambda: refresh_all())

    def refresh_all():
        progress_bar.refresh()
        matrix.refresh()
        # ProcessSequenceBuilder only re-renders itself in response to its OWN actions -
        # without this, the whole-experiment template picker replacing
        # state.process_sequence wholesale would update the data but leave the on-screen
        # rows stale. Same reasoning for variation_template_panel's \N legend, which
        # depends on iter_varying_fields(state) - a 'varies' checkbox toggled anywhere
        # else must still refresh this panel's legend.
        sequence_builder.refresh()
        variation_template_panel.refresh()

    sequence_builder.on_change = refresh_all

    sample_setup = SampleSetupPanel(state, on_change=refresh_all)
    template_picker = create_whole_experiment_template_picker(
        state, url, token, cache, on_change=refresh_all
    )

    refresh_matrix_button = widgets.Button(description="Refresh Table", icon="refresh")
    refresh_matrix_status = widgets.HTML(value="")

    def on_refresh_matrix(_button):
        try:
            matrix.hard_refresh()
        except Exception as exc:
            refresh_matrix_status.value = f"<span style='color:#c0392b'>Failed: {exc}</span>"
            return
        refresh_matrix_status.value = ""

    refresh_matrix_button.on_click(on_refresh_matrix)

    nudge_container = widgets.VBox([])
    nudge_button = widgets.Button(description="Start Nudge Review", button_style="info")

    def on_start_nudge(_button):
        # Rebuilds the queue from the CURRENT state each time - "after autofill" means
        # whenever the user clicks this, not a one-shot snapshot taken at page load.
        nudge_container.children = [NudgePopupFlow(state, on_change=refresh_all)]

    nudge_button.on_click(on_start_nudge)

    finish_section = create_finish_section(state, url, token, cache, progress_bar)

    debug_panel = widgets.Accordion(children=[BatchFieldMappingDebugPanel(url, token, cache)])
    debug_panel.set_title(0, "Debug: Batch Field Mapping")
    debug_panel.selected_index = None  # collapsed by default - diagnostic tool, not everyday UI

    main_interface = widgets.VBox(
        [
            widgets.HTML(value="<h2>Smart Databaser</h2>"),
            widgets.HTML(value="<h4>Sample Setup</h4>"),
            sample_setup,
            # Right after "Apply Sample Setup", per the product ask - copying a template
            # batch's processes/values is the natural next step once samples exist.
            template_picker,
            widgets.HTML(value="<h4>Process Sequence</h4>"),
            sequence_builder,
            widgets.HTML(value="<h4>Varying Fields</h4>"),
            widgets.HTML(
                value=(
                    "<i style='color:#7f8c8d; font-size:11px;'>For large datasets, this "
                    "table can occasionally fail to display - click Refresh if it looks "
                    "empty or stale.</i>"
                )
            ),
            refresh_matrix_button,
            refresh_matrix_status,
            matrix,
            variation_template_panel,
            widgets.HTML(value="<h4>Nudge Review</h4>"),
            nudge_button,
            nudge_container,
            widgets.HTML(value="<h4>Finish</h4>"),
            finish_section,
            debug_panel,
        ],
        layout=widgets.Layout(padding="15px", max_width="1100px"),
    )

    _ui_widget_ids = set(widgets.Widget.widgets.keys()) - ids_before
    return main_interface
