"""
Plot Management Module
Handles all plotting operations including JV curves, boxplots, and histograms.
Extracted from main.py for better organization.
"""

__author__ = "Edgar Nandayapa"
__institution__ = "Helmholtz-Zentrum Berlin"
__created__ = "August 2025"

import logging

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots

try:
    from utils import save_combined_excel_data
except ImportError:

    def save_combined_excel_data(*args, **kwargs):
        return None


logger = logging.getLogger(__name__)


def _flatten_multiindex_columns(self, df):
    """Flatten MultiIndex columns if they exist"""
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = ["_".join(col).strip() for col in df.columns.values]
    return df


def _parse_custom_order(order_str):
    """
    Parse a custom order string into an ordered list of display groups.

    Format examples:
        "L1, L2, L3"                        → simple ordered list
        "(L1, l1, 10min), L2, (L3, 30min)"  → aliased groups; first alias is displayed,
                                               all aliases in a group match the same category

    Returns a list of dicts [{'display': str, 'aliases': [str, ...]}, ...],
    or None if the string is empty.
    """
    order_str = order_str.strip()
    if not order_str:
        return None

    # Split by top-level commas (ignore commas inside parentheses)
    tokens = []
    depth = 0
    current = ""
    for char in order_str:
        if char == "(":
            depth += 1
            current += char
        elif char == ")":
            depth -= 1
            current += char
        elif char == "," and depth == 0:
            tokens.append(current.strip())
            current = ""
        else:
            current += char
    if current.strip():
        tokens.append(current.strip())

    groups = []
    for token in tokens:
        token = token.strip()
        if not token:
            continue
        if token.startswith("(") and token.endswith(")"):
            aliases = [a.strip() for a in token[1:-1].split(",") if a.strip()]
            if aliases:
                groups.append({"display": aliases[0], "aliases": aliases})
        else:
            groups.append({"display": token, "aliases": [token]})

    return groups if groups else None


def plotting_string_action(plot_list, data, supp, is_voila=False, color_scheme=None, sort_order="Alphanumeric ↑", custom_order="", direction_split=False, flip_current=False):  # noqa: E501
    """
    Main plotting function that processes plot codes and creates figures.
    """
    filtered_jv, complete_jv, filtered_curves = data
    omitted_jv, filter_pars, is_conditions, path, samples = supp

    complete_curves = filtered_curves

    # Create plot manager
    plot_manager = PlotManager()
    plot_manager.set_output_path(path)

    if color_scheme is None:
        color_scheme = [
            "rgba(93, 164, 214, 0.7)",
            "rgba(255, 144, 14, 0.7)",
            "rgba(44, 160, 101, 0.7)",
            "rgba(255, 65, 54, 0.7)",
            "rgba(207, 114, 255, 0.7)",
            "rgba(127, 96, 0, 0.7)",
            "rgba(255, 140, 184, 0.7)",
            "rgba(79, 90, 117, 0.7)",
        ]

    # Mapping dictionaries for plot codes
    varx_dict = {
        "a": "sample",
        "b": "cell",
        "c": "direction",
        "d": "ilum",
        "e": "batch",
        "g": "condition",
        "s": "status",
    }
    vary_dict = {
        "v": "voc",
        "j": "jsc",
        "f": "ff",
        "p": "pce",
        "x": "vocxff",
        "u": "vmpp",
        "i": "jmpp",
        "m": "pmpp",
        "r": "rser",
        "h": "rshu",
    }

    fig_list = []
    fig_names = []

    # Convert plot selections to codes if needed
    if isinstance(plot_list[0], tuple):
        plot_codes = plot_list_from_voila(plot_list)
    else:
        plot_codes = plot_list

    for pl in plot_codes:
        # Check if there is "condition" requirement
        if "g" in pl and not is_conditions:
            continue

        # Extract variables from plot code
        var_x = next((varx_dict[key] for key in varx_dict if key in pl), None)
        var_y = next((vary_dict[key] for key in vary_dict if key in pl), None)

        try:
            if pl in ("BCORR", "BCORR_ALL"):
                use_all = pl == "BCORR_ALL"
                corr_data = complete_jv if use_all else filtered_jv
                fig, fig_name = plot_manager.create_correlation_plot(
                    corr_data, [omitted_jv, filter_pars], all_data=use_all
                )
                fig_list.append(fig)
                fig_names.append(fig_name)
                continue
            elif pl in ("BSCORR", "BSCORR_ALL"):
                use_all = pl == "BSCORR_ALL"
                corr_data = complete_jv if use_all else filtered_jv
                fig, fig_name = plot_manager.create_correlation_scatter_matrix(
                    corr_data, [omitted_jv, filter_pars], all_data=use_all
                )
                fig_list.append(fig)
                fig_names.append(fig_name)
                continue
            elif pl.startswith("BVJFP"):
                rest = pl[6:] if len(pl) > 6 else "a"
                dir_split = rest.endswith("D")
                x_code = rest[:-1] if dir_split else rest
                x_code = x_code or "a"
                var_x_map = {
                    "e": "batch", "g": "condition", "a": "sample",
                    "b": "cell", "c": "direction", "s": "status",
                }
                var_x = var_x_map.get(x_code, "sample")
                fig, fig_name = plot_manager.create_voc_jsc_ff_pce_subplots(
                    filtered_jv, [omitted_jv, filter_pars],
                    colors=color_scheme, var_x=var_x, direction_split=dir_split,
                )
                fig_list.append(fig)
                fig_names.append(fig_name)
                continue
            elif "csg" in pl and var_y:
                # Direction, Status and Variable combination plots
                figs, fig_names_combo = plot_manager.create_triple_combination_plots(
                    filtered_jv, var_y, "csg", [omitted_jv, filter_pars], colors=color_scheme
                )
                fig_list.extend(figs)
                fig_names.extend(fig_names_combo)
                continue
            elif "CwH" in pl:
                fig, fig_name = plot_manager.create_jv_best_device_plot(
                    filtered_jv, filtered_curves, colors=color_scheme, show_summary=False,
                    flip_current=flip_current,
                )
            elif "Cxw" in pl:
                # Create curves that match filtered JV data
                working_curves = plot_manager._create_matching_curves_data(
                    filtered_jv, complete_curves
                )
                figs, fig_names_new = plot_manager.create_jv_separated_by_cell_plot(
                    filtered_jv, working_curves, colors=color_scheme, plot_type="working",
                    flip_current=flip_current,
                )
                if isinstance(figs, list) and isinstance(fig_names_new, list):
                    fig_list.extend(figs)
                    fig_names.extend(fig_names_new)
                else:
                    fig_list.append(figs)
                    fig_names.append(fig_names_new)
                continue
            elif "Cdw" in pl:
                # Separated by substrate (working only) - USE FILTERED DATA
                working_curves = plot_manager._create_matching_curves_data(
                    filtered_jv, complete_curves
                )
                figs, fig_names_new = plot_manager.create_jv_separated_by_substrate_plot(
                    filtered_jv, working_curves, colors=color_scheme, plot_type="working",
                    flip_current=flip_current,
                )
                if isinstance(figs, list) and isinstance(fig_names_new, list):
                    fig_list.extend(figs)
                    fig_names.extend(fig_names_new)
                else:
                    fig_list.append(figs)
                    fig_names.append(fig_names_new)
                continue
            elif "sg" in pl and var_y:
                # Status and Variable combination plots
                figs, fig_names_combo = plot_manager.create_combination_plots(
                    filtered_jv, var_y, "sg", [omitted_jv, filter_pars], colors=color_scheme
                )
                fig_list.extend(figs)
                fig_names.extend(fig_names_combo)
                continue
            elif "cg" in pl and var_y:
                # Direction and Variable combination plots
                figs, fig_names_combo = plot_manager.create_combination_plots(
                    filtered_jv, var_y, "cg", [omitted_jv, filter_pars], colors=color_scheme
                )
                fig_list.extend(figs)
                fig_names.extend(fig_names_combo)
                continue
            elif "bg" in pl and var_y:
                # Cell and Variable combination plots
                figs, fig_names_combo = plot_manager.create_combination_plots(
                    filtered_jv, var_y, "bg", [omitted_jv, filter_pars], colors=color_scheme
                )
                fig_list.extend(figs)
                fig_names.extend(fig_names_combo)
                continue
            elif "B" in pl and var_x and var_y:
                fig, fig_name, _ = plot_manager.create_boxplot(
                    filtered_jv,
                    var_x,
                    var_y,
                    [omitted_jv, filter_pars],
                    "data",
                    colors=color_scheme,
                    sort_order=sort_order,
                    custom_order=custom_order,
                    direction_split="D" in pl,
                )
            elif "J" in pl and var_x and var_y:
                fig, fig_name, _ = plot_manager.create_boxplot(
                    omitted_jv, var_x, var_y, [filtered_jv, filter_pars], "junk",
                    sort_order=sort_order,
                    custom_order=custom_order,
                    direction_split="D" in pl,
                )
            elif "H" in pl and var_y:
                fig, fig_name = plot_manager.create_histogram(filtered_jv, var_y)
            # Best-device-by-batch/variable variants (must come before generic "Cw" check)
            elif pl.startswith("CwBT"):
                show_summary = not pl.endswith("H")
                fig, fig_name = plot_manager.create_jv_best_by_batch_together(
                    filtered_jv, filtered_curves, colors=color_scheme,
                    show_summary=show_summary, flip_current=flip_current,
                )
            elif pl.startswith("CwBS"):
                show_summary = not pl.endswith("H")
                figs, fig_names_new = plot_manager.create_jv_best_by_batch_separate(
                    filtered_jv, filtered_curves, colors=color_scheme,
                    show_summary=show_summary, flip_current=flip_current,
                )
                fig_list.extend(figs)
                fig_names.extend(fig_names_new)
                continue
            elif pl.startswith("CwVT"):
                show_summary = not pl.endswith("H")
                fig, fig_name = plot_manager.create_jv_best_by_variable_together(
                    filtered_jv, filtered_curves, colors=color_scheme,
                    show_summary=show_summary, flip_current=flip_current,
                )
            elif pl.startswith("CwVS"):
                show_summary = not pl.endswith("H")
                figs, fig_names_new = plot_manager.create_jv_best_by_variable_separate(
                    filtered_jv, filtered_curves, colors=color_scheme,
                    show_summary=show_summary, flip_current=flip_current,
                )
                fig_list.extend(figs)
                fig_names.extend(fig_names_new)
                continue
            elif "Cw" in pl:
                fig, fig_name = plot_manager.create_jv_best_device_plot(
                    filtered_jv, filtered_curves, colors=color_scheme, flip_current=flip_current,
                )
            elif "Cy" in pl:
                fig, fig_name = plot_manager.create_jv_all_cells_plot(
                    complete_jv, filtered_curves, colors=color_scheme, flip_current=flip_current,
                )
            elif "Cz" in pl:
                working_curves = plot_manager._create_matching_curves_data(
                    filtered_jv, complete_curves
                )
                fig, fig_name = plot_manager.create_jv_working_cells_plot(
                    filtered_jv, working_curves, colors=color_scheme, flip_current=flip_current,
                )
            elif "Co" in pl:
                if not omitted_jv.empty:
                    rejected_pce_min = omitted_jv["PCE(%)"].min()
                    rejected_pce_max = omitted_jv["PCE(%)"].max()
                    rejected_pce_mean = omitted_jv["PCE(%)"].mean()

                    # Show some example rejected samples
                    rejected_samples = omitted_jv[
                        ["sample", "cell", "PCE(%)", "filter_reason"]
                    ].head(5)
                    for _, row in rejected_samples.iterrows():
                        reason = row.get("filter_reason", "No reason specified")
                else:
                    logger.debug("  No rejected data available!")

                # Create filtered curves that match only the omitted JV data
                rejected_curves = plot_manager._create_matching_curves_data(
                    omitted_jv, complete_curves
                )

                logger.debug("  Rejected curves after filtering: %s", len(rejected_curves))

                if not rejected_curves.empty:
                    unique_rejected_devices = (
                        rejected_curves.groupby(["sample", "cell"]).size().reset_index()
                    )
                fig, fig_name = plot_manager.create_jv_non_working_cells_plot(
                    omitted_jv, rejected_curves, colors=color_scheme, flip_current=flip_current,
                )
            elif "Cx" in pl:
                figs, fig_names_new = plot_manager.create_jv_separated_by_cell_plot(
                    complete_jv, complete_curves, colors=color_scheme, flip_current=flip_current,
                )
                if isinstance(figs, list) and isinstance(fig_names_new, list):
                    fig_list.extend(figs)
                    fig_names.extend(fig_names_new)
                else:
                    fig_list.append(figs)
                    fig_names.append(fig_names_new)
                continue
            elif "Cd" in pl:
                figs, fig_names_new = plot_manager.create_jv_separated_by_substrate_plot(
                    complete_jv, complete_curves, colors=color_scheme, plot_type="all",
                    flip_current=flip_current,
                )
                if isinstance(figs, list) and isinstance(fig_names_new, list):
                    fig_list.extend(figs)
                    fig_names.extend(fig_names_new)
                else:
                    fig_list.append(figs)
                    fig_names.append(fig_names_new)
                continue
            else:
                logger.debug("Plot code %s not fully implemented yet", pl)
                continue

            # Only append single figures (combination plots already added above)
            if "fig" in locals():
                fig_list.append(fig)
                fig_names.append(fig_name)

        except Exception as e:
            logger.error("❌ Error creating plot %s: %s", pl, e)
            import traceback

            traceback.print_exc()
            continue

    return fig_list, fig_names


def plot_list_from_voila(plot_list):
    """Convert plot selections from UI to plot codes"""
    jvc_dict = {
        "Voc": "v",
        "Jsc": "j",
        "FF": "f",
        "PCE": "p",
        "Voc x FF": "x",
        "R_ser": "r",
        "R_shu": "h",
        "V_mpp": "u",
        "J_mpp": "i",
        "P_mpp": "m",
    }
    box_dict = {
        "by Batch": "e",
        "by Variable": "g",
        "by Sample": "a",
        "by Cell": "b",
        "by Scan Direction": "c",
        "by Status": "s",
        "by Status and Variable": "sg",
        "by Direction and Variable": "cg",
        "by Cell and Variable": "bg",
        "by Direction, Status and Variable": "csg",
    }
    cur_dict = {
        "All cells": "Cy",
        "Only working cells": "Cz",
        "Rejected cells": "Co",
        "Best device only": "Cw",  # backward compat
        "Best device overall": "Cw",
        "Best device by batch (together)": "CwBT",
        "Best device by batch (separate)": "CwBS",
        "Best device by variable (together)": "CwVT",
        "Best device by variable (separate)": "CwVS",
        "Separated by cell (all)": "Cx",
        "Separated by cell (working only)": "Cxw",
        "Separated by substrate (all)": "Cd",
        "Separated by substrate (working only)": "Cdw",
    }

    new_list = []
    for plot in plot_list:
        code = ""
        if len(plot) == 4:
            plot_type, option1, option2, direction_split_row = plot
        else:
            plot_type, option1, option2 = plot
            direction_split_row = False

        if "omitted" in plot_type:
            code += "J"
            code += jvc_dict.get(option1, "")
            code += box_dict.get(option2, "")
            if direction_split_row:
                code += "D"
        elif plot_type == "Correlation Matrix":
            suffix = "_ALL" if option2 == "All data" else ""
            if option1 == "Heatmap":
                new_list.append("BCORR" + suffix)
            elif option1 == "Scatter":
                new_list.append("BSCORR" + suffix)
            continue
        elif "Boxplot" in plot_type:
            if option1 == "The big 4: Voc, Jsc, FF, PCE":
                x_code = box_dict.get(option2, "a")
                dir_suffix = "D" if direction_split_row else ""
                new_list.append("BVJFP_" + x_code + dir_suffix)
                continue
            code += "B"
            code += jvc_dict.get(option1, "")
            code += box_dict.get(option2, "")
            if direction_split_row:
                code += "D"
        elif "Histogram" in plot_type:
            code += "H"
            code += jvc_dict.get(option1, "")
        elif "JV Curve" in plot_type:
            _best_opts = {
                "Best device only", "Best device overall",
                "Best device by batch (together)", "Best device by batch (separate)",
                "Best device by variable (together)", "Best device by variable (separate)",
            }
            if option1 in _best_opts:
                base = cur_dict.get(option1, "Cw")
                code = base + ("H" if option2 == "Hide JV summary" else "")
            else:
                code += cur_dict.get(option1, "")

        if code:
            new_list.append(code)

    return new_list


class PlotManager:
    """Manages all plotting operations for JV analysis"""

    def __init__(self):
        self.plot_output_path = ""

    def set_output_path(self, path):
        self.plot_output_path = path

    def _extract_rgb_from_color(self, color_string):
        """Extract RGB values from color string"""
        if "rgba(" in color_string:
            rgba_values = color_string.replace("rgba(", "").replace(")", "").split(",")
            return (
                int(rgba_values[0]),
                int(rgba_values[1]),
                int(rgba_values[2]),
                float(rgba_values[3]),
            )
        elif color_string.startswith("#"):
            hex_color = color_string.lstrip("#")
            if len(hex_color) == 6:
                return (
                    int(hex_color[0:2], 16),
                    int(hex_color[2:4], 16),
                    int(hex_color[4:6], 16),
                    0.7,
                )
        return 93, 164, 214, 0.7  # Default fallback

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

    def create_jv_best_device_plot(self, jvc_data, curves_data, colors=None, show_summary=True, flip_current=False):  # noqa: E501
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

        # Add axis lines
        fig.add_shape(type="line", x0=-0.2, y0=0, x1=1.35, y1=0, line=dict(color="gray", width=2))
        fig.add_shape(type="line", x0=0, y0=-25, x1=0, y1=3, line=dict(color="gray", width=2))

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

        # Add axis lines with extended range
        fig.add_shape(type="line", x0=-2, y0=0, x1=10, y1=0, line=dict(color="gray", width=2))
        fig.add_shape(type="line", x0=0, y0=-1000, x1=0, y1=300, line=dict(color="gray", width=2))

        # Group pairs: each measurement index gets one color, shared between Forward and Reverse
        unique_measurements = {}
        for pair in measurement_pairs:
            idx = pair["measurement_index"]
            if idx not in unique_measurements:
                unique_measurements[idx] = []
            unique_measurements[idx].append(pair)

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

        if not df_rev.empty and not df_for.empty:
            # Extract values
            char_vals = ["Voc(V)", "Jsc(mA/cm2)", "FF(%)", "PCE(%)"]
            char_rev = []
            char_for = []

            for cv in char_vals:
                if cv in df_rev.columns:
                    char_rev.append(best_rev_row[cv])
                else:
                    char_rev.append(0)
                if cv in df_for.columns:
                    char_for.append(best_for_row[cv])
                else:
                    char_for.append(0)

            # Add MPP points if available
            if "V_mpp(V)" in df_for.columns and "J_mpp(mA/cm2)" in df_for.columns:
                v_f = best_for_row["V_mpp(V)"]
                j_f = best_for_row["J_mpp(mA/cm2)"]
                if flip_current:
                    j_f = -j_f

                fig.add_trace(
                    go.Scatter(
                        x=[v_f],
                        y=[j_f],
                        mode="markers",
                        marker=dict(color="red", size=10),
                        name="Forward MPP",
                        hoverinfo="text",
                        hovertext=f"MPP Forward<br>V: {v_f:.3f} V<br>J: {j_f:.3f} mA/cm²",
                    )
                )

            if "V_mpp(V)" in df_rev.columns and "J_mpp(mA/cm2)" in df_rev.columns:
                v_r = best_rev_row["V_mpp(V)"]
                j_r = best_rev_row["J_mpp(mA/cm2)"]
                if flip_current:
                    j_r = -j_r

                fig.add_trace(
                    go.Scatter(
                        x=[v_r],
                        y=[j_r],
                        mode="markers",
                        marker=dict(color="red", size=10, symbol="x"),
                        name="Reverse MPP",
                        hoverinfo="text",
                        hovertext=f"MPP Reverse<br>V: {v_r:.3f} V<br>J: {j_r:.3f} mA/cm²",
                    )
                )

        if show_summary:
            # Add JV information as annotations (initially visible)
            text_rev = f"""Rev:
        <br>Voc: {char_rev[0]:>5.2f}
        <br>Jsc:  {char_rev[1]:>5.1f}
        <br>FF:   {char_rev[2]:>5.1f}
        <br>PCE: {char_rev[3]:>5.1f}"""

            text_for = f"For:<br>{char_for[0]:.2f} V<br>{char_for[1]:.1f} mA/cm²<br>{char_for[2]:.1f}%<br>{char_for[3]:.1f}%"  # noqa: E501

            annot_y = 5 if flip_current else -5
            # Add annotations for values
            fig.add_annotation(
                x=0.24,
                y=annot_y,
                text=text_rev,
                showarrow=False,
                font=dict(size=12),
                align="left",
                name="summary_rev",
            )

            fig.add_annotation(
                x=0.55,
                y=annot_y,
                text=text_for,
                showarrow=False,
                font=dict(size=12),
                align="left",
                name="summary_for",
            )

        y_range = [-5, 26] if flip_current else [-26, 5]
        # Update layout with custom modebar
        fig.update_layout(
            title=f"JV Curves - Best Device ({best_sample} [Cell {best_cell}])",
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
            margin=dict(r=150),
        )

        fig.update_xaxes(showgrid=True, gridwidth=1, gridcolor="lightgray")
        fig.update_yaxes(showgrid=True, gridwidth=1, gridcolor="lightgray")

        sample_name = f"JV_best_device_{best_sample} (Cell {best_cell}).html"
        return fig, sample_name

    def create_boxplot(
        self, data, var_x, var_y, filtered_info, datatype="data", wb=None, colors=None, sort_order="Alphanumeric ↑", custom_order="", direction_split=False
    ):
        """Create a boxplot with statistical analysis - ENHANCED with data verification"""
        names_dict = {
            "voc": "Voc(V)",
            "jsc": "Jsc(mA/cm2)",
            "ff": "FF(%)",
            "pce": "PCE(%)",
            "vocxff": "Voc x FF(V%)",
            "vmpp": "V_mpp(V)",
            "jmpp": "J_mpp(mA/cm2)",
            "pmpp": "P_mpp(mW/cm2)",
            "rser": "R_series(Ohmcm2)",
            "rshu": "R_shunt(Ohmcm2)",
        }
        var_name_y = names_dict[var_y]
        trash, filters = filtered_info

        if var_x == "batch" and "batch_for_plotting" in data.columns:
            var_x = "batch_for_plotting"

        # Show what samples are included in this plot
        unique_samples = data["sample"].nunique()  # noqa: F841
        unique_cells = data.groupby("sample")["cell"].nunique().sum()  # noqa: F841

        try:
            data["sample"] = data["sample"].astype(int)
        except ValueError:
            pass

        data = data.copy()  # Don't modify original data

        # Handle MultiIndex if present
        if isinstance(data.columns, pd.MultiIndex):
            data.columns = [
                "_".join(str(col).strip() for col in column if str(col) != "")
                for column in data.columns.values
            ]
        if isinstance(data.index, pd.MultiIndex):
            data = data.reset_index()

        data["Jsc(mA/cm2)"] = data["Jsc(mA/cm2)"].abs()

        # Apply custom order: filter data to only listed categories and relabel aliases
        custom_groups = None
        if sort_order == "Custom" and custom_order:
            custom_groups = _parse_custom_order(custom_order)
            if custom_groups:
                alias_to_display = {}
                for g in custom_groups:
                    for alias in g["aliases"]:
                        alias_to_display[alias] = g["display"]
                data[var_x] = data[var_x].astype(str)
                mask = data[var_x].isin(alias_to_display)
                data = data[mask].copy()
                data[var_x] = data[var_x].map(alias_to_display)
                # Trash counts are no longer meaningful after relabelling
                trash = trash.iloc[0:0]

        # Calculate statistics
        descriptor = data.groupby(var_x)[var_name_y].describe()

        # Get initial ordering
        initial_orderc = descriptor.sort_index()["count"].index

        # Custom ordering to put Reverse before Forward (always overrides sort_order)
        if "direction" in var_x.lower() or (
            len(initial_orderc) == 2 and set(initial_orderc) == {"Forward", "Reverse"}
        ):
            orderc = (
                ["Reverse", "Forward"]
                if set(initial_orderc) == {"Forward", "Reverse"}
                else list(initial_orderc)
            )
        elif sort_order == "Custom" and custom_groups:
            # Preserve the exact order from the parsed groups (already applied to data above)
            present = set(initial_orderc)
            orderc = [g["display"] for g in custom_groups if g["display"] in present]
        elif sort_order == "Alphanumeric ↓":
            orderc = sorted(initial_orderc, reverse=True)
        elif sort_order == "Mean ↑":
            means = data.groupby(var_x)[var_name_y].mean()
            orderc = means.sort_values(ascending=True).index.tolist()
        elif sort_order == "Mean ↓":
            means = data.groupby(var_x)[var_name_y].mean()
            orderc = means.sort_values(ascending=False).index.tolist()
        elif sort_order == "Median ↑":
            medians = data.groupby(var_x)[var_name_y].median()
            orderc = medians.sort_values(ascending=True).index.tolist()
        elif sort_order == "Median ↓":
            medians = data.groupby(var_x)[var_name_y].median()
            orderc = medians.sort_values(ascending=False).index.tolist()
        else:  # "Alphanumeric ↑" (default)
            orderc = list(initial_orderc)  # already sorted by sort_index()

        # Create dictionaries to map categories to their counts
        data_counts = data.groupby(var_x)[var_name_y].count().to_dict()
        trash_counts = trash.groupby(var_x)[var_name_y].count().to_dict() if not trash.empty else {}

        fig = go.Figure()

        # Use provided color scheme or default
        if colors is None:
            colors = [
                "rgba(93, 164, 214, 0.7)",
                "rgba(255, 144, 14, 0.7)",
                "rgba(44, 160, 101, 0.7)",
                "rgba(255, 65, 54, 0.7)",
                "rgba(207, 114, 255, 0.7)",
                "rgba(127, 96, 0, 0.7)",
                "rgba(255, 140, 184, 0.7)",
                "rgba(79, 90, 117, 0.7)",
            ]

        _dir_colors = {
            "Reverse": "rgba(255, 182, 193, 0.8)",
            "Forward": "rgba(173, 216, 230, 0.8)",
        }

        use_direction_split = (
            direction_split
            and "direction" in data.columns
            and var_x != "direction"
        )

        if use_direction_split:
            # Two traces (one per direction); x values are the category labels so Plotly
            # automatically groups them side by side under boxmode="group".
            for direction in ["Reverse", "Forward"]:
                dir_data = data[data["direction"] == direction]
                x_vals, y_vals, customdata = [], [], []
                for category in orderc:
                    cat_dir = dir_data[dir_data[var_x] == category]
                    ys = cat_dir[var_name_y].dropna()
                    if not ys.empty:
                        x_vals.extend([str(category)] * len(ys))
                        y_vals.extend(ys.tolist())
                        customdata.extend(cat_dir.loc[ys.index, ["sample", "cell"]].values.tolist())

                if y_vals:
                    fig.add_trace(
                        go.Box(
                            x=x_vals,
                            y=y_vals,
                            name=direction,
                            legendgroup=direction,
                            boxpoints="all",
                            pointpos=0,
                            jitter=0.5,
                            whiskerwidth=0.4,
                            marker=dict(size=5, opacity=0.7, color="rgba(0,0,0,0.7)"),
                            line=dict(width=1.5),
                            fillcolor=_dir_colors.get(direction, colors[0]),
                            boxmean=True,
                            customdata=customdata,
                            hovertemplate=(
                                f"<b>%{{x}} — {direction}</b><br>"
                                + "Value: %{y:.3f}<br>"
                                + "Sample: %{customdata[0]}<br>"
                                + "Cell: %{customdata[1]}"
                            ),
                        )
                    )
            show_legend = True
        else:
            # Original single-color per category
            for i, category in enumerate(orderc):
                category_data = data[data[var_x] == category][var_name_y].dropna()
                if not category_data.empty:
                    data_count = data_counts.get(category, 0)
                    trash_count = trash_counts.get(category, 0)
                    median = category_data.median()
                    mean = category_data.mean()

                    category_name = (
                        f"{category} (n={data_count})"
                        if trash_count == 0
                        else f"{category} ({data_count}/{data_count + trash_count})"
                    )

                    fig.add_trace(
                        go.Box(
                            y=category_data,
                            name=category_name,
                            boxpoints="all",
                            pointpos=0,
                            jitter=0.5,
                            whiskerwidth=0.4,
                            marker=dict(size=5, opacity=0.7, color="rgba(0,0,0,0.7)"),
                            line=dict(width=1.5),
                            fillcolor=colors[i % len(colors)],
                            boxmean=True,
                            width=0.8,
                            customdata=data[data[var_x] == category][["sample", "cell"]].values,
                            hovertemplate=(
                                f"<b>{category}</b><br>"
                                + "Value: %{y:.3f}<br>"
                                + "Sample: %{customdata[0]}<br>"
                                + "Cell: %{customdata[1]}<br>"
                                + f"Median: {median:.3f}<br>"
                                + f"Mean: {mean:.3f}<br>"
                                + f"Count: {data_count}"
                            ),
                        )
                    )
            show_legend = False

        # Create title with data info
        dir_note = " | split by scan direction" if use_direction_split else ""
        title_text = f"Boxplot of {var_y} by {var_x}{dir_note}" + (
            " (filtered out)" if datatype == "junk" else " (filtered data)"
        )
        subtitle = f"Data from {len(data)} measurements across {data[var_x].nunique()} {var_x} categories (after filtering)"  # noqa: E501

        fig.update_layout(
            title=f"{title_text}<br><sup>{subtitle}</sup>",
            xaxis_title=var_x,
            yaxis_title=var_name_y,
            boxmode="group",
            boxgap=0.05,
            boxgroupgap=0.1,
            template="plotly_white",
            margin=dict(l=40, r=40, t=100, b=80),
            showlegend=show_legend,
            plot_bgcolor="white",
            paper_bgcolor="white",
        )

        # Rotate x-axis labels if many categories
        if len(orderc) > 4:
            fig.update_layout(xaxis=dict(tickangle=-10, tickfont=dict(size=10)))

        # Save to Excel if workbook provided
        if wb:
            try:
                from utils import save_combined_excel_data

                wb = save_combined_excel_data(
                    self.plot_output_path,
                    wb,
                    data,
                    filtered_info,
                    var_x,
                    var_name_y,
                    var_y,
                    descriptor,
                )
            except ImportError:
                pass  # Skip Excel save if utils not available

        sample_name = (
            f"boxplotj_{var_y}_by_{var_x}.html"
            if datatype == "junk"
            else f"boxplot_{var_y}_by_{var_x}.html"
        )

        return fig, sample_name, wb

    def create_histogram(self, df, var_y, colors=None):
        """Create a histogram with statistics"""
        logger.debug("📊 Creating histogram with %s records for %s", len(df), var_y)

        names_dict = {
            "voc": "Voc(V)",
            "jsc": "Jsc(mA/cm2)",
            "ff": "FF(%)",
            "pce": "PCE(%)",
            "vmpp": "V_mpp(V)",
            "jmpp": "J_mpp(mA/cm2)",
            "pmpp": "P_mpp(mW/cm2)",
            "rser": "R_series(Ohmcm2)",
            "rshu": "R_shunt(Ohmcm2)",
        }

        pl_y = names_dict[var_y]

        # Determine number of bins
        bins = {"voc": 20, "jsc": 30}.get(var_y, 40)

        # Create histogram
        fig = go.Figure()

        primary_color = colors[0] if colors else "rgba(0, 0, 255, 0.6)"
        line_color = (
            colors[0].replace("0.6", "1.0")
            if colors and "rgba" in colors[0]
            else "rgba(0, 0, 255, 1)"
        )

        fig.add_trace(
            go.Histogram(
                x=df[pl_y],
                marker=dict(color=primary_color, line=dict(color=line_color, width=1)),
                hovertemplate=f"{pl_y}: %{{x:.3f}}<br>Count: %{{y}}<extra></extra>",
            )
        )

        # Add KDE if enough data points
        if len(df) > 5:
            try:
                from scipy import stats

                kde_x = np.linspace(df[pl_y].min(), df[pl_y].max(), 100)
                kde = stats.gaussian_kde(df[pl_y].dropna())
                kde_y = kde(kde_x) * len(df) * (df[pl_y].max() - df[pl_y].min()) / bins

                fig.add_trace(
                    go.Scatter(
                        x=kde_x,
                        y=kde_y,
                        mode="lines",
                        line=dict(color="red", width=2),
                        name="KDE",
                        hoverinfo="skip",
                    )
                )
            except ImportError:
                pass  # Skip KDE if scipy not available

        # Calculate statistics
        mean_val = df[pl_y].mean()
        median_val = df[pl_y].median()
        std_val = df[pl_y].std()
        min_val = df[pl_y].min()
        max_val = df[pl_y].max()
        count_val = len(df)

        # Create subplot with statistics table
        fig_with_stats = make_subplots(
            rows=2,
            cols=1,
            row_heights=[0.7, 0.3],  # Main plot takes 75%, stats take 25%
            specs=[[{"type": "histogram"}], [{"type": "table"}]],
            subplot_titles=["", "Statistics"],
            vertical_spacing=0.2,
        )

        # Add the histogram trace to the first subplot
        fig_with_stats.add_trace(
            go.Histogram(
                x=df[pl_y],
                marker=dict(color=primary_color, line=dict(color=line_color, width=1)),
                hovertemplate=f"{pl_y}: %{{x:.3f}}<br>Count: %{{y}}<extra></extra>",
            ),
            row=1,
            col=1,
        )

        # Add KDE if enough data points
        if len(df) > 5:
            try:
                from scipy import stats

                kde_x = np.linspace(df[pl_y].min(), df[pl_y].max(), 100)
                kde = stats.gaussian_kde(df[pl_y].dropna())
                kde_y = kde(kde_x) * len(df) * (df[pl_y].max() - df[pl_y].min()) / bins

                fig_with_stats.add_trace(
                    go.Scatter(
                        x=kde_x,
                        y=kde_y,
                        mode="lines",
                        line=dict(color="red", width=2),
                        name="KDE",
                        hoverinfo="skip",
                    ),
                    row=1,
                    col=1,
                )
            except ImportError:
                pass

        # Add statistics table
        fig_with_stats.add_trace(
            go.Table(
                header=dict(values=["Statistic", "Value"], fill_color="lightgray", align="left"),
                cells=dict(
                    values=[
                        ["Count", "Mean", "Median", "Std Dev", "Min", "Max"],
                        [
                            f"{count_val}",
                            f"{mean_val:.3f}",
                            f"{median_val:.3f}",
                            f"{std_val:.3f}",
                            f"{min_val:.3f}",
                            f"{max_val:.3f}",
                        ],
                    ],
                    fill_color="white",
                    align="left",
                ),
            ),
            row=2,
            col=1,
        )

        # Update layout
        fig_with_stats.update_layout(
            title=f"Histogram of {pl_y} (Filtered Data)",
            template="plotly_white",
            bargap=0.1,
            hovermode="closest",
            height=750,
            showlegend=True,  # Change from False to True
            legend=dict(
                x=1.02,
                y=1,
                bgcolor="rgba(255,255,255,0.9)",
                bordercolor="black",
                borderwidth=1,
                xanchor="left",
                yanchor="top",
            ),
            margin=dict(r=150),  # Add right margin for external legend
        )

        fig_with_stats.update_xaxes(title_text=pl_y, row=1, col=1)
        fig_with_stats.update_yaxes(title_text="Frequency", row=1, col=1)
        fig_with_stats.update_xaxes(showgrid=True, gridwidth=1, gridcolor="lightgray", row=1, col=1)
        fig_with_stats.update_yaxes(showgrid=True, gridwidth=1, gridcolor="lightgray", row=1, col=1)

        # Use the subplot figure instead of the original
        fig = fig_with_stats
        sample_name = f"histogram_{var_y}_filtered.html"

        return fig, sample_name

    def create_combination_plots(self, data, var_y, combination_type, filtered_info, colors=None):
        """Create multiple plots separated by condition/direction/cell and grouped by status/condition"""  # noqa: E501
        logger.debug("📊 Creating combination plots: %s", combination_type)

        names_dict = {
            "voc": "Voc(V)",
            "jsc": "Jsc(mA/cm2)",
            "ff": "FF(%)",
            "pce": "PCE(%)",
            "vocxff": "Voc x FF(V%)",
            "vmpp": "V_mpp(V)",
            "jmpp": "J_mpp(mA/cm2)",
            "pmpp": "P_mpp(mW/cm2)",
            "rser": "R_series(Ohmcm2)",
            "rshu": "R_shunt(Ohmcm2)",
        }
        var_name_y = names_dict[var_y]

        # Filter out dark measurements (D1, D2, etc.) for these combination plots
        data = data[~data["status"].str.startswith("D")].copy()
        logger.debug("   Filtered out dark measurements, %s records remaining", len(data))

        # Define what we separate plots by and what we group within plots
        plot_config = {
            "sg": {
                "primary_var": "condition",
                "primary_label": "Condition",
                "secondary_var": "status",
                "secondary_label": "Status",
            },
            "cg": {
                "primary_var": "condition",
                "primary_label": "Condition",
                "secondary_var": "direction",
                "secondary_label": "Direction",
            },
            "bg": {
                "primary_var": "condition",
                "primary_label": "Condition",
                "secondary_var": "cell",
                "secondary_label": "Cell",
            },
        }

        if combination_type not in plot_config:
            logger.warning("Warning: Unknown combination type %s", combination_type)
            return [], []

        config = plot_config[combination_type]
        primary_var = config["primary_var"]
        primary_label = config["primary_label"]
        secondary_var = config["secondary_var"]
        secondary_label = config["secondary_label"]

        # Check if required columns exist
        missing_cols = []
        for col in [primary_var, secondary_var]:
            if col not in data.columns:
                missing_cols.append(col)

        if missing_cols:
            logger.warning("Warning: Missing columns %s in data", missing_cols)
            return [], []

        # Get unique values for primary variable (what we separate plots by)
        primary_values = sorted(data[primary_var].unique())

        if not primary_values:
            logger.warning("Warning: No data found for primary variable %s", primary_var)
            return [], []

        figures = []
        figure_names = []

        # Create separate plot for each primary variable value
        for primary_val in primary_values:
            primary_data = data[data[primary_var] == primary_val]

            if primary_data.empty:
                continue

            # Custom ordering for direction to put Reverse before Forward
            if secondary_var == "direction":
                secondary_values = (
                    ["Reverse", "Forward"]
                    if set(primary_data[secondary_var].unique()) == {"Forward", "Reverse"}
                    else sorted(primary_data[secondary_var].unique())
                )
            else:
                secondary_values = sorted(primary_data[secondary_var].unique())

            if not secondary_values:
                continue

            fig = go.Figure()

            # Use a pleasing color palette
            if colors is None:
                colors = [
                    "rgba(93, 164, 214, 0.7)",
                    "rgba(255, 144, 14, 0.7)",
                    "rgba(44, 160, 101, 0.7)",
                    "rgba(255, 65, 54, 0.7)",
                    "rgba(207, 114, 255, 0.7)",
                    "rgba(127, 96, 0, 0.7)",
                    "rgba(255, 140, 184, 0.7)",
                    "rgba(79, 90, 117, 0.7)",
                ]

            # Add boxplot for each secondary value within this primary value
            for i, secondary_val in enumerate(secondary_values):
                subset_data = primary_data[primary_data[secondary_var] == secondary_val][
                    var_name_y
                ].dropna()

                if not subset_data.empty:
                    count = len(subset_data)
                    median = subset_data.median()
                    mean = subset_data.mean()

                    fig.add_trace(
                        go.Box(
                            y=subset_data,
                            name=f"{secondary_val} (n={count})",
                            boxpoints="all",
                            pointpos=0,
                            jitter=0.5,
                            whiskerwidth=0.4,
                            marker=dict(size=5, opacity=0.7, color="rgba(0,0,0,0.7)"),
                            line=dict(width=1.5),
                            fillcolor=colors[i % len(colors)],
                            boxmean=True,
                            width=0.8,
                            hovertemplate=(
                                f"<b>{secondary_val}</b><br>"
                                + "Value: %{y:.3f}<br>"
                                + f"Median: {median:.3f}<br>"
                                + f"Mean: {mean:.3f}<br>"
                                + f"Count: {count}"
                            ),
                        )
                    )

            # Update layout
            title_text = f"{var_y} by {secondary_label} ({primary_label}: {primary_val})"
            subtitle = f"Data from {len(primary_data)} measurements (light only)"

            fig.update_layout(
                title=f"{title_text}<br><sup>{subtitle}</sup>",
                xaxis_title=f"{secondary_label}",
                yaxis_title=var_name_y,
                boxmode="group",
                boxgap=0.05,
                boxgroupgap=0.1,
                template="plotly_white",
                margin=dict(l=40, r=40, t=100, b=80),
                showlegend=False,
                plot_bgcolor="white",
                paper_bgcolor="white",
            )

            # Rotate x-axis labels if many secondary values
            if len(secondary_values) > 4:
                fig.update_layout(xaxis=dict(tickangle=-10, tickfont=dict(size=10)))

            figures.append(fig)

            # Clean primary_val for filename (remove special characters)
            clean_primary_val = (
                str(primary_val).replace(" ", "_").replace("/", "_").replace("&", "and")
            )
            figure_names.append(
                f"boxplot_{var_y}_by_{secondary_var}_{primary_var}_{clean_primary_val}.html"
            )

        logger.debug("   Created %s combination plots", len(figures))
        return figures, figure_names

    def create_triple_combination_plots(
        self, data, var_y, combination_type, filtered_info, colors=None
    ):
        """Create a single figure with facet subplots per condition, colored by direction."""
        logger.debug("🎨 Creating triple combination plots: %s", combination_type)

        names_dict = {
            "voc": "Voc(V)",
            "jsc": "Jsc(mA/cm2)",
            "ff": "FF(%)",
            "pce": "PCE(%)",
            "vocxff": "Voc x FF(V%)",
            "vmpp": "V_mpp(V)",
            "jmpp": "J_mpp(mA/cm2)",
            "pmpp": "P_mpp(mW/cm2)",
            "rser": "R_series(Ohmcm2)",
            "rshu": "R_shunt(Ohmcm2)",
        }
        var_name_y = names_dict[var_y]

        data = data[~data["status"].str.startswith("D")].copy()
        logger.debug("   Filtered out dark measurements, %s records remaining", len(data))

        required_cols = ["condition", "status", "direction"]
        missing_cols = [col for col in required_cols if col not in data.columns]
        if missing_cols:
            logger.warning("Warning: Missing columns %s in data", missing_cols)
            return [], []

        if data.empty:
            return [], []

        # Order direction so Reverse always comes first
        data["direction"] = pd.Categorical(
            data["direction"], categories=["Reverse", "Forward"], ordered=True
        )
        data = data.sort_values("direction")

        fig = px.box(
            data,
            x="status",
            y=var_name_y,
            color="direction",
            facet_col="condition",
            facet_col_wrap=3,
            points="outliers",
            template="plotly_white",
            color_discrete_map={
                "Reverse": "rgba(255, 182, 193, 0.8)",
                "Forward": "rgba(173, 216, 230, 0.8)",
            },
            title=f"{var_y} by Direction and Status per Condition<br><sup>Light measurements only, {len(data)} records</sup>",  # noqa: E501
        )

        fig.update_traces(quartilemethod="linear", jitter=0.4, marker=dict(size=4, opacity=0.6))

        n_conditions = data["condition"].nunique()
        n_rows = int(np.ceil(n_conditions / 3))

        fig.update_layout(
            height=400 * n_rows,
            boxmode="group",
            boxgap=0.01,
            boxgroupgap=0.02,
            margin=dict(l=60, r=160, t=120, b=80),
            legend=dict(
                x=1.01,
                y=1,
                xanchor="left",
                yanchor="top",
                bgcolor="rgba(255,255,255,0.9)",
                bordercolor="black",
                borderwidth=1,
            ),
        )

        # Clean up facet labels (remove "condition=")
        fig.for_each_annotation(lambda a: a.update(text=a.text.split("=")[-1]))

        figure_name = f"boxplot_{var_y}_by_direction_status_all_conditions.html"
        logger.debug("   Created 1 combined facet figure for %s conditions", n_conditions)
        return [fig], [figure_name]

    def create_correlation_plot(self, data, filtered_info, colors=None, all_data=False):
        """Create a correlation heatmap of all JV parameters."""
        logger.debug("📊 Creating correlation plot")

        col_map = {
            "Voc": "Voc(V)",
            "Jsc": "Jsc(mA/cm2)",
            "FF": "FF(%)",
            "PCE": "PCE(%)",
            "Voc x FF": "Voc x FF(V%)",
            "R_ser": "R_series(Ohmcm2)",
            "R_shu": "R_shunt(Ohmcm2)",
            "V_mpp": "V_mpp(V)",
            "J_mpp": "J_mpp(mA/cm2)",
            "P_mpp": "P_mpp(mW/cm2)",
        }
        display_labels = list(col_map.keys())
        actual_cols = [col_map[k] for k in display_labels]

        available = [c for c in actual_cols if c in data.columns]
        available_labels = [display_labels[actual_cols.index(c)] for c in available]

        subset = data[available].copy()
        subset["Jsc(mA/cm2)"] = subset["Jsc(mA/cm2)"].abs()

        corr = subset.corr()
        corr_rounded = corr.round(2)

        fig = go.Figure(
            go.Heatmap(
                z=corr.values,
                x=available_labels,
                y=available_labels,
                colorscale="RdBu",
                zmid=0,
                zmin=-1,
                zmax=1,
                text=corr_rounded.values,
                texttemplate="%{text}",
                hovertemplate="x: %{x}<br>y: %{y}<br>r = %{z:.3f}<extra></extra>",
                colorbar=dict(title="Pearson r"),
            )
        )

        data_label = "all data" if all_data else "filtered data"
        fig.update_layout(
            title=f"Correlation Matrix of JV Parameters<br><sup>{len(data)} measurements ({data_label})</sup>",
            template="plotly_white",
            autosize=True,
            height=650,
            margin=dict(l=80, r=40, t=100, b=80),
        )

        return fig, "correlation_jv_parameters.html"

    def create_correlation_scatter_matrix(self, data, filtered_info, colors=None, all_data=False):
        """Create a scatter matrix with histograms on the diagonal (lower triangle only)."""
        logger.debug("📊 Creating correlation scatter matrix")

        col_map = {
            "Voc": "Voc(V)",
            "Jsc": "Jsc(mA/cm2)",
            "FF": "FF(%)",
            "PCE": "PCE(%)",
            "Voc x FF": "Voc x FF(V%)",
            "R_ser": "R_series(Ohmcm2)",
            "R_shu": "R_shunt(Ohmcm2)",
            "V_mpp": "V_mpp(V)",
            "J_mpp": "J_mpp(mA/cm2)",
            "P_mpp": "P_mpp(mW/cm2)",
        }
        display_labels = list(col_map.keys())
        actual_cols = [col_map[k] for k in display_labels]

        available = [c for c in actual_cols if c in data.columns]
        available_labels = [display_labels[actual_cols.index(c)] for c in available]

        subset = data[available].copy()
        subset.columns = available_labels
        subset["Jsc"] = subset["Jsc"].abs()

        corr = subset.corr()

        n = len(available_labels)
        scatter_color = "rgba(93, 164, 214, 0.5)"
        hist_color = "rgba(93, 164, 214, 0.7)"

        fig = make_subplots(
            rows=n, cols=n,
            shared_xaxes=False,
            shared_yaxes=False,
            horizontal_spacing=0.04,
            vertical_spacing=0.04,
        )

        for row_idx, label_y in enumerate(available_labels):
            for col_idx, label_x in enumerate(available_labels):
                r, c = row_idx + 1, col_idx + 1

                if col_idx > row_idx:
                    # Upper triangle: show Pearson R value
                    r_val = corr.loc[label_y, label_x]
                    abs_r = abs(r_val)
                    # Color: red (positive) / blue (negative), intensity scales with |r|
                    if r_val > 0:
                        text_color = f"rgba(215, 48, 39, {0.4 + 0.6 * abs_r:.2f})"
                    else:
                        text_color = f"rgba(69, 117, 180, {0.4 + 0.6 * abs_r:.2f})"
                    font_size = int(9 + 9 * abs_r)
                    fig.add_trace(
                        go.Scatter(
                            x=[0.5], y=[0.5],
                            mode="text",
                            text=[f"<b>{r_val:.2f}</b>"],
                            textfont=dict(size=font_size, color=text_color),
                            showlegend=False,
                            hovertemplate=(
                                f"<b>{label_x} vs {label_y}</b><br>Pearson R = {r_val:.3f}<extra></extra>"
                            ),
                        ),
                        row=r, col=c,
                    )
                    fig.update_xaxes(
                        range=[0, 1], showticklabels=False, showgrid=False, zeroline=False,
                        row=r, col=c,
                    )
                    fig.update_yaxes(
                        range=[0, 1], showticklabels=False, showgrid=False, zeroline=False,
                        row=r, col=c,
                    )
                    continue
                elif col_idx == row_idx:
                    # Diagonal: histogram of the variable
                    vals = subset[label_x].dropna()
                    fig.add_trace(
                        go.Histogram(
                            x=vals,
                            marker_color=hist_color,
                            showlegend=False,
                            hovertemplate=f"<b>{label_x}</b><br>Value: %{{x:.3f}}<br>Count: %{{y}}<extra></extra>",
                        ),
                        row=r, col=c,
                    )
                else:
                    # Lower triangle: scatter
                    x_vals = subset[label_x].dropna()
                    # Align indices
                    common_idx = subset[[label_x, label_y]].dropna().index
                    fig.add_trace(
                        go.Scatter(
                            x=subset.loc[common_idx, label_x],
                            y=subset.loc[common_idx, label_y],
                            mode="markers",
                            marker=dict(size=3, color=scatter_color, opacity=0.7),
                            showlegend=False,
                            hovertemplate=(
                                f"<b>{label_x} vs {label_y}</b><br>"
                                f"{label_x}: %{{x:.3f}}<br>"
                                f"{label_y}: %{{y:.3f}}<extra></extra>"
                            ),
                        ),
                        row=r, col=c,
                    )

        # Add axis labels along the edges only
        for i, label in enumerate(available_labels):
            # Bottom row: x-axis titles
            fig.update_xaxes(title_text=label, title_font=dict(size=10), row=n, col=i + 1)
            # Left column: y-axis titles (skip diagonal)
            if i > 0:
                fig.update_yaxes(title_text=label, title_font=dict(size=10), row=i + 1, col=1)

        cell_size = max(110, min(170, 900 // n))
        data_label = "all data" if all_data else "filtered data"
        fig.update_layout(
            title=f"Scatter Matrix of JV Parameters<br><sup>{len(data)} measurements ({data_label}) — diagonal: distribution, lower triangle: scatter</sup>",
            height=cell_size * n + 80,
            autosize=True,
            template="plotly_white",
            margin=dict(l=80, r=40, t=100, b=80),
            showlegend=False,
        )

        return fig, "correlation_scatter_matrix.html"

    def create_voc_jsc_ff_pce_subplots(self, data, filtered_info, colors=None, var_x=None, direction_split=False):
        """Create a 2x2 facet figure with Voc, Jsc, FF, PCE boxplots."""
        logger.debug("📊 Creating Voc/Jsc/FF/PCE subplots")

        params = ["Voc(V)", "Jsc(mA/cm2)", "FF(%)", "PCE(%)"]
        param_labels = ["Voc", "Jsc", "FF", "PCE"]

        available = [c for c in params if c in data.columns]
        if not available:
            logger.warning("Warning: none of the expected columns found in data")
            return None, ""

        data = data.copy()
        data["Jsc(mA/cm2)"] = data["Jsc(mA/cm2)"].abs()

        if var_x is None:
            var_x = "batch_for_plotting" if "batch_for_plotting" in data.columns else "sample"
        elif var_x == "batch" and "batch_for_plotting" in data.columns:
            var_x = "batch_for_plotting"

        if var_x not in data.columns:
            var_x = "sample"

        try:
            data[var_x] = data[var_x].astype(int)
        except (ValueError, TypeError):
            pass

        use_direction_color = (
            direction_split
            and "direction" in data.columns
            and var_x != "direction"
        )

        if use_direction_color:
            # Order direction so Reverse always comes first
            data["direction"] = pd.Categorical(
                data["direction"], categories=["Reverse", "Forward"], ordered=True
            )
            data = data.sort_values("direction")
            id_vars = [var_x, "direction"]
        else:
            id_vars = [var_x]

        # Melt to long format so px.box can use facet_col
        melt_df = data[id_vars + available].melt(
            id_vars=id_vars, value_vars=available, var_name="parameter", value_name="value"
        )

        # Use short labels for display
        label_map = dict(zip(params, param_labels))
        melt_df["parameter"] = melt_df["parameter"].map(label_map)

        # Fix parameter order
        melt_df["parameter"] = pd.Categorical(
            melt_df["parameter"], categories=param_labels, ordered=True
        )
        melt_df = melt_df.sort_values("parameter")

        if colors is None:
            colors = [
                "rgba(93, 164, 214, 0.7)", "rgba(255, 144, 14, 0.7)",
                "rgba(44, 160, 101, 0.7)", "rgba(255, 65, 54, 0.7)",
                "rgba(207, 114, 255, 0.7)", "rgba(127, 96, 0, 0.7)",
                "rgba(255, 140, 184, 0.7)", "rgba(79, 90, 117, 0.7)",
            ]

        dir_note = " | split by scan direction" if use_direction_color else ""
        common_kwargs = dict(
            x=var_x,
            y="value",
            facet_col="parameter",
            facet_col_wrap=2,
            points="all",
            template="plotly_white",
            title=f"The big 4 — Voc, Jsc, FF, PCE by {var_x}{dir_note}<br><sup>{len(data)} measurements (filtered data)</sup>",
        )
        if use_direction_color:
            px_kwargs = {
                **common_kwargs,
                "color": "direction",
                "color_discrete_map": {
                    "Reverse": "rgba(255, 182, 193, 0.8)",
                    "Forward": "rgba(173, 216, 230, 0.8)",
                },
            }
        else:
            px_kwargs = {
                **common_kwargs,
                "color": var_x,
                "color_discrete_sequence": colors,
            }

        fig = px.box(melt_df, **px_kwargs)

        fig.update_traces(
            quartilemethod="linear",
            jitter=0.4,
            pointpos=0,
            marker=dict(size=4, opacity=0.6),
        )

        layout_kwargs = dict(
            height=750,
            boxmode="group",
            boxgap=0.01,
            boxgroupgap=0.02,
        )
        if use_direction_color:
            layout_kwargs["margin"] = dict(l=60, r=160, t=120, b=80)
            layout_kwargs["legend"] = dict(
                x=1.01, y=1, xanchor="left", yanchor="top",
                bgcolor="rgba(255,255,255,0.9)", bordercolor="black", borderwidth=1,
            )
        else:
            layout_kwargs["margin"] = dict(l=60, r=40, t=120, b=80)
            layout_kwargs["showlegend"] = False

        fig.update_layout(**layout_kwargs)

        # Clean up facet labels (remove "parameter=")
        fig.for_each_annotation(lambda a: a.update(text=a.text.split("=")[-1]))

        # Independent y-axes per facet
        fig.update_yaxes(matches=None, showticklabels=True, title="")

        return fig, "boxplot_voc_jsc_ff_pce_2x2.html"

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
        fig.add_shape(type="line", x0=-0.2, y0=0, x1=10, y1=0, line=dict(color="gray", width=2))
        fig.add_shape(type="line", x0=0, y0=-1000, x1=0, y1=3, line=dict(color="gray", width=2))

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
        fig.add_shape(type="line", x0=-0.2, y0=0, x1=10, y1=0, line=dict(color="gray", width=2))
        fig.add_shape(type="line", x0=0, y0=-1000, x1=0, y1=3, line=dict(color="gray", width=2))

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

    def create_jv_non_working_cells_plot(self, jvc_data, curves_data, colors=None, flip_current=False):
        """Plot JV curves for rejected cells only (cells that were filtered out)"""

        if jvc_data.empty:
            fig = go.Figure()
            fig.update_layout(title="No rejected cells found (none were filtered out)")
            return fig, "JV_rejected_cells.html"

        # Use the same logic as create_jv_all_cells_plot but with different title
        fig = go.Figure()

        # Add axis lines
        fig.add_shape(type="line", x0=-0.2, y0=0, x1=10, y1=0, line=dict(color="gray", width=2))
        fig.add_shape(type="line", x0=0, y0=-1000, x1=0, y1=3, line=dict(color="gray", width=2))

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

    def create_jv_separated_by_cell_plot(self, jvc_data, curves_data, colors=None, plot_type="all", flip_current=False):  # noqa: E501
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
            fig.add_shape(type="line", x0=-0.2, y0=0, x1=2, y1=0, line=dict(color="gray", width=1))
            fig.add_shape(type="line", x0=0, y0=-30, x1=0, y1=5, line=dict(color="gray", width=1))

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

    # ------------------------------------------------------------------
    # Best-device variants: by batch / by variable
    # ------------------------------------------------------------------

    def _plot_best_device_curves(self, fig, best_device_jv, best_curves, base_color, label, flip_current=False):  # noqa: E501
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
        char_rev = [df_rev[c].iloc[0] if (not df_rev.empty and c in df_rev.columns) else 0 for c in char_vals]  # noqa: E501
        char_for = [df_for[c].iloc[0] if (not df_for.empty and c in df_for.columns) else 0 for c in char_vals]  # noqa: E501
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
            x=x_rev, y=annot_y, text=text_rev,
            showarrow=False, font=dict(size=12), align="left", name="summary_rev",
        )
        fig.add_annotation(
            x=x_rev + 0.3, y=annot_y, text=text_for,
            showarrow=False, font=dict(size=12), align="left", name="summary_for",
        )

    def create_jv_best_by_batch_together(self, jvc_data, curves_data, colors=None, show_summary=True, flip_current=False):  # noqa: E501
        """One figure showing the best device (highest PCE) for each batch."""
        if colors is None:
            colors = ["#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd", "#8c564b"]

        fig = go.Figure()
        fig.add_shape(type="line", x0=-2, y0=0, x1=10, y1=0, line=dict(color="gray", width=1))
        fig.add_shape(type="line", x0=0, y0=-1000, x1=0, y1=300, line=dict(color="gray", width=1))

        batches = sorted(jvc_data["batch"].unique())
        summary_items = []

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
            self._plot_best_device_curves(fig, batch_jv, best_curves, base_color, label, flip_current)

        y_range = [-5, 26] if flip_current else [-26, 5]
        fig.update_layout(
            title=f"JV Curves - Best Device per Batch ({len(batches)} batches)",
            xaxis_title="Voltage [V]",
            yaxis_title="Current Density [mA/cm²]",
            xaxis=dict(range=[-0.2, 1.5]),
            yaxis=dict(range=y_range),
            template="plotly_white",
            legend=dict(
                x=1.02, y=1, bgcolor="rgba(255,255,255,0.9)",
                bordercolor="black", borderwidth=1, xanchor="left", yanchor="top",
            ),
            showlegend=True,
            margin=dict(r=250),
        )
        return fig, "JV_best_by_batch_together.html"

    def create_jv_best_by_batch_separate(self, jvc_data, curves_data, colors=None, show_summary=True, flip_current=False):  # noqa: E501
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
            fig.add_shape(type="line", x0=-2, y0=0, x1=10, y1=0, line=dict(color="gray", width=1))
            fig.add_shape(type="line", x0=0, y0=-1000, x1=0, y1=300, line=dict(color="gray", width=1))

            base_color = colors[batch_idx % len(colors)]
            label = f"{best_sample}[{best_cell}]"
            self._plot_best_device_curves(fig, batch_jv, best_curves, base_color, label, flip_current)

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
                    x=1.02, y=1, bgcolor="rgba(255,255,255,0.9)",
                    bordercolor="black", borderwidth=1, xanchor="left", yanchor="top",
                ),
                showlegend=True,
                margin=dict(r=200),
            )
            figures.append(fig)
            figure_names.append(f"JV_best_batch_{clean_batch}.html")

        logger.debug("  Created %s best-by-batch figures", len(figures))
        return figures, figure_names

    def create_jv_best_by_variable_together(self, jvc_data, curves_data, colors=None, show_summary=True, flip_current=False):  # noqa: E501
        """One figure showing the best device per condition/variable."""
        if "condition" not in jvc_data.columns:
            fig = go.Figure()
            fig.update_layout(
                title="Best device by variable -- no conditions set (use Tab 2 to assign variable names)"
            )
            return fig, "JV_best_by_variable_together.html"

        if colors is None:
            colors = ["#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd", "#8c564b"]

        fig = go.Figure()
        fig.add_shape(type="line", x0=-2, y0=0, x1=10, y1=0, line=dict(color="gray", width=1))
        fig.add_shape(type="line", x0=0, y0=-1000, x1=0, y1=300, line=dict(color="gray", width=1))

        conditions = sorted(jvc_data["condition"].dropna().unique())
        summary_items = []

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
            self._plot_best_device_curves(fig, cond_jv, best_curves, base_color, label, flip_current)

        y_range = [-5, 26] if flip_current else [-26, 5]
        fig.update_layout(
            title=f"JV Curves - Best Device per Variable ({len(conditions)} conditions)",
            xaxis_title="Voltage [V]",
            yaxis_title="Current Density [mA/cm²]",
            xaxis=dict(range=[-0.2, 1.5]),
            yaxis=dict(range=y_range),
            template="plotly_white",
            legend=dict(
                x=1.02, y=1, bgcolor="rgba(255,255,255,0.9)",
                bordercolor="black", borderwidth=1, xanchor="left", yanchor="top",
            ),
            showlegend=True,
            margin=dict(r=250),
        )
        return fig, "JV_best_by_variable_together.html"

    def create_jv_best_by_variable_separate(self, jvc_data, curves_data, colors=None, show_summary=True, flip_current=False):  # noqa: E501
        """Separate figure per condition/variable, each showing the best device."""
        if "condition" not in jvc_data.columns:
            fig = go.Figure()
            fig.update_layout(
                title="Best device by variable -- no conditions set (use Tab 2 to assign variable names)"
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
            fig.add_shape(type="line", x0=-2, y0=0, x1=10, y1=0, line=dict(color="gray", width=1))
            fig.add_shape(type="line", x0=0, y0=-1000, x1=0, y1=300, line=dict(color="gray", width=1))

            base_color = colors[cond_idx % len(colors)]
            label = f"{best_sample}[{best_cell}]"
            self._plot_best_device_curves(fig, cond_jv, best_curves, base_color, label, flip_current)

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
                    x=1.02, y=1, bgcolor="rgba(255,255,255,0.9)",
                    bordercolor="black", borderwidth=1, xanchor="left", yanchor="top",
                ),
                showlegend=True,
                margin=dict(r=200),
            )
            figures.append(fig)
            figure_names.append(f"JV_best_variable_{clean_cond}.html")

        logger.debug("  Created %s best-by-variable figures", len(figures))
        return figures, figure_names
