"""
Data Management Module
Handles all data loading, processing, filtering, and basic analysis operations.
"""

__author__ = "Edgar Nandayapa"
__institution__ = "Helmholtz-Zentrum Berlin"
__created__ = "August 2025"

import logging
import operator
import os
from typing import Optional

import pandas as pd
from hysprint_utils.api_calls import get_all_JV, get_ids_in_batch, get_sample_description
from hysprint_utils.error_handler import ErrorHandler
from pydantic import BaseModel, ValidationError, field_validator

logger = logging.getLogger(__name__)


class JVRow(BaseModel):
    voc: float
    jsc: float
    ff: float
    pce: float
    v_mpp: float
    j_mpp: float
    p_mpp: float
    r_series: Optional[float] = None
    r_shunt: Optional[float] = None
    sample: str
    batch: str
    condition: str
    cell: str
    direction: str
    ilum: str
    status: str
    sample_id: str

    @field_validator("r_series", "r_shunt", mode="before")
    @classmethod
    def coerce_optional_float(cls, v):
        if v is None or (isinstance(v, float) and v != v):  # NaN check
            return None
        return v


def extract_status_from_metadata(data, metadata):
    """
    Extract status from API metadata containing filename
    """
    import re

    # Look for filename in metadata
    filename_candidates = [
        metadata.get("mainfile", ""),
        metadata.get("upload_name", ""),
        metadata.get("entry_name", ""),
        metadata.get("filename", ""),
        # Also check in data if filename is stored there
        data.get("data_file", "") if isinstance(data, dict) else "",
    ]

    for candidate in filename_candidates:
        if candidate:
            # Primary: token immediately before _jv. in filename (e.g. L1, 5min, 30min, L3)
            status_match = re.search(r"_([A-Za-z0-9]+)_jv\.", candidate)
            if status_match:
                return status_match.group(1)

            # Fallback: L/D followed by digits with surrounding underscores
            status_match = re.search(r"_([LD]\d+)(?:_3min)?_", candidate)
            if not status_match:
                status_match = re.search(r"([LD]\d+)", candidate)

            if status_match:
                return status_match.group(1)

    return "N/A"


class DataManager:
    """Main data management class for JV analysis application"""

    def __init__(self, auth_manager):
        self.auth_manager = auth_manager
        self.data = {}
        self.unique_vals = []
        self.filtered_data = None
        self.omitted_data = None
        self.filter_parameters = []
        # Store export data
        self.export_jvc_data = None
        self.export_curves_data = None

    def load_offline(self, fixture_path) -> bool:
        """Load from a local fixture JSON file (offline / demo mode)."""
        import json

        with open(fixture_path) as f:
            fx = json.load(f)
        sample_ids = fx.get("sample_ids", list(fx["measurements"].keys()))
        all_jvs = {
            sid: [(entry[0], entry[1]) for entry in entries]
            for sid, entries in fx["measurements"].items()
        }
        df_jvc, df_cur = self._build_from_raw(all_jvs, sample_ids)
        if df_jvc.empty:
            return False
        self.data["jvc"] = df_jvc
        self.data["curves"] = df_cur
        self.unique_vals = self._find_unique_values()
        self._export_data(df_jvc, df_cur)
        return True

    def load_batch_data(self, batch_ids, output_widget=None):
        """Load data from selected batch IDs"""
        self.data = {}

        if not self.auth_manager.is_authenticated():
            ErrorHandler.log_error("Authentication required", output_widget=output_widget)
            return False

        if not batch_ids:
            ErrorHandler.log_error(
                "Please select at least one batch to load", output_widget=output_widget
            )
            return False

        try:
            logger.info("Loading data for batch IDs: %s", batch_ids)
            if output_widget:
                with output_widget:
                    print("Loading Data")
                    print("Loading data for batch IDs: %s" % batch_ids)

            url = self.auth_manager.url
            token = self.auth_manager.current_token

            # Get sample IDs and descriptions
            sample_ids = get_ids_in_batch(url, token, batch_ids)
            identifiers = get_sample_description(url, token, sample_ids)

            df_jvc, df_cur = self._process_jv_data_for_analysis(
                sample_ids, output_widget, batch_ids
            )

            # Store data
            self.data["jvc"] = pd.concat(
                [self.data.get("jvc", pd.DataFrame()), df_jvc], ignore_index=True
            )
            self.data["curves"] = pd.concat(
                [self.data.get("curves", pd.DataFrame()), df_cur], ignore_index=True
            )

            # Verify data was loaded successfully before processing
            if self.data["jvc"].empty:
                logger.warning("No JV data was loaded successfully")
                if output_widget:
                    with output_widget:
                        print("Error: No JV data was loaded successfully")
                return False

            # Process sample information
            self._process_sample_info(identifiers)

            if output_widget:
                with output_widget:
                    if not self.data["jvc"].empty:
                        best_main = self.data["jvc"].loc[self.data["jvc"]["PCE(%)"].idxmax()]  # noqa: F841

            # Export data
            self._export_data(df_jvc, df_cur)

            # DIAGNOSTIC: Check data before and after processing
            if output_widget:
                with output_widget:
                    if not df_jvc.empty:
                        best_export = df_jvc.loc[df_jvc["PCE(%)"].idxmax()]  # noqa: F841

            # Find unique values
            self.unique_vals = self._find_unique_values()

            logger.info("Data loaded successfully for %s batches", len(batch_ids))
            if output_widget:
                with output_widget:
                    print("Data Loaded Successfully!")

            return True

        except Exception as e:
            ErrorHandler.handle_data_loading_error(e, output_widget)
            return False

    def _process_jv_data_for_analysis(self, sample_ids, output_widget=None, batch_ids=None):
        """Process JV data for analysis from sample IDs with enhanced error reporting"""
        columns_jvc = [
            "Voc(V)",
            "Jsc(mA/cm2)",
            "FF(%)",
            "PCE(%)",
            "V_mpp(V)",
            "J_mpp(mA/cm2)",
            "P_mpp(mW/cm2)",
            "R_series(Ohmcm2)",
            "R_shunt(Ohmcm2)",
            "sample",
            "batch",
            "condition",
            "cell",
            "direction",
            "ilum",
            "status",
            "sample_id",
        ]

        columns_cur = [
            "index",
            "sample",
            "batch",
            "condition",
            "variable",
            "cell",
            "direction",
            "ilum",
            "sample_id",
            "status",
        ]
        rows_jvc = []
        rows_cur = []

        # Track errors for reporting
        error_summary = {
            "failed_samples": [],
            "failed_batches": [],
            "successful_samples": 0,
            "total_samples": len(sample_ids),
        }

        try:
            url = self.auth_manager.url
            token = self.auth_manager.current_token

            logger.info("Fetching JV data for %d samples", len(sample_ids))
            if output_widget:
                with output_widget:
                    print("Fetching JV data...")
                    print("Total samples to process: %d" % len(sample_ids))

            all_jvs = {}
            successful_batches = []
            failed_batches = []

            for batch_id in batch_ids:
                try:
                    logger.debug("Processing batch: %s", batch_id)
                    if output_widget:
                        with output_widget:
                            print("\n📦 Processing batch: %s" % batch_id)

                    batch_sample_ids = get_ids_in_batch(url, token, [batch_id])

                    logger.debug("Found %d samples in batch %s", len(batch_sample_ids), batch_id)
                    if output_widget:
                        with output_widget:
                            print("   Found %d samples in this batch" % len(batch_sample_ids))

                    batch_jvs = get_all_JV(url, token, batch_sample_ids)

                    missing_jv = [s for s in batch_sample_ids if s not in batch_jvs]
                    if output_widget:
                        with output_widget:
                            print("   JV data: %d/%d samples found" % (len(batch_jvs), len(batch_sample_ids)))
                            if missing_jv:
                                print("   ⚠️ No HySprint_JVmeasurement in NOMAD for: %s" % missing_jv)
                                print("      → Check that JV files (.jv.txt) were uploaded for these samples")

                    all_jvs.update(batch_jvs)
                    successful_batches.append(batch_id)

                    logger.info("Batch %s loaded successfully", batch_id)
                    if output_widget:
                        with output_widget:
                            print("   ✅ Batch loaded successfully")

                except KeyError as e:
                    error_msg = "Missing field '%s'" % e.args[0]
                    failed_batches.append((batch_id, error_msg))
                    error_summary["failed_batches"].append(
                        {"batch_id": batch_id, "error": error_msg, "type": "KeyError"}
                    )
                    logger.warning("Skipping batch %s: %s", batch_id, error_msg)
                    if output_widget:
                        with output_widget:
                            print("   ⚠️ Skipping batch - %s" % error_msg)
                    continue
                except Exception as e:
                    error_msg = str(e)
                    failed_batches.append((batch_id, error_msg))
                    error_summary["failed_batches"].append(
                        {"batch_id": batch_id, "error": error_msg, "type": type(e).__name__}
                    )
                    logger.warning("Skipping batch %s: %s", batch_id, error_msg)
                    if output_widget:
                        with output_widget:
                            print("   ⚠️ Skipping batch - %s" % error_msg)
                    continue

            logger.info(
                "Batch summary: %d successful, %d failed",
                len(successful_batches),
                len(failed_batches),
            )
            if output_widget:
                with output_widget:
                    print("\n" + "=" * 60)
                    print("BATCH SUMMARY:")
                    print("✅ Successfully processed: %d batches" % len(successful_batches))
                    if failed_batches:
                        print("⚠️ Failed: %d batches" % len(failed_batches))
                        for batch_id, error in failed_batches:
                            print("   - %s: %s" % (batch_id, error))
                    print("=" * 60 + "\n")

            # Continue with the successfully loaded data
            if not all_jvs:
                logger.error("No valid JV data could be loaded from any batch")
                if output_widget:
                    with output_widget:
                        print("❌ No valid JV data could be loaded from any batch")
                        print("\nERROR DETAILS:")
                        for batch_error in error_summary["failed_batches"]:
                            print("  Batch: %s" % batch_error["batch_id"])
                            print("  Error Type: %s" % batch_error["type"])
                            print("  Error Message: %s\n" % batch_error["error"])
                return pd.DataFrame(), pd.DataFrame()

            # First pass: determine maximum number of data points across all curves
            max_data_points = 0

            # Process each sample with detailed error handling
            for sample_idx, sid in enumerate(sample_ids, 1):
                try:
                    jv_res = all_jvs.get(sid, [])

                    if not jv_res:
                        logger.debug("No JV data returned for sample %s", sid)
                        if output_widget:
                            with output_widget:
                                print(
                                    "⚠️ [%d/%d] %s: No JV data returned"
                                    % (sample_idx, len(sample_ids), sid)
                                )
                        error_summary["failed_samples"].append(
                            {
                                "sample_id": sid,
                                "error": "No JV data returned from API",
                                "type": "EmptyData",
                            }
                        )
                        continue

                    # Process this sample
                    sample_curves_processed = 0

                    for jv_data, jv_md in jv_res:
                        try:
                            # Check if jv_curve exists
                            if "jv_curve" not in jv_data:
                                logger.warning(
                                    "Missing 'jv_curve' field for sample %s, available keys: %s",
                                    sid,
                                    list(jv_data.keys()),
                                )
                                if output_widget:
                                    with output_widget:
                                        print(
                                            "⚠️ [%d/%d] %s: Missing 'jv_curve' field"
                                            % (sample_idx, len(sample_ids), sid)
                                        )
                                        print("   Available keys: %s" % list(jv_data.keys()))
                                error_summary["failed_samples"].append(
                                    {
                                        "sample_id": sid,
                                        "error": "Missing 'jv_curve' field. Available: %s"
                                        % list(jv_data.keys()),
                                        "type": "MissingField",
                                    }
                                )
                                continue

                            # Check for empty jv_curve list
                            if not jv_data["jv_curve"]:
                                data_file = jv_data.get("data_file", "unknown")
                                if output_widget:
                                    with output_widget:
                                        print(
                                            "⚠️ [%d/%d] %s: Empty JV file (no curves): %s"
                                            % (sample_idx, len(sample_ids), sid, data_file)
                                        )
                                error_summary["failed_samples"].append(
                                    {
                                        "sample_id": sid,
                                        "error": "Empty jv_curve list (file: %s)" % data_file,
                                        "type": "EmptyJVFile",
                                    }
                                )
                                continue

                            # Count curves for this sample
                            for c in jv_data["jv_curve"]:
                                max_data_points = max(
                                    max_data_points,
                                    len(c.get("voltage", [])),
                                    len(c.get("current_density", [])),
                                )
                                sample_curves_processed += 1

                        except Exception as e:
                            logger.warning(
                                "Error processing jv_data for sample %s: %s: %s",
                                sid,
                                type(e).__name__,
                                e,
                            )
                            if output_widget:
                                with output_widget:
                                    print(
                                        "⚠️ [%d/%d] %s: Error in jv_data processing"
                                        % (sample_idx, len(sample_ids), sid)
                                    )
                                    print("   Error: %s: %s" % (type(e).__name__, str(e)))
                            error_summary["failed_samples"].append(
                                {
                                    "sample_id": sid,
                                    "error": "%s: %s" % (type(e).__name__, str(e)),
                                    "type": "ProcessingError",
                                }
                            )
                            continue

                    if sample_curves_processed > 0:
                        error_summary["successful_samples"] += 1
                        logger.debug("Sample %s: %d curves processed", sid, sample_curves_processed)
                        if output_widget:
                            with output_widget:
                                print(
                                    "✅ [%d/%d] %s: %d curves processed"
                                    % (sample_idx, len(sample_ids), sid, sample_curves_processed)
                                )

                except Exception as e:
                    logger.error(
                        "Fatal error processing sample %s: %s: %s", sid, type(e).__name__, e
                    )
                    if output_widget:
                        with output_widget:
                            print("❌ [%d/%d] %s: Fatal error" % (sample_idx, len(sample_ids), sid))
                            print("   Error: %s: %s" % (type(e).__name__, str(e)))
                    error_summary["failed_samples"].append(
                        {
                            "sample_id": sid,
                            "error": "%s: %s" % (type(e).__name__, str(e)),
                            "type": "FatalError",
                        }
                    )
                    continue

            # Add data point columns to columns_cur
            for i in range(max_data_points):
                columns_cur.append(i)

            # Second pass: process the data with correct column structure and detailed error handling  # noqa: E501
            logger.debug("Processing curves data for %d samples", len(sample_ids))
            if output_widget:
                with output_widget:
                    print("\n" + "=" * 60)
                    print("PROCESSING CURVES DATA...")
                    print("=" * 60 + "\n")

            for sample_idx, sid in enumerate(sample_ids, 1):
                jv_res = all_jvs.get(sid, [])
                if not jv_res:
                    continue

                for jv_data, jv_md in jv_res:
                    try:
                        if "jv_curve" not in jv_data or not jv_data["jv_curve"]:
                            continue

                        status = extract_status_from_metadata(jv_data, jv_md)

                        for c in jv_data["jv_curve"]:
                            file_name = "../%s/%s" % (jv_md["upload_id"], jv_data.get("data_file", ""))
                            illum = "Dark" if "dark" in c["cell_name"].lower() else "Light"
                            cell = c["cell_name"][0]
                            direction = "Forward" if "for" in c["cell_name"].lower() else "Reverse"

                            # Extract the sample name
                            sample_clean = file_name.split("/")[-1].split(".")[0]

                            # JV data processing with Pydantic validation
                            try:
                                validated_row = JVRow(
                                    voc=c["open_circuit_voltage"],
                                    jsc=-c["short_circuit_current_density"],
                                    ff=100 * c["fill_factor"],
                                    pce=c["efficiency"],
                                    v_mpp=c["potential_at_maximum_power_point"],
                                    j_mpp=-c["current_density_at_maximun_power_point"],
                                    p_mpp=-c["potential_at_maximum_power_point"]
                                    * c["current_density_at_maximun_power_point"],
                                    r_series=c.get("series_resistance"),
                                    r_shunt=c.get("shunt_resistance"),
                                    sample=sample_clean,
                                    batch=file_name.split("/")[1],
                                    condition="w",
                                    cell=cell,
                                    direction=direction,
                                    ilum=illum,
                                    status=status,
                                    sample_id=sid,
                                )
                                row = list(validated_row.model_dump().values())
                            except ValidationError as exc:
                                logger.warning(
                                    "Skipping invalid JV row for sample %s: %s", sid, exc
                                )
                                continue
                            rows_jvc.append(row)

                            # Process voltage data with proper padding
                            row_v = [
                                "_".join(["Voltage (V)", cell, direction, illum]),
                                sample_clean,
                                file_name.split("/")[1],
                                "w",
                                "Voltage (V)",
                                cell,
                                direction,
                                illum,
                                sid,
                                status,
                            ]
                            voltage_data = c["voltage"] + [None] * (
                                max_data_points - len(c["voltage"])
                            )
                            row_v.extend(voltage_data)

                            # Process current density data with proper padding
                            row_j = [
                                "_".join(["Current Density(mA/cm2)", cell, direction, illum]),
                                sample_clean,
                                file_name.split("/")[1],
                                "w",
                                "Current Density(mA/cm2)",
                                cell,
                                direction,
                                illum,
                                sid,
                                status,
                            ]
                            current_data = c["current_density"] + [None] * (
                                max_data_points - len(c["current_density"])
                            )
                            row_j.extend(current_data)

                            rows_cur.append(row_v)
                            rows_cur.append(row_j)

                    except Exception:
                        # Already logged in first pass
                        continue

            # Create DataFrames
            df_jvc = pd.DataFrame(rows_jvc, columns=columns_jvc)
            df_cur = pd.DataFrame(rows_cur, columns=columns_cur)

            # Calculate Voc x FF if both columns exist
            if "Voc(V)" in df_jvc.columns and "FF(%)" in df_jvc.columns:
                df_jvc["Voc x FF(V%)"] = df_jvc["Voc(V)"] * df_jvc["FF(%)"]

            # Print final summary
            logger.info(
                "Final: %d/%d samples processed, %d JV records, %d curve records",
                error_summary["successful_samples"],
                error_summary["total_samples"],
                len(rows_jvc),
                len(rows_cur),
            )
            if output_widget:
                with output_widget:
                    print("\n" + "=" * 60)
                    print("FINAL SUMMARY:")
                    print(
                        "✅ Successfully processed samples: %d/%d"
                        % (error_summary["successful_samples"], error_summary["total_samples"])
                    )
                    print("✅ Total JV records created: %d" % len(rows_jvc))
                    print("✅ Total curve records created: %d" % len(rows_cur))

                    if error_summary["failed_samples"]:
                        print("\n⚠️ Failed samples: %d" % len(error_summary["failed_samples"]))
                        print("\nDETAILED ERROR LIST:")
                        for idx, error in enumerate(error_summary["failed_samples"], 1):
                            print("\n  [%d] Sample ID: %s" % (idx, error["sample_id"]))
                            print("      Error Type: %s" % error["type"])
                            print("      Error: %s" % error["error"])

                    print("=" * 60)

            return df_jvc, df_cur

        except Exception as e:
            logger.exception(
                "Fatal error in _process_jv_data_for_analysis: %s: %s",
                type(e).__name__,
                e,
            )
            if output_widget:
                with output_widget:
                    print("\n❌ FATAL ERROR in _process_jv_data_for_analysis:")
                    print("   Error Type: %s" % type(e).__name__)
                    print("   Error Message: %s" % str(e))
            ErrorHandler.handle_data_loading_error(e, output_widget)
            return pd.DataFrame(), pd.DataFrame()

    def _build_from_raw(self, all_jvs: dict, sample_ids: list) -> tuple:
        """Core transformation: all_jvs dict -> (df_jvc, df_cur). No API calls."""
        columns_jvc = [
            "Voc(V)", "Jsc(mA/cm2)", "FF(%)", "PCE(%)", "V_mpp(V)",
            "J_mpp(mA/cm2)", "P_mpp(mW/cm2)", "R_series(Ohmcm2)",
            "R_shunt(Ohmcm2)", "sample", "batch", "condition", "cell",
            "direction", "ilum", "status", "sample_id",
        ]
        columns_cur = [
            "index", "sample", "batch", "condition", "variable",
            "cell", "direction", "ilum", "sample_id", "status",
        ]

        max_data_points = 0
        for sid in sample_ids:
            for jv_data, _jv_md in all_jvs.get(sid, []):
                for c in jv_data.get("jv_curve", []):
                    max_data_points = max(
                        max_data_points,
                        len(c.get("voltage", [])),
                        len(c.get("current_density", [])),
                    )

        for i in range(max_data_points):
            columns_cur.append(i)

        rows_jvc, rows_cur = [], []
        for sid in sample_ids:
            for jv_data, jv_md in all_jvs.get(sid, []):
                if "jv_curve" not in jv_data or not jv_data["jv_curve"]:
                    continue
                status = extract_status_from_metadata(jv_data, jv_md)
                for c in jv_data["jv_curve"]:
                    file_name = "../%s/%s" % (jv_md.get("upload_id", ""), jv_data.get("data_file", ""))
                    illum = "Dark" if "dark" in c["cell_name"].lower() else "Light"
                    cell = c["cell_name"][0]
                    direction = "Forward" if "for" in c["cell_name"].lower() else "Reverse"
                    sample_clean = file_name.split("/")[-1].split(".")[0]
                    try:
                        validated_row = JVRow(
                            voc=c["open_circuit_voltage"],
                            jsc=-c["short_circuit_current_density"],
                            ff=100 * c["fill_factor"],
                            pce=c["efficiency"],
                            v_mpp=c["potential_at_maximum_power_point"],
                            j_mpp=-c["current_density_at_maximun_power_point"],
                            p_mpp=-c["potential_at_maximum_power_point"]
                            * c["current_density_at_maximun_power_point"],
                            r_series=c.get("series_resistance"),
                            r_shunt=c.get("shunt_resistance"),
                            sample=sample_clean,
                            batch=file_name.split("/")[1] if "/" in file_name else "",
                            condition="w",
                            cell=cell,
                            direction=direction,
                            ilum=illum,
                            status=status,
                            sample_id=sid,
                        )
                        rows_jvc.append(list(validated_row.model_dump().values()))
                    except ValidationError as exc:
                        logger.warning("Skipping invalid JV row for sample %s: %s", sid, exc)
                        continue

                    row_v = ["_".join(["Voltage (V)", cell, direction, illum]),
                             sample_clean, file_name.split("/")[1] if "/" in file_name else "",
                             "w", "Voltage (V)", cell, direction, illum, sid, status]
                    row_v.extend(c["voltage"] + [None] * (max_data_points - len(c["voltage"])))
                    row_j = ["_".join(["Current Density(mA/cm2)", cell, direction, illum]),
                             sample_clean, file_name.split("/")[1] if "/" in file_name else "",
                             "w", "Current Density(mA/cm2)", cell, direction, illum, sid, status]
                    row_j.extend(c["current_density"] + [None] * (max_data_points - len(c["current_density"])))
                    rows_cur.append(row_v)
                    rows_cur.append(row_j)

        df_jvc = pd.DataFrame(rows_jvc, columns=columns_jvc)
        df_cur = pd.DataFrame(rows_cur, columns=columns_cur)
        if "Voc(V)" in df_jvc.columns and "FF(%)" in df_jvc.columns:
            df_jvc["Voc x FF(V%)"] = df_jvc["Voc(V)"] * df_jvc["FF(%)"]
        return df_jvc, df_cur

    def _create_matching_curves_from_filtered_jv(self, filtered_jv_df):
        """Create curves data that exactly matches filtered JV data using sample_id"""
        if not hasattr(self, "data") or "curves" not in self.data or filtered_jv_df.empty:
            return pd.DataFrame()

        # Get unique sample_id + cell + direction + ilum combinations from filtered JV
        filtered_combinations = set()
        for _, row in filtered_jv_df.iterrows():
            combination = (row["sample_id"], row["cell"], row["direction"], row["ilum"])
            filtered_combinations.add(combination)

        # Filter curves data to match exactly
        def should_include_curve(curve_row):
            if "sample_id" not in curve_row:
                return False
            combination = (
                curve_row["sample_id"],
                curve_row["cell"],
                curve_row["direction"],
                curve_row["ilum"],
            )
            return combination in filtered_combinations

        curves_data = self.data["curves"]
        matching_curves = curves_data[curves_data.apply(should_include_curve, axis=1)].copy()

        return matching_curves

    def _process_sample_info(self, identifiers):
        """Process sample information and create identifiers with enhanced deduplication"""
        if "jvc" not in self.data or self.data["jvc"].empty:
            logger.warning("No JV data available for processing sample info")
            return

        if "sample" not in self.data["jvc"].columns:
            logger.warning(
                "'sample' column missing from JV data; available: %s",
                list(self.data["jvc"].columns),
            )
            return

        # Store original sample paths before cleaning - but now sample is already clean
        self.data["jvc"]["original_sample"] = self.data["jvc"]["sample"].copy()

        # Extract subbatch using rsplit to get the second-to-last part
        self.data["jvc"]["subbatch"] = self.data["jvc"]["sample"].apply(
            lambda x: x.split("_")[-2] if len(x.split("_")) >= 2 else x
        )

        # Extract human-readable batch name for display using original paths
        def extract_display_batch(sample_path):
            filename = sample_path.split("/")[-1].split(".")[0]

            # Use rsplit to remove the last 2 parts, regardless of how many underscores are in the name  # noqa: E501
            if "_" in filename:
                # Split from the right and keep everything except the last 2 parts
                parts = filename.rsplit("_", 2)  # Split into max 3 parts from the right
                result = parts[0]  # Take everything before the last 2 underscores
            else:
                result = filename

            return result

        # Keep the original batch ID from the file path for actual grouping
        self.data["jvc"]["batch"] = self.data["jvc"]["sample"].apply(
            lambda x: x.split("/")[1] if "/" in x else "unknown"
        )

        # Add display batch name for UI purposes using original paths
        self.data["jvc"]["display_batch"] = self.data["jvc"]["original_sample"].apply(
            extract_display_batch
        )

        self.data["jvc"]["identifier"] = self.data["jvc"]["sample"].apply(
            lambda x: x.split("/")[-1].split(".")[0]
        )

        if identifiers:
            self.data["jvc"]["identifier"] = self.data["jvc"]["identifier"].apply(
                lambda x: (
                    f"{'_'.join(x.split('_')[:-1])}&{identifiers.get(x, 'No variation specified')}"
                )
            )
        else:
            self.data["jvc"]["identifier"] = self.data["jvc"]["sample"].apply(
                lambda x: "_".join(x.split("/")[-1].split(".")[0].split("_")[:-1])
            )

    def _export_data(self, df_jvc, df_cur):
        """Store data for potential export"""
        self.export_jvc_data = df_jvc
        self.export_curves_data = df_cur

    def _find_unique_values(self):
        """Find unique values in the dataset"""
        try:
            unique_values = self.data["jvc"]["identifier"].unique()
        except:  # noqa: E722
            unique_values = self.data["jvc"]["sample"].unique()

        return unique_values

    def apply_conditions(self, conditions_dict):
        """Apply conditions mapping to the data"""
        if "jvc" in self.data:
            # Apply the mapping
            self.data["jvc"]["condition"] = self.data["jvc"]["identifier"].map(conditions_dict)

            # Fill any NaN values with a default
            nan_conditions = self.data["jvc"]["condition"].isna().sum()
            if nan_conditions > 0:
                self.data["jvc"]["condition"] = self.data["jvc"]["condition"].fillna("Unknown")

            # Verify that each sample_cell has only one condition
            condition_check = self.data["jvc"].groupby(["sample", "cell"])["condition"].nunique()
            multiple_conditions = condition_check[condition_check > 1]

            if len(multiple_conditions) > 0:
                return False

            return True
        return False

    def apply_filters(
        self, filter_list, direction_filter="Both", selected_items=None, verbose=True
    ):
        """Apply filters to the dataframe with improved two-step process"""
        if not self.data or "jvc" not in self.data:
            return None, None, []

        # Default filters if none provided
        if not filter_list:
            filter_list = [
                ("PCE(%)", "<", "40"),
                ("FF(%)", "<", "89"),
                ("FF(%)", ">", "24"),
                ("Voc(V)", "<", "2"),
                ("Jsc(mA/cm2)", ">", "-30"),
            ]

        # Operator mapping
        operat = {
            "<": operator.lt,
            ">": operator.gt,
            "==": operator.eq,
            "<=": operator.le,
            ">=": operator.ge,
            "!=": operator.ne,
        }

        data = self.data["jvc"].copy()

        # Initialize filter reason column
        data["filter_reason"] = ""
        filtering_options = []

        # Apply sample/cell selection filter if provided
        sample_selection_filtered_count = 0
        if selected_items:
            original_count = len(data)  # noqa: F841

            def is_selected(row):
                cell_key = f"{row['sample']}_{row['cell']}"
                return cell_key in selected_items

            selection_mask = data.apply(is_selected, axis=1)
            data.loc[~selection_mask, "filter_reason"] += "sample/cell not selected, "

            sample_selection_filtered_count = len(data[~selection_mask])
            filtering_options.append(
                f"sample/cell selection ({sample_selection_filtered_count} filtered)"
            )

        # Apply numeric filters
        for col, op, val in filter_list:
            try:
                mask = operat[op](data[col], float(val))
                before_count = len(data[data["filter_reason"] == ""])
                data.loc[~mask, "filter_reason"] += f"{col} {op} {val}, "
                after_count = len(data[data["filter_reason"] == ""])
                filtered_by_this_condition = before_count - after_count

                if filtered_by_this_condition > 0:
                    filtering_options.append(
                        f"{col} {op} {val} ({filtered_by_this_condition} filtered)"
                    )

            except (ValueError, KeyError) as e:
                if verbose:
                    logger.warning("Could not apply filter %s %s %s: %s", col, op, val, e)

        # Apply direction filter
        if direction_filter != "Both" and "direction" in data.columns:
            before_count = len(data[data["filter_reason"] == ""])
            direction_mask = data["direction"] != direction_filter
            data.loc[direction_mask, "filter_reason"] += f"direction != {direction_filter}, "
            after_count = len(data[data["filter_reason"] == ""])
            direction_filtered_count = before_count - after_count

            if direction_filtered_count > 0:
                filtering_options.append(
                    f"direction == {direction_filter} ({direction_filtered_count} filtered)"
                )

        # Separate filtered and omitted data
        omitted = data[data["filter_reason"] != ""].copy()
        filtered = data[data["filter_reason"] == ""].copy()

        # Clean up filter reason string
        omitted["filter_reason"] = omitted["filter_reason"].str.rstrip(", ")

        if "display_batch" in filtered.columns:
            filtered["batch_for_plotting"] = filtered["display_batch"]
        else:
            filtered["batch_for_plotting"] = filtered["batch"]

        if "display_batch" in omitted.columns:
            omitted["batch_for_plotting"] = omitted["display_batch"]
        else:
            omitted["batch_for_plotting"] = omitted["batch"]

        # Store results
        self.filtered_data = filtered
        self.omitted_data = omitted
        self.filter_parameters = filtering_options

        # Update main data dict
        self.data["filtered"] = filtered
        self.data["junk"] = omitted

        # CREATE MATCHING CURVES DATA - ADD THIS BLOCK:
        if not filtered.empty and "sample_id" in filtered.columns:
            # Create curves data that exactly matches filtered JV data
            matching_curves = self._create_matching_curves_from_filtered_jv(filtered)
            self.data["filtered_curves"] = matching_curves

            if verbose:
                logger.debug(
                    "Created %d matching curve records for filtered data", len(matching_curves)
                )
        else:
            self.data["filtered_curves"] = pd.DataFrame()

        return filtered, omitted, filtering_options

    def generate_summary_statistics(self, df=None):
        """Generate comprehensive summary statistics"""
        if df is None:
            df = self.data.get("jvc", pd.DataFrame())

        if df.empty:
            return "No data available for summary."

        try:
            # Basic statistics
            global_mean_PCE = df["PCE(%)"].mean()
            global_std_PCE = df["PCE(%)"].std()
            max_PCE_row = df.loc[df["PCE(%)"].idxmax()]

            # Group statistics by sample and batch
            mean_std_PCE_per_sample = df.groupby(["batch", "sample"])["PCE(%)"].agg(["mean", "std"])
            highest_mean_PCE_sample = mean_std_PCE_per_sample.idxmax()["mean"]
            lowest_mean_PCE_sample = mean_std_PCE_per_sample.idxmin()["mean"]

            # Highest PCE per sample (including batch info)
            if "display_batch" in df.columns:
                highest_PCE_per_sample = df.loc[
                    df.groupby(["sample"])["PCE(%)"].idxmax(),
                    ["batch", "sample", "cell", "PCE(%)", "display_batch"],
                ]
                highest_PCE_per_sample = highest_PCE_per_sample.copy()
                highest_PCE_per_sample["display_name"] = highest_PCE_per_sample[
                    "sample"
                ]  # Use consistent sample naming
                max_PCE_display_name = max_PCE_row["sample"]  # Use consistent naming
            else:
                highest_PCE_per_sample = df.loc[
                    df.groupby(["sample"])["PCE(%)"].idxmax(), ["batch", "sample", "cell", "PCE(%)"]
                ]
                highest_PCE_per_sample = highest_PCE_per_sample.copy()
                highest_PCE_per_sample["display_name"] = (
                    highest_PCE_per_sample["batch"] + "_" + highest_PCE_per_sample["sample"]
                )
                max_PCE_display_name = max_PCE_row.get("batch", "") + "_" + max_PCE_row["sample"]

            # Create detailed markdown table
            markdown_output = f"""
### Summary Statistics

**Global mean PCE(%)**: {global_mean_PCE:.2f} ± {global_std_PCE:.2f}%
**Total measurements**: {len(df)}

#### Best and Worst Samples by Average PCE

| | Sample | Mean PCE(%) | Std PCE(%) |
|---|--------|-------------|------------|
| Best sample | {highest_mean_PCE_sample[1]} | {mean_std_PCE_per_sample.loc[highest_mean_PCE_sample, "mean"]:.2f}% | {mean_std_PCE_per_sample.loc[highest_mean_PCE_sample, "std"]:.2f}% |
| Worst sample | {lowest_mean_PCE_sample[1]} | {mean_std_PCE_per_sample.loc[lowest_mean_PCE_sample, "mean"]:.2f}% | {mean_std_PCE_per_sample.loc[lowest_mean_PCE_sample, "std"]:.2f}% |

#### Top Performing Samples

| Sample | Cell | PCE(%) |
|--------|------|--------|
| **{max_PCE_display_name}** | **{max_PCE_row["cell"]}** | **{max_PCE_row["PCE(%)"]:.2f}%** |
"""

            # Add all samples (sorted by PCE descending)
            all_top_samples = highest_PCE_per_sample.sort_values("PCE(%)", ascending=False)
            for _, row in all_top_samples.iterrows():
                if row["sample"] != max_PCE_row["sample"] or row["batch"] != max_PCE_row["batch"]:
                    display_name = row.get(
                        "display_name", f"{row.get('batch', '')}_{row['sample']}"
                    )
                    markdown_output += (
                        f"| {display_name} | {row['cell']} | {row['PCE(%)']:.2f}% |\n"
                    )

            # Add scan direction comparison if available
            if "direction" in df.columns:
                forward_pce = df[df["direction"] == "Forward"]["PCE(%)"].mean()
                reverse_pce = df[df["direction"] == "Reverse"]["PCE(%)"].mean()

                markdown_output += f"""

#### Performance by Scan Direction

| Direction | Average PCE(%) | Count |
|-----------|----------------|-------|
| Forward | {forward_pce:.2f}% | {len(df[df["direction"] == "Forward"])} |
| Reverse | {reverse_pce:.2f}% | {len(df[df["direction"] == "Reverse"])} |
"""

            # Add distribution statistics
            markdown_output += f"""

#### Distribution Statistics

| Metric | Value |
|--------|-------|
| Median PCE | {df["PCE(%)"].median():.2f}% |
| Min PCE | {df["PCE(%)"].min():.2f}% |
| Max PCE | {df["PCE(%)"].max():.2f}% |
| 25th Percentile | {df["PCE(%)"].quantile(0.25):.2f}% |
| 75th Percentile | {df["PCE(%)"].quantile(0.75):.2f}% |
"""

            return markdown_output

        except Exception as e:
            return f"""
### Summary Statistics

**Error generating detailed statistics**: {str(e)}

**Basic Info**:
- Total measurements: {len(df)}
- Best Overall PCE: {df["PCE(%)"].max():.2f}% (Sample: {df.loc[df["PCE(%)"].idxmax(), "sample"]})
- Average PCE: {df["PCE(%)"].mean():.2f}%
"""

    # Getter methods
    def get_data(self):
        """Get the loaded data"""
        return self.data

    def get_unique_values(self):
        """Get unique values"""
        return self.unique_vals

    def get_filtered_data(self):
        """Get filtered data"""
        return self.filtered_data

    def get_omitted_data(self):
        """Get omitted data"""
        return self.omitted_data

    def get_filter_parameters(self):
        """Get filter parameters"""
        return self.filter_parameters

    def has_data(self):
        """Check if data is loaded"""
        return bool(self.data and "jvc" in self.data and not self.data["jvc"].empty)

    def get_export_data(self):
        """Get the export data for CSV download"""
        return self.export_jvc_data, self.export_curves_data

    def has_export_data(self):
        """Check if export data is available"""
        return self.export_jvc_data is not None and self.export_curves_data is not None
