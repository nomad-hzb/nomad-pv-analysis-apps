# gui_layouts.py
"""
GUI layouts and main application class
Assembles widgets into layouts and contains all application logic
"""

import logging
import os
import warnings

import config
import ipywidgets as widgets
import numpy as np
from background_handlers import BackgroundHandlersMixin
from data_manager import DataManager
from exporters import ResultExporter
from fit_handlers import FitHandlersMixin
from fitting_engine import FittingEngine
from gui_components import GUIComponents
from IPython.display import display
from plot_manager import PlotManager
from utils import debug_output, debug_print

from hysprint_utils.manual import manual_panel

warnings.filterwarnings("ignore", message="Using UFloat objects with std_dev==0")

logger = logging.getLogger(__name__)

# Initialize ipyvuetify FileInput (prevent initialization error)
try:
    from ipyvuetify.extra import FileInput
    from ipyvuetify.extra.file_input import ClientSideFile

    # Create a temporary FileInput to initialize the library
    temp_file_input = FileInput()
    temp_file_input.file_info = [{"name": "test.csv", "size": 100, "lastModified": 0, "type": ""}]
    try:
        c = ClientSideFile(temp_file_input, 0, 1)
        d = c.read()
    except Exception:
        pass
    temp_file_input.file_info = []
    logger.info("ipyvuetify FileInput initialized")
except Exception as e:
    logger.warning("ipyvuetify initialization warning: %s", e)


def _slider_step(span, steps=1000):
    """Round step (a power of ten) giving about `steps` steps across `span`, and the
    number of decimals needed to show it: span 2 -> (0.001, 3), span 5000 -> (1, 0)."""
    if not np.isfinite(span) or span <= 0:
        return 0.1, 1
    exponent = int(np.floor(np.log10(span / steps)))
    return 10.0**exponent, max(0, -exponent)


# =============================================================================
# GUI LAYOUTS
# =============================================================================


class GUILayouts:
    """Assembles GUI layouts from components"""

    def __init__(self, gui_components):
        """
        Parameters:
        -----------
        gui_components : GUIComponents
            GUI components instance with all widgets
        """
        self.components = gui_components
        self.widgets = gui_components.get_all_widgets()

    def create_file_section(self):
        """Create file loading section"""
        if self.components.h5_available:
            section = widgets.VBox(
                [
                    widgets.HTML("<h3>📁 Data Loading</h3>"),
                    self.widgets["h5_filename_label"],
                    self.widgets["mode_dropdown"],
                    widgets.HTML("<i>or upload a CSV file instead:</i>"),
                    self.widgets["file_upload"],
                    self.widgets["csv_density_checkbox"],
                    widgets.HBox(
                        [self.widgets["convert_energy_btn"], self.widgets["energy_unit_display"]]
                    ),
                ]
            )
        else:
            section = widgets.VBox(
                [
                    widgets.HTML("<h3>📁 Data Loading</h3>"),
                    self.widgets["file_upload"],
                    self.widgets["csv_density_checkbox"],
                    widgets.HBox(
                        [self.widgets["convert_energy_btn"], self.widgets["energy_unit_display"]]
                    ),
                ]
            )

        debug_print("Created file section layout", "GUI")
        return section

    def create_time_control_section(self):
        """Create time control section with wavelength range"""
        section = widgets.VBox(
            [
                widgets.HTML("<h3>⏱️ Time Control</h3>"),
                widgets.HBox([self.widgets["time_input"], self.widgets["time_display"]]),
                self.widgets["time_slider"],
                widgets.HTML("<b>Wavelength Range:</b>"),
                self.widgets["wavelength_range_slider"],
            ]
        )

        debug_print("Created time control section layout", "GUI")
        return section

    def create_colorbar_section(self):
        """Create colorbar control section (collapsible)"""
        content_widgets = [
            self.widgets["colorbar_range_slider"],
            self.widgets["colorbar_apply_btn"],
        ]

        section = self.components.create_collapsible_section("🎨 Heatmap Colors", content_widgets)

        # Set to collapsed by default
        section.selected_index = None

        debug_print("Created colorbar section layout", "GUI")
        return section

    def create_background_section(self):
        """Create unified background handling section"""
        # Create containers for each method
        manual_container = widgets.VBox(
            [
                self.widgets["bg_manual_description"],
                widgets.HBox([self.widgets["bg_manual_start"], self.widgets["bg_manual_num"]]),
            ]
        )

        linear_container = widgets.VBox(
            [widgets.HBox([self.widgets["bg_linear_slope"], self.widgets["bg_linear_intercept"]])]
        )

        poly_container = widgets.VBox(
            [self.widgets["bg_poly_degree"], self.widgets["bg_poly_coeffs"]]
        )

        exp_container = widgets.VBox(
            [
                widgets.HBox([self.widgets["bg_exp_amplitude"], self.widgets["bg_exp_decay"]]),
                self.widgets["bg_exp_offset"],
            ]
        )

        custom_container = widgets.VBox(
            [
                self.widgets["bg_custom_description"],
                self.widgets["bg_custom_upload"],
                self.widgets["bg_custom_status"],
            ]
        )

        # Store containers for later access
        self._bg_containers = {
            "Manual": manual_container,
            "Linear": linear_container,
            "Polynomial": poly_container,
            "Exponential": exp_container,
            "Custom": custom_container,
        }

        # HIDE ALL CONTAINERS INITIALLY
        for container in self._bg_containers.values():
            container.layout.visibility = "hidden"
            container.layout.display = "none"

        # Method-specific area that shows only ONE container at a time
        self._method_area = widgets.VBox(
            [manual_container, linear_container, poly_container, exp_container, custom_container],
            layout=widgets.Layout(min_height="80px", max_height="150px"),
        )

        content_widgets = [
            self.widgets["background_method"],
            self._method_area,
            widgets.HBox(
                [
                    self.widgets["bg_autofit_btn"],
                    self.widgets["bg_apply_btn"],
                    self.widgets["bg_remove_btn"],
                ]
            ),
        ]

        section = self.components.create_collapsible_section(
            "🎨 Background Handling", content_widgets
        )

        # Set to collapsed by default
        section.selected_index = None

        # Store reference for later access
        self._background_section = section

        debug_print("Created background section layout", "GUI")
        return section

    def create_fitting_actions_section(self):
        """Create fitting actions section"""
        section = widgets.VBox(
            [
                widgets.HTML("<h3>🔧 Fitting Actions</h3>"),
                widgets.HBox([self.widgets["fit_current_btn"], self.widgets["update_params_btn"]]),
                self.widgets["r_squared_display"],
            ]
        )

        debug_print("Created fitting actions section layout", "GUI")
        return section

    def create_peak_detection_section(self):
        """Create peak detection and fitting section (collapsible)"""
        # Detection parameters: labels on top, widgets below
        param_labels = widgets.HBox(
            [
                widgets.Label("Height:", layout=widgets.Layout(width="100px")),
                widgets.Label("Prominence:", layout=widgets.Layout(width="100px")),
                widgets.Label("Distance (pts):", layout=widgets.Layout(width="100px")),
            ]
        )

        param_widgets = widgets.HBox(
            [
                self.widgets["peak_height_threshold"],
                self.widgets["peak_prominence"],
                self.widgets["peak_distance"],
            ]
        )

        content_widgets = [
            widgets.HTML("<b>Auto-Detection:</b>"),
            self.widgets["auto_detect_btn"],
            widgets.HTML("<b>Detection Parameters:</b>"),
            param_labels,
            param_widgets,
            widgets.HTML("<hr>"),
            widgets.HTML("<b>Peak Models:</b>"),
            self.widgets["add_peak_btn"],
            self.widgets["center_bound_input"],
            self.widgets["peak_list_container"],
        ]

        section = self.components.create_collapsible_section(
            "🔍 Peak Detection & Models", content_widgets
        )

        debug_print("Created peak detection section layout", "GUI")
        return section

    def create_batch_fitting_section(self):
        """Create batch fitting section with unit conversion at bottom"""
        section = widgets.VBox(
            [
                widgets.HTML("<h3>📊 Batch Fitting</h3>"),
                widgets.HTML("<b>Range Selection:</b>"),
                widgets.HBox([self.widgets["fit_start_idx"], self.widgets["fit_end_idx"]]),
                widgets.HTML("<b>Batch Actions:</b>"),
                self.widgets["fit_sequential_checkbox"],
                widgets.HBox([self.widgets["fit_all_btn"], self.widgets["fit_all_range_btn"]]),
                self.widgets["fit_progress"],  # Add progress bar
                widgets.HBox(
                    [
                        self.widgets["export_btn"],
                        self.widgets["save_h5_btn"],
                    ]
                ),
                self.widgets["export_output"],
                widgets.HTML("<hr>"),
            ]
        )

        debug_print("Created batch fitting section layout", "GUI")
        return section

    def create_fitting_control_section(self):
        """Create complete fitting control section"""
        section = widgets.VBox(
            [
                self.create_background_section(),
                self.create_peak_detection_section(),
                self.create_fitting_actions_section(),
                self.create_batch_fitting_section(),
            ],
            layout=widgets.Layout(width=config.CONTROL_PANEL_WIDTH),
        )

        debug_print("Created fitting control section layout", "GUI")
        return section

    def create_fit_visualisation_section(self):
        """Create fit visualisation section with slider navigation"""
        slider_row = widgets.HBox(
            [
                self.widgets["fit_vis_slider"],
                self.widgets["fit_vis_show_components"],
                self.widgets["fit_vis_label"],
            ]
        )
        return widgets.VBox(
            [widgets.HTML("<h4>Fit Visualisation</h4>"), slider_row, self.widgets["fit_vis_output"]]
        )

    def create_visualization_section(self):
        """Create visualization section"""
        section = widgets.VBox(
            [
                widgets.HTML("<h3>📊 Visualizations</h3>"),
                widgets.HTML("<h4>Heatmap</h4>"),
                self.widgets["heatmap_output"],
                widgets.HTML("<h4>Current Spectrum</h4>"),
                self.widgets["spectrum_output"],
                widgets.HTML("<h4>Time Series Analysis</h4>"),
                self.widgets["time_series_output"],
                self.create_fit_visualisation_section(),
            ],
            layout=widgets.Layout(flex="2", width="auto"),
        )

        debug_print("Created visualization section layout", "GUI")
        return section

    def create_control_panel(self):
        """Create complete control panel (left side)"""
        control_panel = widgets.VBox(
            [
                widgets.HTML("<h3>📋 Status</h3>"),
                self.widgets["status_output"],
                widgets.HTML("<hr>"),
                self.create_file_section(),
                self.create_time_control_section(),
                self.create_colorbar_section(),
                self.create_fitting_control_section(),
            ],
            layout=widgets.Layout(
                width=config.CONTROL_PANEL_WIDTH,
                padding="10px",
                border="1px solid #ddd",
                margin="0px 10px 0px 0px",
            ),
        )

        debug_print("Created control panel layout", "GUI")
        return control_panel

    def create_main_layout(self):
        """Create complete main layout"""
        # Header
        header = widgets.HTML("<h1>🔬 Peak Analysis App</h1>")

        # Main content (control panel + visualization)
        main_content = widgets.HBox(
            [self.create_control_panel(), self.create_visualization_section()],
            layout=widgets.Layout(width="100%", height="auto"),
        )

        debug_print("Created main layout", "GUI")
        return header, main_content


# =============================================================================
# MAIN APPLICATION CLASS
# =============================================================================


class PLAnalysisApp(BackgroundHandlersMixin, FitHandlersMixin):
    """Main Photoluminescence Analysis Application"""

    def __init__(self):
        """Initialize the application"""
        debug_print("Initializing PLAnalysisApp", "APP")

        # Initialize managers
        self.data_manager = DataManager()
        self.fitting_engine = FittingEngine()
        self.plot_manager = PlotManager()
        self.plot_manager.app_ref = self
        debug_print("PlotManager app_ref set", "APP")
        self.export_utils = ResultExporter()

        # Initialize GUI components
        self.gui_components = GUIComponents(h5_available=self.data_manager.is_h5_available())
        self.gui_components.create_all_widgets()

        self.gui_layouts = GUILayouts(self.gui_components)

        # Get widget references for easy access
        self.widgets = self.gui_components.get_all_widgets()

        self.wavelength_unit = None  # Track current wavelength unit ('nm' or 'angstrom')

        # State management
        self.peak_models = []  # List of peak model widgets
        self._peak_counter = 0  # Id of the next peak row: never reused, so a removal cannot clash
        self.last_fit_result = None
        self.original_data_matrix = None  # For background subtraction
        self.background_applied = False
        self.background_accordion = None  # Reference to background accordion
        self._fit_vis_indices = []  # Sorted list of successful fit result indices

        # Setup UI and connect callbacks
        self.setup_callbacks()

        # If H5 data is available, trigger initial load
        if self.data_manager.is_h5_available():
            debug_print("H5 data available, triggering initial load", "APP")
            self.on_file_upload({"new": [None]})

    def setup_callbacks(self):
        """Connect all UI callbacks"""
        debug_print("Setting up UI callbacks", "APP")

        # File upload callbacks
        if self.data_manager.is_h5_available():
            self.widgets["mode_dropdown"].observe(self.on_file_upload, names="value")
        self.widgets["file_upload"].observe(self.on_file_upload, names="file_info")
        self.widgets["csv_density_checkbox"].observe(self.on_csv_density_change, names="value")

        # Time control callbacks
        self.widgets["time_slider"].observe(self.on_time_change_slider, names="value")
        self.widgets["time_input"].observe(self.on_time_change_input, names="value")

        # Peak detection and model callbacks
        self.widgets["auto_detect_btn"].on_click(self.on_auto_detect_peaks)
        self.widgets["add_peak_btn"].on_click(self.on_add_peak)

        # Fitting action callbacks
        self.widgets["fit_current_btn"].on_click(self.on_fit_current)
        self.widgets["update_params_btn"].on_click(self.on_update_parameters)

        # Batch fitting callbacks
        self.widgets["fit_all_btn"].on_click(self.on_fit_all)
        self.widgets["fit_all_range_btn"].on_click(self.on_fit_range)

        # Export callbacks
        self.widgets["export_btn"].on_click(self.on_export_results)
        self.widgets["save_h5_btn"].on_click(self.on_save_into_h5)

        # Colorbar control callbacks
        self.widgets["colorbar_apply_btn"].on_click(self.on_colorbar_apply)

        # Auto-apply when slider value changes
        def on_colorbar_slider_change(change):
            """Auto-apply colorbar when slider changes"""
            if self.data_manager.is_data_loaded():
                z_min, z_max = change["new"]
                self.update_heatmap_colorbar(z_min, z_max)

                fmt = self.widgets["colorbar_range_slider"].readout_format
                with self.widgets["status_output"]:
                    self.widgets["status_output"].clear_output()
                    print(f"✅ Colorbar range: {z_min:{fmt}} - {z_max:{fmt}}")

        self.widgets["colorbar_range_slider"].observe(on_colorbar_slider_change, names="value")

        # Background handling callbacks
        self.widgets["background_method"].observe(self.on_background_method_change, names="value")
        self.widgets["bg_autofit_btn"].on_click(self.on_background_autofit)
        self.widgets["bg_apply_btn"].on_click(self.on_background_apply)
        self.widgets["bg_remove_btn"].on_click(self.on_background_remove)
        self.widgets["bg_custom_upload"].observe(self.on_custom_background_upload, names="value")

        # Trigger initial background method change to show/hide correct widgets
        self.on_background_method_change({"new": config.DEFAULT_BACKGROUND_METHOD})

        # Add initial peak model
        self.add_peak_model()

        # Energy conversion callback
        self.widgets["convert_energy_btn"].on_click(self.on_convert_energy)

        def on_wavelength_range_change(change):
            """Update wavelength range visualization when slider changes"""
            try:
                debug_print(
                    f"===== WAVELENGTH RANGE CALLBACK TRIGGERED: {change['new']} =====", "DEBUG"
                )

                if not self.data_manager.is_data_loaded():
                    debug_print("Data not loaded, returning", "DEBUG")
                    return

                debug_print("Data is loaded, proceeding...", "DEBUG")

                wavelength_range = change["new"]

                # Check if range is at borders (don't show lines)
                wl_min, wl_max = (
                    self.data_manager.wavelengths.min(),
                    self.data_manager.wavelengths.max(),
                )
                debug_print(f"wl_min={wl_min}, wl_max={wl_max}, range={wavelength_range}", "DEBUG")

                if wavelength_range[0] == wl_min and wavelength_range[1] == wl_max:
                    wavelength_range = None
                    debug_print("Range is at borders, setting to None", "DEBUG")

                # Update spectrum plot
                debug_print("About to call _update_wavelength_range_on_spectrum", "DEBUG")
                self._update_wavelength_range_on_spectrum(wavelength_range)
                debug_print("Finished _update_wavelength_range_on_spectrum", "DEBUG")

                # Update heatmap
                debug_print("About to call _update_wavelength_range_on_heatmap", "DEBUG")
                self._update_wavelength_range_on_heatmap(wavelength_range)
                debug_print("Finished _update_wavelength_range_on_heatmap", "DEBUG")

            except Exception as e:
                debug_print(f"ERROR in wavelength range callback: {e}", "ERROR")
                import traceback

                traceback.print_exc()

        self.widgets["wavelength_range_slider"].observe(on_wavelength_range_change, names="value")
        debug_print(
            f"Wavelength range callback connected to {self.widgets['wavelength_range_slider']}",
            "APP",
        )

        self.widgets["fit_vis_slider"].observe(self.on_fit_vis_slider_change, names="value")
        self.widgets["fit_vis_show_components"].observe(
            lambda change: self._update_fit_vis_plot(self.widgets["fit_vis_slider"].value),
            names="value",
        )

        debug_print("Callbacks setup complete", "APP")

    def _update_wavelength_range_on_heatmap(self, wavelength_range):
        """Update only the wavelength range lines on heatmap"""
        if self.plot_manager.heatmap_fig is None:
            return

        fig = self.plot_manager.heatmap_fig

        # Remove existing wavelength range shapes (keep time position line)
        new_shapes = []
        for shape in fig.layout.shapes:
            # Keep vertical lines (time position), remove horizontal lines (wavelength range)
            if shape.type == "line" and shape.x0 == shape.x1:  # Vertical line
                new_shapes.append(shape)
        fig.layout.shapes = new_shapes

        # Add new shapes if range is specified
        if wavelength_range is not None:
            # Get x-axis range from figure
            if fig.data and len(fig.data) > 0:
                x_data = fig.data[0].x
                x_min, x_max = min(x_data), max(x_data)
            else:
                x_min, x_max = 0, 1

            # Add bottom line
            fig.add_shape(
                type="line",
                x0=x_min,
                x1=x_max,
                y0=wavelength_range[0],
                y1=wavelength_range[0],
                line=dict(color="green", width=2, dash="dash"),
            )

            # Add top line
            fig.add_shape(
                type="line",
                x0=x_min,
                x1=x_max,
                y0=wavelength_range[1],
                y1=wavelength_range[1],
                line=dict(color="green", width=2, dash="dash"),
            )

    def _store_accordion_reference(self):
        """Store reference to background accordion for programmatic control"""
        try:
            if hasattr(self.gui_layouts, "_background_section"):
                self.background_accordion = self.gui_layouts._background_section
                debug_print("Stored background accordion reference", "APP")
        except Exception as e:
            debug_print(f"Could not store accordion reference: {e}", "APP")

    # =========================================================================
    # FILE LOADING
    # =========================================================================

    def on_csv_density_change(self, change):
        """The user says whether the CSV intensities are a PL spectrum (see
        DataManager.intensity_is_density); it decides how nm <-> eV treats them."""
        self.data_manager.csv_intensity_is_density = bool(change["new"])

    def on_file_upload(self, change):
        """Handle file upload - works with both ipyvuetify and ipywidgets"""
        debug_print("!!! CALLBACK TRIGGERED !!!", "APP")
        import sys

        sys.stdout.flush()

        try:
            debug_print("=" * 50, "APP")
            debug_print("File upload triggered", "APP")

            # Handle H5 mode (a CSV upload is the other source, see below)
            from_csv_widget = isinstance(change, dict) and change.get("name") == "file_info"
            if self.data_manager.is_h5_available() and not from_csv_widget:
                mode = self.widgets["mode_dropdown"].value
                with self.widgets["status_output"]:
                    self.widgets["status_output"].clear_output()
                    print("Loading data from H5...")

                self.data_manager.load_from_h5(mode)
                self.wavelength_unit = self.data_manager.unit
                h5_path = self.data_manager.h5_path
                if h5_path:
                    filename = os.path.basename(h5_path)
                    self.widgets["h5_filename_label"].value = f"<b>File:</b> {filename}"
                self.update_ui_after_data_load()
                self.update_visualizations(update_heatmap=True)

                data_info = self.data_manager.get_data_info()
                with self.widgets["status_output"]:
                    self.widgets["status_output"].clear_output()
                    print("✅ Successfully loaded data!")
                    print(
                        f"📊 {data_info['time_points']} time points, {data_info['wavelengths']} wavelengths"
                    )
                    print(
                        f"⏱️ Time range: {data_info['time_range'][0]:.3f} - {data_info['time_range'][1]:.3f} s"
                    )
                    print(
                        f"🌈 Wavelength range: {data_info['wavelength_range'][0]:.1f} - {data_info['wavelength_range'][1]:.1f} nm"
                    )
                return

            # Handle ipyvuetify FileInput
            debug_print(f"Change type: {type(change)}", "APP")
            debug_print(
                f"Change keys: {change.keys() if isinstance(change, dict) else 'not a dict'}", "APP"
            )

            # Get files from ipyvuetify FileInput
            file_data_list = self.widgets["file_upload"].get_files()

            debug_print(f"File data list type: {type(file_data_list)}", "APP")
            debug_print(
                f"File data list length: {len(file_data_list) if file_data_list else 0}", "APP"
            )

            if not file_data_list or len(file_data_list) == 0:
                debug_print("No files in upload", "APP")
                return

            # Get first file
            file_data = file_data_list[0]

            debug_print(f"File data type: {type(file_data)}", "APP")
            debug_print(
                f"File data keys: {file_data.keys() if isinstance(file_data, dict) else 'not a dict'}",
                "APP",
            )

            # Extract filename and content
            if isinstance(file_data, dict):
                filename = file_data.get("name", "unknown")
                debug_print(f"Filename: {filename}", "APP")

                # Read file content
                if "file_obj" in file_data:
                    file_content = file_data["file_obj"].read()
                    debug_print(f"File content type: {type(file_content)}", "APP")
                    debug_print(f"File content length: {len(file_content)}", "APP")

                    # Show first 100 bytes for debugging
                    if isinstance(file_content, (bytes, memoryview)):
                        debug_print(f"First 100 bytes: {bytes(file_content[:100])}", "APP")
                else:
                    debug_print("No 'file_obj' in file_data", "APP")
                    with self.widgets["status_output"]:
                        self.widgets["status_output"].clear_output()
                        print("❌ Error: Could not read file content")
                    return
            else:
                debug_print(f"Unexpected file_data structure: {file_data}", "APP")
                return

            # Load the data
            with self.widgets["status_output"]:
                self.widgets["status_output"].clear_output()
                print(f"Loading {filename}...")

            debug_print("About to call data_manager.load_from_file", "APP")
            self.data_manager.load_from_file(file_content)
            self.wavelength_unit = self.data_manager.unit
            if "h5_filename_label" in self.widgets:
                self.widgets["h5_filename_label"].value = f"<b>File:</b> {filename} (CSV upload)"
            debug_print("Data loaded successfully", "APP")

            # Update UI controls with loaded data
            debug_print("Updating UI after data load", "APP")
            self.update_ui_after_data_load()
            debug_print("UI updated after data load", "APP")

            # Initial visualization
            debug_print("Updating visualizations", "APP")
            self.update_visualizations(update_heatmap=True)
            debug_print("Visualizations updated", "APP")

            # Initialize wavelength range visualization if not at borders
            wavelength_range = self.widgets["wavelength_range_slider"].value
            wl_min, wl_max = (
                self.data_manager.wavelengths.min(),
                self.data_manager.wavelengths.max(),
            )
            if wavelength_range[0] != wl_min or wavelength_range[1] != wl_max:
                self._update_wavelength_range_on_heatmap(wavelength_range)

            # Display success message
            data_info = self.data_manager.get_data_info()
            with self.widgets["status_output"]:
                self.widgets["status_output"].clear_output()
                print(f"✅ Successfully loaded {filename}!")
                print(
                    f"📊 {data_info['time_points']} time points, {data_info['wavelengths']} wavelengths"
                )
                print(
                    f"⏱️ Time range: {data_info['time_range'][0]:.3f} - {data_info['time_range'][1]:.3f} s"
                )
                print(
                    f"🌈 Wavelength range: {data_info['wavelength_range'][0]:.1f} - {data_info['wavelength_range'][1]:.1f} nm"
                )

        except Exception as e:
            import traceback

            with self.widgets["status_output"]:
                self.widgets["status_output"].clear_output()
                print(f"❌ Error loading file: {str(e)}")
                print("\n🔍 Full traceback:")
                print(traceback.format_exc())
            debug_print(f"ERROR: {e}", "APP")
            debug_print(f"Full traceback:\n{traceback.format_exc()}", "APP")

    def _convert_peak_rows(self):
        """Carry the start values of the peak rows over to the new axis after nm <-> eV, so
        they stay on the same peaks. Centre c -> hc/c, widths w -> hc*w/c^2 (sigma, and the
        Lorentzian gamma of the Voigt types), and for a PL spectrum the height h -> h*c^2/hc
        (the density rescaling of the data). The same formulas serve both directions. Bounds
        typed in the old unit are cleared, and Linear/Polynomial rows are left alone."""
        hc = config.HC_EV_NM
        density = self.data_manager.intensity_is_density
        for peak_row in self.peak_models:
            w = peak_row._widgets
            kind = w["type"].value
            if kind in ("Linear", "Polynomial"):
                continue
            center = w["center"].value
            if center > 0:
                w["sigma"].value = hc * w["sigma"].value / center**2
                if kind in ("Voigt", "Skewed Voigt"):
                    w["gamma"].value = hc * w["gamma"].value / center**2
                if density:
                    w["height"].value = w["height"].value * center**2 / hc
                w["center"].value = hc / center
            for key in (
                "center_min",
                "center_max",
                "height_min",
                "height_max",
                "sigma_min",
                "sigma_max",
                "gamma_min",
                "gamma_max",
            ):
                w[key].value = ""

    def _reset_background_state(self):
        """Forget the stored pre-background data. Called on every new data load: the
        stored matrix belongs to the previous file or H5 mode, and applying or removing a
        background afterwards would otherwise replace the new data with the old."""
        self.original_data_matrix = None
        self.background_applied = False
        self.background_model = None
        if "bg_remove_btn" in self.widgets:
            self.widgets["bg_remove_btn"].disabled = True

    def _clear_fit_results(self):
        """Drop fit results that belong to data that is no longer shown (a new file, H5
        mode or x unit), so they can't be saved under the new data's labels."""
        self.fitting_engine.clear_fitting_results()
        self.fitting_engine.batch_settings = None
        self.last_fit_result = None
        self._fit_vis_indices = []

    def _reverse_background_state(self):
        """Keep the stored pre-background data and background in step with the data
        matrix: the nm <-> eV conversion reverses its columns and, for a PL spectrum,
        rescales its intensities."""
        if self.original_data_matrix is not None:
            self.original_data_matrix = self.original_data_matrix[:, ::-1]
        if getattr(self, "background_model", None) is not None:
            self.background_model = self.background_model[::-1]
        if self.data_manager.intensity_is_density:
            # Same intensity rescaling as the data (I -> I * lambda^2 / hc going to eV and
            # E^2 / hc coming back), written in terms of the new axis x: hc / x^2 both ways
            factor = config.HC_EV_NM / self.data_manager.wavelengths**2
            if self.original_data_matrix is not None:
                self.original_data_matrix = self.original_data_matrix * factor
            if getattr(self, "background_model", None) is not None:
                self.background_model = self.background_model * factor

    def update_ui_after_data_load(self):
        """Update UI controls after data is loaded"""
        debug_print("Updating UI after data load", "update_ui_after_data_load")
        self._reset_background_state()
        self._clear_fit_results()

        # Enable energy conversion button for PL data
        if self.wavelength_unit in ["nm", "eV"]:
            self.widgets["convert_energy_btn"].disabled = False
        else:
            self.widgets["convert_energy_btn"].disabled = True

        # change display of energy unit
        self.widgets["energy_unit_display"].value = f"Current unit: {self.wavelength_unit}"

        # Get time range
        min_idx, max_idx = self.data_manager.get_time_range()
        debug_print(
            f"Time range indices: min={min_idx}, max={max_idx}", "update_ui_after_data_load"
        )

        # Update time controls
        self.widgets["time_slider"].max = max_idx
        self.widgets["time_slider"].value = 0
        self.widgets["time_slider"].disabled = False

        self.widgets["time_input"].max = max_idx
        self.widgets["time_input"].value = 0
        self.widgets["time_input"].disabled = False

        # Update fit range controls
        self.widgets["fit_start_idx"].max = max_idx
        self.widgets["fit_start_idx"].value = 0
        self.widgets["fit_start_idx"].disabled = False

        self.widgets["fit_end_idx"].max = max_idx
        self.widgets["fit_end_idx"].value = max_idx
        self.widgets["fit_end_idx"].disabled = False

        # Enable background handling
        self.widgets["bg_manual_start"].max = max_idx
        self.widgets["bg_manual_num"].max = min(50, max_idx + 1)
        self.widgets["bg_apply_btn"].disabled = False

        # Enable background handling
        self.widgets["bg_manual_start"].max = max_idx
        self.widgets["bg_manual_num"].max = min(50, max_idx + 1)
        self.widgets["bg_apply_btn"].disabled = False

        # Enable detection parameters
        self.widgets["peak_height_threshold"].disabled = False
        self.widgets["peak_prominence"].disabled = False
        self.widgets["peak_distance"].disabled = False

        # Get wavelength range
        wavelength_min = float(self.data_manager.wavelengths.min())
        wavelength_max = float(self.data_manager.wavelengths.max())
        debug_print(
            f"Wavelength range: min={wavelength_min}, max={wavelength_max}",
            "update_ui_after_data_load",
        )

        # Enable wavelength range controls
        self.widgets["wavelength_range_slider"].max = 1e12
        self.widgets["wavelength_range_slider"].min = wavelength_min
        self.widgets["wavelength_range_slider"].max = wavelength_max
        self.widgets["wavelength_range_slider"].value = [wavelength_min, wavelength_max]
        if self.wavelength_unit in ["1/Å"]:
            self.widgets[
                "wavelength_range_slider"
            ].description = f"q Range ({self.wavelength_unit})"
        else:
            self.widgets[
                "wavelength_range_slider"
            ].description = f"λ Range ({self.wavelength_unit})"
        self.widgets["wavelength_range_slider"].disabled = False

        # Enable colorbar controls (range from finite values, see get_data_info)
        data_min, data_max = self.data_manager.get_data_info()["intensity_range"]

        # Ensure min < max
        if data_min >= data_max:
            data_max = data_min + 1000.0

        # Step and shown decimals follow the data: about 1000 steps across the range,
        # so absorbance (~0 to 2) gets 0.001 steps and PL counts (~1e4) whole numbers
        step, decimals = _slider_step(data_max - data_min)
        self.widgets["colorbar_range_slider"].step = step
        self.widgets["colorbar_range_slider"].readout_format = f".{decimals}f"

        # Set colorbar range
        # Set max first if increasing range
        if data_max > self.widgets["colorbar_range_slider"].max:
            self.widgets["colorbar_range_slider"].max = data_max
            self.widgets["colorbar_range_slider"].min = data_min
        else:
            self.widgets["colorbar_range_slider"].min = data_min
            self.widgets["colorbar_range_slider"].max = data_max

        self.widgets["colorbar_range_slider"].value = (data_min, data_max)
        self.widgets["colorbar_range_slider"].disabled = False
        self.widgets["colorbar_apply_btn"].disabled = False

        # Set min and max carefully to avoid min > max error
        if data_min < data_max:
            # Set max first if increasing range
            if data_max > self.widgets["colorbar_range_slider"].max:
                self.widgets["colorbar_range_slider"].max = data_max
                self.widgets["colorbar_range_slider"].min = data_min
            else:
                self.widgets["colorbar_range_slider"].min = data_min
                self.widgets["colorbar_range_slider"].max = data_max
            self.widgets["colorbar_range_slider"].value = (data_min, data_max)
        else:
            # Handle edge case where min == max
            self.widgets["colorbar_range_slider"].min = data_min - 1
            self.widgets["colorbar_range_slider"].max = data_max + 1
            self.widgets["colorbar_range_slider"].value = (data_min, data_max)
        self.widgets["colorbar_range_slider"].disabled = False
        self.widgets["colorbar_apply_btn"].disabled = False

        # Show/hide Save into h5 button based on data source
        if self.data_manager.data_source == "h5":
            self.widgets["save_h5_btn"].layout.display = ""
        else:
            self.widgets["save_h5_btn"].layout.display = "none"

        # Set mode-dependent default center bound
        h5_mode = self.data_manager.h5_mode or ""
        if "giwaxs" in h5_mode:
            default_bound = config.CENTER_BOUND_DEFAULTS["giwaxs"]
        elif "absorbance" in h5_mode:
            default_bound = config.CENTER_BOUND_DEFAULTS["absorbance"]
        elif "transmission" in h5_mode:
            default_bound = config.CENTER_BOUND_DEFAULTS["transmission"]
        else:
            default_bound = config.CENTER_BOUND_DEFAULTS["default"]
        self.widgets["center_bound_input"].value = default_bound

        debug_print("UI updated after data load", "update_ui_after_data_load")

    def _update_wavelength_range_on_spectrum(self, wavelength_range):
        """Update only the wavelength range lines on spectrum plot"""
        try:
            debug_print(f"Updating spectrum range to {wavelength_range}", "SPECTRUM")
            debug_print(f"self.plot_manager = {self.plot_manager}", "SPECTRUM")
            debug_print(
                f"self.plot_manager.spectrum_fig = {self.plot_manager.spectrum_fig}", "SPECTRUM"
            )
            debug_print(
                f"spectrum_fig is None? {self.plot_manager.spectrum_fig is None}", "SPECTRUM"
            )
        except Exception as e:
            print(f"!!!! EXCEPTION in debug prints: {e}")
            import traceback

            traceback.print_exc()
            return

        # Early return if no range specified or no figure exists
        if wavelength_range is None or self.plot_manager.spectrum_fig is None:
            debug_print("No range or no spectrum fig, returning early", "SPECTRUM")
            return

        fig = self.plot_manager.spectrum_fig
        debug_print(f"Number of shapes before: {len(fig.layout.shapes)}", "SPECTRUM")

        # Remove existing wavelength range shapes (vertical green dashed lines)
        new_shapes = []
        for shape in fig.layout.shapes:
            # Remove if it's a vertical green dashed line
            is_green = getattr(shape.line, "color", None) == "green"
            is_dashed = getattr(shape.line, "dash", None) == "dash"
            is_vertical = shape.type == "line" and shape.x0 == shape.x1

            should_remove = is_green and is_dashed and is_vertical
            debug_print(
                f"Shape: x0={shape.x0}, green={is_green}, dashed={is_dashed}, vertical={is_vertical}, remove={should_remove}",
                "SPECTRUM",
            )

            if not should_remove:
                new_shapes.append(shape)

        fig.layout.shapes = new_shapes
        debug_print(f"Number of shapes after removal: {len(fig.layout.shapes)}", "SPECTRUM")

        # Add new shapes if range is specified
        if wavelength_range is not None:
            # Get y-axis range from figure
            if fig.data and len(fig.data) > 0:
                y_data = fig.data[0].y
                y_min, y_max = min(y_data), max(y_data)
            else:
                y_min, y_max = 0, 1

            # Add left line
            left_shape = fig.add_shape(
                type="line",
                x0=wavelength_range[0],
                x1=wavelength_range[0],
                y0=y_min,
                y1=y_max,
                line=dict(color="green", width=2, dash="dash"),
            )
            left_shape._is_wl_range = True

            # Add right line
            right_shape = fig.add_shape(
                type="line",
                x0=wavelength_range[1],
                x1=wavelength_range[1],
                y0=y_min,
                y1=y_max,
                line=dict(color="green", width=2, dash="dash"),
            )
            right_shape._is_wl_range = True

    # =========================================================================
    # TIME CONTROL
    # =========================================================================

    def on_time_change_slider(self, change):
        """Handle time slider change"""
        new_idx = change["new"]
        debug_print(f"Time slider changed to {new_idx}", "APP")

        # Update input to match (without triggering its callback)
        self.widgets["time_input"].unobserve(self.on_time_change_input, names="value")
        self.widgets["time_input"].value = new_idx
        self.widgets["time_input"].observe(self.on_time_change_input, names="value")

        # Update data manager and visualizations
        self.data_manager.set_current_time(new_idx)
        self.update_visualizations()

    def on_time_change_input(self, change):
        """Handle time input change"""
        new_idx = change["new"]
        debug_print(f"Time input changed to {new_idx}", "APP")

        # Update slider to match (without triggering its callback)
        self.widgets["time_slider"].unobserve(self.on_time_change_slider, names="value")
        self.widgets["time_slider"].value = new_idx
        self.widgets["time_slider"].observe(self.on_time_change_slider, names="value")

        # Update data manager and visualizations
        self.data_manager.set_current_time(new_idx)
        self.update_visualizations()

    # =========================================================================
    # PEAK DETECTION AND MODELS
    # =========================================================================

    def on_auto_detect_peaks(self, button):
        """Auto-detect peaks in current spectrum"""
        if not self.data_manager.is_data_loaded():
            return

        try:
            debug_print("Auto-detecting peaks", "APP")

            current_spectrum = self.data_manager.get_current_spectrum()
            wavelengths = self.data_manager.wavelengths

            # Get wavelength range from slider
            wl_range = self.widgets["wavelength_range_slider"].value
            wl_min = float(wavelengths.min())
            wl_max = float(wavelengths.max())
            is_limited = (wl_range[0] > wl_min) or (wl_range[1] < wl_max)

            # If range is limited, only detect peaks in that range
            if is_limited:
                mask = (wavelengths >= wl_range[0]) & (wavelengths <= wl_range[1])
                wavelengths_detect = wavelengths[mask]
                spectrum_detect = current_spectrum[mask]
                debug_print(
                    f"Detecting peaks in range: {wl_range[0]:.1f} - {wl_range[1]:.1f} {self.wavelength_unit}",
                    "APP",
                )
            else:
                wavelengths_detect = wavelengths
                spectrum_detect = current_spectrum
                debug_print("Detecting peaks in full range", "APP")

            # Get detection parameters from UI. Defaults are computed from finite
            # points only; a single NaN/inf would otherwise make them NaN/inf and
            # silently suppress every peak.
            finite_spectrum = spectrum_detect[np.isfinite(spectrum_detect)]
            min_height = self.widgets["peak_height_threshold"].value
            if min_height == 0 and finite_spectrum.size:
                min_height = np.max(finite_spectrum) * 0.05

            min_prominence = self.widgets["peak_prominence"].value
            if min_prominence == 0 and finite_spectrum.size:
                min_prominence = np.std(finite_spectrum) * 2

            min_distance = self.widgets["peak_distance"].value

            # Detect peaks
            peaks_info = self.fitting_engine.detect_peaks(
                wavelengths_detect,
                spectrum_detect,
                height=min_height,
                prominence=min_prominence,
                distance=min_distance,
            )

            # Clear existing peak models
            self.clear_peak_models()

            # Add models for detected peaks (round to 3 decimals for display)
            for peak in peaks_info:
                rounded_peak = {
                    "center": round(peak["center"], 3),
                    "height": round(peak["height"], 3),
                    "sigma": round(peak["sigma"], 3),
                    "type": peak.get("type", config.DEFAULT_PEAK_MODEL),
                }
                self.add_peak_model(peak_info=rounded_peak)

            with self.widgets["status_output"]:
                self.widgets["status_output"].clear_output()
                print(f"🔍 Detected {len(peaks_info)} peaks")
                if is_limited:
                    print(f"   Range: {wl_range[0]:.1f} - {wl_range[1]:.1f} {self.wavelength_unit}")
                for i, peak in enumerate(peaks_info):
                    print(
                        f"  Peak {i + 1}: {peak['center']:.3f} {self.wavelength_unit}, height: {peak['height']:.1f}"
                    )

            debug_print(f"Detected {len(peaks_info)} peaks", "APP")

        except Exception as e:
            with self.widgets["status_output"]:
                self.widgets["status_output"].clear_output()
                print(f"❌ Error detecting peaks: {str(e)}")
            debug_print(f"Error in peak detection: {e}", "APP")

    def on_add_peak(self, button):
        """Add a new peak model"""
        self.add_peak_model()

    def add_peak_model(self, peak_info=None):
        """
        Add a new peak model to the interface

        Parameters:
        -----------
        peak_info : dict, optional
            Initial peak information from detection
        """
        if peak_info is None:
            peak_info = {
                "center": 700.0,
                "height": 1000.0,
                "sigma": 10.0,
                "type": config.DEFAULT_PEAK_MODEL,
            }

        peak_idx = self._peak_counter
        self._peak_counter += 1
        debug_print(f"Adding peak model {peak_idx}", "APP")

        # Create peak row widget
        peak_row = self.gui_components.create_peak_row_widget(peak_idx, peak_info)

        # Setup remove button callback
        peak_row._widgets["remove"].on_click(lambda b: self.remove_peak_model(peak_idx))

        # Store peak model
        self.peak_models.append(peak_row)

        # Update peak list container
        self.update_peak_list_container()

    def on_convert_energy(self, button):
        """Convert between wavelength (nm) and energy (eV)"""
        if not self.data_manager.is_data_loaded():
            return

        try:
            debug_print(f"Converting from {self.wavelength_unit}", "APP")

            if self.wavelength_unit == "nm":
                success = self.data_manager.convert_wavelength_to_energy()
                if success:
                    self.wavelength_unit = "eV"
                    self._reverse_background_state()
                    self._clear_fit_results()
                    self._convert_peak_rows()
                    self.widgets["energy_unit_display"].value = "E (eV)"

                    wl_min = float(self.data_manager.wavelengths.min())
                    wl_max = float(self.data_manager.wavelengths.max())
                    mid = (wl_min + wl_max) / 2

                    # Scale center bound: Δ(eV) ≈ mid_eV² · Δ(nm) / hc
                    self.widgets["center_bound_input"].value = round(
                        mid**2 * self.widgets["center_bound_input"].value / config.HC_EV_NM, 4
                    )

                    # Expand range first, then set new limits
                    self.widgets["wavelength_range_slider"].min = min(
                        wl_min, self.widgets["wavelength_range_slider"].min
                    )
                    self.widgets["wavelength_range_slider"].max = max(
                        wl_max, self.widgets["wavelength_range_slider"].max
                    )
                    self.widgets["wavelength_range_slider"].value = (wl_min, wl_max)
                    self.widgets["wavelength_range_slider"].min = wl_min
                    self.widgets["wavelength_range_slider"].max = wl_max
                    self.widgets["wavelength_range_slider"].description = "E Range (eV)"

                    with self.widgets["status_output"]:
                        self.widgets["status_output"].clear_output()
                        print("✅ Converted to energy (eV)")
                        print(f"   Range: {wl_min:.2f} - {wl_max:.2f} eV")
            elif self.wavelength_unit == "eV":
                success = self.data_manager.convert_energy_to_wavelength()
                if success:
                    self.wavelength_unit = "nm"
                    self._reverse_background_state()
                    self._clear_fit_results()
                    self._convert_peak_rows()
                    self.widgets["energy_unit_display"].value = "λ (nm)"

                    wl_min = float(self.data_manager.wavelengths.min())
                    wl_max = float(self.data_manager.wavelengths.max())
                    mid = (wl_min + wl_max) / 2

                    # Scale center bound: Δ(nm) ≈ mid_nm² · Δ(eV) / hc
                    self.widgets["center_bound_input"].value = round(
                        mid**2 * self.widgets["center_bound_input"].value / config.HC_EV_NM, 4
                    )

                    # Expand range first, then set new limits
                    self.widgets["wavelength_range_slider"].min = min(
                        wl_min, self.widgets["wavelength_range_slider"].min
                    )
                    self.widgets["wavelength_range_slider"].max = max(
                        wl_max, self.widgets["wavelength_range_slider"].max
                    )
                    self.widgets["wavelength_range_slider"].value = (wl_min, wl_max)
                    self.widgets["wavelength_range_slider"].min = wl_min
                    self.widgets["wavelength_range_slider"].max = wl_max
                    self.widgets["wavelength_range_slider"].description = "λ Range (nm)"

                    with self.widgets["status_output"]:
                        self.widgets["status_output"].clear_output()
                        print("✅ Converted to wavelength (nm)")
                        print(f"   Range: {wl_min:.1f} - {wl_max:.1f} nm")
            else:
                debug_print("Unknown wavelength unit, cannot convert", "APP")

            # Update all visualizations
            self.update_visualizations(update_heatmap=True)

            debug_print(f"Energy conversion complete. New unit: {self.wavelength_unit}", "APP")

        except Exception as e:
            import traceback

            with self.widgets["status_output"]:
                self.widgets["status_output"].clear_output()
                print(f"❌ Error converting: {str(e)}")
                print("\n🔍 Full traceback:")
                print(traceback.format_exc())
            debug_print(f"Error in energy conversion: {e}", "APP")

    def on_colorbar_apply(self, button):
        """Apply colorbar range from slider"""
        if not self.data_manager.is_data_loaded():
            return

        try:
            # Small delay to ensure any typed values are committed
            import time

            time.sleep(0.1)

            z_min, z_max = self.widgets["colorbar_range_slider"].value

            self.update_heatmap_colorbar(z_min, z_max)

            with self.widgets["status_output"]:
                self.widgets["status_output"].clear_output()
                fmt = self.widgets["colorbar_range_slider"].readout_format
                print("✅ Colorbar range applied")
                print(f"   Range: {z_min:{fmt}} - {z_max:{fmt}}")

            debug_print(f"Colorbar range applied: {z_min:.1f} - {z_max:.1f}", "APP")

        except Exception as e:
            debug_print(f"Error applying colorbar: {e}", "APP")

    def update_heatmap_colorbar(self, z_min, z_max):
        """Update heatmap colorbar range dynamically"""
        if self.plot_manager.heatmap_fig is None:
            debug_print("No heatmap to update", "APP")
            return

        try:
            # Update the heatmap's zmin and zmax using FigureWidget
            with self.plot_manager.heatmap_fig.batch_update():
                self.plot_manager.heatmap_fig.data[0].zmin = z_min
                self.plot_manager.heatmap_fig.data[0].zmax = z_max

            debug_print(f"Updated heatmap colorbar: {z_min:.1f} - {z_max:.1f}", "APP")

        except Exception as e:
            debug_print(f"Error updating heatmap colorbar: {e}", "APP")

    def remove_peak_model(self, peak_idx):
        """Remove a peak model"""
        if len(self.peak_models) <= 1:
            with self.widgets["status_output"]:
                print("⚠️ Must keep at least one peak model")
            return

        debug_print(f"Removing peak model {peak_idx}", "APP")

        # Find and remove the peak model
        model_to_remove = None
        for i, model in enumerate(self.peak_models):
            if hasattr(model, "_peak_idx") and model._peak_idx == peak_idx:
                model_to_remove = i
                break

        if model_to_remove is not None:
            self.peak_models.pop(model_to_remove)
            self.update_peak_list_container()

    def clear_peak_models(self):
        """Clear all peak models"""
        debug_print("Clearing all peak models", "APP")
        self.peak_models.clear()
        self._peak_counter = 0
        self.update_peak_list_container()

    def update_peak_list_container(self):
        """Update the peak list container widget with grid layout"""
        if len(self.peak_models) == 0:
            self.widgets["peak_list_container"].children = tuple()
        else:
            # Use GridBox for better layout (2 columns)

            self.widgets["peak_list_container"].children = tuple(self.peak_models)

    # =========================================================================
    # FITTING OPERATIONS
    # =========================================================================

    def update_visualizations(self, update_heatmap: bool = False):
        """Update both heatmap and spectrum visualizations
        Parameters
        ----------
        update_heatmap      : boolean value that decides whether a new heatmap gets drawn"""
        if not self.data_manager.is_data_loaded():
            return

        debug_print("Updating visualizations", "APP")

        # Update time display
        current_time = self.data_manager.get_current_time_value()
        self.widgets["time_display"].value = f"Time: {current_time:.3f}s"

        # Update heatmap
        self.update_heatmap(update_heatmap=update_heatmap)

        # Update spectrum plot
        self.update_spectrum_plot()

    def update_heatmap(self, update_heatmap: bool = False):
        """Update heatmap visualization - only update line if heatmap exists
        Parameters
        ----------
        update_heatmap      : boolean value that decides whether a new heatmap gets drawn"""

        # Check if heatmap already exists
        if self.plot_manager.heatmap_fig is None or update_heatmap:
            # Flip colorscale for absorbance modes (only when H5 data is loaded)
            mode = self.data_manager.h5_mode
            if mode is not None and mode in ("absorbance_raw", "absorbance_binned"):
                self.plot_manager.visualization.colorscale = config.DEFAULT_COLORSCALE + "_r"
            else:
                self.plot_manager.visualization.colorscale = config.DEFAULT_COLORSCALE

            # Create heatmap for the first time
            with self.widgets["heatmap_output"]:
                self.widgets["heatmap_output"].clear_output()

                fig = self.plot_manager.create_heatmap(
                    self.data_manager.data_matrix,
                    self.data_manager.wavelengths,
                    self.data_manager.timestamps,
                    current_time_idx=self.data_manager.current_time_idx,
                    wavelength_unit=self.wavelength_unit,
                    time_unit=self.data_manager.time_unit,
                )

                display(fig)
        else:
            # Just update the line position (no redraw needed)
            self.plot_manager.update_heatmap_line(
                self.data_manager.timestamps, self.data_manager.current_time_idx
            )

    def update_spectrum_plot(self, fit_result=None):
        """Update spectrum plot"""
        with self.widgets["spectrum_output"]:
            self.widgets["spectrum_output"].clear_output()

            # Get wavelength range for display if limited
            wl_range = self.widgets["wavelength_range_slider"].value
            wavelengths = self.data_manager.wavelengths
            wl_min = float(wavelengths.min())
            wl_max = float(wavelengths.max())
            is_limited = (wl_range[0] > wl_min) or (wl_range[1] < wl_max)

            wl_range_display = wl_range if is_limited else None

            peak_name_map = {
                f"p{i}": pm._widgets["name"].value for i, pm in enumerate(self.peak_models)
            }
            fig = self.plot_manager.create_spectrum_plot(
                self.data_manager.wavelengths,
                self.data_manager.get_current_spectrum(),
                fit_result=fit_result,
                wavelength_range=wl_range_display,
                wavelength_unit=self.wavelength_unit,
                name_map=peak_name_map,
            )

            # Apply current wavelength range visualization BEFORE displaying
            wavelength_range = self.widgets["wavelength_range_slider"].value
            if wavelength_range[0] != wl_min or wavelength_range[1] != wl_max:
                self._update_wavelength_range_on_spectrum(wavelength_range)

            # Display the FigureWidget directly
            display(fig)

    def refresh_fit_vis(self):
        """Update fit visualisation slider and plot after fitting"""
        if not self.fitting_engine.has_fitting_results():
            return

        self._fit_vis_indices = sorted(self.fitting_engine.fitting_results.keys())

        if not self._fit_vis_indices:
            return

        n = len(self._fit_vis_indices)
        slider = self.widgets["fit_vis_slider"]
        # Temporarily disable observer to avoid double-trigger
        slider.max = max(n - 1, 0)
        slider.disabled = False
        slider.value = 0

        self._update_fit_vis_plot(0)

    def on_fit_vis_slider_change(self, change):
        """Handle fit visualisation slider change"""
        self._update_fit_vis_plot(change["new"])

    def _update_fit_vis_plot(self, slider_val):
        """Display the fit result for the given slider position"""
        debug_print(f"Updating fit visualization for slider value: {slider_val}", "APP")
        if not self._fit_vis_indices or slider_val >= len(self._fit_vis_indices):
            return

        time_idx = self._fit_vis_indices[slider_val]
        fit_result = self.fitting_engine.fitting_results.get(time_idx)

        if fit_result is None:
            return

        success = fit_result.get("success", False)
        time_val = fit_result.get("time", 0)
        r2 = fit_result.get("r_squared", float("nan"))
        status = "" if success else "  |  FIT FAILED"
        self.widgets["fit_vis_label"].value = (
            f"Index: {time_idx}  |  Time: {time_val:.3f} {self.data_manager.time_unit}"
            f"  |  R²: {r2:.4f}{status}"
        )

        # Raw data is drawn over the batch-fit wavelength range, non-finite points
        # included. The fit traces use the result's own fit_x (finite points only),
        # so the two arrays may differ in length and must not share an x-axis.
        full_wl = self.data_manager.wavelengths
        raw_intensities = self.data_manager.data_matrix[time_idx]
        wavelengths = self.fitting_engine.fit_wavelengths
        if wavelengths is None:
            wavelengths = full_wl
        if len(wavelengths) != len(raw_intensities):
            mask = (full_wl >= wavelengths.min()) & (full_wl <= wavelengths.max())
            raw_intensities = raw_intensities[mask]

        show_components = self.widgets["fit_vis_show_components"].value
        components = fit_result.get("components", {})
        debug_print(
            f"FitVis: success={success}, show_components={show_components}, stored components={list(components.keys())}",
            "APP",
        )

        # Pass None fit_result for failed frames so the plotter only draws raw data
        fig = self.plot_manager.create_fit_vis_plot(
            fit_result if success else None,
            wavelengths,
            raw_intensities,
            wavelength_unit=self.wavelength_unit or "nm",
            time_unit=self.data_manager.time_unit,
            show_components=show_components,
        )

        with self.widgets["fit_vis_output"]:
            self.widgets["fit_vis_output"].clear_output(wait=True)
            fig.show(renderer=config.PLOT_RENDERER)

    def create_time_series_plots(self):
        """Create time series plots from fitting results"""
        if not self.fitting_engine.has_fitting_results():
            return

        try:
            debug_print("Creating time series plots", "APP")

            # Explicitly clear output first
            with self.widgets["time_series_output"]:
                self.widgets["time_series_output"].clear_output(wait=True)

            self.plot_manager.create_time_series_plots(
                self.fitting_engine.fitting_results,
                output_widget=self.widgets["time_series_output"],
                wavelength_unit=self.wavelength_unit,
                time_unit=self.data_manager.time_unit,
            )

            debug_print("Time series plots created", "APP")

        except Exception as e:
            with self.widgets["time_series_output"]:
                self.widgets["time_series_output"].clear_output()
                print(f"❌ Error creating time series plots: {str(e)}")
            debug_print(f"Error creating time series plots: {e}", "APP")

    # =========================================================================
    # UTILITY METHODS
    # =========================================================================

    # =========================================================================
    # DISPLAY
    # =========================================================================

    def display_app(self):
        """Display the complete application interface"""
        debug_print("Displaying application", "APP")

        header, main_content = self.gui_layouts.create_main_layout()

        # Store accordion reference after layout is created
        self._store_accordion_reference()

        if config.DEBUG_MODE:
            display(debug_output)
        display(header)
        display(manual_panel(__file__))
        display(main_content)

        debug_print("Application displayed", "APP")
