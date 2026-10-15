# exporters.py
"""Export utilities for analysis results"""

import json
from datetime import datetime

import config
import lmfit
import numpy as np
import pandas as pd
from utils import debug_print

# Units of fitted peak parameters. Intensities are arbitrary units, written as "-";
# the area (lmfit's `amplitude`) is too. Its value does depend on whether the fit ran
# in nm or eV, which the fit group's `x_unit` attribute records.
_X_UNIT_PARAMS = {
    "center",
    "position",
    "sigma",
    "fwhm",
    "width",
    "width_10pct",
    "width_50pct",
}
_UNITLESS_PARAMS = {"height", "amplitude", "area", "skew"}


def parameter_unit(param, model_type, x_unit):
    """Unit of a fitted peak parameter, or None if unknown (e.g. polynomial terms).

    `gamma` depends on the model: the Lorentzian half width for Voigt and Skewed
    Voigt, but a dimensionless skewness for Skewed Gaussian.
    """
    if param == "gamma":
        return "-" if model_type == "Skewed Gaussian" else x_unit
    if param in _X_UNIT_PARAMS:
        return x_unit
    if param in _UNITLESS_PARAMS:
        return "-"
    return None


class ResultExporter:
    """Class to handle export of fitting results and analysis"""

    def __init__(self):
        debug_print("ResultExporter initialized", "Exporter")
        # self.export_formats = ['xlsx', 'csv', 'json', 'hdf5']

    def export_to_excel(self, fitting_results, timestamps, filename=None):
        """
        Export fitting results to Excel file with multiple sheets

        Parameters:
        -----------
        fitting_results : dict
            Dictionary of fitting results from batch fitting
        timestamps : array
            Time values
        filename : str, optional
            Output filename

        Returns:
        --------
        str: Path to exported file
        """
        if filename is None:
            filename = f"peak_fitting_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"

        # Create Excel writer
        with pd.ExcelWriter(filename, engine="openpyxl") as writer:
            # Sheet 1: Peak parameters (main data)
            peak_params_df, stderr_df = self._create_peak_parameters_dataframe(fitting_results)
            peak_params_df.to_excel(writer, sheet_name="Peak_Parameters", index=False)

            # Sheet 2: Standard errors
            if not stderr_df.empty:
                stderr_df.to_excel(writer, sheet_name="Standard_Errors", index=False)

            # Sheet 3: Fitting quality metrics
            quality_df = self._create_quality_metrics_dataframe(fitting_results)
            quality_df.to_excel(writer, sheet_name="Fitting_Quality", index=False)

        return filename

    def export_to_isa_h5(
        self,
        fitting_results,
        h5_path,
        time_unit="s",
        h5_mode=None,
        wavelength_unit="nm",
        fit_settings=None,
    ):
        """
        Export fitting results into the existing HDF5 file.

        A timestamped subgroup is created under /fitting_results/ with the name
        fit_YYYYMMDD_HH_MM_SS. The group carries attributes for the time and
        index range covered as well as the creation timestamp. All columns from
        the merged dataframe (peak_params, stderr, quality) are written as
        individual datasets under that group. Each dataset has peak_name and
        model_type attributes.

        Parameters:
        -----------
        fitting_results : dict
            Dictionary of fitting results from batch fitting
        h5_path : str
        fit_settings : dict, optional
            Settings behind these results (FittingEngine.batch_settings), each
            written as a group attribute; None values are skipped
        """
        import h5py

        debug_print("Exporting fitting results to HDF5: " + h5_path, "Exporter")

        peak_params_df, stderr_df = self._create_peak_parameters_dataframe(fitting_results)
        quality_df = self._create_quality_metrics_dataframe(fitting_results)

        # Merge the three dataframes into one row per frame; columns shared between them
        # are kept once. They must be matched on the frame, not on row position: the
        # parameter tables skip failed frames and are sorted, the quality table keeps
        # every frame in result order.
        frame_keys = ["Time_Index", "Time"]
        combined_df = None
        for df in (peak_params_df, stderr_df, quality_df):
            if df.empty:
                continue
            if combined_df is None:
                combined_df = df.copy()
                continue
            new_cols = [c for c in df.columns if c not in combined_df.columns]
            if new_cols:
                combined_df = combined_df.merge(
                    df[frame_keys + new_cols], on=frame_keys, how="outer"
                )
        if combined_df is None:
            combined_df = pd.DataFrame(columns=frame_keys)
        else:
            combined_df = combined_df.sort_values("Time_Index").reset_index(drop=True)

        # Batch fits run in one mode; "mixed" would mean results were merged
        modes = {
            "sequential" if r.get("smart_init_used") else "parallel"
            for r in fitting_results.values()
            if r
        }
        fit_mode = modes.pop() if len(modes) == 1 else ("mixed" if modes else "N/A")

        # Build peak_id -> {name, model_type} mapping from the first successful result
        peak_info_map = {}
        peak_models = []
        for result in fitting_results.values():
            if result and result.get("success"):
                peak_models = result.get("peak_models", [])
                for i, pm in enumerate(result.get("peak_models", [])):
                    pid = f"p{i}"
                    peak_info_map[pid] = {
                        "name": pm.get("name", pid),
                        "model_type": pm.get("type", "Unknown"),
                    }
                break

        debug_print("Peak info map: " + str(peak_info_map), "Exporter")

        # Time and index range from the merged df
        min_time = (
            float(combined_df["Time"].min()) if "Time" in combined_df.columns else float("nan")
        )
        max_time = (
            float(combined_df["Time"].max()) if "Time" in combined_df.columns else float("nan")
        )
        min_index = (
            int(combined_df["Time_Index"].min()) if "Time_Index" in combined_df.columns else -1
        )
        max_index = (
            int(combined_df["Time_Index"].max()) if "Time_Index" in combined_df.columns else -1
        )

        now = datetime.now()
        group_name = now.strftime("fit_%Y%m%d_%H_%M_%S")

        with h5py.File(h5_path, "a") as h5f:
            # two saves within one second used to share a group and leave stale datasets of
            # the first behind: a taken name gets a counter
            base_name, counter = group_name, 1
            while f"fitting_results/{group_name}" in h5f:
                counter += 1
                group_name = f"{base_name}_{counter}"
            grp = h5f.require_group(f"fitting_results/{group_name}")

            # Group-level attributes
            grp.attrs["min_time"] = min_time
            grp.attrs["max_time"] = max_time
            grp.attrs["min_index"] = min_index
            grp.attrs["max_index"] = max_index
            grp.attrs["h5_mode"] = h5_mode if h5_mode is not None else "N/A"
            grp.attrs["created_at"] = now.isoformat()
            grp.attrs["peak_explorer_version"] = config.APP_VERSION
            grp.attrs["lmfit_version"] = lmfit.__version__
            grp.attrs["x_unit"] = wavelength_unit
            grp.attrs["fit_mode"] = fit_mode
            # Full fit setup: start values, user bounds, Fix flags and names
            grp.attrs["peak_models"] = json.dumps(peak_models, default=float)
            # background_model, poly_degree, center_bound, fit_x_min/max (in x_unit)
            for key, value in (fit_settings or {}).items():
                if value is not None:
                    grp.attrs[key] = value

            # One dataset per column
            for col in combined_df.columns:
                series = pd.to_numeric(combined_df[col], errors="coerce")
                data = series.values.astype(float)
                if col in grp:
                    del grp[col]
                ds = grp.create_dataset(col, data=data)

                # Store time_unit as attribute on the Time dataset
                if col == "Time":
                    ds.attrs["time_unit"] = time_unit

                # Resolve peak_id from column name (e.g. "p0_center" -> "p0")
                parts = col.split("_")
                peak_id = (
                    parts[0]
                    if len(parts) > 1 and parts[0].startswith("p") and parts[0][1:].isdigit()
                    else None
                )

                # Only store peak_name and model_type if dataset starts with 'p' and contains no strings
                if peak_id is not None and not any(isinstance(v, str) for v in data):
                    info = peak_info_map.get(peak_id, {})
                    ds.attrs["peak_name"] = info.get("name", "N/A")
                    ds.attrs["model_type"] = info.get("model_type", "N/A")

                    # Determine unit from base parameter name (strip _stderr suffix)
                    base_param = col[len(peak_id) + 1 :]  # e.g. "center" or "center_stderr"
                    base_param = base_param.removesuffix("_stderr")
                    unit = parameter_unit(base_param, info.get("model_type"), wavelength_unit)
                    if unit is not None:
                        ds.attrs["unit"] = unit

        debug_print(
            f"Saved fitting results to {h5_path} under /fitting_results/{group_name}", "Exporter"
        )

    def _create_peak_parameters_dataframe(self, fitting_results):
        """Create comprehensive peak parameters dataframe and separate stderr dataframe"""
        param_data = []
        stderr_data = []
        renamed_to_area = set()  # peak_ids whose amplitude column was renamed to area

        # debug_print("Fitting_results: " + str(fitting_results), "Exporter")

        for idx, result in fitting_results.items():
            if result is None or not result.get("success", False):
                continue

            base_row = {"Time_Index": result["index"], "Time": result["time"]}

            # Extract peak parameters
            parameters = result.get("parameters", {})

            # debug_print("Raw Parameters: " + str(parameters), "Exporter")

            # Group parameters by peak
            peak_params = {}
            for param_name, param_data_item in parameters.items():
                if param_name.startswith("p") and "_" in param_name:
                    peak_id = param_name.split("_")[0]
                    param_type = "_".join(param_name.split("_")[1:])

                    if peak_id not in peak_params:
                        peak_params[peak_id] = {}
                    peak_params[peak_id][param_type] = param_data_item["value"]
                    peak_params[peak_id][f"{param_type}_stderr"] = param_data_item.get(
                        "stderr", np.nan
                    )

            # debug_print("Peak Parameters" + str(peak_params), "Exporter")

            # Create single row with all peaks' parameters
            if peak_params:
                row = base_row.copy()
                stderr_row = base_row.copy()

                # Sort peaks by ID for consistent ordering
                sorted_peaks = sorted(peak_params.keys(), key=lambda x: int(x[1:]))

                peak_models = result.get("peak_models", [])
                for peak_id in sorted_peaks:
                    params = peak_params[peak_id]
                    peak_index = int(peak_id[1:])
                    peak_type = (
                        peak_models[peak_index]["type"]
                        if peak_index < len(peak_models)
                        else "Unknown"
                    )
                    row[f"{peak_id}_model_type"] = peak_type

                    # debug_print(f"Processing {peak_id} with model {peak_type}", "Exporter")
                    # debug_print("params: " + str(params), "Exporter")

                    # Add main parameters with peak_id prefix
                    for param_type, value in params.items():
                        if not param_type.endswith("_stderr"):
                            # Handle special naming cases
                            if param_type == "amplitude":
                                col_name = f"{peak_id}_amplitude"
                            elif param_type == "center":
                                col_name = f"{peak_id}_center"
                            elif param_type == "sigma":
                                col_name = f"{peak_id}_sigma"
                            elif param_type == "gamma":  # For Voigt profiles
                                col_name = f"{peak_id}_gamma"
                            else:
                                col_name = f"{peak_id}_{param_type}"

                            row[col_name] = value

                            # Add stderr to separate dataframe
                            stderr_key = f"{param_type}_stderr"
                            if stderr_key in params:
                                stderr_row[f"{col_name}_stderr"] = params[stderr_key]

                    # Calculate derived parameters. Checked numerically against
                    # lmfit's model definitions (#21): area, height, fwhm, width_10pct.

                    # Rename amplitude -> area for peak types where lmfit's `amplitude`
                    # is the integrated area under the curve.
                    if peak_type in (
                        "Gaussian",
                        "Voigt",
                        "Lorentzian",
                        "Skewed Gaussian",
                        "Skewed Voigt",
                    ):
                        amplitude = params["amplitude"]
                        amplitude_stderr = params.get("amplitude_stderr")
                        amplitude_stderr = np.nan if amplitude_stderr is None else amplitude_stderr
                        row[f"{peak_id}_area"] = amplitude
                        stderr_row[f"{peak_id}_area_stderr"] = amplitude_stderr
                        renamed_to_area.add(peak_id)

                    if peak_type == "Gaussian":
                        sigma = params["sigma"]
                        sigma_stderr = params.get("sigma_stderr")
                        sigma_stderr = np.nan if sigma_stderr is None else sigma_stderr

                        # Calculate peak width at different heights
                        row[f"{peak_id}_width_10pct"] = 4.29 * sigma
                        stderr_row[f"{peak_id}_width_10pct_stderr"] = 4.29 * sigma_stderr

                # Add R_squared as the last column
                row["R_Squared"] = result.get("r_squared", np.nan)
                stderr_row["R_Squared"] = np.nan  # R_squared doesn't have stderr

                param_data.append(row)
                stderr_data.append(stderr_row)

        main_df = pd.DataFrame(param_data).sort_values("Time_Index").reset_index(drop=True)
        stderr_df = pd.DataFrame(stderr_data).sort_values("Time_Index").reset_index(drop=True)
        # Only drop amplitude columns for peaks where we renamed amplitude -> area;
        # peak types without that rename keep their amplitude column.
        amplitude_cols = [f"{pid}_amplitude" for pid in renamed_to_area]
        amplitude_stderr_cols = [f"{pid}_amplitude_stderr" for pid in renamed_to_area]
        main_df = main_df.drop(columns=amplitude_cols, errors="ignore")
        stderr_df = stderr_df.drop(columns=amplitude_stderr_cols, errors="ignore")

        return main_df, stderr_df

    def _create_quality_metrics_dataframe(self, fitting_results):
        """Create fitting quality metrics dataframe"""
        quality_data = []

        for idx, result in fitting_results.items():
            if result is None:
                continue

            row = {
                "Time_Index": result["index"],
                "Time": result["time"],
                "Success": result.get("success", False),
                "R_Squared": result.get("r_squared", np.nan),
                "Chi_Squared": result.get("chi_squared", np.nan),
                "Reduced_Chi_Squared": result.get("reduced_chi_squared", np.nan),
                "AIC": result.get("aic", np.nan),
                "BIC": result.get("bic", np.nan),
            }

            # Calculate additional metrics if residuals are available
            if result.get("residuals") is not None:
                residuals = result["residuals"]
                row["RMSE"] = np.sqrt(np.mean(residuals**2))
                row["MAE"] = np.mean(np.abs(residuals))
                row["Max_Residual"] = np.max(np.abs(residuals))

            quality_data.append(row)

        return pd.DataFrame(quality_data)
