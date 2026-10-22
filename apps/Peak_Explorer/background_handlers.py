"""Background handlers of PLAnalysisApp (gui_layouts.py): custom upload, method choice,
auto-fit, apply and remove. A mixin: it relies on the attributes PLAnalysisApp sets up."""

import logging
import warnings

import config
import numpy as np
from utils import debug_print

warnings.filterwarnings("ignore", message="Using UFloat objects with std_dev==0")

logger = logging.getLogger(__name__)


class BackgroundHandlersMixin:
    def load_custom_background(self, file_content):
        """
        Load custom background from uploaded file

        Parameters:
        -----------
        file_content : bytes
            File content with 2 columns: wavelength, intensity

        Returns:
        --------
        array: Background intensity values
        """
        import io

        try:
            # Convert bytes to string
            if isinstance(file_content, bytes):
                content_str = file_content.decode("utf-8")
            elif isinstance(file_content, memoryview):
                content_str = file_content.tobytes().decode("utf-8")
            else:
                content_str = str(file_content)

            # Parse the file
            data = np.loadtxt(io.StringIO(content_str), delimiter=",")

            if data.shape[1] != 2:
                raise ValueError("File must have exactly 2 columns: wavelength, intensity")

            bg_wavelengths = data[:, 0]
            bg_intensities = data[:, 1]

            # Interpolate to match current wavelength grid
            from scipy.interpolate import interp1d

            interp_func = interp1d(
                bg_wavelengths,
                bg_intensities,
                kind="linear",
                bounds_error=False,
                fill_value="extrapolate",
            )

            background = interp_func(self.data_manager.wavelengths)

            debug_print(f"Loaded custom background: {len(bg_wavelengths)} points", "APP")
            return background

        except Exception as e:
            raise ValueError(f"Error loading custom background: {str(e)}")

    def on_custom_background_upload(self, change):
        """Handle custom background file upload"""
        if not change["new"]:
            return

        try:
            # Get the uploaded files - change['new'] is a tuple of FileUpload objects
            uploaded_files = change["new"]
            if not uploaded_files or len(uploaded_files) == 0:
                return

            # Get first file from tuple
            file_upload = uploaded_files[0]
            file_name = file_upload["name"]
            file_content = file_upload["content"]

            # Try to load and validate the file
            background = self.load_custom_background(file_content)

            # Update status
            self.widgets[
                "bg_custom_status"
            ].value = f"✅ Loaded: {file_name} ({len(background)} points)"

            # Enable apply button
            self.widgets["bg_apply_btn"].disabled = False

            debug_print(f"Custom background uploaded: {file_name}", "APP")

        except Exception as e:
            self.widgets["bg_custom_status"].value = f"❌ Error: {str(e)}"
            debug_print(f"Error loading custom background: {e}", "APP")

    def on_background_method_change(self, change):
        """Handle background method selection change"""
        method = change["new"]
        debug_print(f"Background method changed to: {method}", "APP")

        # Get data loaded state
        data_loaded = self.data_manager.is_data_loaded()

        # Hide all containers first
        if hasattr(self.gui_layouts, "_bg_containers"):
            for container in self.gui_layouts._bg_containers.values():
                container.layout.visibility = "hidden"
                container.layout.display = "none"

        # If None is selected, disable all buttons and return
        if method == "None":
            self.widgets["bg_apply_btn"].disabled = True
            self.widgets["bg_autofit_btn"].disabled = True
            self.widgets["bg_autofit_btn"].layout.visibility = "hidden"
            return

        # Show and enable the selected method's container
        if (
            hasattr(self.gui_layouts, "_bg_containers")
            and method in self.gui_layouts._bg_containers
        ):
            self.gui_layouts._bg_containers[method].layout.visibility = "visible"
            self.gui_layouts._bg_containers[method].layout.display = "flex"

            # Enable widgets for the selected method
            if method == "Manual" and data_loaded:
                self.widgets["bg_manual_start"].disabled = False
                self.widgets["bg_manual_num"].disabled = False
            elif method == "Linear" and data_loaded:
                self.widgets["bg_linear_slope"].disabled = False
                self.widgets["bg_linear_intercept"].disabled = False
            elif method == "Polynomial" and data_loaded:
                self.widgets["bg_poly_degree"].disabled = False
                self.widgets["bg_poly_coeffs"].disabled = False
            elif method == "Exponential" and data_loaded:
                self.widgets["bg_exp_amplitude"].disabled = False
                self.widgets["bg_exp_decay"].disabled = False
                self.widgets["bg_exp_offset"].disabled = False
            elif method == "Custom" and data_loaded:
                self.widgets["bg_custom_upload"].disabled = False

        # Enable/disable action buttons
        can_apply = data_loaded
        self.widgets["bg_apply_btn"].disabled = not can_apply

        # Auto-fit button only for model-based methods
        if method in ["Linear", "Polynomial", "Exponential"]:
            self.widgets["bg_autofit_btn"].disabled = not data_loaded
            self.widgets["bg_autofit_btn"].layout.visibility = "visible"
        else:
            self.widgets["bg_autofit_btn"].disabled = True
            self.widgets["bg_autofit_btn"].layout.visibility = "hidden"

    def _background_fit_points(self, wavelengths, spectrum):
        """(x, y) of the finite points outside the windows of the current peak models (centre
        +/- 3 widths, the Lorentzian width included for the Voigt types). With no peak models,
        or when too little would be left to fit, every finite point is used."""
        x = np.asarray(wavelengths, dtype=float)
        y = np.asarray(spectrum, dtype=float)
        keep = np.isfinite(x) & np.isfinite(y)
        outside = keep.copy()
        for row in self.peak_models:
            fields = row._widgets
            if fields["type"].value in ("Linear", "Polynomial"):
                continue
            half = 3.0 * abs(fields["sigma"].value)
            if fields["type"].value in ("Voigt", "Skewed Voigt"):
                half += 3.0 * abs(fields["gamma"].value)
            outside &= np.abs(x - fields["center"].value) > half
        if outside.sum() < max(10, 0.1 * keep.sum()):
            outside = keep
        return x[outside], y[outside]

    def on_background_autofit(self, button):
        """Auto-fit background model to current spectrum"""
        if not self.data_manager.is_data_loaded():
            return

        method = self.widgets["background_method"].value
        spectrum_all = self.data_manager.get_current_spectrum()
        axis_all = self.data_manager.wavelengths
        # fit on the points between the peaks: a fit through the peaks lets the "background"
        # swallow part of the signal
        wavelengths, current_spectrum = self._background_fit_points(axis_all, spectrum_all)
        n_peak_points = int(np.isfinite(spectrum_all).sum()) - wavelengths.size

        try:
            debug_print(f"Auto-fitting background: {method}", "APP")

            if method == "Linear":
                # Fit linear: y = slope * x + intercept
                coeffs = np.polyfit(wavelengths, current_spectrum, 1)
                self.widgets["bg_linear_slope"].value = float(coeffs[0])
                self.widgets["bg_linear_intercept"].value = float(coeffs[1])
                self.background_model = coeffs[0] * axis_all + coeffs[1]
                debug_print(
                    f"Background model set (Linear): shape={self.background_model.shape}, min={self.background_model.min():.2f}, max={self.background_model.max():.2f}",
                    "APP",
                )

            elif method == "Polynomial":
                degree = self.widgets["bg_poly_degree"].value
                coeffs = np.polyfit(wavelengths, current_spectrum, degree)
                self.widgets["bg_poly_coeffs"].value = ", ".join([f"{c:.2e}" for c in coeffs])
                self.background_model = np.polyval(coeffs, axis_all)
                debug_print(
                    f"Background model set (Polynomial): shape={self.background_model.shape}, min={self.background_model.min():.2f}, max={self.background_model.max():.2f}",
                    "APP",
                )

            elif method == "Exponential":
                # Fit exponential: y = amplitude * exp(-decay * x) + offset
                from scipy.optimize import curve_fit

                def exp_func(x, amplitude, decay, offset):
                    return amplitude * np.exp(-decay * x) + offset

                # Initial guess
                p0 = [current_spectrum.max(), 0.001, current_spectrum.min()]
                popt, _ = curve_fit(exp_func, wavelengths, current_spectrum, p0=p0, maxfev=5000)

                self.widgets["bg_exp_amplitude"].value = float(popt[0])
                self.widgets["bg_exp_decay"].value = float(popt[1])
                self.widgets["bg_exp_offset"].value = float(popt[2])
                self.background_model = exp_func(axis_all, *popt)
                debug_print(
                    f"Background model set (Exponential): shape={self.background_model.shape}, min={self.background_model.min():.2f}, max={self.background_model.max():.2f}",
                    "APP",
                )

            # Update spectrum plot to show background
            self.update_spectrum_with_background()

            with self.widgets["status_output"]:
                self.widgets["status_output"].clear_output()
                print(f"✅ {method} background auto-fitted")
                if n_peak_points > 0:
                    print(f"   {n_peak_points} points inside the peak windows were left out")
                print("   Adjust parameters if needed, then click 'Apply Background'")

            debug_print(f"Background auto-fit complete: {method}", "APP")

        except Exception as e:
            with self.widgets["status_output"]:
                self.widgets["status_output"].clear_output()
                print(f"❌ Error auto-fitting background: {str(e)}")
            debug_print(f"Error in background autofit: {e}", "APP")

    def on_background_apply(self, button):
        """Apply background removal to data"""
        if not self.data_manager.is_data_loaded():
            return

        method = self.widgets["background_method"].value

        if method == "None":
            with self.widgets["status_output"]:
                self.widgets["status_output"].clear_output()
                print("⚠️ Select a background method first")
            return

        try:
            debug_print(f"Applying background: {method}", "APP")

            # Store original if not already stored
            if self.original_data_matrix is None:
                self.original_data_matrix = self.data_manager.data_matrix.copy()

            wavelengths = self.data_manager.wavelengths

            if method == "Manual":
                start_idx = self.widgets["bg_manual_start"].value
                num_curves = self.widgets["bg_manual_num"].value
                end_idx = min(start_idx + num_curves, len(self.data_manager.timestamps))

                # Calculate average background
                background = np.nanmean(self.original_data_matrix[start_idx:end_idx, :], axis=0)

            elif method == "Linear":
                slope = self.widgets["bg_linear_slope"].value
                intercept = self.widgets["bg_linear_intercept"].value
                background = slope * wavelengths + intercept

            elif method == "Polynomial":
                coeffs_str = self.widgets["bg_poly_coeffs"].value
                coeffs = [float(c.strip()) for c in coeffs_str.split(",")]
                background = np.polyval(coeffs, wavelengths)

            elif method == "Exponential":
                amplitude = self.widgets["bg_exp_amplitude"].value
                decay = self.widgets["bg_exp_decay"].value
                offset = self.widgets["bg_exp_offset"].value
                background = amplitude * np.exp(-decay * wavelengths) + offset

            elif method == "Custom":
                # Check if file was uploaded
                uploaded_files = self.widgets["bg_custom_upload"].value
                if not uploaded_files or len(uploaded_files) == 0:
                    with self.widgets["status_output"]:
                        self.widgets["status_output"].clear_output()
                        print("❌ Please upload a background file first")
                    return

                # Get the uploaded file - value is a tuple
                file_upload = uploaded_files[0]
                background = self.load_custom_background(file_upload["content"])

            # Apply background subtraction
            self.data_manager.data_matrix = self.original_data_matrix - background
            self.data_manager.current_spectrum = self.data_manager.data_matrix[
                self.data_manager.current_time_idx, :
            ]

            self.background_applied = True
            self.background_model = background

            # Enable remove button
            self.widgets["bg_remove_btn"].disabled = False

            # Update visualizations
            self.plot_manager.heatmap_fig = None
            self.update_visualizations()

            with self.widgets["status_output"]:
                self.widgets["status_output"].clear_output()
                print(f"✅ {method} background applied to all data")

                # Close the background handling accordion
                if self.background_accordion is not None:
                    self.background_accordion.selected_index = None
                    debug_print("Closed background handling accordion", "APP")

            # Close the background handling accordion
            try:
                # Find the background accordion widget
                for widget in self.gui_layouts.create_fitting_control_section().children:
                    if hasattr(widget, "set_title") and hasattr(widget, "selected_index"):
                        # Check if this is the background handling accordion
                        if widget.get_title(0) == "🎨 Background Handling":
                            widget.selected_index = None
                            debug_print("Closed background handling accordion", "APP")
                            break
            except Exception as e:
                debug_print(f"Could not close accordion: {e}", "APP")

            debug_print(f"Background applied: {method}", "APP")

        except Exception as e:
            with self.widgets["status_output"]:
                self.widgets["status_output"].clear_output()
                print(f"❌ Error applying background: {str(e)}")
            debug_print(f"Error applying background: {e}", "APP")

    def on_background_remove(self, button):
        """Remove applied background and restore original data"""
        if self.original_data_matrix is None:
            with self.widgets["status_output"]:
                self.widgets["status_output"].clear_output()
                print("⚠️ No background to remove")
            return

        try:
            debug_print("Removing background", "APP")

            # Restore original data
            self.data_manager.data_matrix = self.original_data_matrix.copy()
            self.data_manager.current_spectrum = self.data_manager.data_matrix[
                self.data_manager.current_time_idx, :
            ]

            self.background_applied = False
            self.background_model = None

            # Disable remove button
            self.widgets["bg_remove_btn"].disabled = True

            # Update visualizations
            self.plot_manager.heatmap_fig = None
            self.update_visualizations()

            with self.widgets["status_output"]:
                self.widgets["status_output"].clear_output()
                print("✅ Background removed - original data restored")

            debug_print("Background removed", "APP")

        except Exception as e:
            with self.widgets["status_output"]:
                self.widgets["status_output"].clear_output()
                print(f"❌ Error removing background: {str(e)}")
            debug_print(f"Error removing background: {e}", "APP")

    def update_spectrum_with_background(self):
        """Update spectrum plot showing the fitted background"""
        with self.widgets["spectrum_output"]:
            self.widgets["spectrum_output"].clear_output()

            import plotly.graph_objects as go

            fig = go.Figure()

            # Current spectrum
            fig.add_trace(
                go.Scatter(
                    x=self.data_manager.wavelengths,
                    y=self.data_manager.get_current_spectrum(),
                    mode="lines",
                    name="Spectrum",
                    line=dict(color="blue", width=2),
                )
            )

            # Background model
            if self.background_model is not None:
                fig.add_trace(
                    go.Scatter(
                        x=self.data_manager.wavelengths,
                        y=self.background_model,
                        mode="lines",
                        name="Background Model",
                        line=dict(color="red", width=2, dash="dash"),
                    )
                )

            fig.update_layout(
                title="Spectrum with Background Model",
                xaxis_title="Wavelength (nm)",
                yaxis_title="Intensity",
                height=500,
                template="plotly_white",
            )

            fig.show(renderer=config.PLOT_RENDERER)
