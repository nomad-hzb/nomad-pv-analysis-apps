import base64
import html
import io
import json
import logging
from datetime import datetime
from pathlib import Path

import ipywidgets as widgets
import nomad_prefill
from IPython.display import display

from hysprint_utils.manual import manual_panel
from hysprint_utils.process_specs import (
    ATMOSPHERIC_CONFIG_KEY,
    AVAILABLE_PROCESSES,
    PROCESSES,
    build_default_config_by_process_type,
)

logger = logging.getLogger(__name__)

_APP_DIR = Path(__file__).resolve().parent
DEFAULT_TEMPLATES_FILE = _APP_DIR / "templates" / "process_templates.json"


def default_templates() -> dict:
    """The built-in templates, used (in memory only) when the templates file cannot be read."""
    return {
        "empty_template": {
            "name": "Empty Template",
            "description": "Start with just Experiment Info",
            "category": "Basic",
            "process_sequence": [{"process": "Experiment Info"}],
        },
        "simple_coating": {
            "name": "Simple Coating",
            "description": "Basic coating process",
            "category": "Coating Processes",
            "process_sequence": [
                {"process": "Experiment Info"},
                {"process": "Cleaning O2-Plasma", "config": {"solvents": 2}},
                {
                    "process": "Spin Coating",
                    "config": {"solvents": 1, "solutes": 1, "spinsteps": 1},
                },
                {"process": "Evaporation"},
            ],
        },
    }


def _known_config_keys(process_name: str) -> set[str]:
    meta = PROCESSES.get(process_name, {}).get("meta", {})
    keys = {key for key, *_ in meta.get("numeric_config", [])}
    keys |= {key for key, *_ in meta.get("boolean_config", [])}
    return keys | {ATMOSPHERIC_CONFIG_KEY}


def validate_template(template) -> list[str]:
    """Why a template cannot be applied, as a list of plain sentences (empty when it can).

    A template needs a name and a process sequence, and every process in it must be one the
    app offers (an unknown name used to crash the process rows half way through applying it).
    Config keys the process does not know are not an error here: applying the template drops
    them."""
    if not isinstance(template, dict):
        return ["it is not a template entry"]
    problems = []
    if not template.get("name"):
        problems.append("it has no name")
    sequence = template.get("process_sequence")
    if not isinstance(sequence, list) or not sequence:
        problems.append("it has no process_sequence")
        return problems
    for position, step in enumerate(sequence, start=1):
        process = step.get("process") if isinstance(step, dict) else None
        if process not in AVAILABLE_PROCESSES:
            problems.append(f"step {position} uses the unknown process {process!r}")
    return problems


try:
    from experiment_excel_builder import ExperimentExcelBuilder

    EXCEL_BUILDER_AVAILABLE = True
except ImportError:
    EXCEL_BUILDER_AVAILABLE = False
    logger.warning("ExperimentExcelBuilder not found. Install it or check the import path.")


class MinimalistExperimentBuilder:
    def __init__(self, templates_file=None):
        self.templates_file = Path(templates_file) if templates_file else DEFAULT_TEMPLATES_FILE
        self.current_sequence = []
        self.templates = {}

        # Available process types - shared/hysprint_utils/process_specs.py is the single
        # source of truth (also used by smart_databaser's data_manager.py), so this list
        # and the config controls below can't silently drift out of sync the way they
        # once did (see process_specs.py's docstring for the history).
        self.available_processes = AVAILABLE_PROCESSES

        self.setup_widgets()
        self.load_templates()

        # Add default Experiment Info process
        self.current_sequence = [{"process": "Experiment Info"}]
        self._update_process_display()

    def load_templates(self):
        """Load the templates from the JSON file. A file that is missing or cannot be read
        never gets overwritten: the built-in templates are used in memory instead and the
        reason is shown in the status area. Templates that cannot be applied are left out of
        the dropdown, each with the reason."""
        raw = {}
        try:
            if self.templates_file.exists():
                with open(self.templates_file, encoding="utf-8") as f:
                    raw = json.load(f).get("templates", {})
            else:
                self._status(
                    f"Template file {self.templates_file} not found, using the built-in templates.",
                    "warning",
                )
                raw = default_templates()
        except Exception as exc:  # noqa: BLE001
            logger.error("Error loading templates: %s", exc)
            self._status(
                f"Could not read the templates file ({exc}). Using the built-in templates; "
                "the file was not changed.",
                "error",
            )
            raw = default_templates()

        self.templates = {}
        for key, template in raw.items():
            problems = validate_template(template)
            if problems:
                self._status(f"Template '{key}' skipped: {'; '.join(problems)}.", "warning")
            else:
                self.templates[key] = template
        logger.info("Loaded %d templates.", len(self.templates))
        self._update_template_dropdown()

    def _status(self, message, kind="info"):
        """Show a message in the Status panel (logging alone is never rendered under Voila)."""
        icon = {"error": "❌", "warning": "⚠️", "success": "✅"}.get(kind, "")
        with self.status_output:
            print(f"{icon} {message}".strip())
        logger.log(
            {"error": logging.ERROR, "warning": logging.WARNING}.get(kind, logging.INFO), message
        )

    def setup_widgets(self):
        """Initialize all widgets"""
        # Template selection
        self.template_dropdown = widgets.Dropdown(
            options=["Select template..."],
            description="Template:",
            style={"description_width": "80px"},
            layout=widgets.Layout(width="300px"),
        )

        self.apply_button = widgets.Button(
            description="Apply", button_style="primary", layout=widgets.Layout(width="80px")
        )

        # Process sequence area
        self.process_sequence_area = widgets.VBox([])

        # Generation controls
        # Unticked while the prefill panel is open (_on_prefill_toggle): a prefilled file is
        # meant to be uploaded, and an example row left in it would become a sample.
        self.is_testing_checkbox = widgets.Checkbox(
            value=True,
            description="Add example values on 1st row",
            style={"description_width": "initial"},
        )

        self.include_readme_checkbox = widgets.Checkbox(
            value=False,
            description="Create README.md for annotations",
            style={"description_width": "initial"},
        )

        self.generate_button = widgets.Button(
            description="Generate Excel",
            button_style="success",
            layout=widgets.Layout(width="150px"),
        )

        self.download_area = widgets.HTML(value="")
        self.status_output = widgets.Output()

        # Prefill from NOMAD: hidden in normal use, opened by its own button. Nothing is
        # fetched until the panel is opened.
        self.prefill_toggle = widgets.ToggleButton(
            value=False,
            description="Prefill from NOMAD",
            icon="download",
            tooltip=(
                "Fill one row per sample of one of your NOMAD uploads: its Nomad ID and what "
                "NOMAD knows of the sample and its substrate"
            ),
            layout=widgets.Layout(width="180px", margin="0 0 0 10px"),
        )
        self.prefill_upload_dropdown = widgets.Dropdown(
            options=[(self.PREFILL_PLACEHOLDER, None)],
            value=None,
            description="NOMAD upload:",
            style={"description_width": "initial"},
            layout=widgets.Layout(width="600px"),
        )
        self.prefill_info = widgets.HTML(value="")
        # What NOMAD's Excel parser does with the file (nomad-hysprint HySprintExperimentParser:
        # it writes every entry with create_archive, which never replaces an existing file).
        self.prefill_note = widgets.HTML(
            value=(
                "<div style='font-size: 0.9em; color: #555; max-width: 600px;'>"
                "Upload the generated file into <b>this same upload</b>: only there are the new "
                "processes linked to these samples. Samples and process steps that already exist "
                "in the upload are kept as they are; new values for them in this file are "
                "ignored. Measurements need no new Excel.</div>"
            )
        )
        self.prefill_panel = widgets.VBox(
            [self.prefill_upload_dropdown, self.prefill_info, self.prefill_note],
            layout=widgets.Layout(display="none", margin="0 0 10px 0"),
        )
        self.prefill_samples = []
        self._prefill_connection = None  # (url, token) once the uploads were loaded
        self._example_row_before_prefill = self.is_testing_checkbox.value

        # Event handlers
        self.apply_button.on_click(self._on_apply_template)
        self.generate_button.on_click(self._on_generate_excel)
        self.prefill_toggle.observe(self._on_prefill_toggle, names="value")
        self.prefill_upload_dropdown.observe(self._on_prefill_upload_change, names="value")

    PREFILL_PLACEHOLDER = "Select an upload..."

    def _prefill_message(self, message, kind="info"):
        color = {"error": "#c0392b", "warning": "#b9770e"}.get(kind, "#2c3e50")
        self.prefill_info.value = f"<span style='color: {color};'>{html.escape(message)}</span>"

    def _on_prefill_toggle(self, change):
        """Open or close the prefill panel. The first opening loads the uploads; a closed
        panel means no prefill, whatever upload was chosen in it. Opening unticks the example
        row and closing gives it back the value it had before."""
        self.prefill_panel.layout.display = None if change["new"] else "none"
        if change["new"]:
            self._example_row_before_prefill = self.is_testing_checkbox.value
            self.is_testing_checkbox.value = False
        else:
            self.is_testing_checkbox.value = self._example_row_before_prefill
        if change["new"] and self._prefill_connection is None:
            self._load_prefill_uploads()

    def _load_prefill_uploads(self):
        self._prefill_message("Loading your NOMAD uploads...")
        try:
            url, token = nomad_prefill.connect()
            uploads = nomad_prefill.fetch_uploads(url, token)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Could not load the NOMAD uploads")
            self._prefill_message(f"Could not load your NOMAD uploads: {exc}", "error")
            return
        self._prefill_connection = (url, token)
        self.prefill_upload_dropdown.options = [
            (self.PREFILL_PLACEHOLDER, None),
            *nomad_prefill.upload_choices(uploads),
        ]
        self.prefill_upload_dropdown.value = None
        if uploads:
            self._prefill_message(f"{len(uploads)} uploads found. Pick the one of this batch.")
        else:
            self._prefill_message("You have no NOMAD uploads.", "warning")

    def _on_prefill_upload_change(self, change):
        """Fetch the samples of the chosen upload, so the user sees what will be filled."""
        self.prefill_samples = []
        upload_id = change["new"]
        if upload_id is None or self._prefill_connection is None:
            self._prefill_message("")
            return
        self._prefill_message("Loading the samples of this upload...")
        try:
            self.prefill_samples = nomad_prefill.fetch_samples_in_upload(
                *self._prefill_connection, upload_id
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("Could not load the samples of upload %s", upload_id)
            self._prefill_message(f"Could not load the samples of this upload: {exc}", "error")
            return
        if self.prefill_samples:
            first, last = self.prefill_samples[0].lab_id, self.prefill_samples[-1].lab_id
            columns = ", ".join(nomad_prefill.filled_columns(self.prefill_samples))
            self._prefill_message(
                f"{len(self.prefill_samples)} samples ({first} to {last}). Filled columns: "
                f"{columns}."
            )
        else:
            self._prefill_message("This upload has no samples.", "warning")

    def _samples_to_prefill(self):
        """The samples to write into the sheet: only while the prefill panel is open."""
        return self.prefill_samples if self.prefill_toggle.value else []

    def _update_template_dropdown(self):
        """Update template dropdown with all available templates"""
        template_names = ["Select template..."] + [t["name"] for t in self.templates.values()]
        self.template_dropdown.options = template_names

    def _on_apply_template(self, button):
        """Apply selected template"""
        template_name = self.template_dropdown.value
        self.status_output.clear_output()
        if template_name == "Select template...":
            self._status("Please select a template.", "warning")
            return

        # Find template
        selected_template = None
        for template in self.templates.values():
            if template["name"] == template_name:
                selected_template = template
                break

        if selected_template:
            # Deep copy the process sequence
            self.current_sequence = []
            dropped = []
            for process in selected_template["process_sequence"]:
                new_process = {"process": process["process"]}
                if "config" in process:
                    known = _known_config_keys(process["process"])
                    new_process["config"] = {
                        k: v for k, v in process["config"].items() if k in known
                    }
                    dropped += [
                        f"{process['process']}: {k}" for k in process["config"] if k not in known
                    ]
                self.current_sequence.append(new_process)

            self._update_process_display()
            self._status(
                f"Applied {template_name} ({len(self.current_sequence)} processes).", "success"
            )
            if dropped:
                self._status(
                    f"Ignored settings this process does not have: {', '.join(dropped)}.", "warning"
                )

    def _update_process_display(self):
        """Update the process sequence display"""
        if not self.current_sequence:
            self.process_sequence_area.children = []
            return

        process_rows = []

        for i, process_data in enumerate(self.current_sequence):
            row = self._create_process_row(i, process_data)
            process_rows.append(row)

        self.process_sequence_area.children = process_rows

    def _create_process_row(self, index, process_data):
        """Create a single row for a process"""
        process_name = process_data["process"]
        # A control shows config.get(key, minimum), but the sheet is built from the config
        # alone: write the minimum in, so what is shown is what is generated (a template without
        # "spinsteps" showed "Steps: 1" and generated no rotation columns).
        meta = PROCESSES.get(process_name, {}).get("meta", {})
        for key, _label, min_val, _max_val in meta.get("numeric_config", []):
            if key not in process_data.get("config", {}):
                process_data.setdefault("config", {})[key] = min_val
        config = process_data.get("config", {})

        # Index label
        index_label = widgets.HTML(
            value=f"<span style='font-weight: bold; color: #666; min-width: 25px; display: inline-block;'>{index + 1}.</span>",  # noqa: E501
            layout=widgets.Layout(width="30px"),
        )

        # Process type dropdown
        process_dropdown = widgets.Dropdown(
            options=self.available_processes,
            value=process_name,
            layout=widgets.Layout(width="180px"),
            disabled=(index == 0),  # Can't change Experiment Info
        )
        process_dropdown.observe(
            lambda change, idx=index: self._update_process_type(idx, change["new"]), names="value"
        )

        # Configuration controls
        numeric_controls, checkbox_controls = self._create_inline_config_controls(
            index, process_name, config
        )

        # Action buttons (always on the right)
        action_buttons = self._create_action_buttons(index)

        # Main row with numeric controls
        main_row_elements = [index_label, process_dropdown] + numeric_controls

        # Add spacer to push buttons to the right
        spacer = widgets.HTML(value="", layout=widgets.Layout(flex="1"))
        main_row_elements.append(spacer)
        main_row_elements.extend(action_buttons)

        main_row = widgets.HBox(
            main_row_elements,
            layout=widgets.Layout(
                margin="1px 0",
                padding="5px",
                border="1px solid #e0e0e0",
                border_radius="4px 4px 0 0" if checkbox_controls else "4px",
                align_items="center",
            ),
        )

        # If there are checkboxes, create a second row
        if checkbox_controls:
            checkbox_row_elements = [
                widgets.HTML(value="", layout=widgets.Layout(width="30px")),  # Align with index
                widgets.HTML(value="", layout=widgets.Layout(width="180px")),  # Align with dropdown
            ]
            checkbox_row_elements.extend(checkbox_controls)

            checkbox_row = widgets.HBox(
                checkbox_row_elements,
                layout=widgets.Layout(
                    margin="0",
                    padding="5px",
                    border="1px solid #e0e0e0",
                    border_top="none",
                    border_radius="0 0 4px 4px",
                    align_items="center",
                ),
            )

            # Return container with both rows
            return widgets.VBox([main_row, checkbox_row], layout=widgets.Layout(margin="2px 0"))
        else:
            return main_row

    def _create_inline_config_controls(self, index, process_name, config):
        """Create inline configuration controls - returns (numeric_controls, checkbox_controls)

        Numeric/checkbox controls are rendered generically from
        PROCESSES[process_name]["meta"]["numeric_config"/"boolean_config"] in
        shared/hysprint_utils/process_specs.py, instead of one hand-written
        if/elif block per process type - the exact pattern gui_components.py's
        own _sync_config_controls already used, now shared by both apps' GUIs
        so a new process type's controls can't be added to one and missed in
        the other."""
        numeric_controls = []
        checkbox_controls = []

        # Add Atmospheric Values checkbox for all processes except Experiment Info
        # This must be added BEFORE the early return for non-configurable processes
        if process_name != "Experiment Info":
            atmospheric_checkbox = widgets.Checkbox(
                value=config.get("add_atmospheric", False),
                description="Add Atmospheric Values",
                style={"description_width": "initial"},
                layout=widgets.Layout(width="190px"),
            )
            atmospheric_checkbox.observe(
                lambda change, idx=index: self._update_config(
                    idx, "add_atmospheric", change["new"]
                ),
                names="value",
            )
            checkbox_controls.append(atmospheric_checkbox)

        meta = PROCESSES.get(process_name, {}).get("meta", {})

        for key, label, min_val, max_val in meta.get("numeric_config", []):
            widget = widgets.BoundedIntText(
                value=config.get(key, min_val),
                min=min_val,
                max=max_val,
                description=f"{label}:",
                style={"description_width": "initial"},
                layout=widgets.Layout(width="130px"),
            )
            widget.observe(
                lambda change, idx=index, k=key: self._update_config(idx, k, change["new"]),
                names="value",
            )
            numeric_controls.append(widget)

        for key, label in meta.get("boolean_config", []):
            checkbox = widgets.Checkbox(
                value=config.get(key, False),
                description=label,
                style={"description_width": "initial"},
                layout=widgets.Layout(width="150px"),
            )
            checkbox.observe(
                lambda change, idx=index, k=key: self._update_config(idx, k, change["new"]),
                names="value",
            )
            checkbox_controls.append(checkbox)

        return numeric_controls, checkbox_controls

    def _create_action_buttons(self, index):
        """Create action buttons for a process row"""
        buttons = []

        # Add button (insert process below)
        add_button = widgets.Button(
            description="",
            icon="plus",
            button_style="success",
            layout=widgets.Layout(width="30px", height="28px"),
        )
        add_button.on_click(lambda b, idx=index: self._add_process_below(idx))
        buttons.append(add_button)

        # Remove button (can't remove Experiment Info)
        if index > 0:
            remove_button = widgets.Button(
                description="",
                icon="minus",
                button_style="danger",
                layout=widgets.Layout(width="30px", height="28px"),
            )
            remove_button.on_click(lambda b, idx=index: self._remove_process(idx))
            buttons.append(remove_button)
        else:
            # Spacer for Experiment Info row
            spacer = widgets.HTML(value="", layout=widgets.Layout(width="30px"))
            buttons.append(spacer)

        return buttons

    def _update_process_type(self, index, new_process_type):
        """Update process type"""
        if index < len(self.current_sequence):
            self.current_sequence[index]["process"] = new_process_type

            # Reset config when changing process type: every type with defaults in the
            # catalogue gets them, every other type none. (A hand-kept list of 7 types used
            # to leave Co-Evaporation/Ink Recycling without a config, so their controls showed
            # "Materials: 1" while the sheet generated no material columns.)
            defaults = self._get_default_config(new_process_type)
            if defaults:
                self.current_sequence[index]["config"] = defaults
            else:
                self.current_sequence[index].pop("config", None)

            self._update_process_display()

    def _get_default_config(self, process_name):
        """Get default configuration for a process - shared/hysprint_utils/
        process_specs.py is the single source of truth (see also data_manager.py's
        DEFAULT_CONFIG_BY_PROCESS_TYPE, derived from the same function)."""
        return build_default_config_by_process_type().get(process_name, {})

    def _update_config(self, process_index, key, value):
        """Update configuration for a process"""
        if process_index < len(self.current_sequence):
            if "config" not in self.current_sequence[process_index]:
                self.current_sequence[process_index]["config"] = {}

            self.current_sequence[process_index]["config"][key] = value

    def _add_process_below(self, index):
        """Add a new process below the current one"""
        new_process = {"process": "Generic Process"}
        self.current_sequence.insert(index + 1, new_process)
        self._update_process_display()
        self.status_output.clear_output()
        self._status(f"Added a process at position {index + 2}.")

    def _remove_process(self, index):
        """Remove a process (can't remove Experiment Info)"""
        if index > 0 and index < len(self.current_sequence):
            removed_process = self.current_sequence.pop(index)
            self._update_process_display()
            self.status_output.clear_output()
            self._status(f"Removed {removed_process['process']}.")

    def _on_generate_excel(self, button):
        """Generate the Excel file, or say why it could not be generated (never a placeholder
        file: those used to be offered as "Excel Ready" and uploaded to NOMAD)."""
        self.status_output.clear_output()
        self.download_area.value = ""
        if not self.current_sequence:
            self._status("No processes configured.", "warning")
            return

        try:
            samples = self._samples_to_prefill()
            excel_data = self._generate_excel_data(samples)
            filename = f"experiment_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
            self.download_area.value = self._create_download_link(excel_data, filename)
            self._status(f"Excel file generated: {filename}", "success")
            if samples:
                self._status(f"Prefilled {len(samples)} samples from NOMAD.", "success")

            if self.include_readme_checkbox.value:
                readme_html = self._create_readme_download_link(
                    self._generate_readme(), "README.md"
                )
                self.download_area.value += readme_html
        except Exception as exc:  # noqa: BLE001
            logger.exception("Excel generation failed")
            self._status(f"The Excel file could not be generated: {exc}", "error")

    def _generate_excel_data(self, samples=None):
        """The Excel file's bytes from ExperimentExcelBuilder; raises when it cannot be built.
        samples: PrefillSamples to prefill, or None."""
        if not EXCEL_BUILDER_AVAILABLE:
            raise RuntimeError("ExperimentExcelBuilder is not available (import failed).")
        rows = [sample.as_row() for sample in samples or []]
        builder = ExperimentExcelBuilder(
            self.current_sequence, self.is_testing_checkbox.value, samples=rows or None
        )
        builder.build_excel()
        buffer = io.BytesIO()
        builder.workbook.save(buffer)
        excel_data = buffer.getvalue()
        if not excel_data.startswith(b"PK"):
            raise RuntimeError("the generated file is not a valid Excel workbook")
        return excel_data

    def _generate_readme(self):
        """Generate README.md template"""
        readme_template = """# Scientific Question
(What specific hypothesis or question does this experiment address?)

> Example: Does annealing temperature affect the VOC of triple-cation perovskite devices?

---

# Approach
(Briefly describe the experimental design, key parameters, and any deviations from standard
protocol.)

## Conditions
| Parameter | Value |
|-----------|-------|
| ... | ... |

## Method
"""

        # Add process sequence
        for i, process in enumerate(self.current_sequence, 1):
            readme_template += f"{i}. {process['process']}"
            if "config" in process and process["config"]:
                config_str = ", ".join([f"{k}={v}" for k, v in process["config"].items()])
                readme_template += f" ({config_str})"
            readme_template += "\n"

        readme_template += """
---

# Results
(Summarize the key outputs. Link to data files or NOMAD entries where relevant.)

- **Key finding:** ...
- **Data location:** `path/to/data` or [NOMAD entry](#)

---

# Learnings
(What do the results tell you? What was surprising or confirmed?)

## Interpretation
...

## Caveats / Limitations
- ...

---

# Next Steps
(Concrete follow-up actions, not just observations.)
- [ ] Task one (owner, deadline)
- [ ] Task two

---

# References
- Related experiments: [link]
- Protocol used: [link]
"""

        return readme_template

    def _create_download_link(self, excel_data, filename):
        """Create download link"""
        b64_data = base64.b64encode(excel_data).decode()
        mime = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        testing = "On" if self.is_testing_checkbox.value else "Off"

        return f"""
        <div style="padding: 12px; background-color: #d4edda; border: 1px solid #c3e6cb;
                    border-radius: 6px; margin: 10px 0;">
            <div style="display: flex; align-items: center; margin-bottom: 8px;">
                <span style="font-size: 18px; margin-right: 8px;">📊</span>
                <strong style="color: #155724;">Excel Ready</strong>
            </div>
            <div style="font-size: 14px; color: #155724; margin-bottom: 10px;">
                {filename} • {len(self.current_sequence)} processes • Testing: {testing}
            </div>
            <a href="data:{mime};base64,{b64_data}"
               download="{filename}" 
               style="display: inline-block; padding: 8px 16px; background-color: #28a745;
                      color: white; text-decoration: none; border-radius: 4px;
                      font-weight: bold; font-size: 14px;">
                📥 Download
            </a>
        </div>
        """

    def _create_readme_download_link(self, readme_content, filename):
        """Create download link for README file"""
        b64_data = base64.b64encode(readme_content.encode("utf-8")).decode()

        return f"""
        <div style="padding: 12px; background-color: #e7f3ff; border: 1px solid #b3d9ff;
                    border-radius: 6px; margin: 10px 0;">
            <div style="display: flex; align-items: center; margin-bottom: 8px;">
                <span style="font-size: 18px; margin-right: 8px;">📝</span>
                <strong style="color: #004085;">README Template</strong>
            </div>
            <div style="font-size: 14px; color: #004085; margin-bottom: 10px;">
                {filename} • Experiment documentation template
            </div>
            <a href="data:text/markdown;base64,{b64_data}" 
               download="{filename}" 
               style="display: inline-block; padding: 8px 16px; background-color: #007bff;
                      color: white; text-decoration: none; border-radius: 4px;
                      font-weight: bold; font-size: 14px;">
                📥 Download README
            </a>
        </div>
        """

    def display(self):
        """Display the interface"""

        # Compact header
        header = widgets.HTML(
            value="""
            <div style="padding: 15px; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                        color: white; border-radius: 8px; margin-bottom: 20px;">
                <h2 style="margin: 0 0 5px 0; font-size: 1.8em;">🧪 Experiment Builder</h2>
                <p style="margin: 0; font-size: 0.95em; opacity: 0.9;">
                    Configure processes and generate Excel files</p>
            </div>
            """
        )

        # Template selection - compact
        template_section = widgets.VBox(
            [
                manual_panel(__file__),
                widgets.HTML(
                    value="<h4 style='margin: 15px 0 8px 0; color: #2c3e50;'>📋 Template</h4>"
                ),
                widgets.HBox(
                    [self.template_dropdown, self.apply_button],
                    layout=widgets.Layout(margin="0 0 15px 0"),
                ),
            ]
        )

        # Process sequence - compact
        sequence_section = widgets.VBox(
            [
                widgets.HTML(
                    value="<h4 style='margin: 15px 0 8px 0; color: #2c3e50;'>⚙️ Process Sequence</h4>"  # noqa: E501
                ),
                self.process_sequence_area,
            ]
        )

        # Generation - compact
        generation_section = widgets.VBox(
            [
                widgets.HTML(
                    value="<h4 style='margin: 15px 0 8px 0; color: #2c3e50;'>📊 Generate</h4>"
                ),
                widgets.VBox(
                    [self.is_testing_checkbox, self.include_readme_checkbox],
                    layout=widgets.Layout(margin="0 0 10px 0"),
                ),
                widgets.HBox(
                    [self.generate_button, self.prefill_toggle],
                    layout=widgets.Layout(margin="0 0 10px 0"),
                ),
                self.prefill_panel,
                self.download_area,
            ]
        )

        # Status - compact
        status_section = widgets.VBox(
            [
                widgets.HTML(
                    value="<h5 style='margin: 15px 0 5px 0; color: #7f8c8d;'>📝 Status</h5>"
                ),
                self.status_output,
            ]
        )

        # Main interface - more compact
        main_interface = widgets.VBox(
            [header, template_section, sequence_section, generation_section, status_section],
            layout=widgets.Layout(padding="15px", max_width="1000px"),
        )

        # Only display once, don't return the interface to avoid duplication
        display(main_interface)


# Convenience function
def create_experiment_app(templates_file=None):
    """Create and display the experiment builder interface"""
    app = MinimalistExperimentBuilder(templates_file)
    app.display()
    return app


def main():
    """Main function"""
    return create_experiment_app()
