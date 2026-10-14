"""Fitting handlers of PLAnalysisApp (gui_layouts.py): fit parameters, fit current/all/range,
update from fit, Excel export and save into h5. A mixin: it relies on the attributes
PLAnalysisApp sets up."""

import logging
import warnings

import config
from IPython.display import display
from utils import debug_print

warnings.filterwarnings("ignore", message="Using UFloat objects with std_dev==0")

logger = logging.getLogger(__name__)


class FitHandlersMixin:
    def prepare_fit_parameters(self):
        """Prepare fitting parameters from UI inputs"""
        params = {
            "background_model": "None",
            "poly_degree": 2,
            "center_bound": self.widgets["center_bound_input"].value,
            "peak_models": [],
        }

        for peak_model in self.peak_models:
            model_type = peak_model._widgets["type"].value

            peak_params = {"type": model_type, "name": peak_model._widgets["name"].value}

            # Add parameters based on model type
            if model_type == "Linear":
                peak_params["slope"] = peak_model._widgets["slope"].value
                peak_params["intercept"] = peak_model._widgets["intercept"].value

            elif model_type == "Polynomial":
                peak_params["poly_degree"] = peak_model._widgets["poly_degree"].value

                # Use fitted coefficients if available
                if hasattr(peak_model, "_fitted_coeffs"):
                    peak_params["fitted_coeffs"] = peak_model._fitted_coeffs

            else:  # Gaussian, Voigt, Lorentzian, Skewed Gaussian, Skewed Voigt
                peak_params["center"] = peak_model._widgets["center"].value
                peak_params["height"] = peak_model._widgets["height"].value
                peak_params["sigma"] = peak_model._widgets["sigma"].value

                # Add gamma for models that use it
                if model_type in ["Voigt", "Skewed Gaussian", "Skewed Voigt"]:
                    peak_params["gamma"] = peak_model._widgets["gamma"].value

                # Add fix flags
                peak_params["fix_center"] = peak_model._widgets["fix_center"].value
                peak_params["fix_height"] = peak_model._widgets["fix_height"].value
                peak_params["fix_sigma"] = peak_model._widgets["fix_sigma"].value

                if model_type in ["Voigt", "Skewed Gaussian", "Skewed Voigt"]:
                    peak_params["fix_gamma"] = peak_model._widgets["fix_gamma"].value

                # Add bounds (empty string = use default).
                # Accept both "." and "," as decimal separators so users in
                # comma-decimal locales don't silently lose their bound.
                def _parse_bound(val):
                    try:
                        return float(val.strip().replace(",", "."))
                    except (ValueError, AttributeError):
                        return None

                for key in (
                    "center_min",
                    "center_max",
                    "height_min",
                    "height_max",
                    "sigma_min",
                    "sigma_max",
                ):
                    v = _parse_bound(peak_model._widgets[key].value)
                    if v is not None:
                        peak_params[key] = v

                if model_type in ["Voigt", "Skewed Gaussian", "Skewed Voigt"]:
                    for key in ("gamma_min", "gamma_max"):
                        v = _parse_bound(peak_model._widgets[key].value)
                        if v is not None:
                            peak_params[key] = v

            params["peak_models"].append(peak_params)

        # Print bounds summary to status output
        bound_keys = (
            "center_min",
            "center_max",
            "height_min",
            "height_max",
            "sigma_min",
            "sigma_max",
            "gamma_min",
            "gamma_max",
        )
        with self.widgets["status_output"]:
            for i, pm in enumerate(params["peak_models"]):
                active_bounds = {k: pm[k] for k in bound_keys if k in pm}
                if active_bounds:
                    bounds_str = ", ".join(f"{k}={v:.4g}" for k, v in active_bounds.items())
                    print(f"Model {i + 1} bounds: {bounds_str}")

        debug_print(f"Prepared fit parameters: {len(params['peak_models'])} models", "APP")
        return params

    def on_fit_current(self, button):
        """Fit current spectrum"""
        if not self.data_manager.is_data_loaded():
            return

        try:
            debug_print("Fitting current spectrum", "APP")

            # Check if we have any peak models
            if len(self.peak_models) == 0:
                with self.widgets["status_output"]:
                    self.widgets["status_output"].clear_output()
                    print("❌ No peak models defined. Add at least one peak model first.")
                return

            # Prepare fitting parameters
            fit_params = self.prepare_fit_parameters()
            debug_print(f"Fit params: {fit_params}", "APP")

            self.fitting_engine.create_fit_parameters(**fit_params)

            # Get wavelength range from slider
            wl_range = self.widgets["wavelength_range_slider"].value
            wavelengths = self.data_manager.wavelengths
            spectrum = self.data_manager.get_current_spectrum()

            # Check if range is limited (not the full range)
            wl_min = float(wavelengths.min())
            wl_max = float(wavelengths.max())
            is_limited = (wl_range[0] > wl_min) or (wl_range[1] < wl_max)

            if is_limited:
                # Fit only in the selected range
                mask = (wavelengths >= wl_range[0]) & (wavelengths <= wl_range[1])
                wavelengths_fit = wavelengths[mask]
                spectrum_fit = spectrum[mask]

                debug_print(
                    f"Fitting limited range: {wl_range[0]:.1f} - {wl_range[1]:.1f} {self.wavelength_unit}",
                    "APP",
                )
                debug_print(
                    f"Full data points: {len(wavelengths)}, Fit data points: {len(wavelengths_fit)}",
                    "APP",
                )
                debug_print(
                    f"Wavelength fit range: {wavelengths_fit.min():.2f} - {wavelengths_fit.max():.2f}",
                    "APP",
                )
            else:
                wavelengths_fit = wavelengths
                spectrum_fit = spectrum
                debug_print("Fitting full wavelength range", "APP")
                debug_print(f"Data points: {len(wavelengths)}", "APP")

            # Perform fitting
            result = self.fitting_engine.fit_current_spectrum(wavelengths_fit, spectrum_fit)

            debug_print(f"Fit result: success={result.success}, rsquared={result.rsquared}", "APP")

            # Store for parameter update
            self.last_fit_result = result

            # Update R-squared display
            self.widgets["r_squared_display"].value = f"<b>R²:</b> {result.rsquared:.4f}"

            # Enable update parameters button (the start values are only updated below when
            # the fit is good, otherwise by this button)
            self.widgets["update_params_btn"].disabled = False

            # The plotter uses result.fit_x as x-axis for all fit traces, so no
            # padding is needed. For a limited wavelength range the fit was already
            # run on the masked subset, so fit_x is already the correct shorter array.
            debug_print(
                f"Fit x-axis: {len(result.fit_x)} points out of {len(wavelengths)} wavelengths",
                "APP",
            )

            # Update spectrum plot with fit
            with self.widgets["spectrum_output"]:
                self.widgets["spectrum_output"].clear_output()

                # Pass wavelength range if limited
                wl_range_display = wl_range if is_limited else None

                peak_name_map = {
                    f"p{i}": pm._widgets["name"].value for i, pm in enumerate(self.peak_models)
                }
                fig = self.plot_manager.create_spectrum_plot(
                    self.data_manager.wavelengths,
                    self.data_manager.get_current_spectrum(),
                    fit_result=result,
                    wavelength_range=wl_range_display,
                    wavelength_unit=self.wavelength_unit,
                    name_map=peak_name_map,
                )

                display(fig)

            # Automatically update parameters from successful fit
            if result.rsquared > 0.5:  # Only auto-update if fit is decent
                self.on_update_parameters(None)
                auto_updated = True
            else:
                auto_updated = False

            with self.widgets["status_output"]:
                self.widgets["status_output"].clear_output()
                print(f"✅ Fit completed. R² = {result.rsquared:.4f}")
                if is_limited:
                    print(f"   Range: {wl_range[0]:.1f} - {wl_range[1]:.1f} {self.wavelength_unit}")
                if auto_updated:
                    print("✅ Parameters automatically updated for batch fitting")
                else:
                    print("⚠️ Low R² - click 'Update from Fit' manually if needed")

            debug_print(
                f"Fit complete: R²={result.rsquared:.4f}, auto-updated={auto_updated}", "APP"
            )

        except Exception as e:
            import traceback

            with self.widgets["status_output"]:
                self.widgets["status_output"].clear_output()
                print(f"❌ Error fitting spectrum: {str(e)}")
                print("\n🔍 Full traceback:")
                print(traceback.format_exc())
            debug_print(f"Error in fitting: {e}", "APP")

    def on_update_parameters(self, button):
        """Update model parameters with fitted values"""
        try:
            debug_print("DEBUG: on_update_parameters called")
            if self.last_fit_result is None:
                with self.widgets["status_output"]:
                    self.widgets["status_output"].clear_output()
                    print("❌ No fit result available. Please fit current spectrum first.")
                return

            debug_print("Updating parameters from fit result", "APP")

            result = self.last_fit_result
            fitted_params = result.params

            with self.widgets["status_output"]:
                self.widgets["status_output"].clear_output()
                print("🔄 Updating model parameters with fitted values...")

            report = []  # shown in the Output below: a print outside it is dropped under Voila
            # Update ALL model parameters in UI
            updated_count = 0
            for i, model in enumerate(self.peak_models):
                model_type = model._widgets["type"].value
                prefix = f"p{i}_"

                if model_type in [
                    "Gaussian",
                    "Voigt",
                    "Lorentzian",
                    "Skewed Gaussian",
                    "Skewed Voigt",
                ]:
                    # Update center
                    center_param = f"{prefix}center"
                    if center_param in fitted_params:
                        model._widgets["center"].value = round(fitted_params[center_param].value, 3)
                        report.append(
                            f"  Model {i + 1} center: {fitted_params[center_param].value:.3f}"
                        )
                        updated_count += 1

                    # Update sigma
                    sigma_param = f"{prefix}sigma"
                    if sigma_param in fitted_params:
                        model._widgets["sigma"].value = round(fitted_params[sigma_param].value, 3)
                        report.append(
                            f"  Model {i + 1} sigma: {fitted_params[sigma_param].value:.3f}"
                        )
                        updated_count += 1

                    # Update gamma for models that have it
                    if model_type in ["Voigt", "Skewed Gaussian", "Skewed Voigt"]:
                        gamma_param = f"{prefix}gamma"
                        if gamma_param in fitted_params:
                            model._widgets["gamma"].value = round(
                                fitted_params[gamma_param].value, 3
                            )
                            report.append(
                                f"  Model {i + 1} gamma: {fitted_params[gamma_param].value:.3f}"
                            )
                            updated_count += 1

                    # Update height: a fitted parameter for every peak type (see
                    # FittingModels._set_height), so no conversion from the area
                    height_param = f"{prefix}height"
                    if height_param in fitted_params:
                        height = fitted_params[height_param].value
                        model._widgets["height"].value = round(height, 3)
                        report.append(f"  Model {i + 1} height: {height:.3f}")
                        updated_count += 1

                elif model_type == "Linear":
                    # Update slope and intercept
                    slope_param = f"{prefix}slope"
                    intercept_param = f"{prefix}intercept"

                    if slope_param in fitted_params:
                        model._widgets["slope"].value = round(fitted_params[slope_param].value, 3)
                        report.append(
                            f"  Model {i + 1} slope: {fitted_params[slope_param].value:.3f}"
                        )
                        updated_count += 1

                    if intercept_param in fitted_params:
                        model._widgets["intercept"].value = round(
                            fitted_params[intercept_param].value, 3
                        )
                        report.append(
                            f"  Model {i + 1} intercept: {fitted_params[intercept_param].value:.3f}"
                        )
                        updated_count += 1

                elif model_type == "Polynomial":
                    # Update polynomial coefficients
                    # First, figure out the degree
                    degree = model._widgets["poly_degree"].value

                    # Extract all coefficients
                    coeffs = []
                    for j in range(degree + 1):
                        coeff_param = f"{prefix}c{j}"
                        if coeff_param in fitted_params:
                            coeffs.append(fitted_params[coeff_param].value)
                        else:
                            coeffs.append(0.0)  # Fallback

                    # Store them (we'll need to add a way to pass these)
                    # For now, just print them
                    report.append(f"  Model {i + 1} (Polynomial degree {degree}):")
                    for j, coeff in enumerate(coeffs):
                        report.append(f"    c{j}: {coeff:.6f}")

                    # Store coefficients in the model for later use
                    if not hasattr(model, "_fitted_coeffs"):
                        model._fitted_coeffs = {}
                    model._fitted_coeffs = coeffs
                    updated_count += 1

            with self.widgets["status_output"]:
                for line in report:
                    print(line)
                print(f"✅ Updated {updated_count} parameters from fit")

            debug_print(f"Updated {updated_count} parameters from fit", "APP")

        except Exception as e:
            import traceback

            with self.widgets["status_output"]:
                self.widgets["status_output"].clear_output()
                print(f"❌ Error updating parameters: {str(e)}")
                print("\n🔍 Traceback:")
                traceback.print_exc()
            debug_print(f"Error updating parameters: {e}", "APP")

    def on_fit_all(self, button):
        """Fit all spectra using batch processing"""
        if not self.data_manager.is_data_loaded():
            return

        try:
            with self.widgets["status_output"]:
                self.widgets["status_output"].clear_output()
                print("Starting batch fitting... This may take a while.")

            debug_print("Starting batch fitting for all spectra", "APP")

            # Show progress bar
            self.widgets["fit_progress"].layout.visibility = "visible"
            self.widgets["fit_progress"].value = 0
            self.widgets["fit_progress"].description = "Fitting..."

            # Prepare fitting parameters
            fit_params = self.prepare_fit_parameters()
            self.fitting_engine.create_fit_parameters(**fit_params)

            # Get wavelength range from slider
            wl_range = self.widgets["wavelength_range_slider"].value
            wavelengths = self.data_manager.wavelengths
            wl_min = float(wavelengths.min())
            wl_max = float(wavelengths.max())
            is_limited = (wl_range[0] > wl_min) or (wl_range[1] < wl_max)

            # Apply wavelength range mask if limited
            if is_limited:
                mask = (wavelengths >= wl_range[0]) & (wavelengths <= wl_range[1])
                wavelengths_fit = wavelengths[mask]
                data_matrix_fit = self.data_manager.data_matrix[:, mask]
                debug_print(
                    f"Batch fitting with wavelength range: {wl_range[0]:.1f} - {wl_range[1]:.1f} {self.wavelength_unit}",
                    "APP",
                )
                debug_print(
                    f"Full wavelengths: {len(wavelengths)}, Fit wavelengths: {len(wavelengths_fit)}",
                    "APP",
                )
            else:
                wavelengths_fit = wavelengths
                data_matrix_fit = self.data_manager.data_matrix
                debug_print("Batch fitting full wavelength range", "APP")

            # Perform batch fitting
            fit_sequential = self.widgets["fit_sequential_checkbox"].value
            results = self.fitting_engine.fit_all_spectra(
                wavelengths_fit,
                data_matrix_fit,
                self.data_manager.timestamps,
                use_smart_init=fit_sequential,
            )

            # Count successful fits
            successful = sum(1 for r in results.values() if r and r.get("success", False))

            # Store results for export
            self.fitting_engine.fitting_results = results

            # Enable export button
            self.widgets["export_btn"].disabled = False

            # Create time series visualizations with explicit clear
            with self.widgets["time_series_output"]:
                self.widgets["time_series_output"].clear_output(wait=True)

            self.create_time_series_plots()
            self.refresh_fit_vis()

            debug_print("Time series plots refreshed", "APP")

            with self.widgets["status_output"]:
                self.widgets["status_output"].clear_output()
                print("✅ Batch fitting completed!")
                print(f"📊 Fitted {successful}/{len(results)} spectra successfully.")

            # Update progress bar to complete
            self.widgets["fit_progress"].value = 100
            self.widgets["fit_progress"].description = "Complete!"
            self.widgets["fit_progress"].bar_style = "success"

            debug_print(f"Batch fitting complete: {successful}/{len(results)} successful", "APP")

        except Exception as e:
            with self.widgets["status_output"]:
                self.widgets["status_output"].clear_output()
                print(f"❌ Error in batch fitting: {str(e)}")
            debug_print(f"Error in batch fitting: {e}", "APP")

    def on_fit_range(self, button):
        """Fit spectra in selected range"""
        if not self.data_manager.is_data_loaded():
            return

        try:
            start_idx = self.widgets["fit_start_idx"].value
            end_idx = self.widgets["fit_end_idx"].value

            if start_idx >= end_idx:
                with self.widgets["status_output"]:
                    self.widgets["status_output"].clear_output()
                    print("❌ Start index must be less than end index")
                return

            with self.widgets["status_output"]:
                self.widgets["status_output"].clear_output()
                print(f"Starting range fitting ({start_idx} to {end_idx})...")

            debug_print(f"Starting range fitting: {start_idx} to {end_idx}", "APP")

            # Show progress bar
            self.widgets["fit_progress"].layout.visibility = "visible"
            self.widgets["fit_progress"].value = 0
            self.widgets["fit_progress"].description = "Fitting..."

            # Prepare fitting parameters
            fit_params = self.prepare_fit_parameters()
            self.fitting_engine.create_fit_parameters(**fit_params)

            # Get wavelength range from slider
            wl_range = self.widgets["wavelength_range_slider"].value
            wavelengths = self.data_manager.wavelengths
            wl_min = float(wavelengths.min())
            wl_max = float(wavelengths.max())
            is_limited = (wl_range[0] > wl_min) or (wl_range[1] < wl_max)

            # Apply wavelength range mask if limited
            if is_limited:
                mask = (wavelengths >= wl_range[0]) & (wavelengths <= wl_range[1])
                wavelengths_fit = wavelengths[mask]
                data_matrix_fit = self.data_manager.data_matrix[:, mask]
                debug_print(
                    f"Range fitting with wavelength range: {wl_range[0]:.1f} - {wl_range[1]:.1f} {self.wavelength_unit}",
                    "APP",
                )
                debug_print(
                    f"Full wavelengths: {len(wavelengths)}, Fit wavelengths: {len(wavelengths_fit)}",
                    "APP",
                )
            else:
                wavelengths_fit = wavelengths
                data_matrix_fit = self.data_manager.data_matrix
                debug_print("Range fitting full wavelength range", "APP")

            # Perform batch fitting on range with progress callback
            fit_sequential = self.widgets["fit_sequential_checkbox"].value
            results = self.fitting_engine.fit_all_spectra(
                wavelengths_fit,
                data_matrix_fit,
                self.data_manager.timestamps,
                fit_range=(start_idx, end_idx),
                use_smart_init=fit_sequential,
            )

            # Count successful fits
            successful = sum(1 for r in results.values() if r and r.get("success", False))

            # Enable export button
            self.widgets["export_btn"].disabled = False

            # Create time series visualizations with explicit clear
            with self.widgets["time_series_output"]:
                self.widgets["time_series_output"].clear_output(wait=True)

            self.create_time_series_plots()
            self.refresh_fit_vis()

            debug_print("Time series plots refreshed", "APP")

            with self.widgets["status_output"]:
                self.widgets["status_output"].clear_output()
                print("✅ Range fitting completed!")
                print(f"📊 Fitted {successful}/{len(results)} spectra successfully.")

            # Update progress bar to complete
            self.widgets["fit_progress"].value = 100
            self.widgets["fit_progress"].description = "Complete!"
            self.widgets["fit_progress"].bar_style = "success"

            debug_print(f"Range fitting complete: {successful}/{len(results)} successful", "APP")

        except Exception as e:
            with self.widgets["status_output"]:
                self.widgets["status_output"].clear_output()
                print(f"❌ Error in range fitting: {str(e)}")
            debug_print(f"Error in range fitting: {e}", "APP")

    # =========================================================================
    # EXPORT
    # =========================================================================

    def on_export_results(self, button):
        """Export fitting results"""
        if not self.fitting_engine.has_fitting_results():
            with self.widgets["export_output"]:
                self.widgets["export_output"].clear_output()
                print("❌ No fitting results to export. Please fit spectra first.")
            return

        try:
            debug_print("Exporting results", "APP")

            import base64
            from datetime import datetime

            from IPython.display import HTML, display

            # Create filename
            filename = f"pl_fitting_results_{datetime.now().strftime(config.TIMESTAMP_FORMAT)}.xlsx"

            # Export to Excel in memory
            import io

            excel_buffer = io.BytesIO()

            # Use export_utils to create Excel file
            self.export_utils.export_to_excel(
                self.fitting_engine.fitting_results,
                self.data_manager.timestamps,
                filename=excel_buffer,  # Write to buffer instead of file
            )

            # Get the buffer content
            excel_buffer.seek(0)
            excel_data = excel_buffer.read()

            # Encode to base64
            b64 = base64.b64encode(excel_data).decode()

            # Create download link with JavaScript
            js_code = f"""
            var link = document.createElement('a');
            link.href = 'data:application/vnd.openxmlformats-officedocument.spreadsheetml.sheet;base64,{b64}';
            link.download = '{filename}';
            document.body.appendChild(link);
            link.click();
            document.body.removeChild(link);
            """

            with self.widgets["export_output"]:
                self.widgets["export_output"].clear_output()
                print("✅ Results prepared for download!")
                print(f"📊 File: {filename}")
                print()

                # Display download button
                download_button_html = f"""
                <button onclick="{js_code}" style="
                    background-color: #28a745;
                    color: white;
                    padding: 10px 20px;
                    border: none;
                    border-radius: 5px;
                    cursor: pointer;
                    font-size: 14px;
                    font-weight: bold;
                ">
                    📥 Download {filename}
                </button>
                """

                display(HTML(download_button_html))
                print()
                print(
                    "💡 Click the button above to download. If it doesn't work automatically, the download should start shortly."
                )

            debug_print(f"Results prepared for download: {filename}", "APP")

        except Exception as e:
            import traceback

            with self.widgets["export_output"]:
                self.widgets["export_output"].clear_output()
                print(f"❌ Error exporting results: {str(e)}")
                print("\n🔍 Full traceback:")
                print(traceback.format_exc())
            debug_print(f"Error exporting: {e}", "APP")

    # =========================================================================
    # VISUALIZATION
    # =========================================================================

    def on_save_into_h5(self, button):
        debug_print("Save into H5 triggered", "SAVE_H5")

        has_results = self.fitting_engine.has_fitting_results()
        debug_print(f"has_fitting_results: {has_results}", "SAVE_H5")
        if not has_results:
            with self.widgets["status_output"]:
                self.widgets["status_output"].clear_output()
                print("❌ No fitting results to export. Please fit spectra first.")
            return

        if self.data_manager.data_source != "h5":
            with self.widgets["status_output"]:
                self.widgets["status_output"].clear_output()
                print(
                    "❌ Only data loaded from an h5 file can be saved into it (not a CSV upload)."
                )
            return

        h5_path = self.data_manager.h5_path
        time_unit = self.data_manager.time_unit
        h5_mode = self.data_manager.h5_mode
        debug_print(f"h5_path: {h5_path}", "SAVE_H5")
        debug_print(f"time_unit: {time_unit}", "SAVE_H5")
        debug_print(f"h5_mode: {h5_mode}", "SAVE_H5")
        debug_print(f"wavelength_unit: {self.wavelength_unit}", "SAVE_H5")
        debug_print(
            f"fitting_results keys: {list(self.fitting_engine.fitting_results.keys())[:5]}",
            "SAVE_H5",
        )

        try:
            self.export_utils.export_to_isa_h5(
                self.fitting_engine.fitting_results,
                h5_path,
                time_unit=time_unit,
                h5_mode=h5_mode,
                wavelength_unit=self.wavelength_unit,
                fit_settings=self.fitting_engine.batch_settings,
            )
            with self.widgets["status_output"]:
                self.widgets["status_output"].clear_output()
                print("✅ Fitting results saved to H5 file.")
        except OSError as e:
            if "lock" in str(e).lower() or "unable to open" in str(e).lower():
                with self.widgets["status_output"]:
                    self.widgets["status_output"].clear_output()
                    print(
                        "⚠️ Could not save: the H5 file is currently open in another program. Please close it and try again."
                    )
            else:
                with self.widgets["status_output"]:
                    self.widgets["status_output"].clear_output()
                    print(f"❌ OSError saving to H5: {e}")
            debug_print(f"OSError saving to H5: {e}", "SAVE_H5")
        except Exception as e:
            import traceback

            tb = traceback.format_exc()
            debug_print(f"Unexpected error saving to H5: {e}\n{tb}", "SAVE_H5")
            with self.widgets["status_output"]:
                self.widgets["status_output"].clear_output()
                print(f"❌ Unexpected error saving to H5: {type(e).__name__}: {e}")
                print(tb)
