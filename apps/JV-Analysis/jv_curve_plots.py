"""JV curve plots, as a mixin of PlotManager (plot_manager.py).

JV curve plots (all cells, working, rejected, best device, separated by cell or substrate).
"""

import logging

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

logger = logging.getLogger(__name__)


class JVCurvePlotsMixin:
    """Needs PlotManager's _extract_rgb_from_color and its parameter tables."""

    def _create_matching_curves_data(self, jv_data, curves_data):
        """Create curves data that matches specific JV measurements EXACTLY including status"""
        if jv_data.empty:
            return curves_data.iloc[0:0].copy()  # Return empty DataFrame with same structure

        # Check if status field exists in both datasets
        has_status_jv = "status" in jv_data.columns
        has_status_curves = "status" in curves_data.columns

        # Use sample_id for precise matching if available
        if "sample_id" in jv_data.columns and "sample_id" in curves_data.columns:
            logger.debug("  Using sample_id for precise matching")

            # Create set of exact measurement combinations from JV data
            jv_combinations = set()
            duplicate_combinations = []

            for _, row in jv_data.iterrows():
                if has_status_jv and has_status_curves:
                    # Use 5-field matching including status
                    combination = (
                        row["sample_id"],
                        row["cell"],
                        row["direction"],
                        row["ilum"],
                        row["status"],
                    )
                else:
                    # Use 4-field matching without status
                    combination = (row["sample_id"], row["cell"], row["direction"], row["ilum"])

                if combination in jv_combinations:
                    duplicate_combinations.append(combination)
                jv_combinations.add(combination)

            logger.debug("  JV combinations to match: %s", len(jv_combinations))
            logger.debug("  Total JV records: %s", len(jv_data))
            logger.debug("  Duplicate combinations found: %s", len(duplicate_combinations))

            if len(duplicate_combinations) > 0:
                logger.debug("  Example duplicates: %s", duplicate_combinations[:3])
                # Show what makes these records different
                example_dup = duplicate_combinations[0] if duplicate_combinations else None
                if example_dup:
                    if has_status_jv and has_status_curves:
                        sample_id, cell, direction, ilum, status = example_dup
                        matching_records = jv_data[
                            (jv_data["sample_id"] == sample_id)
                            & (jv_data["cell"] == cell)
                            & (jv_data["direction"] == direction)
                            & (jv_data["ilum"] == ilum)
                            & (jv_data["status"] == status)
                        ]
                    else:
                        sample_id, cell, direction, ilum = example_dup
                        matching_records = jv_data[
                            (jv_data["sample_id"] == sample_id)
                            & (jv_data["cell"] == cell)
                            & (jv_data["direction"] == direction)
                            & (jv_data["ilum"] == ilum)
                        ]
                    logger.debug("  Records with same combination:")
                    for _, record in matching_records.iterrows():
                        logger.debug(
                            "    PCE: %.2f%%, Status: %s",
                            record["PCE(%)"],
                            record.get("status", "N/A"),
                        )

            # Filter curves using exact matching
            def should_include_curve(curve_row):
                if has_status_jv and has_status_curves:
                    combination = (
                        curve_row["sample_id"],
                        curve_row["cell"],
                        curve_row["direction"],
                        curve_row["ilum"],
                        curve_row["status"],
                    )
                else:
                    combination = (
                        curve_row["sample_id"],
                        curve_row["cell"],
                        curve_row["direction"],
                        curve_row["ilum"],
                    )
                return combination in jv_combinations

            matching_curves = curves_data[curves_data.apply(should_include_curve, axis=1)].copy()

        else:
            # Fallback to sample name matching
            logger.debug("  Using sample name matching (fallback)")

            jv_combinations = set()
            for _, row in jv_data.iterrows():
                combination = (row["sample"], row["cell"], row["direction"], row["ilum"])
                jv_combinations.add(combination)

            def should_include_curve(curve_row):
                combination = (
                    curve_row["sample"],
                    curve_row["cell"],
                    curve_row["direction"],
                    curve_row["ilum"],
                )
                return combination in jv_combinations

            matching_curves = curves_data[curves_data.apply(should_include_curve, axis=1)].copy()

        logger.debug("  Matching curve records found: %s", len(matching_curves))
        logger.debug(
            "  Expected ratio curves/JV: %.1fx (should be ~2x)",
            len(matching_curves) / len(jv_data) if jv_data is not None and len(jv_data) > 0 else 0,
        )

        # Additional verification: check if we're getting the right samples
        if not matching_curves.empty:
            unique_curve_devices = set()
            for _, row in matching_curves.iterrows():
                device = f"{row['sample']}_{row['cell']}"
                unique_curve_devices.add(device)

            unique_jv_devices = set()
            for _, row in jv_data.iterrows():
                device = f"{row['sample']}_{row['cell']}"
                unique_jv_devices.add(device)

            logger.debug("  Unique devices in curves: %s", len(unique_curve_devices))
            logger.debug("  Unique devices in JV: %s", len(unique_jv_devices))
            logger.debug(
                "  Device overlap: %s", len(unique_curve_devices.intersection(unique_jv_devices))
            )

            # Show some examples to verify correctness
            if len(unique_curve_devices) > 0:
                curve_examples = list(unique_curve_devices)[:3]
                jv_examples = list(unique_jv_devices)[:3]
                logger.debug("  Curve device examples: %s", curve_examples)
                logger.debug("  JV device examples: %s", jv_examples)

        return matching_curves

    def create_jv_best_device_plot(
        self, jvc_data, curves_data, colors=None, show_summary=True, flip_current=False
    ):  # noqa: E501
        """Plot JV curves for the best device (highest PCE) with all available measurements"""

        voltage_rows = curves_data[curves_data["variable"] == "Voltage (V)"]
        if not voltage_rows.empty:
            first_v_row = voltage_rows.iloc[0]  # noqa: F841

        # Find best device (sample + cell combination with highest PCE)
        best_idx = jvc_data["PCE(%)"].idxmax()
        best_sample = jvc_data.loc[best_idx]["sample"]
        best_cell = jvc_data.loc[best_idx]["cell"]
        best_pce = jvc_data.loc[best_idx]["PCE(%)"]  # noqa: F841

        # Get ALL measurements for this sample+cell combination (not just best measurement)
        best_device_jv = jvc_data[
            (jvc_data["sample"] == best_sample) & (jvc_data["cell"] == best_cell)
        ]
        best_device_curves = curves_data[
            (curves_data["sample"] == best_sample) & (curves_data["cell"] == best_cell)
        ]

        all_matching_curves = curves_data[curves_data["sample"] == best_sample]

        if len(all_matching_curves) > 0:
            device_curves = all_matching_curves[all_matching_curves["cell"] == best_cell]  # noqa: F841

        # Get ALL measurements for this sample+cell combination (not just best measurement)
        best_device_jv = jvc_data[
            (jvc_data["sample"] == best_sample) & (jvc_data["cell"] == best_cell)
        ]
        best_device_curves = curves_data[
            (curves_data["sample"] == best_sample) & (curves_data["cell"] == best_cell)
        ]

        if not best_device_curves.empty:
            voltage_curves = best_device_curves[best_device_curves["variable"] == "Voltage (V)"]
            current_curves = best_device_curves[
                best_device_curves["variable"] == "Current Density(mA/cm2)"
            ]

        if best_device_curves.empty:
            logger.debug("No curve data found for best device")
            return None, ""

        # Organize curves by status, direction
        voltage_curves = best_device_curves[best_device_curves["variable"] == "Voltage (V)"]  # noqa: F841
        current_curves = best_device_curves[  # noqa: F841
            best_device_curves["variable"] == "Current Density(mA/cm2)"
        ]

        fig = go.Figure()

        # Add axis lines. xref/yref="paper" span the full plot regardless of the
        # current axis range, and (unlike data-referenced shapes) don't get pulled
        # into the axis autorange computation -- otherwise the modebar's "Autoscale"
        # button would zoom out to include these lines instead of just the data.
        fig.add_shape(
            type="line",
            xref="paper",
            x0=0,
            x1=1,
            yref="y",
            y0=0,
            y1=0,
            line=dict(color="gray", width=2),
        )
        fig.add_shape(
            type="line",
            xref="x",
            x0=0,
            x1=0,
            yref="paper",
            y0=0,
            y1=1,
            line=dict(color="gray", width=2),
        )

        if colors is None:
            colors = ["#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd", "#8c564b"]

        voltage_measurements = {}
        current_measurements = {}

        for idx, curve_row in best_device_curves.iterrows():
            direction = curve_row["direction"]
            variable_type = curve_row["variable"]

            # Extract the actual data values
            data_values = []
            for col in curve_row.index[8:]:
                try:
                    val = float(curve_row[col])
                    if not pd.isna(val):
                        data_values.append(val)
                except (ValueError, TypeError):
                    continue

            # Group by direction
            key = f"{direction}"

            # Store voltage and current data in lists to handle multiple measurements
            if variable_type == "Voltage (V)":
                if key not in voltage_measurements:
                    voltage_measurements[key] = []
                voltage_measurements[key].append(data_values)
            elif variable_type == "Current Density(mA/cm2)":
                if key not in current_measurements:
                    current_measurements[key] = []
                current_measurements[key].append(data_values)

        # Create proper measurement pairs by matching voltage and current data
        measurement_pairs = []
        voltage_list = []
        current_list = []

        # Collect all voltage and current measurements with their metadata
        for key in voltage_measurements.keys():
            direction = key.split("_", 1)
            for i, voltage_array in enumerate(voltage_measurements[key]):
                voltage_list.append(
                    {
                        "data": voltage_array,
                        "direction": direction,
                        "measurement_id": f"{direction}_{i}",
                    }
                )

        for key in current_measurements.keys():
            direction = key.split("_", 1)
            for i, current_array in enumerate(current_measurements[key]):
                current_list.append(
                    {
                        "data": current_array,
                        "direction": direction,
                        "measurement_id": f"{direction}_{i}",
                    }
                )

        # Match voltage and current by measurement_id
        for v_item in voltage_list:
            for c_item in current_list:
                if v_item["measurement_id"] == c_item["measurement_id"]:
                    measurement_pairs.append(
                        {
                            "voltage": v_item["data"],
                            "current": c_item["data"],
                            "direction": v_item["direction"],
                            "measurement_index": int(v_item["measurement_id"].split("_")[1]),
                        }
                    )
                    break

        # Sort pairs to ensure consistent ordering
        measurement_pairs.sort(key=lambda x: (x["measurement_index"], x["direction"]))

        # Group pairs: each measurement index gets one color, shared between Forward and Reverse
        unique_measurements = {}
        for pair in measurement_pairs:
            idx = pair["measurement_index"]
            if idx not in unique_measurements:
                unique_measurements[idx] = []
            unique_measurements[idx].append(pair)

        # Track every plotted point so the axis range can fall back to the data's own
        # extent (with an edge gap) once it no longer fits the default window.
        plotted_voltages = []
        plotted_currents = []

        # Plot each measurement pair with proper color pairing
        for measurement_idx, pairs in unique_measurements.items():
            # Get base color from color scheme
            color_index = measurement_idx % len(colors)
            base_color = colors[color_index]

            # Extract RGB values from rgba color string
            r, g, b, alpha = self._extract_rgb_from_color(base_color)

            # Plot both reverse and forward for this measurement
            for pair in pairs:
                voltage_values = pair["voltage"]
                current_values = pair["current"]
                if flip_current:
                    current_values = [-v for v in current_values]
                direction = pair["direction"]

                if len(voltage_values) > 0 and len(current_values) > 0:
                    plotted_voltages.extend(voltage_values)
                    plotted_currents.extend(current_values)
                    if direction == "Reverse":
                        # Forward gets 50% lighter color with solid line and crosses
                        light_r = min(255, int(r + (255 - r) * 0.5))
                        light_g = min(255, int(g + (255 - g) * 0.5))
                        light_b = min(255, int(b + (255 - b) * 0.5))
                        line_color = f"rgba({light_r}, {light_g}, {light_b}, {alpha})"
                        line_style = "dash"
                        marker_symbol = "circle"
                    else:
                        # Reverse gets the main color with dashed line and dots
                        line_color = base_color
                        line_style = "solid"
                        marker_symbol = "x"

                    # Create trace name
                    trace_name = f"{direction} #{measurement_idx + 1}"

                    fig.add_trace(
                        go.Scatter(
                            x=voltage_values,
                            y=current_values,
                            mode="lines+markers",
                            line=dict(dash=line_style, color=line_color, width=2),
                            marker=dict(size=6, color=line_color, symbol=marker_symbol),
                            name=trace_name,
                            # legendgroup=f"measurement_{measurement_idx}",
                            showlegend=True,
                        )
                    )

        # Add MPP points and JV characteristics (from older version)
        # Get JV characteristics values for Forward and Reverse
        df_rev = best_device_jv[(best_device_jv["direction"] == "Reverse")]
        df_for = best_device_jv[(best_device_jv["direction"] == "Forward")]

        # Pick the row with the highest PCE within each direction (not simply the first row)
        best_rev_row = df_rev.loc[df_rev["PCE(%)"].idxmax()] if not df_rev.empty else None
        best_for_row = df_for.loc[df_for["PCE(%)"].idxmax()] if not df_for.empty else None

        char_vals = ["Voc(V)", "Jsc(mA/cm2)", "FF(%)", "PCE(%)"]

        def _characteristics(row):
            return [row[cv] if cv in row.index else 0 for cv in char_vals]

        # Each scan direction that exists gets its own MPP marker and summary; a device
        # measured in one direction only used to crash this plot.
        for label, row, symbol in (
            ("Forward", best_for_row, "circle"),
            ("Reverse", best_rev_row, "x"),
        ):
            if row is None or "V_mpp(V)" not in row.index or "J_mpp(mA/cm2)" not in row.index:
                continue
            v_mpp = row["V_mpp(V)"]
            j_mpp = -row["J_mpp(mA/cm2)"] if flip_current else row["J_mpp(mA/cm2)"]
            fig.add_trace(
                go.Scatter(
                    x=[v_mpp],
                    y=[j_mpp],
                    mode="markers",
                    marker=dict(color="red", size=10, symbol=symbol),
                    name=f"{label} MPP",
                    hoverinfo="text",
                    hovertext=f"MPP {label}<br>V: {v_mpp:.3f} V<br>J: {j_mpp:.3f} mA/cm²",
                )
            )

        if show_summary:
            # Anchor the text block by its top/bottom edge (instead of centering it on
            # annot_y) and start it a couple of units clear of the y=0 line, so it never
            # sits on top of the zero-reference line drawn above.
            annot_y = 2 if flip_current else -2
            annot_yanchor = "bottom" if flip_current else "top"
            if best_rev_row is not None:
                char_rev = _characteristics(best_rev_row)
                text_rev = f"""Rev:
        <br>Voc: {char_rev[0]:>5.2f}
        <br>Jsc:  {char_rev[1]:>5.1f}
        <br>FF:   {char_rev[2]:>5.1f}
        <br>PCE: {char_rev[3]:>5.1f}"""
                fig.add_annotation(
                    x=0.24,
                    y=annot_y,
                    yanchor=annot_yanchor,
                    text=text_rev,
                    showarrow=False,
                    font=dict(size=12),
                    align="left",
                    name="summary_rev",
                )
            if best_for_row is not None:
                char_for = _characteristics(best_for_row)
                text_for = f"For:<br>{char_for[0]:.2f} V<br>{char_for[1]:.1f} mA/cm²<br>{char_for[2]:.1f}%<br>{char_for[3]:.1f}%"  # noqa: E501
                fig.add_annotation(
                    x=0.55,
                    y=annot_y,
                    yanchor=annot_yanchor,
                    text=text_for,
                    showarrow=False,
                    font=dict(size=12),
                    align="left",
                    name="summary_for",
                )

        # Default axis windows requested for this plot. As long as the measured data
        # fits inside them, keep them fixed (so repeat views of different devices are
        # visually comparable); once data falls outside, fall back to the data's own
        # extent plus a 7% edge gap instead of clipping it.
        default_x_range = (-0.2, 1.2)
        default_y_range = (-5, 25) if flip_current else (-25, 5)
        edge_gap = 0.07

        def _resolve_range(values, default_range):
            lo_default, hi_default = default_range
            if not values:
                return [lo_default, hi_default]
            data_min, data_max = min(values), max(values)
            if data_min >= lo_default and data_max <= hi_default:
                return [lo_default, hi_default]
            span = data_max - data_min
            pad = span * edge_gap if span > 0 else (abs(data_max) * edge_gap or 1)
            return [data_min - pad, data_max + pad]

        x_range = _resolve_range(plotted_voltages, default_x_range)
        y_range = _resolve_range(plotted_currents, default_y_range)

        # Update layout with custom modebar
        fig.update_layout(
            title=f"JV Curves - Best Device ({best_sample} [Cell {best_cell}])",
            xaxis_title="Voltage [V]",
            yaxis_title="Current Density [mA/cm²]",
            xaxis=dict(range=x_range),
            yaxis=dict(range=y_range),
            template="plotly_white",
            # 4:3 aspect ratio by default; the resizable display wrapper picks this up
            # as the plot's initial size and lets the user drag-resize it from there.
            width=800,
            height=600,
            legend=dict(
                x=1.02,
                y=1,
                bgcolor="rgba(255,255,255,0.9)",
                bordercolor="black",
                borderwidth=1,
                xanchor="left",
                yanchor="top",
            ),
            showlegend=True,
            margin=dict(r=150),
        )

        fig.update_xaxes(showgrid=True, gridwidth=1, gridcolor="lightgray")
        fig.update_yaxes(showgrid=True, gridwidth=1, gridcolor="lightgray")

        sample_name = f"JV_best_device_{best_sample} (Cell {best_cell}).html"
        return fig, sample_name

    def create_jv_all_cells_plot(self, jvc_data, curves_data, colors=None, flip_current=False):
        """Plot JV curves for all cells in the complete dataset"""

        jv_devices = set(jvc_data[["sample", "cell"]].apply(tuple, axis=1))
        curves_devices = set(curves_data[["sample", "cell"]].apply(tuple, axis=1))

        matching_devices = jv_devices.intersection(curves_devices)
        jv_only_devices = jv_devices - curves_devices
        curves_only_devices = curves_devices - jv_devices

        logger.debug("  Matching devices: %s", len(matching_devices))
        logger.debug("  JV-only devices (no curves): %s", len(jv_only_devices))
        logger.debug("  Curves-only devices (no JV): %s", len(curves_only_devices))

        if len(jv_only_devices) > 0:
            logger.debug("  Examples of JV-only devices: %s", list(jv_only_devices)[:5])
        if len(curves_only_devices) > 0:
            logger.debug("  Examples of curves-only devices: %s", list(curves_only_devices)[:5])

        # Check if the best device from JV data has curves
        best_idx = jvc_data["PCE(%)"].idxmax()
        best_sample = jvc_data.loc[best_idx]["sample"]
        best_cell = jvc_data.loc[best_idx]["cell"]
        best_pce = jvc_data.loc[best_idx]["PCE(%)"]
        best_device_curves = curves_data[
            (curves_data["sample"] == best_sample) & (curves_data["cell"] == best_cell)
        ]

        logger.debug("  Best device: %s_%s (PCE: %.2f%%)", best_sample, best_cell, best_pce)
        logger.debug("  Best device has %s curve records", len(best_device_curves))

        # Use the existing best device plot logic but for multiple devices
        fig = go.Figure()

        # Add axis lines
        fig.add_shape(
            type="line",
            xref="paper",
            x0=0,
            x1=1,
            yref="y",
            y0=0,
            y1=0,
            line=dict(color="gray", width=2),
        )
        fig.add_shape(
            type="line",
            xref="x",
            x0=0,
            x1=0,
            yref="paper",
            y0=0,
            y1=1,
            line=dict(color="gray", width=2),
        )

        if colors is None:
            colors = ["#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd", "#8c564b"]

        # Get unique sample-cell combinations from filtered data
        unique_devices = jvc_data.groupby(["sample", "cell"]).first().reset_index()

        plot_count = 0
        for idx, device_row in unique_devices.iterrows():
            # if plot_count >= 20:  # Limit to prevent overcrowding
            #    break

            sample = device_row["sample"]
            cell = device_row["cell"]

            # Get curves for this device
            device_curves = curves_data[
                (curves_data["sample"] == sample) & (curves_data["cell"] == cell)
            ]

            if device_curves.empty:
                continue

            # Process curves similar to best device plot
            voltage_data = {}
            current_data = {}

            for _, curve_row in device_curves.iterrows():
                direction = curve_row["direction"]
                variable_type = curve_row["variable"]

                # Extract data values
                data_values = []
                for col in curve_row.index[8:]:
                    try:
                        val = float(curve_row[col])
                        if not pd.isna(val):
                            data_values.append(val)
                    except (ValueError, TypeError):
                        continue

                key = f"{direction}"

                if variable_type == "Voltage (V)":
                    voltage_data[key] = data_values
                elif variable_type == "Current Density(mA/cm2)":
                    current_data[key] = data_values

            # Plot curves for this device
            for key in voltage_data.keys():
                if key in current_data:
                    voltage_values = voltage_data[key]
                    current_values = current_data[key]
                    if flip_current:
                        current_values = [-v for v in current_values]
                    direction = key.split("_", 1)

                    if len(voltage_values) > 0 and len(current_values) > 0:
                        color_index = plot_count % len(colors)
                        base_color = colors[color_index]

                        line_style = "solid" if direction == "Reverse" else "dash"
                        marker_symbol = "circle" if direction == "Reverse" else "x"

                        trace_name = f"{sample}_{cell} {direction}"

                        fig.add_trace(
                            go.Scatter(
                                x=voltage_values,
                                y=current_values,
                                mode="lines+markers",
                                line=dict(dash=line_style, color=base_color, width=1),
                                marker=dict(size=4, color=base_color, symbol=marker_symbol),
                                name=trace_name,
                                showlegend=True,
                            )
                        )

            plot_count += 1

        _y_range_all = [-5, 30] if flip_current else [-30, 5]
        fig.update_layout(
            title=f"JV Curves - All Cells ({len(unique_devices)} devices, showing first {min(20, len(unique_devices))})",  # noqa: E501
            xaxis_title="Voltage [V]",
            yaxis_title="Current Density [mA/cm²]",
            xaxis=dict(range=[-0.2, 2.0]),
            yaxis=dict(range=_y_range_all),
            template="plotly_white",
            legend=dict(
                x=1.02,
                y=1,
                bgcolor="rgba(255,255,255,0.9)",
                bordercolor="black",
                borderwidth=1,
                xanchor="left",
                yanchor="top",
            ),
            showlegend=True,
            margin=dict(r=200),
        )

        sample_name = "JV_all_cells.html"
        return fig, sample_name

    def create_jv_working_cells_plot(self, jvc_data, curves_data, colors=None, flip_current=False):
        """Plot JV curves for working cells only (cells that passed filters)"""

        if not jvc_data.empty:
            working_pce_min = jvc_data["PCE(%)"].min()
            working_pce_max = jvc_data["PCE(%)"].max()
            working_pce_mean = jvc_data["PCE(%)"].mean()
            logger.debug(
                "  Working PCE range: %.2f%% to %.2f%% (mean: %.2f%%)",
                working_pce_min,
                working_pce_max,
                working_pce_mean,
            )

        if jvc_data.empty:
            # Return empty plot
            fig = go.Figure()
            fig.update_layout(title="No working cells found (none passed filters)")
            return fig, "JV_working_cells.html"

        # Use the same logic as create_jv_all_cells_plot but with different title
        fig = go.Figure()

        # Add axis lines
        fig.add_shape(
            type="line",
            xref="paper",
            x0=0,
            x1=1,
            yref="y",
            y0=0,
            y1=0,
            line=dict(color="gray", width=2),
        )
        fig.add_shape(
            type="line",
            xref="x",
            x0=0,
            x1=0,
            yref="paper",
            y0=0,
            y1=1,
            line=dict(color="gray", width=2),
        )

        if colors is None:
            colors = ["#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd", "#8c564b"]

        unique_devices = jvc_data.groupby(["sample", "cell"]).first().reset_index()

        # Show PCE range of working devices
        pce_min = jvc_data["PCE(%)"].min()  # noqa: F841
        pce_max = jvc_data["PCE(%)"].max()  # noqa: F841
        pce_mean = jvc_data["PCE(%)"].mean()  # noqa: F841

        plot_count = 0
        for idx, device_row in unique_devices.iterrows():
            sample = device_row["sample"]
            cell = device_row["cell"]

            # Get curves for this device
            device_curves = curves_data[
                (curves_data["sample"] == sample) & (curves_data["cell"] == cell)
            ]

            if device_curves.empty:
                continue

            # Process curves similar to best device plot
            voltage_data = {}
            current_data = {}

            for _, curve_row in device_curves.iterrows():
                direction = curve_row["direction"]
                variable_type = curve_row["variable"]

                # Extract data values
                data_values = []
                for col in curve_row.index[8:]:
                    try:
                        val = float(curve_row[col])
                        if not pd.isna(val):
                            data_values.append(val)
                    except (ValueError, TypeError):
                        continue

                key = f"{direction}"

                if variable_type == "Voltage (V)":
                    voltage_data[key] = data_values
                elif variable_type == "Current Density(mA/cm2)":
                    current_data[key] = data_values

            # Plot curves for this device
            for key in voltage_data.keys():
                if key in current_data:
                    voltage_values = voltage_data[key]
                    current_values = current_data[key]
                    if flip_current:
                        current_values = [-v for v in current_values]
                    direction = key.split("_", 1)

                    if len(voltage_values) > 0 and len(current_values) > 0:
                        color_index = plot_count % len(colors)
                        base_color = colors[color_index]

                        line_style = "solid" if direction == "Reverse" else "dash"
                        marker_symbol = "circle" if direction == "Reverse" else "x"

                        trace_name = f"{sample}_{cell} {direction}"

                        fig.add_trace(
                            go.Scatter(
                                x=voltage_values,
                                y=current_values,
                                mode="lines+markers",
                                line=dict(dash=line_style, color=base_color, width=1),
                                marker=dict(size=4, color=base_color, symbol=marker_symbol),
                                name=trace_name,
                                showlegend=True,
                            )
                        )

            plot_count += 1

        _y_range_wk = [-5, 30] if flip_current else [-30, 5]
        fig.update_layout(
            title=f"JV Curves - Working Cells Only ({len(unique_devices)} devices passed filters)",
            xaxis_title="Voltage [V]",
            yaxis_title="Current Density [mA/cm²]",
            xaxis=dict(range=[-0.2, 2.0]),
            yaxis=dict(range=_y_range_wk),
            template="plotly_white",
            legend=dict(
                x=1.02,
                y=1,
                bgcolor="rgba(255,255,255,0.9)",
                bordercolor="black",
                borderwidth=1,
                xanchor="left",
                yanchor="top",
            ),
            showlegend=True,
            margin=dict(r=200),
        )

        return fig, "JV_working_cells.html"

    def create_jv_non_working_cells_plot(
        self, jvc_data, curves_data, colors=None, flip_current=False
    ):
        """Plot JV curves for rejected cells only (cells that were filtered out)"""

        if jvc_data.empty:
            fig = go.Figure()
            fig.update_layout(title="No rejected cells found (none were filtered out)")
            return fig, "JV_rejected_cells.html"

        # Use the same logic as create_jv_all_cells_plot but with different title
        fig = go.Figure()

        # Add axis lines
        fig.add_shape(
            type="line",
            xref="paper",
            x0=0,
            x1=1,
            yref="y",
            y0=0,
            y1=0,
            line=dict(color="gray", width=2),
        )
        fig.add_shape(
            type="line",
            xref="x",
            x0=0,
            x1=0,
            yref="paper",
            y0=0,
            y1=1,
            line=dict(color="gray", width=2),
        )

        if colors is None:
            colors = ["#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd", "#8c564b"]

        # Get unique sample-cell combinations from REJECTED data
        unique_devices = jvc_data.groupby(["sample", "cell"]).first().reset_index()

        # Show PCE range of rejected devices
        pce_min = jvc_data["PCE(%)"].min()  # noqa: F841
        pce_max = jvc_data["PCE(%)"].max()  # noqa: F841
        pce_mean = jvc_data["PCE(%)"].mean()  # noqa: F841

        plot_count = 0
        for idx, device_row in unique_devices.iterrows():
            sample = device_row["sample"]
            cell = device_row["cell"]

            # Get curves for this device
            device_curves = curves_data[
                (curves_data["sample"] == sample) & (curves_data["cell"] == cell)
            ]

            if device_curves.empty:
                continue

            # Process curves similar to best device
            voltage_data = {}
            current_data = {}

            for _, curve_row in device_curves.iterrows():
                direction = curve_row["direction"]
                variable_type = curve_row["variable"]

                # Extract data values
                data_values = []
                for col in curve_row.index[8:]:
                    try:
                        val = float(curve_row[col])
                        if not pd.isna(val):
                            data_values.append(val)
                    except (ValueError, TypeError):
                        continue

                key = f"{direction}"

                if variable_type == "Voltage (V)":
                    voltage_data[key] = data_values
                elif variable_type == "Current Density(mA/cm2)":
                    current_data[key] = data_values

            # Plot curves for this device
            for key in voltage_data.keys():
                if key in current_data:
                    voltage_values = voltage_data[key]
                    current_values = current_data[key]
                    if flip_current:
                        current_values = [-v for v in current_values]
                    direction = key.split("_", 1)

                    if len(voltage_values) > 0 and len(current_values) > 0:
                        color_index = plot_count % len(colors)
                        base_color = colors[color_index]

                        line_style = "solid" if direction == "Reverse" else "dash"
                        marker_symbol = "circle" if direction == "Reverse" else "x"

                        trace_name = f"{sample}_{cell} {direction}"

                        fig.add_trace(
                            go.Scatter(
                                x=voltage_values,
                                y=current_values,
                                mode="lines+markers",
                                line=dict(dash=line_style, color=base_color, width=1),
                                marker=dict(size=4, color=base_color, symbol=marker_symbol),
                                name=trace_name,
                                showlegend=True,
                            )
                        )

            plot_count += 1

        _y_range_rej = [-5, 30] if flip_current else [-30, 5]
        fig.update_layout(
            title=f"JV Curves - Rejected Cells ({len(unique_devices)} devices filtered out)",
            xaxis_title="Voltage [V]",
            yaxis_title="Current Density [mA/cm²]",
            xaxis=dict(range=[-0.2, 2.0]),
            yaxis=dict(range=_y_range_rej),
            template="plotly_white",
            legend=dict(
                x=1.02,
                y=1,
                bgcolor="rgba(255,255,255,0.9)",
                bordercolor="black",
                borderwidth=1,
                xanchor="left",
                yanchor="top",
            ),
            showlegend=True,
            margin=dict(r=200),
        )

        return fig, "JV_rejected_cells.html"

    def create_jv_separated_by_cell_plot(
        self, jvc_data, curves_data, colors=None, plot_type="all", flip_current=False
    ):  # noqa: E501
        """Create separate figures for each sample, with 6 subplots (one per cell) in each figure"""
        if plot_type == "working":
            logger.debug("Creating JV curves separated by cell (working cells only)")
        else:
            logger.debug("Creating JV curves separated by cell (all cells)")

        if colors is None:
            colors = ["#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd", "#8c564b"]

        # Get unique samples
        unique_samples = jvc_data["sample"].unique()
        logger.debug("  Found %s unique samples", len(unique_samples))

        figures = []
        figure_names = []

        for sample in unique_samples:
            sample_jv = jvc_data[jvc_data["sample"] == sample]
            sample_curves = curves_data[curves_data["sample"] == sample]

            if sample_curves.empty:
                continue

            # Get unique cells for this sample
            unique_cells = sorted(sample_jv["cell"].unique())
            logger.debug("  Sample %s: %s cells", sample, len(unique_cells))

            # Create subplots (2 rows x 3 cols for 6 cells)
            rows, cols = 2, 3
            fig = make_subplots(
                rows=rows,
                cols=cols,
                subplot_titles=[f"Cell {cell}" for cell in unique_cells[:6]],  # Limit to 6 cells
                shared_xaxes=False,
                shared_yaxes=False,
                vertical_spacing=0.15,
                horizontal_spacing=0.08,
            )

            for i, cell in enumerate(unique_cells[:6]):  # Limit to 6 cells
                row = (i // cols) + 1
                col = (i % cols) + 1

                cell_curves = sample_curves[sample_curves["cell"] == cell]

                if cell_curves.empty:
                    continue

                # Process curves for this cell - HANDLE MULTIPLE MEASUREMENTS
                voltage_measurements = []  # List of voltage arrays with metadata
                current_measurements = []  # List of current arrays with metadata

                for _, curve_row in cell_curves.iterrows():
                    direction = curve_row["direction"]
                    variable_type = curve_row["variable"]
                    status = curve_row.get("status", "N/A")

                    # Extract data values
                    data_values = []
                    for col_idx in curve_row.index[8:]:  # Skip metadata columns
                        try:
                            val = float(curve_row[col_idx])
                            if not pd.isna(val):
                                data_values.append(val)
                        except (ValueError, TypeError):
                            continue

                    # Store with full metadata to distinguish measurements
                    measurement_info = {
                        "direction": direction,
                        "status": status,
                        "data": data_values,
                    }

                    if variable_type == "Voltage (V)":
                        voltage_measurements.append(measurement_info)
                    elif variable_type == "Current Density(mA/cm2)":
                        current_measurements.append(measurement_info)

                # Create measurement pairs by matching direction, and status
                measurement_pairs = []
                for v_measurement in voltage_measurements:
                    for c_measurement in current_measurements:
                        if (
                            v_measurement["direction"] == c_measurement["direction"]
                            and
                            # v_measurement['illumination'] == c_measurement['illumination'] and
                            v_measurement["status"] == c_measurement["status"]
                        ):
                            measurement_pairs.append(
                                {
                                    "voltage": v_measurement["data"],
                                    "current": c_measurement["data"],
                                    "direction": v_measurement["direction"],
                                    #'illumination': v_measurement['illumination'],
                                    "status": v_measurement["status"],
                                }
                            )

                # Plot all measurement pairs with proper coloring like best device plot
                for pair_idx, pair in enumerate(measurement_pairs):
                    if len(pair["voltage"]) > 0 and len(pair["current"]) > 0:
                        # Get base color from color scheme
                        color_index = pair_idx % len(colors)
                        base_color = colors[color_index]

                        # Extract RGB values for color manipulation
                        r, g, b, alpha = self._extract_rgb_from_color(base_color)

                        if pair["direction"] == "Reverse":
                            # Reverse gets the main color with solid line and circles
                            line_color = f"rgba({r}, {g}, {b}, {alpha})"
                            line_style = "solid"
                            marker_symbol = "circle"
                        else:
                            # Forward gets 50% lighter color with dashed line and x markers
                            light_r = min(255, int(r + (255 - r) * 0.5))
                            light_g = min(255, int(g + (255 - g) * 0.5))
                            light_b = min(255, int(b + (255 - b) * 0.5))
                            line_color = f"rgba({light_r}, {light_g}, {light_b}, {alpha})"
                            line_style = "dash"
                            marker_symbol = "x"

                        # Create trace name with status info
                        trace_name = f"{pair['direction']} {pair['status']}"
                        c_vals = pair["current"]
                        if flip_current:
                            c_vals = [-v for v in c_vals]

                        fig.add_trace(
                            go.Scatter(
                                x=pair["voltage"],
                                y=c_vals,
                                mode="lines+markers",
                                line=dict(dash=line_style, color=line_color, width=2),
                                marker=dict(size=4, color=line_color, symbol=marker_symbol),
                                name=trace_name,
                                showlegend=(i == 0),  # Only show legend for first subplot
                                legendgroup=f"{pair['direction']}_{pair['status']}",
                            ),
                            row=row,
                            col=col,
                        )

            # Update layout with appropriate title
            if plot_type == "working":
                fig.update_layout(
                    title=f"JV Curves by Cell - Sample: {sample} (Working Cells Only)",
                    template="plotly_white",
                    height=650,  # Increased from 600
                    showlegend=True,
                    margin=dict(
                        t=80, b=60, l=50, r=50
                    ),  # Add margins: top=100, bottom=80, left=60, right=60
                )
                figure_name = f"JV_by_cell_working_{sample}.html"
            else:
                fig.update_layout(
                    title=f"JV Curves by Cell - Sample: {sample} (All Cells)",
                    template="plotly_white",
                    height=650,  # Increased from 600
                    showlegend=True,
                    margin=dict(t=80, b=60, l=50, r=50),  # Add margins
                )
                figure_name = f"JV_by_cell_all_{sample}.html"

            # Update axes for all subplots
            _y_range_cell = [-5, 30] if flip_current else [-30, 5]
            for i in range(1, min(len(unique_cells), 6) + 1):
                subplot_row = ((i - 1) // cols) + 1
                subplot_col = ((i - 1) % cols) + 1
                fig.update_xaxes(
                    title_text="Voltage [V]", range=[-0.2, 1.5], row=subplot_row, col=subplot_col
                )
                fig.update_yaxes(
                    title_text="Current Density [mA/cm²]",
                    range=_y_range_cell,
                    row=subplot_row,
                    col=subplot_col,
                )

            figures.append(fig)
            figure_names.append(figure_name)

        logger.debug("  Created %s figures (one per sample)", len(figures))
        return figures, figure_names

    def create_jv_separated_by_substrate_plot(
        self, jvc_data, curves_data, colors=None, plot_type="all", flip_current=False
    ):
        """Create separate plots for each sample, showing all cells together with multiple measurements"""  # noqa: E501
        if plot_type == "working":
            logger.debug("Creating JV curves separated by sample (working cells only)")
        else:
            logger.debug("Creating JV curves separated by sample (all cells)")

        if colors is None:
            colors = ["#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd", "#8c564b"]

        # Get unique samples
        unique_samples = jvc_data["sample"].unique()
        logger.debug("  Found %s unique samples", len(unique_samples))

        figures = []
        figure_names = []

        for sample in unique_samples:
            sample_jv = jvc_data[jvc_data["sample"] == sample]
            sample_curves = curves_data[curves_data["sample"] == sample]

            if sample_curves.empty:
                continue

            fig = go.Figure()

            # Add axis lines
            fig.add_shape(
                type="line",
                xref="paper",
                x0=0,
                x1=1,
                yref="y",
                y0=0,
                y1=0,
                line=dict(color="gray", width=1),
            )
            fig.add_shape(
                type="line",
                xref="x",
                x0=0,
                x1=0,
                yref="paper",
                y0=0,
                y1=1,
                line=dict(color="gray", width=1),
            )

            # Get unique cells for this sample
            unique_cells = sorted(sample_jv["cell"].unique())
            logger.debug("  Sample %s: %s cells", sample, len(unique_cells))

            # Plot all cells for this sample with multiple measurements
            color_idx = 0
            for cell in unique_cells:
                cell_curves = sample_curves[sample_curves["cell"] == cell]

                if cell_curves.empty:
                    continue

                # Process curves for this cell - HANDLE MULTIPLE MEASUREMENTS
                voltage_measurements = []  # List of voltage arrays with metadata
                current_measurements = []  # List of current arrays with metadata

                for _, curve_row in cell_curves.iterrows():
                    direction = curve_row["direction"]
                    variable_type = curve_row["variable"]
                    status = curve_row.get("status", "N/A")

                    # Extract data values
                    data_values = []
                    for col_idx in curve_row.index[8:]:  # Skip metadata columns
                        try:
                            val = float(curve_row[col_idx])
                            if not pd.isna(val):
                                data_values.append(val)
                        except (ValueError, TypeError):
                            continue

                    # Store with full metadata to distinguish measurements
                    measurement_info = {
                        "direction": direction,
                        "status": status,
                        "data": data_values,
                    }

                    if variable_type == "Voltage (V)":
                        voltage_measurements.append(measurement_info)
                    elif variable_type == "Current Density(mA/cm2)":
                        current_measurements.append(measurement_info)

                # Create measurement pairs by matching direction, and status
                measurement_pairs = []
                for v_measurement in voltage_measurements:
                    for c_measurement in current_measurements:
                        if (
                            v_measurement["direction"] == c_measurement["direction"]
                            and
                            # v_measurement['illumination'] == c_measurement['illumination'] and
                            v_measurement["status"] == c_measurement["status"]
                        ):
                            measurement_pairs.append(
                                {
                                    "voltage": v_measurement["data"],
                                    "current": c_measurement["data"],
                                    "direction": v_measurement["direction"],
                                    #'illumination': v_measurement['illumination'],
                                    "status": v_measurement["status"],
                                    "cell": cell,
                                }
                            )

                # Plot all measurement pairs for this cell
                for pair in measurement_pairs:
                    if len(pair["voltage"]) > 0 and len(pair["current"]) > 0:
                        # Get base color from color scheme for this cell
                        base_color = colors[color_idx % len(colors)]

                        # Extract RGB values for color manipulation
                        r, g, b, alpha = self._extract_rgb_from_color(base_color)

                        if pair["direction"] == "Reverse":
                            # Reverse gets the main color with solid line and circles
                            line_color = f"rgba({r}, {g}, {b}, {alpha})"
                            line_style = "solid"
                            marker_symbol = "circle"
                        else:
                            # Forward gets 50% lighter color with dashed line and x markers
                            light_r = min(255, int(r + (255 - r) * 0.5))
                            light_g = min(255, int(g + (255 - g) * 0.5))
                            light_b = min(255, int(b + (255 - b) * 0.5))
                            line_color = f"rgba({light_r}, {light_g}, {light_b}, {alpha})"
                            line_style = "dash"
                            marker_symbol = "x"

                        # Create trace name with cell and status info
                        trace_name = f"Cell {pair['cell']} {pair['direction']} {pair['status']}"
                        c_vals = pair["current"]
                        if flip_current:
                            c_vals = [-v for v in c_vals]

                        fig.add_trace(
                            go.Scatter(
                                x=pair["voltage"],
                                y=c_vals,
                                mode="lines+markers",
                                line=dict(dash=line_style, color=line_color, width=2),
                                marker=dict(size=4, color=line_color, symbol=marker_symbol),
                                name=trace_name,
                                showlegend=True,
                            )
                        )

                color_idx += 1

            # Update layout with appropriate title
            _y_range_sub = [-5, 30] if flip_current else [-30, 5]
            if plot_type == "working":
                fig.update_layout(
                    title=f"JV Curves - Sample: {sample} (Working Cells Only)",
                    xaxis_title="Voltage [V]",
                    yaxis_title="Current Density [mA/cm²]",
                    xaxis=dict(range=[-0.2, 1.5]),
                    yaxis=dict(range=_y_range_sub),
                    template="plotly_white",
                    legend=dict(
                        x=1.02,
                        y=1,
                        bgcolor="rgba(255,255,255,0.9)",
                        bordercolor="black",
                        borderwidth=1,
                        xanchor="left",
                        yanchor="top",
                    ),
                    showlegend=True,
                    margin=dict(r=200),
                )
                figure_name = f"JV_by_sample_working_{sample}.html"
            else:
                fig.update_layout(
                    title=f"JV Curves - Sample: {sample} (All Cells)",
                    xaxis_title="Voltage [V]",
                    yaxis_title="Current Density [mA/cm²]",
                    xaxis=dict(range=[-0.2, 1.5]),
                    yaxis=dict(range=_y_range_sub),
                    template="plotly_white",
                    legend=dict(
                        x=1.02,
                        y=1,
                        bgcolor="rgba(255,255,255,0.9)",
                        bordercolor="black",
                        borderwidth=1,
                        xanchor="left",
                        yanchor="top",
                    ),
                    showlegend=True,
                    margin=dict(r=200),
                )
                figure_name = f"JV_by_sample_all_{sample}.html"

            figures.append(fig)
            figure_names.append(figure_name)

        logger.debug("  Created %s figures (one per sample)", len(figures))
        return figures, figure_names

    def _plot_best_device_curves(
        self, fig, best_device_jv, best_curves, base_color, label, flip_current=False
    ):  # noqa: E501
        """Add traces for one best-device to an existing figure."""
        r, g, b, alpha = self._extract_rgb_from_color(base_color)

        voltage_meas, current_meas = {}, {}
        for _, curve_row in best_curves.iterrows():
            direction = curve_row["direction"]
            var_type = curve_row["variable"]
            vals = []
            for col in curve_row.index[8:]:
                try:
                    v = float(curve_row[col])
                    if not pd.isna(v):
                        vals.append(v)
                except (ValueError, TypeError):
                    continue
            if var_type == "Voltage (V)":
                voltage_meas.setdefault(direction, []).append(vals)
            elif var_type == "Current Density(mA/cm2)":
                current_meas.setdefault(direction, []).append(vals)

        for direction, v_list in voltage_meas.items():
            c_list = current_meas.get(direction, [])
            for v_vals, c_vals in zip(v_list, c_list):
                if flip_current:
                    c_vals = [-v for v in c_vals]
                if not v_vals or not c_vals:
                    continue
                if direction == "Reverse":
                    line_color = base_color
                    line_style = "solid"
                else:
                    lr = min(255, int(r + (255 - r) * 0.5))
                    lg = min(255, int(g + (255 - g) * 0.5))
                    lb = min(255, int(b + (255 - b) * 0.5))
                    line_color = f"rgba({lr}, {lg}, {lb}, {alpha})"
                    line_style = "dash"
                fig.add_trace(
                    go.Scatter(
                        x=v_vals,
                        y=c_vals,
                        mode="lines+markers",
                        line=dict(dash=line_style, color=line_color, width=2),
                        marker=dict(size=5, color=line_color),
                        name=f"{label} {direction}",
                        showlegend=True,
                    )
                )

    def _add_jv_summary_annotation(self, fig, best_jv_df, x_rev=0.24, flip_current=False):
        """Add Voc/Jsc/FF/PCE annotations for one best device (Rev and For, data coordinates)."""
        df_rev = best_jv_df[best_jv_df["direction"] == "Reverse"]
        df_for = best_jv_df[best_jv_df["direction"] == "Forward"]
        if df_rev.empty and df_for.empty:
            return
        char_vals = ["Voc(V)", "Jsc(mA/cm2)", "FF(%)", "PCE(%)"]
        char_rev = [
            df_rev[c].iloc[0] if (not df_rev.empty and c in df_rev.columns) else 0
            for c in char_vals
        ]  # noqa: E501
        char_for = [
            df_for[c].iloc[0] if (not df_for.empty and c in df_for.columns) else 0
            for c in char_vals
        ]  # noqa: E501
        annot_y = 5 if flip_current else -5
        text_rev = (
            f"Rev:<br>Voc: {char_rev[0]:>5.2f}"
            f"<br>Jsc:  {char_rev[1]:>5.1f}"
            f"<br>FF:   {char_rev[2]:>5.1f}"
            f"<br>PCE: {char_rev[3]:>5.1f}"
        )
        text_for = (
            f"For:<br>{char_for[0]:.2f} V"
            f"<br>{char_for[1]:.1f} mA/cm²"
            f"<br>{char_for[2]:.1f}%"
            f"<br>{char_for[3]:.1f}%"
        )
        fig.add_annotation(
            x=x_rev,
            y=annot_y,
            text=text_rev,
            showarrow=False,
            font=dict(size=12),
            align="left",
            name="summary_rev",
        )
        fig.add_annotation(
            x=x_rev + 0.3,
            y=annot_y,
            text=text_for,
            showarrow=False,
            font=dict(size=12),
            align="left",
            name="summary_for",
        )

    def create_jv_best_by_batch_together(
        self, jvc_data, curves_data, colors=None, show_summary=True, flip_current=False
    ):  # noqa: E501
        """One figure showing the best device (highest PCE) for each batch."""
        if colors is None:
            colors = ["#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd", "#8c564b"]

        fig = go.Figure()
        fig.add_shape(
            type="line",
            xref="paper",
            x0=0,
            x1=1,
            yref="y",
            y0=0,
            y1=0,
            line=dict(color="gray", width=1),
        )
        fig.add_shape(
            type="line",
            xref="x",
            x0=0,
            x1=0,
            yref="paper",
            y0=0,
            y1=1,
            line=dict(color="gray", width=1),
        )

        batches = sorted(jvc_data["batch"].unique())

        for batch_idx, batch in enumerate(batches):
            batch_jv = jvc_data[jvc_data["batch"] == batch]
            if batch_jv.empty:
                continue
            best_idx = batch_jv["PCE(%)"].idxmax()
            best_sample = batch_jv.loc[best_idx]["sample"]
            best_cell = batch_jv.loc[best_idx]["cell"]

            best_curves = curves_data[
                (curves_data["sample"] == best_sample) & (curves_data["cell"] == best_cell)
            ]
            if best_curves.empty:
                continue

            base_color = colors[batch_idx % len(colors)]
            label = f"{batch}: {best_sample}[{best_cell}]"
            self._plot_best_device_curves(
                fig, batch_jv, best_curves, base_color, label, flip_current
            )

        y_range = [-5, 26] if flip_current else [-26, 5]
        fig.update_layout(
            title=f"JV Curves - Best Device per Batch ({len(batches)} batches)",
            xaxis_title="Voltage [V]",
            yaxis_title="Current Density [mA/cm²]",
            xaxis=dict(range=[-0.2, 1.5]),
            yaxis=dict(range=y_range),
            template="plotly_white",
            legend=dict(
                x=1.02,
                y=1,
                bgcolor="rgba(255,255,255,0.9)",
                bordercolor="black",
                borderwidth=1,
                xanchor="left",
                yanchor="top",
            ),
            showlegend=True,
            margin=dict(r=250),
        )
        return fig, "JV_best_by_batch_together.html"

    def create_jv_best_by_batch_separate(
        self, jvc_data, curves_data, colors=None, show_summary=True, flip_current=False
    ):  # noqa: E501
        """Separate figure per batch, each showing the best device in that batch."""
        if colors is None:
            colors = ["#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd", "#8c564b"]

        batches = sorted(jvc_data["batch"].unique())
        figures, figure_names = [], []

        for batch_idx, batch in enumerate(batches):
            batch_jv = jvc_data[jvc_data["batch"] == batch]
            if batch_jv.empty:
                continue
            best_idx = batch_jv["PCE(%)"].idxmax()
            best_sample = batch_jv.loc[best_idx]["sample"]
            best_cell = batch_jv.loc[best_idx]["cell"]

            best_curves = curves_data[
                (curves_data["sample"] == best_sample) & (curves_data["cell"] == best_cell)
            ]
            if best_curves.empty:
                continue

            fig = go.Figure()
            fig.add_shape(
                type="line",
                xref="paper",
                x0=0,
                x1=1,
                yref="y",
                y0=0,
                y1=0,
                line=dict(color="gray", width=1),
            )
            fig.add_shape(
                type="line",
                xref="x",
                x0=0,
                x1=0,
                yref="paper",
                y0=0,
                y1=1,
                line=dict(color="gray", width=1),
            )

            base_color = colors[batch_idx % len(colors)]
            label = f"{best_sample}[{best_cell}]"
            self._plot_best_device_curves(
                fig, batch_jv, best_curves, base_color, label, flip_current
            )

            if show_summary:
                best_jv = batch_jv[
                    (batch_jv["sample"] == best_sample) & (batch_jv["cell"] == best_cell)
                ]
                self._add_jv_summary_annotation(fig, best_jv, flip_current=flip_current)

            y_range = [-5, 26] if flip_current else [-26, 5]
            clean_batch = str(batch).replace(" ", "_").replace("/", "_")
            fig.update_layout(
                title=f"JV Curves - Best Device: Batch {batch} ({best_sample} [{best_cell}])",
                xaxis_title="Voltage [V]",
                yaxis_title="Current Density [mA/cm²]",
                xaxis=dict(range=[-0.2, 1.5]),
                yaxis=dict(range=y_range),
                template="plotly_white",
                legend=dict(
                    x=1.02,
                    y=1,
                    bgcolor="rgba(255,255,255,0.9)",
                    bordercolor="black",
                    borderwidth=1,
                    xanchor="left",
                    yanchor="top",
                ),
                showlegend=True,
                margin=dict(r=200),
            )
            figures.append(fig)
            figure_names.append(f"JV_best_batch_{clean_batch}.html")

        logger.debug("  Created %s best-by-batch figures", len(figures))
        return figures, figure_names

    def create_jv_best_by_variable_together(
        self, jvc_data, curves_data, colors=None, show_summary=True, flip_current=False
    ):  # noqa: E501
        """One figure showing the best device per condition/variable."""
        if "condition" not in jvc_data.columns:
            fig = go.Figure()
            fig.update_layout(
                title=(
                    "Best device by variable -- no conditions set "
                    "(use Tab 2 to assign variable names)"
                )
            )
            return fig, "JV_best_by_variable_together.html"

        if colors is None:
            colors = ["#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd", "#8c564b"]

        fig = go.Figure()
        fig.add_shape(
            type="line",
            xref="paper",
            x0=0,
            x1=1,
            yref="y",
            y0=0,
            y1=0,
            line=dict(color="gray", width=1),
        )
        fig.add_shape(
            type="line",
            xref="x",
            x0=0,
            x1=0,
            yref="paper",
            y0=0,
            y1=1,
            line=dict(color="gray", width=1),
        )

        conditions = sorted(jvc_data["condition"].dropna().unique())

        for cond_idx, condition in enumerate(conditions):
            cond_jv = jvc_data[jvc_data["condition"] == condition]
            if cond_jv.empty:
                continue
            best_idx = cond_jv["PCE(%)"].idxmax()
            best_sample = cond_jv.loc[best_idx]["sample"]
            best_cell = cond_jv.loc[best_idx]["cell"]

            best_curves = curves_data[
                (curves_data["sample"] == best_sample) & (curves_data["cell"] == best_cell)
            ]
            if best_curves.empty:
                continue

            base_color = colors[cond_idx % len(colors)]
            label = f"{condition}: {best_sample}[{best_cell}]"
            self._plot_best_device_curves(
                fig, cond_jv, best_curves, base_color, label, flip_current
            )

        y_range = [-5, 26] if flip_current else [-26, 5]
        fig.update_layout(
            title=f"JV Curves - Best Device per Variable ({len(conditions)} conditions)",
            xaxis_title="Voltage [V]",
            yaxis_title="Current Density [mA/cm²]",
            xaxis=dict(range=[-0.2, 1.5]),
            yaxis=dict(range=y_range),
            template="plotly_white",
            legend=dict(
                x=1.02,
                y=1,
                bgcolor="rgba(255,255,255,0.9)",
                bordercolor="black",
                borderwidth=1,
                xanchor="left",
                yanchor="top",
            ),
            showlegend=True,
            margin=dict(r=250),
        )
        return fig, "JV_best_by_variable_together.html"

    def create_jv_best_by_variable_separate(
        self, jvc_data, curves_data, colors=None, show_summary=True, flip_current=False
    ):  # noqa: E501
        """Separate figure per condition/variable, each showing the best device."""
        if "condition" not in jvc_data.columns:
            fig = go.Figure()
            fig.update_layout(
                title=(
                    "Best device by variable -- no conditions set "
                    "(use Tab 2 to assign variable names)"
                )
            )
            return [fig], ["JV_best_by_variable_separate.html"]

        if colors is None:
            colors = ["#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd", "#8c564b"]

        conditions = sorted(jvc_data["condition"].dropna().unique())
        figures, figure_names = [], []

        for cond_idx, condition in enumerate(conditions):
            cond_jv = jvc_data[jvc_data["condition"] == condition]
            if cond_jv.empty:
                continue
            best_idx = cond_jv["PCE(%)"].idxmax()
            best_sample = cond_jv.loc[best_idx]["sample"]
            best_cell = cond_jv.loc[best_idx]["cell"]

            best_curves = curves_data[
                (curves_data["sample"] == best_sample) & (curves_data["cell"] == best_cell)
            ]
            if best_curves.empty:
                continue

            fig = go.Figure()
            fig.add_shape(
                type="line",
                xref="paper",
                x0=0,
                x1=1,
                yref="y",
                y0=0,
                y1=0,
                line=dict(color="gray", width=1),
            )
            fig.add_shape(
                type="line",
                xref="x",
                x0=0,
                x1=0,
                yref="paper",
                y0=0,
                y1=1,
                line=dict(color="gray", width=1),
            )

            base_color = colors[cond_idx % len(colors)]
            label = f"{best_sample}[{best_cell}]"
            self._plot_best_device_curves(
                fig, cond_jv, best_curves, base_color, label, flip_current
            )

            if show_summary:
                best_jv = cond_jv[
                    (cond_jv["sample"] == best_sample) & (cond_jv["cell"] == best_cell)
                ]
                self._add_jv_summary_annotation(fig, best_jv, flip_current=flip_current)

            y_range = [-5, 26] if flip_current else [-26, 5]
            clean_cond = str(condition).replace(" ", "_").replace("/", "_")
            fig.update_layout(
                title=f"JV Curves - Best Device: {condition} ({best_sample} [{best_cell}])",
                xaxis_title="Voltage [V]",
                yaxis_title="Current Density [mA/cm²]",
                xaxis=dict(range=[-0.2, 1.5]),
                yaxis=dict(range=y_range),
                template="plotly_white",
                legend=dict(
                    x=1.02,
                    y=1,
                    bgcolor="rgba(255,255,255,0.9)",
                    bordercolor="black",
                    borderwidth=1,
                    xanchor="left",
                    yanchor="top",
                ),
                showlegend=True,
                margin=dict(r=200),
            )
            figures.append(fig)
            figure_names.append(f"JV_best_variable_{clean_cond}.html")

        logger.debug("  Created %s best-by-variable figures", len(figures))
        return figures, figure_names
