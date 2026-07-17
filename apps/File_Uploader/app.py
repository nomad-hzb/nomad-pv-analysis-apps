"""Main application orchestrator for File_Uploader."""

import logging
import time

import ipywidgets as widgets
from data_manager import TOKEN, URL_API, state
from gui_components import (
    create_file_count_display,
    create_file_input,
    create_file_selector,
    create_load_button,
    create_measurement_type_dropdown,
    create_output_widgets,
    create_sample_button,
    create_sample_output_area,
    create_upload_button,
    create_upload_button_container,
    on_file_input_change,
    on_sample_button_first_click,
    on_search_field_change,
    on_selection_change,
    upload_files_for_samples,
)
from IPython.display import HTML, display

from hysprint_utils.batch_selection import create_batch_selection

logger = logging.getLogger(__name__)

# Widget IDs created by the most recent initialize_ui call.  On the next call
# we close only these — not framework-level singletons (ipyvuetify templates).
_ui_widget_ids: set = set()


def initialize_ui(
    batch_ids_list, get_batch_ids, get_ids_in_batch, get_sample_description, get_nomad_ids_of_entry
):
    """Initialise and display the entire file-uploader user interface."""
    global _ui_widget_ids

    # Close widgets created by the previous call to initialize_ui.
    # ipywidgets keeps every widget alive in Widget.widgets even after
    # clear_output() removes it from the display; stale instances accumulate
    # across cell re-runs and their on_click handlers all fire on one click.
    for _wid in list(_ui_widget_ids):
        _w = widgets.Widget.widgets.get(_wid)
        if _w is not None:
            try:
                _w.close()
            except Exception:
                pass
    _ui_widget_ids = set()

    # Snapshot existing widget IDs so we can identify what we create below.
    _ids_before = set(widgets.Widget.widgets.keys())

    load_button = create_load_button()
    upload_and_process = create_upload_button()
    out, out2 = create_output_widgets()
    upload_button_container = create_upload_button_container()

    try:
        batch_selection_container = create_batch_selection(
            URL_API, TOKEN, lambda selector: on_load_button_clicked(None)
        )
        # Remove the internal "Load Data" button from the container — we
        # display a separate load_button below to keep the layout consistent
        # with the fallback path.
        batch_selection_container.children = batch_selection_container.children[:2]
    except Exception as _e:
        print(
            f"Warning: batch selector API call failed"
            f" ({type(_e).__name__}: {_e}); using pre-fetched list"
        )
        logger.warning("create_batch_selection failed: %s", _e)
        _search_fb = widgets.Text(
            placeholder="Search batch IDs",
            layout=widgets.Layout(width="400px"),
        )
        _bids_fb = widgets.SelectMultiple(
            options=batch_ids_list,
            layout=widgets.Layout(width="400px", height="200px"),
        )
        batch_selection_container = widgets.VBox([_search_fb, _bids_fb])
    # Keep Python references to children for callbacks — do NOT add them to a
    # separate VBox, as placing a widget in two VBox parents confuses ipywidgets.
    search_field = batch_selection_container.children[0]
    batch_ids = batch_selection_container.children[1]

    file_count_display = create_file_count_display()
    file_selector = create_file_selector()
    dropdown_all_files = create_measurement_type_dropdown()
    file_input = create_file_input()
    state.file_input_widget = file_input

    def on_load_button_clicked(b):
        logger.debug("on_load_button_clicked fired (load_button id=%s)", id(load_button))
        _on_load_button_clicked(
            b,
            batch_ids,
            file_selector,
            file_count_display,
            out,
            out2,
            get_ids_in_batch,
            get_sample_description,
            dropdown_all_files,
            on_sample_button_first_click,
            upload_button_container,
            upload_and_process,
        )

    def on_upload_file(b):
        logger.debug("on_upload_file fired (upload_button id=%s)", id(upload_and_process))
        _on_upload_file(upload_and_process, out2, get_nomad_ids_of_entry)

    def on_file_change(change):
        on_file_input_change(change, file_input, file_selector, file_count_display, out2)

    def on_selection_change_wrapper(change):
        on_selection_change(change, out2)

    def on_search_change(change):
        on_search_field_change(change, batch_ids_list, batch_ids)

    load_button.on_click(on_load_button_clicked)
    upload_and_process.on_click(on_upload_file)
    file_input.observe(on_file_change, names="file_info")
    file_selector.observe(on_selection_change_wrapper, names="value")
    search_field.observe(on_search_change, names="value")

    display(
        widgets.VBox([batch_selection_container, load_button, out, upload_button_container, out2])
    )

    # Record every widget created during this call so the next run can clean them up.
    _ui_widget_ids = set(widgets.Widget.widgets.keys()) - _ids_before


def _on_load_button_clicked(
    b,
    batch_ids,
    file_selector,
    file_count_display,
    out,
    out2,
    get_ids_in_batch,
    get_sample_description,
    dropdown_all_files,
    on_sample_button_first_click_func,
    upload_button_container,
    upload_and_process,
):
    """Handle load button click: fetch sample IDs and build the sample panel."""
    try:
        out.clear_output()
        state.reset_upload()

        selected_batch = batch_ids.value
        if isinstance(selected_batch, tuple):
            selected_batch = selected_batch[0] if selected_batch else None
        if not selected_batch:
            with out:
                print("Please select a batch first.")
            return

        with out:
            print(f"Loading '{selected_batch}'…")

        try:
            sample_ids = get_ids_in_batch(URL_API, TOKEN, [selected_batch])
            logger.info("Loaded %d sample IDs for batch %s", len(sample_ids), selected_batch)
        except AssertionError as exc:
            logger.warning("Batch loading assertion failed: %s", exc)
            with out:
                out.clear_output()
                print(f"Batch loading failed: {exc}")
                print(
                    "This usually means duplicate batch entries exist. "
                    "Remove duplicates and reload, or contact a data steward."
                )
            return
        except Exception as exc:
            logger.exception("Unexpected error in get_ids_in_batch")
            with out:
                out.clear_output()
                print(f"Error loading batch: {exc}")
            return

        sample_descriptions = get_sample_description(URL_API, TOKEN, sample_ids)
        time.sleep(0.2)

        for sample_id in sample_ids:
            state.set_sample_files(sample_id, [])

        for sample_id in sample_ids:
            try:
                description = sample_descriptions.get(sample_id, "")
                sample_button = create_sample_button(sample_id, description)
                output_area = create_sample_output_area()
                state.output_areas[sample_id] = output_area

                sample_button.on_click(
                    on_sample_button_first_click_func(
                        sample_id, output_area, file_selector, dropdown_all_files, out2
                    )
                )

                state.sample_id_buttons.append(
                    widgets.VBox(
                        [sample_button, output_area],
                        layout=widgets.Layout(flex="0 0 auto", margin="2px 0"),
                    )
                )
            except Exception:
                logger.exception("Error creating button for %s", sample_id)
                raise

        left_panel = widgets.VBox(
            [
                widgets.HBox([file_count_display]),
                state.file_input_widget,
                widgets.HTML(
                    "<div style='margin-bottom:5px;margin-top:10px;font-style:italic;color:#555;'>"
                    "Select files from the list below, then click a sample ID to assign them."
                    "</div>"
                ),
                file_selector,
            ],
            layout=widgets.Layout(
                width="530px", height="800px", padding="10px", border="1px solid #ddd", margin="5px"
            ),
        )

        right_panel = widgets.VBox(
            [dropdown_all_files] + state.sample_id_buttons,
            layout=widgets.Layout(
                width="600px",
                height="600px",
                overflow="scroll",
                padding="10px",
                border="1px solid #ddd",
                margin="5px",
            ),
        )

        with out:
            out.clear_output()
            display(HTML("<h3>Select a Sample ID and Upload Files</h3>"))
            display(
                widgets.HBox(
                    [left_panel, right_panel],
                    layout=widgets.Layout(width="100%", align_items="flex-start"),
                )
            )

        with upload_button_container:
            upload_button_container.clear_output()
            display(upload_and_process)

    except Exception as exc:
        logger.exception("Unhandled exception in _on_load_button_clicked")
        with out:
            out.clear_output()
            print(f"Unexpected error: {exc}")


def _on_upload_file(upload_and_process, out2, get_nomad_ids_of_entry):
    upload_files_for_samples(
        state.sample_files_dict,
        state.file_type_dict,
        state.uploaded_files_data,
        get_nomad_ids_of_entry,
        out2,
    )
