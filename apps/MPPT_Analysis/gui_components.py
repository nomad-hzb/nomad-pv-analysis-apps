"""
GUI components for MPPT Analysis App
"""

import base64
import io
import logging
import os
import zipfile
from datetime import datetime

import ipywidgets as widgets
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from IPython.display import HTML, display
from plotly.subplots import make_subplots

from hysprint_utils.batch_selection import create_batch_selection

logger = logging.getLogger(__name__)

APP_VERSION = "0.2.0"


def _html_float_format(value):
    """DataFrame.to_html's float_format must be a callable, unlike to_csv's -
    passing a printf-style string like "%.4f" raises TypeError: 'str' object
    is not callable on at least some pandas versions (confirmed on the NOMAD
    Oasis JupyterHub's pandas, even though it didn't raise locally here)."""
    return f"{value:.4f}"


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
                print(
                    f"✅ Data loaded successfully! Found {len(sample_ids)} samples with MPPT data"
                )
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

    def _build_full_fit_results_df(self):
        """Every selected sample/curve, fitted or not - unfitted ones get an
        explicit 'Not fitted' marker in every column rather than a blank cell.
        Fitted rows include point range and an underdetermined-fit flag
        alongside the model's own parameters, so this is also what the
        Download tab's Fit_Results sheet exports (rule: don't silently drop
        the same "say so" provenance the app itself shows)."""
        dm = self.data_manager
        curves = self.app_state.data["curves"]
        sample_ids = self.app_state.data["sample_ids"]
        selected_samples = self.app_state.data.get("selected_samples", [])

        fitted_rows = []
        not_fitted_keys = []
        for sample_id in selected_samples:
            curve_ids = dm.get_curve_ids_for_sample(curves, sample_ids, sample_id)
            known = [cid for (sid, cid) in self.app_state.fitted_curves_data if sid == sample_id]
            for cid in known:
                if cid not in curve_ids:
                    curve_ids.append(cid)
            if not curve_ids:
                curve_ids = known or [0]

            for curve_id in curve_ids:
                fit = self.app_state.fitted_curves_data.get((sample_id, curve_id))
                if fit is None:
                    not_fitted_keys.append((sample_id, curve_id))
                    continue
                row = {
                    "sample_id": sample_id,
                    "curve_id": curve_id,
                    "model": fit["model"].abbreviated_name,
                    "n_frames": len(fit["time"]),
                    "max_time_h": float(fit["time"].max()) if len(fit["time"]) else None,
                    "point_start": fit.get("point_start"),
                    "point_end": fit.get("point_end"),
                    "note": "⚠️ underdetermined fit" if fit.get("warning") else "",
                }
                row.update(fit.get("params", {}))
                fitted_rows.append(row)

        fitted_df = (
            pd.DataFrame(fitted_rows)
            if fitted_rows
            else pd.DataFrame(columns=["sample_id", "curve_id"])
        )
        columns = (
            list(fitted_df.columns)
            if not fitted_df.empty
            else ["sample_id", "curve_id", "model", "n_frames", "max_time_h"]
        )
        not_fitted_rows = []
        for sample_id, curve_id in not_fitted_keys:
            row = dict.fromkeys(columns, "Not fitted")
            row["sample_id"] = sample_id
            row["curve_id"] = curve_id
            not_fitted_rows.append(row)

        if not_fitted_rows:
            return pd.concat([fitted_df, pd.DataFrame(not_fitted_rows)], ignore_index=True)
        return fitted_df

    def create_fitting_tab(self):
        """Create the curve fitting tab: model/range/parameter controls on the
        left, a live raw-data + fit + residuals preview on the right, apply-
        to-all-or-one-sample-at-a-time fitting, and a results table covering
        every selected sample (fitted or not)."""
        from data_manager import fit_curve
        from fitting_tools import available_fit_model_list

        dm = self.data_manager
        curves = self.app_state.data["curves"]
        sample_ids = self.app_state.data["sample_ids"]
        selected_samples = list(self.app_state.data.get("selected_samples", []))

        model_options = [
            (f"{model.abbreviated_name}", i) for i, model in enumerate(available_fit_model_list)
        ]

        model_selector = widgets.Dropdown(
            options=model_options,
            value=0,
            description="Model:",
            layout=widgets.Layout(width="380px"),
            style={"description_width": "initial"},
        )
        formula_display = widgets.HTMLMath(value="")
        param_fields_container = widgets.VBox([])
        current_param_fields = {}  # {display_name: FloatText}, rebuilt per model/sample

        frame_range_selector = widgets.IntRangeSlider(
            value=(0, 0),
            min=0,
            max=0,
            step=1,
            description="Point Range:",
            continuous_update=False,  # refit/redraw the preview only on release, not every drag tick
            layout=widgets.Layout(width="380px"),
            style={"description_width": "initial"},
        )
        frame_range_info = widgets.HTML(value="")

        apply_to_all_checkbox = widgets.Checkbox(
            value=True,
            description="Apply to all selected samples",
            indent=False,
        )
        sample_dropdown = widgets.Dropdown(
            options=selected_samples,
            value=selected_samples[0] if selected_samples else None,
            description="Sample:",
            layout=widgets.Layout(width="380px", display="none"),
            style={"description_width": "initial"},
        )

        auto_fit_button = widgets.Button(
            description="Auto Fit",
            button_style="primary",
            tooltip="Fit using this model's own default starting guess, ignoring the fields below",
            layout=widgets.Layout(width="150px"),
        )
        manual_fit_button = widgets.Button(
            description="Fit With These Values",
            button_style="info",
            tooltip="Fit seeded from the parameter values below instead of the model's default guess",
            layout=widgets.Layout(width="200px"),
        )
        fit_status = widgets.Output()
        preview_output = widgets.Output()

        results_toggle = widgets.Accordion(
            children=[widgets.Output()], titles=("Show all fitting results",)
        )
        results_toggle.selected_index = 0

        stats_toggle = widgets.Accordion(
            children=[widgets.Output()], titles=("Statistical Summary",)
        )
        stats_toggle.selected_index = None

        def _sample_point_count(sample_id):
            lengths = []
            for curve_id in dm.get_curve_ids_for_sample(curves, sample_ids, sample_id):
                t_data, _ = dm.get_raw_curve(curves, sample_ids, sample_id, curve_id)
                if t_data is not None:
                    lengths.append(len(t_data))
            return min(lengths) if lengths else 0

        def _current_preview_sample():
            if apply_to_all_checkbox.value:
                return selected_samples[0] if selected_samples else None
            return sample_dropdown.value

        def get_current_param_values():
            return {name: field.value for name, field in current_param_fields.items()}

        def set_param_fields(params_dict):
            """Show a fit's converged values in the fields - called after any
            successful fit, auto or manual, per the agreed design: the fields
            always reflect the latest optimized result, not what was typed."""
            for name, field in current_param_fields.items():
                if name in params_dict:
                    field.value = float(params_dict[name])

        def rebuild_param_fields(change=None):
            nonlocal current_param_fields
            model = available_fit_model_list[model_selector.value]
            sample_id = _current_preview_sample()
            defaults = {}
            if sample_id:
                t_data, y_data = dm.get_raw_curve(curves, sample_ids, sample_id, 0)
                if t_data is not None and len(t_data):
                    start, end = frame_range_selector.value
                    t_sub, y_sub = t_data[start : end + 1], y_data[start : end + 1]
                    if len(t_sub) >= 1:
                        try:
                            defaults = model.default_guess(y_sub, t_sub)
                        except Exception:
                            logger.warning("default_guess failed for %s", model.name, exc_info=True)
            fields = {}
            rows = []
            for name in model.columns[: model.n_params]:
                field = widgets.FloatText(
                    value=round(float(defaults.get(name, 0.0)), 6),
                    description=name,
                    layout=widgets.Layout(width="240px"),
                    style={"description_width": "70px"},
                )
                field.observe(lambda change: update_preview(), names="value")
                fields[name] = field
                rows.append(field)
            current_param_fields = fields
            param_fields_container.children = rows

        def update_formula(change):
            model = available_fit_model_list[model_selector.value]
            params = ", ".join(model.columns)
            formula_display.value = (
                f"<b>Selected Model:</b> $${model.description}$$<br><b>Parameters:</b> {params}"
            )

        def update_range_bounds(change=None):
            if apply_to_all_checkbox.value:
                n_points = min((_sample_point_count(sid) for sid in selected_samples), default=0)
                suffix = " (limited to shortest measurement among selected samples)"
            else:
                n_points = (
                    _sample_point_count(sample_dropdown.value) if sample_dropdown.value else 0
                )
                suffix = ""
            new_max = max(n_points - 1, 0)
            frame_range_selector.max = new_max
            frame_range_selector.value = (0, new_max)
            frame_range_info.value = f"<small>0 – {new_max} measurement points{suffix}</small>"

        def update_preview(change=None):
            sample_id = _current_preview_sample()
            with preview_output:
                preview_output.clear_output(wait=True)
                if not sample_id:
                    print("Select a sample to preview.")
                    return

                t_data, y_data = dm.get_raw_curve(curves, sample_ids, sample_id, 0)
                if t_data is None or len(y_data) == 0:
                    print(f"No curve data available for {sample_id}.")
                    return

                start, end = frame_range_selector.value
                model = available_fit_model_list[model_selector.value]

                fig = make_subplots(
                    rows=2,
                    cols=1,
                    shared_xaxes=True,
                    row_heights=[0.72, 0.28],
                    vertical_spacing=0.04,
                )
                fig.add_trace(
                    go.Scatter(
                        x=np.arange(len(y_data)),
                        y=y_data,
                        mode="lines",
                        name="Raw data",
                        line=dict(width=2, color="#1f77b4"),
                    ),
                    row=1,
                    col=1,
                )
                for x in (start, end):
                    fig.add_vline(x=x, line_dash="dash", line_color="green", row=1, col=1)
                    fig.add_vline(x=x, line_dash="dash", line_color="green", row=2, col=1)

                fit = fit_curve(t_data, y_data, model, (start, end), get_current_param_values())
                if fit is not None:
                    x_fit = np.arange(
                        fit["point_start"], fit["point_start"] + len(fit["fitted_power"])
                    )
                    fig.add_trace(
                        go.Scatter(
                            x=x_fit,
                            y=fit["fitted_power"],
                            mode="lines",
                            name="Fit",
                            line=dict(width=2, color="red", dash="dash"),
                        ),
                        row=1,
                        col=1,
                    )
                    residuals = fit["original_power"] - fit["fitted_power"]
                    fig.add_trace(
                        go.Scatter(
                            x=x_fit,
                            y=residuals,
                            mode="markers",
                            name="Residual (raw - fit)",
                            marker=dict(size=5, color="#d62728"),
                        ),
                        row=2,
                        col=1,
                    )
                    fig.add_hline(y=0, line_dash="dot", line_color="gray", row=2, col=1)

                curve_note = (
                    ""
                    if len(dm.get_curve_ids_for_sample(curves, sample_ids, sample_id)) <= 1
                    else " (curve 0)"
                )
                fig.update_yaxes(title_text="Power Density", row=1, col=1)
                fig.update_yaxes(title_text="Residual", row=2, col=1)
                fig.update_xaxes(title_text="Measurement point index", row=2, col=1)
                fig.update_layout(
                    title=f"Preview - {sample_id}{curve_note}",
                    height=560,
                    margin=dict(t=40),
                )
                display(go.FigureWidget(fig))
                if fit is None:
                    print("⚠️ Not enough points in the selected range to fit (need at least 2).")
                elif fit.get("warning"):
                    print(f"⚠️ {fit['warning']}")

        def refresh_results_panels():
            full_df = self._build_full_fit_results_df()
            with results_toggle.children[0]:
                results_toggle.children[0].clear_output(wait=True)
                display(HTML("<h4>Detailed Fit Results</h4>"))
                if full_df.empty:
                    print("No samples selected.")
                else:
                    display(
                        HTML(
                            '<div style="overflow-x:auto;">'
                            + full_df.to_html(index=False, float_format=_html_float_format)
                            + "</div>"
                        )
                    )

            with stats_toggle.children[0]:
                stats_toggle.children[0].clear_output(wait=True)
                display(HTML("<h4>Statistical Summary</h4>"))
                if self.app_state.has_fit_results():
                    numerical_cols = self.app_state.fit_results.select_dtypes(
                        include=[np.number]
                    ).columns
                    if len(numerical_cols) > 0:
                        stats_df = self.app_state.fit_results[numerical_cols].describe()
                        display(
                            HTML(
                                '<div style="overflow-x:auto;">'
                                + stats_df.to_html(float_format=_html_float_format)
                                + "</div>"
                            )
                        )
                    else:
                        print("No numerical parameters to summarize")
                else:
                    print("No fitting results available yet.")

        def on_model_change(change):
            update_formula(change)
            rebuild_param_fields()
            update_preview()

        def on_mode_toggle(change):
            sample_dropdown.layout.display = "none" if apply_to_all_checkbox.value else ""
            if not apply_to_all_checkbox.value and not sample_dropdown.value and selected_samples:
                sample_dropdown.value = selected_samples[0]
            update_range_bounds()
            rebuild_param_fields()
            update_preview()

        def on_sample_change(change):
            update_range_bounds()
            rebuild_param_fields()
            update_preview()

        def perform_fitting(use_manual_values):
            if not selected_samples:
                with fit_status:
                    fit_status.clear_output()
                    print("⚠️ No samples selected. Please complete sample selection first.")
                return

            model = available_fit_model_list[model_selector.value]
            frame_range = frame_range_selector.value
            initial_values = get_current_param_values() if use_manual_values else None

            with fit_status:
                fit_status.clear_output()
                print("🔄 Fitting...")
                try:
                    if apply_to_all_checkbox.value:
                        fitted = {}
                        for sample_id in selected_samples:
                            for curve_id, fit in dm.fit_sample(
                                curves,
                                sample_ids,
                                sample_id,
                                model,
                                frame_range=frame_range,
                                initial_values=initial_values,
                            ).items():
                                fitted[(sample_id, curve_id)] = fit
                        self.app_state.set_fit_results(fitted)
                        new_fits = fitted
                    else:
                        sample_id = sample_dropdown.value
                        if not sample_id:
                            print("⚠️ No sample selected.")
                            return
                        fits = dm.fit_sample(
                            curves,
                            sample_ids,
                            sample_id,
                            model,
                            frame_range=frame_range,
                            initial_values=initial_values,
                        )
                        self.app_state.update_sample_fit_results(sample_id, fits)
                        new_fits = {(sample_id, cid): fit for cid, fit in fits.items()}

                    fit_count = len(new_fits)
                    if fit_count:
                        print(f"✅ Fitting completed! {fit_count} curve(s) fitted successfully")
                        for (sid, cid), fit in new_fits.items():
                            if fit.get("warning"):
                                print(f"⚠️ {sid} (curve {cid}): {fit['warning']}")
                        # Show the converged values, not what was typed - same for
                        # both buttons, per the agreed design.
                        preview_sample = _current_preview_sample()
                        preview_fit = new_fits.get((preview_sample, 0)) or next(
                            iter(new_fits.values()), None
                        )
                        if preview_fit:
                            set_param_fields(preview_fit.get("params", {}))
                        if self.app_controller:
                            # "Fit This Sample" stays on the Curve Fitting tab so you
                            # can keep working through samples one at a time; only
                            # "Fit All Curves" jumps to Visualization.
                            self.app_controller.enable_plotting_tab(
                                navigate=apply_to_all_checkbox.value
                            )
                    else:
                        print("❌ Fitting failed. No curves could be fitted successfully.")
                        print("This might be due to insufficient data points or numerical issues.")
                except Exception as e:
                    print(f"❌ Error during fitting: {str(e)}")
                    import traceback

                    traceback.print_exc()

            refresh_results_panels()
            update_preview()

        update_formula(None)
        update_range_bounds()
        rebuild_param_fields()
        refresh_results_panels()

        model_selector.observe(on_model_change, names="value")
        frame_range_selector.observe(update_preview, names="value")
        apply_to_all_checkbox.observe(on_mode_toggle, names="value")
        sample_dropdown.observe(on_sample_change, names="value")
        auto_fit_button.on_click(lambda b: perform_fitting(False))
        manual_fit_button.on_click(lambda b: perform_fitting(True))

        left_column = widgets.VBox(
            [
                model_selector,
                formula_display,
                widgets.HTML('<b>Parameters (editable - seeds "Fit With These Values"):</b>'),
                param_fields_container,
                frame_range_selector,
                frame_range_info,
                widgets.HBox([auto_fit_button, manual_fit_button]),
                fit_status,
            ],
            layout=widgets.Layout(width="420px"),
        )
        right_column = widgets.VBox(
            [
                widgets.HBox([apply_to_all_checkbox, sample_dropdown]),
                preview_output,
            ],
            layout=widgets.Layout(width="700px"),
        )

        update_preview()

        controls = widgets.VBox(
            [
                widgets.HTML("<h3>Curve Fitting</h3>"),
                widgets.HTML(
                    f"<p>Fit mathematical models to {len(selected_samples)} selected samples.</p>"
                ),
                widgets.HBox([left_column, right_column]),
                results_toggle,
                stats_toggle,
            ]
        )

        return controls

    def _create_write_to_nomad_section(self):
        """'Add fit results to NOMAD' button + explicit modify-the-database
        warning, gated behind a second Confirm/Cancel step before anything is
        actually written."""
        write_button = widgets.Button(
            description="Add fit results to NOMAD",
            button_style="warning",
            layout=widgets.Layout(width="260px"),
        )
        confirm_button = widgets.Button(
            description="Confirm - write to NOMAD", button_style="danger"
        )
        cancel_button = widgets.Button(description="Cancel")
        confirm_box = widgets.HBox(
            [confirm_button, cancel_button], layout=widgets.Layout(display="none")
        )
        write_status = widgets.Output()

        def on_write_click(b):
            confirm_box.layout.display = ""
            write_button.disabled = True
            with write_status:
                write_status.clear_output()
                display(
                    HTML(
                        "<div style='padding:10px;border:1px solid #f0ad4e;background:#fcf8e3;'>"
                        "⚠️ <b>This will modify existing values in the NOMAD database</b> "
                        "for every fitted sample's entry (fit method, point range used, and "
                        "any computed T95/T80/Ts95/Ts80/stabilization time). This cannot be "
                        "undone from this app. Are you sure?</div>"
                    )
                )

        def do_cancel(b):
            confirm_box.layout.display = "none"
            write_button.disabled = False
            with write_status:
                write_status.clear_output()

        def do_confirm(b):
            confirm_box.layout.display = "none"
            write_button.disabled = False
            with write_status:
                write_status.clear_output()
                if not self.app_state.fitted_curves_data:
                    print("⚠️ No fitted curves to write.")
                    return
                print("🔄 Writing fit results to NOMAD...")
                computed_by = f"MPPT_Analysis {APP_VERSION} ({os.environ.get('NOMAD_CLIENT_USER', 'unknown user')})"
                outcomes = self.data_manager.write_fit_results_to_nomad(
                    self.app_state.data.get("entries"),
                    self.app_state.fitted_curves_data,
                    computed_by,
                )
                write_status.clear_output()
                for outcome in outcomes:
                    icon = "✅" if outcome["success"] else "❌"
                    print(
                        f"{icon} {outcome['sample_id']} (curve {outcome['curve_id']}): "
                        f"{outcome['message']}"
                    )

        write_button.on_click(on_write_click)
        confirm_button.on_click(do_confirm)
        cancel_button.on_click(do_cancel)

        return widgets.VBox([write_button, confirm_box, write_status])

    def create_plotting_tab(self):
        """Create the plotting tab with curve and histogram plots"""
        write_section = self._create_write_to_nomad_section()

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
                        # go.FigureWidget renders via the ipywidgets comm protocol; a
                        # plain go.Figure relies on a notebook mimetype renderer that
                        # isn't guaranteed to be registered (see commit 8928055).
                        for fig in figs:
                            display(go.FigureWidget(fig))
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
                        display(go.FigureWidget(fig))
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
                widgets.HTML("<h3>MPPT Visualization</h3>"),
                widgets.HTML(
                    f"<p>Plot analysis for {self.app_state.get_selected_samples_count()} selected samples with {self.app_state.get_fit_results_count()} fitted curves.</p>"
                ),
                write_section,
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

                # Sheet 3: Fit results - every selected sample/curve, including
                # ones not yet fitted (matches the Curve Fitting tab's own table)
                if self.app_state.has_selected_samples():
                    self._build_full_fit_results_df().to_excel(
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
