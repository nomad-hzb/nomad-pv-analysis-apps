"""
All ipywidgets code for File_Uploader: widget factories, callbacks,
upload orchestration, and the user guide.
"""

import json
import logging
import threading
import time
from collections import defaultdict
from io import BytesIO
from zipfile import ZipFile

import ipywidgets as widgets
import requests
from data_manager import (
    MEASUREMENT_TYPES,
    TOKEN,
    URL_API,
    categorize_files,
    create_nomad_filename,
    extract_filenames_from_vuetify,
    get_file_extension,
    get_normalized_type,
    match_files_to_samples,
    natural_sort_key,
    read_file_from_widget,
    split_json_by_sample,
    state,
)
from IPython.display import HTML, display

try:
    from ipyvuetify.extra import FileInput as _FileInput
except ImportError:
    _FileInput = None

logger = logging.getLogger(__name__)

# Cap on simultaneous chunked file reads in flight. Firing every file's read
# at once (the old behaviour) could overwhelm the comm channel on large
# batches and make the whole upload look frozen with no visible cause.
MAX_CONCURRENT_READS = 6
# A read that hasn't settled within this many seconds is treated as stuck so
# it surfaces as a visible error instead of hanging the queue forever.
READ_TIMEOUT_S = 30

# ---------------------------------------------------------------------------
# Guide content
# ---------------------------------------------------------------------------
_GUIDE_HTML = """
<div style="padding: 15px; border: 1px solid #ddd; border-radius: 5px;
            background-color: #f9f9f9; margin: 10px 0;">
<h2>Quick Start Guide</h2>
<h3>1. <strong>Search and Select Batch</strong></h3>
<ul>
<li>Use the search field to filter available batches by name.</li>
<li>Select your target batch from the list.</li>
<li>Click <strong>Load Data</strong> to retrieve sample IDs for that batch.</li>
</ul>
<h3>2. <strong>Upload Files</strong></h3>
<ul>
<li>Click <strong>Choose Files</strong> to select your measurement data files.</li>
<li>The system automatically recognises common file types.</li>
<li>Unrecognised files are flagged for manual type assignment.</li>
</ul>
<h3>3. <strong>Assign Files to Samples</strong></h3>
<ul>
<li>Select files from the file list.</li>
<li>Click a sample ID button to assign the selected files to that sample.</li>
</ul>
<h3>4. <strong>Verify and Process</strong></h3>
<ul>
<li>Review file assignments and types for each sample.</li>
<li>Adjust file types using the dropdown menus if needed.</li>
<li>Click <strong>Upload and process Data</strong> when ready
    (this action is not reversible).</li>
</ul>
</div>
"""


# ---------------------------------------------------------------------------
# File input widget
# ---------------------------------------------------------------------------
def create_file_input():
    if _FileInput is None:
        raise ImportError("ipyvuetify is required for FileInput")
    return _FileInput(
        multiple=True,
        label="Click to add files",
        v_model=[],
        v_slots=[{"name": "selection", "children": ""}],
    )


def get_file_input_css_style():
    return """
<style>
    .v-chip { display: none !important; }
    .v-file-input__text { display: none !important; }
</style>
"""


# ---------------------------------------------------------------------------
# Widget factories
# ---------------------------------------------------------------------------
def create_load_button():
    return widgets.Button(description="Load Data")


def create_upload_button():
    return widgets.Button(
        description="Upload and process Data (not reversible)",
        layout=widgets.Layout(width="800px", height="80px"),
    )


def create_output_widgets():
    return widgets.Output(), widgets.Output()


def create_upload_button_container():
    return widgets.Output()


def create_file_count_display():
    return widgets.HTML(value="<i>No files selected</i>")


def create_file_status_display():
    """Live status line for in-progress/failed chunked file reads."""
    return widgets.HTML(value="")


def create_file_selector():
    return widgets.SelectMultiple(
        options=[],
        description="Files:",
        disabled=False,
        layout=widgets.Layout(width="450px", height="500px"),
    )


def create_measurement_type_dropdown():
    return widgets.Dropdown(
        options=[""] + MEASUREMENT_TYPES,
        value="",
        description="Override all types:",
        layout=widgets.Layout(width="400px", height="50px"),
        style={"description_width": "initial"},
    )


def create_auto_match_button():
    return widgets.Button(
        description="Auto-match files to samples by number",
        style=widgets.ButtonStyle(button_color="#5DADE2", text_color="black"),
        tooltip=(
            "Matches unassigned files to sample IDs by number (e.g. S8.txt, "
            "S8_1.txt -> a sample ID ending in 8). File naming varies a lot, so "
            "this won't catch every case -- ambiguous or numberless files are "
            "left for manual assignment, and Reset undoes it if it guesses wrong."
        ),
        layout=widgets.Layout(width="320px", height="36px"),
    )


def create_reset_assignments_button():
    return widgets.Button(
        description="Reset all assignments",
        style=widgets.ButtonStyle(button_color="#D6EAF8", text_color="black"),
        tooltip=(
            "Unassigns every file from every sample (including manual "
            "assignments) and returns them to the file list. Does not affect "
            "anything already uploaded to NOMAD."
        ),
        layout=widgets.Layout(width="320px", height="36px"),
    )


def create_sample_button(sample_id, description):
    return widgets.Button(
        description=f"{sample_id} [{description}]",
        layout=widgets.Layout(width="400px", height="40px"),
    )


def create_sample_output_area():
    return widgets.Output(layout=widgets.Layout(height="auto", min_height="0px"))


def create_add_files_button():
    return widgets.Button(
        description="Add Files",
        layout=widgets.Layout(width="80px", padding="0px", margin="2px", overflow="hidden"),
    )


def create_remove_button():
    return widgets.Button(
        description="Remove",
        layout=widgets.Layout(width="80px", padding="0px", margin="2px", overflow="hidden"),
    )


def create_file_type_dropdown_for_file(measurement_types, default_type="hy"):
    return widgets.Dropdown(
        options=measurement_types,
        value=default_type,
        description="",
        layout=widgets.Layout(width="90px", height="26px"),
    )


def create_sample_file_selector(files_list):
    return widgets.SelectMultiple(
        options=files_list,
        description="",
        disabled=False,
        layout=widgets.Layout(width="230px", height="100px"),
    )


# ---------------------------------------------------------------------------
# Bounded, visible chunked-read orchestration
# ---------------------------------------------------------------------------
def _run_read_queue(jobs, max_concurrent=MAX_CONCURRENT_READS):
    """Run chunked-read jobs with bounded concurrency.

    Each job is a callable taking `on_done`; it must call `on_done()` exactly
    once when its read settles (success, error, or timeout). Previously every
    file in a batch started reading at once, which could overwhelm the comm
    channel on large selections and make the upload look frozen with no
    visible cause.
    """
    pending = list(jobs)
    in_flight = [0]

    def start_next():
        while pending and in_flight[0] < max_concurrent:
            job = pending.pop(0)
            in_flight[0] += 1
            job(on_job_done)

    def on_job_done():
        in_flight[0] -= 1
        start_next()

    start_next()


def _render_file_status_html(status_dict):
    """Stay blank in the normal case; only surface files that failed or hung.

    Kept deliberately silent while reads are in progress or succeeding --
    it exists purely so a stuck/failed chunked read (the original cause of
    uploads silently freezing) is still visible instead of invisible.
    """
    problems = {f: s for f, s in status_dict.items() if s not in ("reading", "done")}
    if not problems:
        return ""
    items = "".join(f"<li>{fname}: {status}</li>" for fname, status in problems.items())
    return (
        "<div style='color:#d9534f;'><b>File read problems (re-select them to retry):</b>"
        f"<ul style='max-height:120px;overflow-y:auto;'>{items}</ul></div>"
    )


def _set_file_status(fname, status_text, status_display):
    state.file_read_status[fname] = status_text
    if status_display is None:
        return
    try:
        status_display.value = _render_file_status_html(state.file_read_status)
    except Exception:
        logger.exception("Failed to update file status display for %s", fname)


def _make_regular_read_job(fname, file_index, file_input, status_display):
    def job(on_done):
        settled = {"flag": False}

        def finish(status_text):
            if settled["flag"]:
                return
            settled["flag"] = True
            timer.cancel()
            _set_file_status(fname, status_text, status_display)
            on_done()

        def on_complete(content_bytes):
            state.uploaded_files_data[fname]["file_content"] = content_bytes
            logger.info("Loaded regular file: %s (%d bytes)", fname, len(content_bytes))
            finish("done")

        def on_error(msg):
            logger.error("Reading %s: %s", fname, msg)
            finish(f"error: {msg}")

        def on_timeout():
            logger.error("Timed out reading %s after %ds", fname, READ_TIMEOUT_S)
            finish("timed out")

        timer = threading.Timer(READ_TIMEOUT_S, on_timeout)
        timer.daemon = True
        timer.start()
        _set_file_status(fname, "reading", status_display)
        read_file_from_widget(file_input, file_index, on_complete, on_error)

    return job


def _make_json_read_job(fname, file_index, file_input, file_selector, status_display):
    json_base = fname.rsplit(".", 1)[0]

    def job(on_done):
        settled = {"flag": False}

        def finish(status_text):
            if settled["flag"]:
                return
            settled["flag"] = True
            timer.cancel()
            _set_file_status(fname, status_text, status_display)
            on_done()

        def on_complete(content_bytes):
            try:
                json_data = json.loads(content_bytes.decode("utf-8"))
                samples = split_json_by_sample(json_data)
                logger.info("%s: %d samples found: %s", fname, len(samples), list(samples.keys()))
                for sample_id, sample_data in samples.items():
                    output_filename = f"{sample_id}.{sample_id}-{json_base}.jv.json"
                    state.uploaded_files_data[sample_id] = {
                        "name": output_filename,
                        "is_json": True,
                        "file_content": sample_data["json_content"],
                        "source_file": fname,
                    }
                current = list(file_selector.options)
                if fname in current:
                    current.remove(fname)
                current.extend(samples.keys())
                file_selector.options = sorted(current, key=natural_sort_key)
                finish("done")
            except Exception as exc:
                logger.error("Parsing %s: %s", fname, exc)
                finish(f"error: {exc}")

        def on_error(msg):
            logger.error("Reading JSON %s: %s", fname, msg)
            finish(f"error: {msg}")

        def on_timeout():
            logger.error("Timed out reading %s after %ds", fname, READ_TIMEOUT_S)
            finish("timed out")

        timer = threading.Timer(READ_TIMEOUT_S, on_timeout)
        timer.daemon = True
        timer.start()
        _set_file_status(fname, "reading", status_display)
        read_file_from_widget(file_input, file_index, on_complete, on_error)

    return job


# ---------------------------------------------------------------------------
# Callbacks
# ---------------------------------------------------------------------------
def on_file_input_change(
    change, file_input, file_selector, file_count_display, out_widget, file_status_display=None
):
    """Handle file input change from the FileInput widget."""
    logger.info("on_file_input_change triggered")
    try:
        if not (isinstance(change, dict) and "new" in change):
            logger.debug("No files in change dict")
            return

        file_data_list = change["new"]
        if not file_data_list:
            logger.debug("Empty file list, returning early")
            return

        filenames = extract_filenames_from_vuetify(file_data_list)
        logger.debug("Extracted %d filenames", len(filenames))

        json_files = [f for f in filenames if f.lower().endswith(".json")]
        regular_files = [f for f in filenames if not f.lower().endswith(".json")]
        logger.debug("JSON: %d, regular: %d", len(json_files), len(regular_files))

        # Add to, never wipe, the existing pool: people commonly load files in
        # several rounds (some jv now, more jv later, then PL). Previously this
        # reset uploaded_files_data/file_read_status wholesale on every new
        # selection, silently discarding already-loaded content for files a
        # prior round had already assigned to a sample.
        state.file_input_widget = file_input
        already_assigned = {f for files in state.sample_files_dict.values() for f in files}

        recognized_files, unrecognized_files, files_with_dots = categorize_files(
            regular_files, MEASUREMENT_TYPES
        )

        for file_name in regular_files:
            epoch_s = None
            for fi in file_input.file_info:
                if fi["name"] == file_name:
                    epoch_s = int(fi["lastModified"] / 1000)
                    break
            state.uploaded_files_data[file_name] = {
                "name": file_name,
                "is_json": False,
                "file_content": None,
                "epoch_time": epoch_s,
            }

        # Map each filename to its real position(s) in file_input.file_info so
        # chunked reads always target the right file, even when JSON and
        # regular files are interleaved in the original selection order
        # (recomputing the index by counting within a filtered sublist, as
        # before, silently reads the wrong file or collides two files onto
        # the same index once that assumption breaks).
        name_to_indices = defaultdict(list)
        for idx, fd in enumerate(file_data_list):
            if isinstance(fd, dict) and "name" in fd:
                name_to_indices[fd["name"]].append(idx)

        def next_index_for(name):
            indices = name_to_indices.get(name)
            return indices.pop(0) if indices else None

        read_jobs = []

        for regular_file_name in regular_files:
            file_index = next_index_for(regular_file_name)
            if file_index is None:
                logger.error("No file_info index found for %s", regular_file_name)
                continue
            read_jobs.append(
                _make_regular_read_job(
                    regular_file_name, file_index, file_input, file_status_display
                )
            )

        all_display_files = list(recognized_files) + list(unrecognized_files)

        for json_file_name in json_files:
            all_display_files.append(json_file_name)
            file_index = next_index_for(json_file_name)
            if file_index is None:
                logger.error("No file_info index found for %s", json_file_name)
                continue
            read_jobs.append(
                _make_json_read_job(
                    json_file_name, file_index, file_input, file_selector, file_status_display
                )
            )

        _run_read_queue(read_jobs)

        new_unassigned = [f for f in all_display_files if f not in already_assigned]
        file_selector.options = sorted(
            set(file_selector.options) | set(new_unassigned), key=natural_sort_key
        )
        file_count = len(file_selector.options)
        file_count_display.value = (
            f"<b>{file_count} files waiting to be assigned</b>"
            if file_count > 0
            else "<i>No files selected</i>"
        )

        with out_widget:
            out_widget.clear_output()
            print(f"Uploaded {len(filenames)} files. Reading in background, see status above.")

            if unrecognized_files:
                unrecognized_html = (
                    "<div style='color:#d9534f;padding:10px;border:1px solid #d9534f;"
                    "border-radius:5px;margin-top:10px;'>"
                    "<p><strong>The following files were not recognised by filename:</strong></p>"
                    "<p>Content-based detection may still identify some of these once they finish "
                    "loading; otherwise select the correct type: "
                    "jv, eqe, mppt, sem, xrd, pes, nmr, trpl, trspv</p>"
                    "<ul style='max-height:150px;overflow-y:auto;'>"
                )
                for f in unrecognized_files:
                    unrecognized_html += f"<li>{f}</li>"
                unrecognized_html += "</ul></div>"
                display(widgets.HTML(unrecognized_html))

            if files_with_dots:
                dots_html = (
                    "<div style='color:#f0ad4e;padding:10px;border:1px solid #f0ad4e;"
                    "border-radius:5px;margin-top:10px;'>"
                    "<p><strong>Warning: filenames with periods (.) may cause issues:</strong></p>"
                    "<p>Use underscores (_) instead of periods in filenames.</p>"
                    "<ul style='max-height:150px;overflow-y:auto;'>"
                )
                for f in files_with_dots:
                    dots_html += f"<li>{f}</li>"
                dots_html += "</ul></div>"
                display(widgets.HTML(dots_html))

    except Exception as exc:
        logger.exception("Error in on_file_input_change")
        with out_widget:
            out_widget.clear_output()
            print(f"Error processing file input: {exc}")


def on_selection_change(change, out_widget):
    if change["type"] == "change" and change["name"] == "value":
        selected = change["new"]
        with out_widget:
            out_widget.clear_output()
            if selected:
                print(f"Selected files: {', '.join(selected)}")
            else:
                print("No files selected")


def on_remove_button_click(sample_id, sample_select, file_selector, update_callback, out_widget):
    def handle_click(b):
        selected_files = list(sample_select.value)
        if selected_files:
            state.remove_files_from_sample(sample_id, selected_files)
            file_selector.options = sorted(
                list(file_selector.options) + selected_files, key=natural_sort_key
            )
            update_callback()
            with out_widget:
                out_widget.clear_output()
                remaining = state.sample_files_dict[sample_id]
                print(f"Removed files from {sample_id}. Remaining: {remaining}")

    return handle_click


def on_sample_button_click(sample_id, sample_select, file_selector, update_callback, out_widget):
    def handle_click(b):
        logger.debug(
            "on_sample_button_click fired for %s (add_button id=%s)",
            sample_id,
            id(b.owner) if hasattr(b, "owner") else "?",
        )
        selected_files = list(file_selector.value)
        if selected_files:
            state.add_files_to_sample(sample_id, selected_files)
            file_selector.options = [f for f in file_selector.options if f not in selected_files]
            update_callback()
            with out_widget:
                out_widget.clear_output()
                print(f"Updated files for {sample_id}: {state.sample_files_dict[sample_id]}")

    return handle_click


def on_sample_button_first_click(
    sample_id, output_area, file_selector, dropdown_all_files, out_widget
):
    """Return a click handler that expands the sample panel on first click."""
    _registered_observer = [None]

    def handle_first_click(b):
        try:
            logger.debug(
                "handle_first_click fired for %s (button id=%s, override_observers=%d)",
                sample_id,
                id(b.owner) if hasattr(b, "owner") else "?",
                len(dropdown_all_files._trait_notifiers.get("value", {}).get("change", [])),
            )

            sample_select = create_sample_file_selector(state.sample_files_dict[sample_id])
            add_button = create_add_files_button()
            remove_button = create_remove_button()
            file_type_container = widgets.VBox([], layout=widgets.Layout(margin="0", padding="0"))

            def update_file_types():
                if sample_id not in state.file_type_dict:
                    state.file_type_dict[sample_id] = {}
                rows = []
                override_type = dropdown_all_files.value if dropdown_all_files.value else None
                for file_name in state.sample_files_dict.get(sample_id, []):
                    if override_type:
                        default_type = override_type
                    else:
                        file_info = state.uploaded_files_data.get(file_name, {})
                        if file_info.get("is_json"):
                            # JSON mode is exclusively the JV-scan format (output
                            # always ends in ".jv.json") -- the file_name here is the
                            # sample ID, not the real filename, so it carries no "jv"
                            # hint for get_normalized_type to find.
                            default_type = "jv"
                        else:
                            normalized = get_normalized_type(
                                file_name, file_info.get("file_content")
                            )
                            default_type = normalized if normalized else "hy"
                    if file_name not in state.file_type_dict[sample_id]:
                        state.set_file_type(sample_id, file_name, default_type)
                    if override_type:
                        state.set_file_type(sample_id, file_name, override_type)

                    dropdown = create_file_type_dropdown_for_file(
                        MEASUREMENT_TYPES, state.file_type_dict[sample_id][file_name]
                    )

                    def make_observer(fname):
                        def observer(change):
                            state.set_file_type(sample_id, fname, change["new"])

                        return observer

                    dropdown.observe(make_observer(file_name), names="value")
                    truncated = file_name[:15] + "..." if len(file_name) > 20 else file_name
                    _style = "width:150px;font-size:0.9em;overflow:hidden"
                    label_html = f"<div style='{_style}'>{truncated}</div>"
                    rows.append(
                        widgets.HBox(
                            [dropdown, widgets.HTML(label_html)],
                            layout=widgets.Layout(margin="0", padding="0", height="30px"),
                        )
                    )
                file_type_container.children = tuple(rows)

            def update_sample_select_and_types():
                sample_select.options = state.sample_files_dict[sample_id]
                update_file_types()

            def on_override_change(change):
                if change["type"] == "change" and change["name"] == "value":
                    update_file_types()

            if _registered_observer[0] is not None:
                try:
                    dropdown_all_files.unobserve(_registered_observer[0], names="value")
                except ValueError:
                    pass
            _registered_observer[0] = on_override_change
            dropdown_all_files.observe(on_override_change, names="value")
            add_button.on_click(
                on_sample_button_click(
                    sample_id,
                    sample_select,
                    file_selector,
                    update_sample_select_and_types,
                    out_widget,
                )
            )
            remove_button.on_click(
                on_remove_button_click(
                    sample_id,
                    sample_select,
                    file_selector,
                    update_sample_select_and_types,
                    out_widget,
                )
            )
            update_file_types()

            with output_area:
                output_area.clear_output()
                btn_col = widgets.VBox([add_button, remove_button])
                type_label = widgets.HTML(
                    "<small style='margin-bottom:5px'><b>Recognised Type:</b></small>"
                )
                type_col = widgets.VBox(
                    [type_label, file_type_container],
                    layout=widgets.Layout(margin="0 0 0 15px"),
                )
                display(widgets.HBox([widgets.HBox([btn_col, sample_select]), type_col]))

            selected_files = list(file_selector.value)
            if selected_files:
                state.add_files_to_sample(sample_id, selected_files)
                update_sample_select_and_types()
                file_selector.options = [
                    f for f in file_selector.options if f not in selected_files
                ]
                with out_widget:
                    out_widget.clear_output()
                    print(f"Added files to {sample_id}: {state.sample_files_dict[sample_id]}")

        except Exception as exc:
            logger.exception("Exception in on_sample_button_first_click for %s", sample_id)
            with out_widget:
                print(f"Error setting up sample panel for {sample_id}: {exc}")
            raise

    return handle_first_click


def on_auto_match_click(file_selector, out_widget):
    """Return a click handler that assigns unassigned files to samples by trailing number."""

    def handle_click(b):
        filenames = list(file_selector.options)
        sample_ids = list(state.sample_files_dict.keys())
        matches, unmatched = match_files_to_samples(filenames, sample_ids)

        for filename, sample_id in matches.items():
            state.add_files_to_sample(sample_id, [filename])

        if matches:
            file_selector.options = [f for f in file_selector.options if f not in matches]

        affected_samples = sorted({sample_id for sample_id in matches.values()})
        for sample_id in affected_samples:
            button = state.sample_buttons.get(sample_id)
            if button is not None:
                button.click()

        with out_widget:
            out_widget.clear_output()
            print(
                f"Auto-matched {len(matches)} file(s) to "
                f"{len(affected_samples)} sample(s) by number."
            )
            if unmatched:
                print(f"Left {len(unmatched)} file(s) for manual assignment:")
                for filename, reason in unmatched.items():
                    print(f"  {filename}: {reason}")

    return handle_click


def on_reset_assignments_click(file_selector, out_widget):
    """Return a click handler that unassigns every file from every sample."""

    def handle_click(b):
        reclaimed = []
        affected_samples = []
        for sample_id, files in state.sample_files_dict.items():
            if files:
                reclaimed.extend(files)
                affected_samples.append(sample_id)

        for sample_id in affected_samples:
            state.sample_files_dict[sample_id] = []
            state.file_type_dict.pop(sample_id, None)

        if reclaimed:
            file_selector.options = sorted(
                set(file_selector.options) | set(reclaimed), key=natural_sort_key
            )

        for sample_id in affected_samples:
            button = state.sample_buttons.get(sample_id)
            if button is not None:
                button.click()

        with out_widget:
            out_widget.clear_output()
            print(
                f"Reset {len(reclaimed)} file assignment(s) across "
                f"{len(affected_samples)} sample(s)."
            )

    return handle_click


def on_search_field_change(change, batch_ids_list, batch_ids):
    """Filter the batch selector based on the search field value."""
    if change["type"] == "change" and change["name"] == "value":
        term = change["new"].lower()
        batch_ids.options = (
            batch_ids_list if not term else [d for d in batch_ids_list if term in d.lower()]
        )


# ---------------------------------------------------------------------------
# Upload orchestration
# ---------------------------------------------------------------------------
def upload_files_for_samples(
    sample_files_dict, file_type_dict, uploaded_files_data, get_nomad_ids_of_entry, out_widget
):
    """Build per-upload ZIP archives and push them to NOMAD."""
    upload_ids = {}

    with out_widget:
        print("Preparing archives...")

    for sample_id, file_names in sample_files_dict.items():
        if not file_names:
            continue
        entry_id, upload_id = get_nomad_ids_of_entry(URL_API, TOKEN, sample_id)
        time.sleep(0.2)
        if upload_id not in upload_ids:
            upload_ids[upload_id] = BytesIO()

        for file_name in file_names:
            if file_name not in uploaded_files_data:
                logger.warning("No data found for file: %s", file_name)
                continue
            file_data = uploaded_files_data[file_name]
            file_content = file_data.get("file_content")
            if not file_content:
                logger.warning("No content for file: %s", file_name)
                continue

            if file_data.get("is_json"):
                new_file_name = f"{sample_id}.{file_data['name']}"
            else:
                measurement_type = file_type_dict.get(sample_id, {}).get(file_name, "hy")
                file_extension = get_file_extension(file_name)
                base_name = ".".join(file_name.split(".")[:-1])
                if measurement_type == "jv" and file_data.get("epoch_time"):
                    base_name = f"{file_data['epoch_time']}_{base_name}"
                new_file_name = create_nomad_filename(
                    sample_id, base_name, measurement_type, file_extension
                )

            with ZipFile(upload_ids[upload_id], "a") as zf:
                zf.writestr(new_file_name, file_content)

    # Sized to the number of distinct uploads (not sample count -- many
    # samples commonly share one upload_id), so the bar actually reaches 100%.
    progress = widgets.FloatProgress(
        value=0.0,
        min=0.0,
        max=float(max(len(upload_ids), 1)),
        description="Uploading:",
        bar_style="info",
        orientation="horizontal",
        layout=widgets.Layout(width="500px"),
    )
    with out_widget:
        display(progress)

    for i, (upload_id, zip_file) in enumerate(upload_ids.items()):
        base = float(i)
        progress.value = base + 0.1  # ZIP ready, PUT about to start

        try:
            response = requests.put(
                f"{URL_API}/uploads/{upload_id}/raw/",
                data={"wait_for_processing": False},
                headers={"Authorization": f"Bearer {TOKEN}"},
                files={"file": ("data.zip", zip_file.getvalue(), "application/json")},
            )
            response.raise_for_status()
            progress.value = base + 0.4  # PUT acknowledged
        except Exception as exc:
            logger.error("Error uploading to %s: %s", upload_id, exc)
            with out_widget:
                print(f"Error uploading to {upload_id}: {exc}")
                print("Check access and restart voila!")

        time.sleep(1)
        _process_upload(upload_id, out_widget, progress, base + 0.4, base + 0.7)
        time.sleep(1)
        _process_upload(upload_id, out_widget, progress, base + 0.7, base + 1.0)
        progress.value = base + 1.0

    progress.bar_style = "success"
    with out_widget:
        print("Done!")


def _process_upload(upload_id, out_widget, progress_bar=None, current_value=0.0, total_value=1.0):
    requests.post(
        f"{URL_API}/uploads/{upload_id}/action/process",
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    fill = float(current_value)
    while True:
        time.sleep(2)
        resp = requests.get(
            f"{URL_API}/uploads/{upload_id}",
            headers={"Authorization": f"Bearer {TOKEN}"},
        )
        if not resp.json()["data"]["process_running"]:
            if progress_bar is not None:
                progress_bar.value = total_value
            break
        if progress_bar is not None:
            # Asymptotic fill: each poll closes 40 % of remaining distance so
            # the bar visibly advances every 2 s but never overshoots total_value.
            fill += (total_value - fill) * 0.4
            progress_bar.value = fill


# ---------------------------------------------------------------------------
# Guide
# ---------------------------------------------------------------------------
def display_guide():
    """Render a collapsible quick-start guide widget."""
    guide_button = widgets.Button(
        description="Show Guide",
        button_style="info",
        layout=widgets.Layout(width="150px", height="40px"),
    )
    guide_output = widgets.Output()
    guide_visible = [False]

    def toggle_guide(b):
        with guide_output:
            guide_output.clear_output()
            if not guide_visible[0]:
                display(HTML(_GUIDE_HTML))
                guide_button.description = "Hide Guide"
                guide_button.button_style = "warning"
                guide_visible[0] = True
            else:
                guide_button.description = "Show Guide"
                guide_button.button_style = "info"
                guide_visible[0] = False

    guide_button.on_click(toggle_guide)
    display(widgets.VBox([guide_button, guide_output], layout=widgets.Layout(margin="0 0 20px 0")))
