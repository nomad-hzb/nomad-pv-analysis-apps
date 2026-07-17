"""
GUI components for MPPT Analysis App
"""

import base64
import io
import zipfile
from datetime import datetime

import ipywidgets as widgets
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from IPython.display import HTML, display
from plotly.subplots import make_subplots

from hysprint_utils.batch_selection import create_batch_selection


class GUIComponents:
    """Creates and manages GUI components for the MPPT Analysis App"""

    def __init__(self, app_state, data_manager, plot_manager, app_controller=None):
        self.app_state = app_state
        self.data_manager = data_manager
        self.plot_manager = plot_manager
        self.app_controller = app_controller

    def create_batch_tab(self):
        """Create the batch selection tab"""
        filter_status = widgets.Output(layout={"border": "1px solid #ccc", "padding": "10px"})
        load_status = widgets.Output(layout={"border": "1px solid #ccc", "padding": "10px"})

        filter_button = widgets.Button(
            description="Show MPPT Batches",
            button_style="info",
            tooltip="Narrow the list to only batches that contain MPPT measurements",
            layout=widgets.Layout(width="200px"),
        )

        def on_load(selector):
            if not selector.value:
                with load_status:
                    load_status.clear_output()
                    print("⚠️ Please select at least one batch")
                return
            with load_status:
                load_status.clear_output()
                print("🔄 Loading MPPT data...")
                result, error = self.data_manager.load_data_from_batches(selector.value)
                if error:
                    print(f"❌ {error}")
                    return
                curves, sample_ids, entries, properties = result
                self.app_state.load_curves_data(curves, sample_ids, entries, properties)
                print(f"✅ Data loaded successfully! Found {len(sample_ids)} samples with MPPT data")
                if self.app_controller:
                    self.app_controller.enable_sample_tab()

        try:
            batch_widget = create_batch_selection(
                self.data_manager.url, self.data_manager.token, on_load
            )
            selector = batch_widget.children[1]  # SelectMultiple is children[1]
        except Exception as exc:
            msg = str(exc)
            batch_widget = widgets.VBox([widgets.HTML("<p>Batch list unavailable.</p>")])
            selector = widgets.SelectMultiple()
            with filter_status:
                if "401" in msg or "Unauthorized" in msg:
                    print("❌ Authentication failed (401) — token invalid or expired.")
                    print("   Use the 'Load demo data' button above to explore the app offline.")
                else:
                    print(f"❌ Could not load batch list: {exc}")

        def apply_mppt_filter(b):
            filter_button.disabled = True
            filter_button.description = "🔄 Filtering..."
            with filter_status:
                filter_status.clear_output(wait=True)
                try:
                    mppt_batches = self.data_manager.get_mppt_batch_ids()
                    selector.options = mppt_batches
                    if mppt_batches:
                        print(f"✅ Showing {len(mppt_batches)} batches with MPPT data")
                    else:
                        print("⚠️ No MPPT batches found on this server.")
                except Exception as exc:
                    msg = str(exc)
                    if "401" in msg or "Unauthorized" in msg:
                        print("❌ Authentication failed (401) — token invalid or expired.")
                    else:
                        print(f"❌ Could not filter batches: {exc}")
            filter_button.description = "Show MPPT Batches"
            filter_button.disabled = False

        filter_button.on_click(apply_mppt_filter)

        return widgets.VBox(
            [
                widgets.HTML("<h3>Batch Selection</h3>"),
                filter_button,
                batch_widget,
                filter_status,
                load_status,
            ]
        )

    def create_sample_tab(self):
        """Create the sample selection tab"""
        name_preset = widgets.Dropdown(
            options=[
                ("Sample Name", "sample_name"),
                ("Batch", "batch"),
                ("Sample Description", "sample_description"),
                ("Custom", "custom"),
            ],
            value="sample_name",
            description="Name preset:",
            tooltip="Presets for how the samples will be named",
        )

        selection_status = widgets.Output()
        selectors_container = widgets.VBox()

        confirm_button = widgets.Button(
            description="Confirm Selection",
            button_style="primary",
            layout=widgets.Layout(width="200px"),
        )

        def create_sample_selectors():
            self.app_state.sample_selectors = {}
            selector_widgets = []

            for sample_id in self.app_state.data["sample_ids"]:
                selector = self.create_sample_selector(sample_id, name_preset.value)
                self.app_state.sample_selectors[sample_id] = selector
                selector_widgets.append(selector["container"])

            selectors_container.children = selector_widgets

            with selection_status:
                selection_status.clear_output()
                print(
                    f"⚠️ Selection not confirmed - {len(self.app_state.data['sample_ids'])} samples available"
                )

        def confirm_selection(b):
            selected_samples = []
            custom_names = {}

            for sample_id, selector in self.app_state.sample_selectors.items():
                if selector["checkbox"].value:
                    selected_samples.append(sample_id)
                    if name_preset.value == "custom" and selector["text"].value.strip():
                        custom_names[sample_id] = selector["text"].value.strip()

            if not selected_samples:
                with selection_status:
                    selection_status.clear_output()
                    print("⚠️ Please select at least one sample")
                return

            self.app_state.set_selected_samples(selected_samples, custom_names)

            with selection_status:
                selection_status.clear_output()
                print(f"✅ Selection confirmed - {len(selected_samples)} samples selected")
                if custom_names:
                    print("Custom names applied:")
                    for sample_id, name in custom_names.items():
                        print(f"  {sample_id} → {name}")

            # Enable fitting tab through app controller
            if self.app_controller:
                self.app_controller.enable_fitting_tab()

        def on_preset_change(change):
            create_sample_selectors()

        name_preset.observe(on_preset_change, names="value")
        confirm_button.on_click(confirm_selection)

        create_sample_selectors()

        controls = widgets.VBox(
            [
                widgets.HTML("<h3>Sample Selection</h3>"),
                widgets.HTML(
                    f"<p>Found {len(self.app_state.data['sample_ids'])} samples with MPPT data.</p>"
                ),
                name_preset,
                selectors_container,
                confirm_button,
                selection_status,
            ]
        )

        return controls

    def create_sample_selector(self, sample_id, preset_type):
        """Create a sample selector widget"""
        if preset_type == "batch":
            item_split = sample_id.split("&")
            if len(item_split) >= 2:
                default_name = item_split[0]
            else:
                default_name = "_".join(sample_id.split("_")[:-1])
        elif preset_type == "sample_name":
            item_split = sample_id.split("&")
            if len(item_split) >= 2:
                default_name = "&".join(item_split[1:])
            else:
                default_name = sample_id
        elif preset_type == "sample_description":
            default_name = (
                self.app_state.data["properties"].loc[sample_id, "description"]
                if sample_id in self.app_state.data["properties"].index
                else sample_id
            )
        else:
            default_name = ""

        checkbox = widgets.Checkbox(
            value=True,
            description=sample_id,
            layout=widgets.Layout(width="300px"),
            style={"description_width": "initial"},
        )

        if preset_type == "custom":
            text_input = widgets.Text(
                value=default_name,
                placeholder="Enter custom name",
                layout=widgets.Layout(width="200px"),
            )
            container = widgets.HBox([checkbox, text_input])
        else:
            name_label = widgets.Label(value=default_name, layout=widgets.Layout(width="200px"))
            text_input = widgets.Text(value=default_name, layout=widgets.Layout(display="none"))
            container = widgets.HBox([checkbox, name_label])

        return {"checkbox": checkbox, "text": text_input, "container": container}

    def create_fitting_tab(self):
        """Create the curve fitting tab"""
        from fitting_tools import available_fit_model_list

        model_options = [
            (f"{model.abbreviated_name}", i) for i, model in enumerate(available_fit_model_list)
        ]

        model_selector = widgets.Dropdown(
            options=model_options,
            value=0,
            description="Model:",
            layout=widgets.Layout(width="400px"),
            style={"description_width": "initial"},
        )

        # Compute the minimum point count across all selected curves so the
        # slider range is guaranteed to be valid for every curve being fitted.
        _point_counts = []
        if self.app_state.has_curves_data():
            _curves = self.app_state.data["curves"]
            _selected = self.app_state.data.get("selected_samples", [])
            for _sid in _selected:
                try:
                    _sd = _curves.loc[_sid]
                    if hasattr(_sd.index, "nlevels") and _sd.index.nlevels > 1:
                        for _cidx in _sd.index.get_level_values(0).unique():
                            _point_counts.append(len(_sd.loc[_cidx]))
                    else:
                        _point_counts.append(len(_sd))
                except (KeyError, IndexError):
                    continue
        _min_points = min(_point_counts) if _point_counts else 100

        frame_range_selector = widgets.IntRangeSlider(
            value=(0, _min_points - 1),
            min=0,
            max=_min_points - 1,
            step=1,
            description="Point Range:",
            layout=widgets.Layout(width="500px"),
            style={"description_width": "initial"},
        )
        frame_range_info = widgets.HTML(
            value=f"<small>0 – {_min_points - 1} measurement points "
                  f"(limited to shortest measurement among selected samples)</small>"
        )

        fit_button = widgets.Button(
            description="Fit All Curves",
            button_style="primary",
            layout=widgets.Layout(width="200px"),
        )

        fit_status = widgets.Output()
        formula_display = widgets.HTMLMath(value="")

        results_toggle = widgets.Accordion(
            children=[widgets.Output()], titles=("Show all fitting results",)
        )
        results_toggle.selected_index = None

        stats_toggle = widgets.Accordion(
            children=[widgets.Output()], titles=("Statistical Summary",)
        )
        stats_toggle.selected_index = 0

        def update_formula(change):
            model = available_fit_model_list[model_selector.value]
            params = ", ".join(model.columns)
            formula_display.value = (
                f"<b>Selected Model:</b> $${ model.description }$$"
                f"<br><b>Parameters:</b> {params}"
            )

        def perform_fitting(b):
            if not self.app_state.has_selected_samples():
                with fit_status:
                    fit_status.clear_output()
                    print("⚠️ No samples selected. Please complete sample selection first.")
                return

            with fit_status:
                fit_status.clear_output()
                print("🔄 Fitting curves...")

                try:
                    model = available_fit_model_list[model_selector.value]

                    # Get both results and fitted curves data
                    _start, _end = frame_range_selector.value
                    _frame_range = (_start, None if _end >= _min_points - 1 else _end)
                    fit_results, fitted_curves_data = self.data_manager.fit_all_samples_lmfit(
                        self.app_state.data["curves"],
                        self.app_state.data["sample_ids"],
                        self.app_state.data["selected_samples"],
                        model,
                        frame_range=_frame_range,
                    )

                    self.app_state.set_fit_results(fit_results, fitted_curves_data, model)

                    if self.app_state.has_fit_results():
                        print(
                            f"✅ Fitting completed! {len(fit_results)} curves fitted successfully"
                        )

                        with results_toggle.children[0]:
                            results_toggle.children[0].clear_output()
                            display(HTML("<h4>Detailed Fit Results</h4>"))
                            display(HTML(
                                '<div style="overflow-x:auto;">'
                                + fit_results.to_html(index=False, float_format="%.4f")
                                + "</div>"
                            ))

                        with stats_toggle.children[0]:
                            stats_toggle.children[0].clear_output()
                            display(HTML("<h4>Statistical Summary</h4>"))

                            numerical_cols = fit_results.select_dtypes(include=[np.number]).columns
                            if len(numerical_cols) > 0:
                                stats_df = fit_results[numerical_cols].describe()
                                display(HTML(
                                    '<div style="overflow-x:auto;">'
                                    + stats_df.to_html(float_format="%.4f")
                                    + "</div>"
                                ))
                            else:
                                print("No numerical parameters to summarize")

                        # Enable plotting tab through app controller
                        if self.app_controller:
                            self.app_controller.enable_plotting_tab()

                    else:
                        print("❌ Fitting failed. No curves could be fitted successfully.")
                        print("This might be due to insufficient data points or numerical issues.")

                except Exception as e:
                    print(f"❌ Error during fitting: {str(e)}")
                    import traceback

                    traceback.print_exc()

        update_formula(None)

        model_selector.observe(update_formula, names="value")
        fit_button.on_click(perform_fitting)

        controls = widgets.VBox(
            [
                widgets.HTML("<h3>Curve Fitting</h3>"),
                widgets.HTML(
                    f"<p>Fit mathematical models to {self.app_state.get_selected_samples_count()} selected samples.</p>"
                ),
                model_selector,
                formula_display,
                frame_range_selector,
                frame_range_info,
                fit_button,
                fit_status,
                stats_toggle,
                results_toggle,
            ]
        )

        return controls

    def create_plotting_tab(self):
        """Create the plotting tab with curve and histogram plots"""
        # Plot type selector
        plot_variable = widgets.Dropdown(
            options=[
                ("Power Density", "power_density"),
                ("Voltage", "voltage"),
                ("Current Density", "current_density"),
            ],
            value="power_density",
            description="Variable:",
            layout=widgets.Layout(width="200px"),
        )

        # Plot style selector
        plot_style = widgets.Dropdown(
            options=[
                ("Individual (each curve separate)", "individual"),
                ("All together (one plot)", "together"),
                ("By sample (grouped by sample)", "by_sample"),
                ("By area (median + quartiles)", "area_quartiles"),
                ("By area (mean + std dev)", "area_std"),
            ],
            value="individual",
            description="Plot style:",
            layout=widgets.Layout(width="300px"),
        )

        # Show fitting lines checkbox
        show_fits_checkbox = widgets.Checkbox(
            value=True,
            description="Show fitting lines",
            tooltip="Overlay fitted curves from the selected model",
        )

        # Generate plots button
        plot_button = widgets.Button(
            description="Generate Plots",
            button_style="primary",
            layout=widgets.Layout(width="200px"),
        )

        # Output areas
        curves_output = widgets.Output()
        histograms_output = widgets.Output()

        def generate_plots(b):
            if not self.app_state.has_fit_results():
                with curves_output:
                    curves_output.clear_output()
                    print("⚠️ No fitting results available. Please complete curve fitting first.")
                return

            with curves_output:
                curves_output.clear_output(wait=True)
                try:
                    figs = self.plot_manager.plot_curves(
                        plot_variable.value, plot_style.value, show_fits_checkbox.value
                    )
                    if figs:
                        for fig in figs:
                            display(fig)
                    else:
                        print("⚠️ No curve data to plot.")
                except Exception as e:
                    print(f"❌ Error generating curve plots: {str(e)}")
                    import traceback

                    traceback.print_exc()

            with histograms_output:
                histograms_output.clear_output(wait=True)
                try:
                    fig = self.plot_manager.plot_histograms()
                    if fig is not None:
                        display(fig)
                    else:
                        print("⚠️ No histogram data available.")
                except Exception as e:
                    print(f"❌ Error generating histograms: {str(e)}")
                    import traceback

                    traceback.print_exc()

        plot_button.on_click(generate_plots)

        # Auto-generate on first open
        generate_plots(None)

        controls = widgets.VBox(
            [
                widgets.HTML("<h3>MPPT Curve Plotting</h3>"),
                widgets.HTML(
                    f"<p>Plot analysis for {self.app_state.get_selected_samples_count()} selected samples with {self.app_state.get_fit_results_count()} fitted curves.</p>"
                ),
                widgets.HBox([plot_variable, plot_style]),
                show_fits_checkbox,
                plot_button,
                widgets.HTML("<h4>Curve Plots</h4>"),
                curves_output,
                widgets.HTML("<h4>Parameter Histograms</h4>"),
                histograms_output,
            ]
        )

        return controls

    def create_download_tab(self):
        """Create the download results tab"""
        # File format options
        excel_format = widgets.Checkbox(
            value=True,
            description="Excel file with multiple sheets",
            disabled=True,
            tooltip="Main results file with curve data, fit results, and statistics",
        )

        plots_format = widgets.Dropdown(
            options=[
                ("HTML (Interactive)", "html"),
                ("PNG (Static Images)", "png"),
                ("Both HTML and PNG", "both"),
            ],
            value="html",
            description="Plot format:",
            layout=widgets.Layout(width="300px"),
        )

        include_raw_data = widgets.Checkbox(
            value=True,
            description="Include raw curve data",
            tooltip="Include the original MPPT curve measurements",
        )

        include_fitted_data = widgets.Checkbox(
            value=True,
            description="Include fitted curve data",
            tooltip="Include the fitted curves from mathematical models",
        )

        # Download button
        download_button = widgets.Button(
            description="📦 Generate Download Package",
            button_style="success",
            layout=widgets.Layout(width="250px"),
        )

        # Status output
        download_status = widgets.Output()

        # Download link output
        download_link = widgets.Output()

        def generate_download_package(b):
            if not self.app_state.has_fit_results():
                with download_status:
                    download_status.clear_output()
                    print("⚠️ No fitting results available. Please complete curve fitting first.")
                return

            with download_status:
                download_status.clear_output()
                print("🔄 Generating download package...")

                try:
                    self._create_download_package(
                        plots_format.value,
                        include_raw_data.value,
                        include_fitted_data.value,
                        download_link,
                        download_status,
                    )
                except Exception as e:
                    print(f"❌ Error generating download package: {str(e)}")
                    import traceback

                    traceback.print_exc()

        download_button.on_click(generate_download_package)

        controls = widgets.VBox(
            [
                widgets.HTML("<h3>📦 Download Analysis Results</h3>"),
                widgets.HTML(
                    "<p>Create a comprehensive zip file containing all analysis results.</p>"
                ),
                widgets.HTML("<h4>📋 Package Contents:</h4>"),
                excel_format,
                widgets.HTML("<h4>📊 Plot Options:</h4>"),
                plots_format,
                widgets.HTML("<h4>📈 Data Options:</h4>"),
                include_raw_data,
                include_fitted_data,
                download_button,
                download_status,
                download_link,
            ]
        )

        return controls

    def _create_download_package(
        self, plots_format, include_raw_data, include_fitted_data, download_link, download_status
    ):
        """Create the download package with Excel files and plots"""
        # Create a BytesIO buffer for the zip file
        zip_buffer = io.BytesIO()

        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
            # 1. Create Excel file with multiple sheets
            excel_buffer = io.BytesIO()
            with pd.ExcelWriter(excel_buffer, engine="openpyxl") as writer:
                # Sheet 1: Raw curve data
                if include_raw_data and self.app_state.has_curves_data():
                    self._add_raw_data_sheet(writer)

                # Sheet 2: Fitted curve data
                if include_fitted_data and self.app_state.fitted_curves_data:
                    self._add_fitted_data_sheet(writer)

                # Sheet 3: Fit results
                if self.app_state.has_fit_results():
                    self.app_state.fit_results.to_excel(
                        writer, sheet_name="Fit_Results", index=False
                    )

                # Sheet 4: Statistical summary
                if self.app_state.has_fit_results():
                    self._add_statistical_summary_sheet(writer)

                # Sheet 5: Sample information
                if self.app_state.has_selected_samples():
                    self._add_sample_info_sheet(writer)

            # Add Excel file to zip
            zip_file.writestr("MPPT_Analysis_Results.xlsx", excel_buffer.getvalue())

            # 2. Generate basic plots
            print("📊 Generating basic plots...")
            plot_counter = self._add_plots_to_zip(zip_file, plots_format)

            # 3. Generate histograms
            self._add_histograms_to_zip(zip_file, plots_format)

            # 4. Add README
            self._add_readme_to_zip(zip_file, plot_counter, plots_format)

        # Prepare download
        zip_buffer.seek(0)
        zip_data = zip_buffer.read()

        # Create download link
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"MPPT_Analysis_Results_{timestamp}.zip"

        # Encode for download
        b64_data = base64.b64encode(zip_data).decode()

        with download_link:
            download_link.clear_output()
            display(
                HTML(f'''
            <div style="padding: 20px; border: 2px solid #28a745; border-radius: 10px; background-color: #d4edda;">
                <h3 style="color: #155724; margin-top: 0;">✅ Download Package Ready!</h3>
                <p><strong>File size:</strong> {len(zip_data) / 1024 / 1024:.2f} MB</p>
                <p><strong>Contents:</strong></p>
                <ul>
                    <li>Excel file with {self.app_state.get_fit_results_count()} fitted curves</li>
                    <li>Plots ({plots_format} format)</li>
                    <li>Parameter histograms</li>
                    <li>README with analysis details</li>
                </ul>
                <a href="data:application/zip;base64,{b64_data}" 
                   download="{filename}" 
                   style="background-color: #28a745; color: white; padding: 10px 20px; 
                          text-decoration: none; border-radius: 5px; font-weight: bold;">
                    📥 Download {filename}
                </a>
            </div>
            ''')
            )

        print(f"✅ Package generated successfully! ({len(zip_data) / 1024 / 1024:.2f} MB)")

    def _add_raw_data_sheet(self, writer):
        """Add raw curve data to Excel"""
        all_data = {}
        max_length = 0

        for sample_id in self.app_state.data.get("selected_samples", []):
            try:
                sample_data = self.app_state.data["curves"].loc[sample_id]
                if hasattr(sample_data.index, "nlevels") and sample_data.index.nlevels > 1:
                    for curve_idx in sample_data.index.get_level_values(0).unique():
                        curve_data = sample_data.loc[curve_idx]
                        col_prefix = f"{sample_id}_curve_{curve_idx}"

                        all_data[f"{col_prefix}_time"] = curve_data["time"].values
                        all_data[f"{col_prefix}_power_density"] = curve_data["power_density"].values
                        all_data[f"{col_prefix}_voltage"] = curve_data["voltage"].values
                        all_data[f"{col_prefix}_current_density"] = curve_data[
                            "current_density"
                        ].values

                        max_length = max(max_length, len(curve_data))
                else:
                    col_prefix = f"{sample_id}_curve_0"
                    all_data[f"{col_prefix}_time"] = sample_data["time"].values
                    all_data[f"{col_prefix}_power_density"] = sample_data["power_density"].values
                    all_data[f"{col_prefix}_voltage"] = sample_data["voltage"].values
                    all_data[f"{col_prefix}_current_density"] = sample_data[
                        "current_density"
                    ].values

                    max_length = max(max_length, len(sample_data))
            except:  # noqa: E722
                continue

        # Pad all arrays to the same length
        for key, values in all_data.items():
            if len(values) < max_length:
                padded = np.full(max_length, np.nan)
                padded[: len(values)] = values
                all_data[key] = padded

        if all_data:
            raw_curves_df = pd.DataFrame(all_data)
            raw_curves_df.to_excel(writer, sheet_name="Raw_Curve_Data", index=False)

    def _add_fitted_data_sheet(self, writer):
        """Add fitted curve data to Excel"""
        fitted_data_dict = {}
        max_length = 0

        for (sample_id, curve_id), fitted_data in self.app_state.fitted_curves_data.items():
            col_prefix = f"{sample_id}_curve_{curve_id}"

            fitted_data_dict[f"{col_prefix}_time"] = fitted_data["time"]
            fitted_data_dict[f"{col_prefix}_fitted_power_density"] = fitted_data["fitted_power"]
            fitted_data_dict[f"{col_prefix}_original_power_density"] = fitted_data.get(
                "original_power", fitted_data["fitted_power"]
            )

            max_length = max(max_length, len(fitted_data["time"]))

        # Pad all arrays to the same length
        for key, values in fitted_data_dict.items():
            if len(values) < max_length:
                padded = np.full(max_length, np.nan)
                padded[: len(values)] = values
                fitted_data_dict[key] = padded

        if fitted_data_dict:
            fitted_curves_df = pd.DataFrame(fitted_data_dict)
            fitted_curves_df.to_excel(writer, sheet_name="Fitted_Curve_Data", index=False)

    def _add_statistical_summary_sheet(self, writer):
        """Add statistical summary to Excel"""
        numerical_cols = self.app_state.fit_results.select_dtypes(include=[np.number]).columns
        if len(numerical_cols) > 0:
            stats_df = self.app_state.fit_results[numerical_cols].describe()
            stats_df.to_excel(writer, sheet_name="Statistical_Summary")

    def _add_sample_info_sheet(self, writer):
        """Add sample information to Excel"""
        sample_info_list = []
        for sample_id in self.app_state.data["selected_samples"]:
            info = {
                "sample_id": sample_id,
                "description": self.app_state.data["properties"].loc[sample_id, "description"]
                if sample_id in self.app_state.data["properties"].index
                else "",
                "custom_name": self.app_state.data.get("custom_names", {}).get(sample_id, ""),
            }
            sample_info_list.append(info)

        sample_info_df = pd.DataFrame(sample_info_list)
        sample_info_df.to_excel(writer, sheet_name="Sample_Information", index=False)

    def _add_plots_to_zip(self, zip_file, plots_format):
        """Add basic plots to zip file"""
        plot_counter = 0

        try:
            selected_data = self.data_manager.get_selected_curve_data(
                self.app_state.data["curves"],
                self.app_state.data["sample_ids"],
                self.app_state.data["selected_samples"],
                "power_density",
            )

            if selected_data:
                for i, curve in enumerate(selected_data[:3]):  # Limit to first 3
                    try:
                        fig = go.Figure()

                        # Add original data
                        fig.add_trace(
                            go.Scatter(
                                x=curve["time"],
                                y=curve["data"],
                                mode="lines",
                                name="Data",
                                line=dict(width=2, color="blue"),
                            )
                        )

                        # Add fitted curve if available
                        curve_key = (curve["sample_id"], curve["curve_id"])
                        if curve_key in self.app_state.fitted_curves_data:
                            fitted_data = self.app_state.fitted_curves_data[curve_key]
                            fig.add_trace(
                                go.Scatter(
                                    x=fitted_data["time"],
                                    y=fitted_data["fitted_power"],
                                    mode="lines",
                                    name="Fit",
                                    line=dict(width=2, color="red", dash="dash"),
                                )
                            )

                        fig.update_layout(
                            title=f"Power Density - {curve['sample_id']} Curve {curve['curve_id']}",
                            xaxis_title="Time (hours)",
                            yaxis_title="Power Density",
                            width=800,
                            height=500,
                        )

                        plot_counter += 1
                        plot_name = f"{plot_counter:02d}_power_density_{curve['sample_id']}_curve_{curve['curve_id']}"

                        if plots_format in ["html", "both"]:
                            html_str = fig.to_html(include_plotlyjs="cdn")
                            zip_file.writestr(f"plots/{plot_name}.html", html_str)

                        if plots_format in ["png", "both"]:
                            try:
                                img_bytes = fig.to_image(format="png", width=800, height=600)
                                zip_file.writestr(f"plots/{plot_name}.png", img_bytes)
                            except:  # noqa: E722
                                print(f"⚠️ Could not generate PNG for plot {i + 1}")

                        print(f"Generated plot {i + 1}")

                    except Exception as e:
                        print(f"⚠️ Error generating plot {i + 1}: {str(e)}")
                        continue

                print(f"Generated {plot_counter} individual plots")

        except Exception as e:
            print(f"⚠️ Error in plot generation: {str(e)}")

        return plot_counter

    def _add_histograms_to_zip(self, zip_file, plots_format):
        """Add histogram plots to zip file"""
        try:
            available_params = list(self.app_state.fit_results.columns)
            hist_params = [
                param for param in ["t80", "T80", "tS", "ts", "Ts80"] if param in available_params
            ]

            if hist_params:
                n_params = len(hist_params)
                cols = min(2, n_params)
                rows = (n_params + 1) // 2

                fig = make_subplots(
                    rows=rows,
                    cols=cols,
                    subplot_titles=[f"{param} Distribution" for param in hist_params],
                )

                for i, param in enumerate(hist_params):
                    row = i // cols + 1
                    col = i % cols + 1

                    values = self.app_state.fit_results[param].dropna()

                    if len(values) > 0:
                        fig.add_trace(
                            go.Histogram(x=values, name=param, opacity=0.7, nbinsx=20),
                            row=row,
                            col=col,
                        )

                fig.update_layout(
                    title="Parameter Distributions from Curve Fitting",
                    height=400 * rows,
                    width=800,
                    showlegend=False,
                )

                for i, param in enumerate(hist_params):
                    row = i // cols + 1
                    col = i % cols + 1
                    fig.update_xaxes(title_text=f"{param} (hours)", row=row, col=col)
                    fig.update_yaxes(title_text="Count", row=row, col=col)

                plot_name = "histograms_1"

                if plots_format in ["html", "both"]:
                    html_str = fig.to_html(include_plotlyjs="cdn")
                    zip_file.writestr(f"plots/{plot_name}.html", html_str)

                if plots_format in ["png", "both"]:
                    try:
                        img_bytes = fig.to_image(format="png", width=800, height=600)
                        zip_file.writestr(f"plots/{plot_name}.png", img_bytes)
                    except:  # noqa: E722
                        print("⚠️ Could not generate PNG histogram")

        except Exception as e:
            print(f"⚠️ Error generating histograms: {str(e)}")

    def _add_readme_to_zip(self, zip_file, plot_counter, plots_format):
        """Add README file to zip"""
        readme_content = f"""
MPPT Analysis Results Package
Generated: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}

CONTENTS:
=========
1. MPPT_Analysis_Results.xlsx - Excel file with multiple sheets containing raw data, fitted curves, fit results, and statistics
2. plots/ folder - {plots_format.upper()} plots of the analysis results
3. README.txt - This file

ANALYSIS DETAILS:
================
Selected Samples: {self.app_state.get_selected_samples_count()}
Total Fitted Curves: {self.app_state.get_fit_results_count()}
Variables Analyzed: Power Density, Voltage, Current Density

For detailed information about the analysis parameters and methods, 
please refer to the original MPPT analysis notebook.
"""
        zip_file.writestr("README.txt", readme_content)

    def create_disabled_tab(self, tab_name, message):
        """Create a disabled placeholder tab"""
        disabled_message = widgets.HTML(
            value=f"<div style='text-align: center; padding: 50px; color: #888;'>"
            f"<h3>🔒 {tab_name}</h3>"
            f"<p>{message}</p>"
            f"</div>"
        )
        return widgets.VBox([disabled_message])
