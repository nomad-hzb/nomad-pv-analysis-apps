"""
Plot Management Module
Handles all plotting operations including JV curves, boxplots, and histograms.
Extracted from main.py for better organization.
"""

__author__ = "Edgar Nandayapa"
__institution__ = "Helmholtz-Zentrum Berlin"
__created__ = "August 2025"

import logging

import pandas as pd
from jv_curve_plots import JVCurvePlotsMixin
from jv_stat_plots import (  # noqa: F401 (kept importable from here)
    StatPlotsMixin,
    _parse_custom_order,
)

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


def _tag_omitted(figures, names):
    """Mark combination figures built from the omitted rows, so they are not mistaken for the
    kept data."""
    for figure in figures:
        title = figure.layout.title.text or ""
        figure.update_layout(title_text=f"{title} (omitted data)".strip())
    return figures, [f"{name} (omitted)" for name in names]


def plotting_string_action(
    plot_list,
    data,
    supp,
    is_voila=False,
    color_scheme=None,
    sort_order="Alphanumeric ↑",
    custom_order="",
    direction_split=False,
    flip_current=False,
):  # noqa: E501
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
        # "J..." codes are the omitted-data variants: the same plots built from the rows the
        # filters removed (they used to fall into the kept-data branches below)
        omitted_plot = pl.startswith("J")
        combo_data, combo_other = (
            (omitted_jv, [filtered_jv, filter_pars])
            if omitted_plot
            else (filtered_jv, [omitted_jv, filter_pars])
        )

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
                    "e": "batch",
                    "g": "condition",
                    "a": "sample",
                    "b": "cell",
                    "c": "direction",
                    "s": "status",
                }
                var_x = var_x_map.get(x_code, "sample")
                fig, fig_name = plot_manager.create_voc_jsc_ff_pce_subplots(
                    filtered_jv,
                    [omitted_jv, filter_pars],
                    colors=color_scheme,
                    var_x=var_x,
                    direction_split=dir_split,
                )
                fig_list.append(fig)
                fig_names.append(fig_name)
                continue
            elif "csg" in pl and var_y:
                # Direction, Status and Variable combination plots
                figs, fig_names_combo = plot_manager.create_triple_combination_plots(
                    combo_data, var_y, "csg", combo_other, colors=color_scheme
                )
                if omitted_plot:
                    figs, fig_names_combo = _tag_omitted(figs, fig_names_combo)
                fig_list.extend(figs)
                fig_names.extend(fig_names_combo)
                continue
            elif "CwH" in pl:
                fig, fig_name = plot_manager.create_jv_best_device_plot(
                    filtered_jv,
                    filtered_curves,
                    colors=color_scheme,
                    show_summary=False,
                    flip_current=flip_current,
                )
            elif "Cxw" in pl:
                # Create curves that match filtered JV data
                working_curves = plot_manager._create_matching_curves_data(
                    filtered_jv, complete_curves
                )
                figs, fig_names_new = plot_manager.create_jv_separated_by_cell_plot(
                    filtered_jv,
                    working_curves,
                    colors=color_scheme,
                    plot_type="working",
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
                    filtered_jv,
                    working_curves,
                    colors=color_scheme,
                    plot_type="working",
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
                    combo_data, var_y, "sg", combo_other, colors=color_scheme
                )
                if omitted_plot:
                    figs, fig_names_combo = _tag_omitted(figs, fig_names_combo)
                fig_list.extend(figs)
                fig_names.extend(fig_names_combo)
                continue
            elif "cg" in pl and var_y:
                # Direction and Variable combination plots
                figs, fig_names_combo = plot_manager.create_combination_plots(
                    combo_data, var_y, "cg", combo_other, colors=color_scheme
                )
                if omitted_plot:
                    figs, fig_names_combo = _tag_omitted(figs, fig_names_combo)
                fig_list.extend(figs)
                fig_names.extend(fig_names_combo)
                continue
            elif "bg" in pl and var_y:
                # Cell and Variable combination plots
                figs, fig_names_combo = plot_manager.create_combination_plots(
                    combo_data, var_y, "bg", combo_other, colors=color_scheme
                )
                if omitted_plot:
                    figs, fig_names_combo = _tag_omitted(figs, fig_names_combo)
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
                    omitted_jv,
                    var_x,
                    var_y,
                    [filtered_jv, filter_pars],
                    "junk",
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
                    filtered_jv,
                    filtered_curves,
                    colors=color_scheme,
                    show_summary=show_summary,
                    flip_current=flip_current,
                )
            elif pl.startswith("CwBS"):
                show_summary = not pl.endswith("H")
                figs, fig_names_new = plot_manager.create_jv_best_by_batch_separate(
                    filtered_jv,
                    filtered_curves,
                    colors=color_scheme,
                    show_summary=show_summary,
                    flip_current=flip_current,
                )
                fig_list.extend(figs)
                fig_names.extend(fig_names_new)
                continue
            elif pl.startswith("CwVT"):
                show_summary = not pl.endswith("H")
                fig, fig_name = plot_manager.create_jv_best_by_variable_together(
                    filtered_jv,
                    filtered_curves,
                    colors=color_scheme,
                    show_summary=show_summary,
                    flip_current=flip_current,
                )
            elif pl.startswith("CwVS"):
                show_summary = not pl.endswith("H")
                figs, fig_names_new = plot_manager.create_jv_best_by_variable_separate(
                    filtered_jv,
                    filtered_curves,
                    colors=color_scheme,
                    show_summary=show_summary,
                    flip_current=flip_current,
                )
                fig_list.extend(figs)
                fig_names.extend(fig_names_new)
                continue
            elif "Cw" in pl:
                fig, fig_name = plot_manager.create_jv_best_device_plot(
                    filtered_jv,
                    filtered_curves,
                    colors=color_scheme,
                    flip_current=flip_current,
                )
            elif "Cy" in pl:
                fig, fig_name = plot_manager.create_jv_all_cells_plot(
                    complete_jv,
                    filtered_curves,
                    colors=color_scheme,
                    flip_current=flip_current,
                )
            elif "Cz" in pl:
                working_curves = plot_manager._create_matching_curves_data(
                    filtered_jv, complete_curves
                )
                fig, fig_name = plot_manager.create_jv_working_cells_plot(
                    filtered_jv,
                    working_curves,
                    colors=color_scheme,
                    flip_current=flip_current,
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
                    omitted_jv,
                    rejected_curves,
                    colors=color_scheme,
                    flip_current=flip_current,
                )
            elif "Cx" in pl:
                figs, fig_names_new = plot_manager.create_jv_separated_by_cell_plot(
                    complete_jv,
                    complete_curves,
                    colors=color_scheme,
                    flip_current=flip_current,
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
                    complete_jv,
                    complete_curves,
                    colors=color_scheme,
                    plot_type="all",
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
                "Best device only",
                "Best device overall",
                "Best device by batch (together)",
                "Best device by batch (separate)",
                "Best device by variable (together)",
                "Best device by variable (separate)",
            }
            if option1 in _best_opts:
                base = cur_dict.get(option1, "Cw")
                code = base + ("H" if option2 == "Hide JV summary" else "")
            else:
                code += cur_dict.get(option1, "")

        if code:
            new_list.append(code)

    return new_list


class PlotManager(JVCurvePlotsMixin, StatPlotsMixin):
    """Manages all plotting operations for JV analysis"""

    # Short option code -> actual JV parameter column name. These are the real
    # DataFrame column names (also used for data access), so they keep their existing
    # "name(unit)" form -- never rename these values, only their *display* form below.
    PARAM_COLUMNS = {
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

    # Column name -> axis/legend display label, with units in [..] rather than (..).
    UNIT_LABELS = {col: col.replace("(", " [").replace(")", "]") for col in PARAM_COLUMNS.values()}

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

    # ------------------------------------------------------------------
    # Best-device variants: by batch / by variable
    # ------------------------------------------------------------------
