"""
Data management functions for MPPT Analysis App
"""

import json
import logging
import warnings
from datetime import datetime

import numpy as np
import pandas as pd
import requests
from pydantic import BaseModel, ValidationError, field_validator

from hysprint_utils.api_calls import (
    get_all_mppt,
    get_batch_ids,
    get_ids_in_batch,
    get_sample_description,
)
from hysprint_utils.config import ENTRY_TYPES

logger = logging.getLogger(__name__)

# StabilityFiguresOfMerit field name -> fitting_tools.py model column names that
# feed it. Column names aren't consistent across models (T80 vs t80, tS vs Ts...),
# so write-back has to alias-match rather than assume one spelling.
_ISOS_METRIC_ALIASES = {
    "T95": ["T95", "t95"],
    "T80": ["T80", "t80"],
    "Ts95": ["Ts95", "ts95"],
    "Ts80": ["Ts80", "ts80"],
    "initial_stabilization_time": ["tS", "ts"],
}
_ISOS_ALIAS_COLUMNS = {alias for aliases in _ISOS_METRIC_ALIASES.values() for alias in aliases}
# model.columns entries that go to their own dedicated schema field, not the
# generic fit_parameters bag: the ISOS metrics above, plus R2 -> fit_r_squared
# and LEY -> lifetime_energy_yield.
_DEDICATED_FIELD_COLUMNS = _ISOS_ALIAS_COLUMNS | {"R2", "LEY"}

# Everything else in a model's columns (its actual free parameters, e.g. A,
# tau, beta, slope, intercept, PCE0, k, t0, b, ...) goes into fit_parameters -
# a generic {name, value, unit, error} bag, since the parameter set genuinely
# varies per model. (value, unit, factor): factor converts the app's internal
# value (hours for time, mW/cm^2 for power-density-like amplitudes) into the
# unit written to NOMAD - times 3600 for hours->seconds, matching every other
# time-based field this app writes. Derived by dimensional analysis of each
# model's own equation in this file's docstrings/comments - not guessed.
# Same parameter *name* can mean different things in different models (e.g.
# "k" is 1/time in Logistic+Exp but power-density/time in ERFC+Linear), so
# this is keyed by model.abbreviated_name, not by parameter name alone.
_LEFTOVER_PARAM_UNITS = {
    "Stretched Exp": {
        "A": ("mW/cm^2", 1.0),
        "tau": ("s", 3600.0),
        "beta": ("", 1.0),
    },
    "Linear": {
        "slope": ("mW/cm^2/s", 1.0 / 3600.0),
        "intercept": ("mW/cm^2", 1.0),
    },
    "Exponential": {
        "amplitude": ("mW/cm^2", 1.0),
        "decay": ("s", 3600.0),
    },
    "Biexponential": {
        "A1": ("mW/cm^2", 1.0),
        "tau1": ("s", 3600.0),
        "A2": ("mW/cm^2", 1.0),
        "tau2": ("s", 3600.0),
    },
    "Logistic+Exp": {
        "A": ("mW/cm^2", 1.0),
        "tau": ("s", 3600.0),
        "L": ("mW/cm^2", 1.0),
        "k": ("1/s", 1.0 / 3600.0),
        "x0": ("s", 3600.0),
    },
    "ERFC+Linear": {
        "PCE0": ("mW/cm^2", 1.0),
        "k": ("mW/cm^2/s", 1.0 / 3600.0),
        "t0": ("s", 3600.0),
        "b": ("s", 3600.0),
        "T80_linear": ("s", 3600.0),
    },
}

RESAMPLE_POINTS = 200  # fitted_time/fitted_power_density point cap agreed with nomad-baseclasses


class MPPTRow(BaseModel):
    time: float
    power_density: float
    voltage: float
    current_density: float

    @field_validator("time", "power_density", "voltage", "current_density", mode="before")
    @classmethod
    def coerce_numeric(cls, v):
        if v is None:
            return float("nan")
        return float(v)


def fit_curve(t_data, y_data, model, frame_range=None):
    """Slice to frame_range (point indices), fit with model, return a result
    dict or None if there aren't enough valid points to fit at all.

    frame_range: (start, end) - end is the last index to include, or None for
    "to the end of the array". point_start/point_end in the result reflect
    the requested range (not shrunk by any NaN rows dropped internally), since
    that's what the user actually configured.

    Points strictly fewer than model.n_params already fail via the exception
    handler below (scipy's leastsq refuses to run when there are more free
    parameters than data points) and return None like any other fit failure.
    The boundary case - points exactly equal to model.n_params - is solvable
    (an exact, zero-residual fit through every point) but has zero degrees of
    freedom and is not statistically meaningful; that case succeeds but the
    result carries a "warning" string flagging it, for the caller to surface
    rather than silently present as a normal fit.
    """
    if frame_range is not None:
        start, end = frame_range
        t_sliced = t_data[start:] if end is None else t_data[start : end + 1]
        y_sliced = y_data[start:] if end is None else y_data[start : end + 1]
    else:
        start = 0
        end = len(t_data) - 1
        t_sliced, y_sliced = t_data, y_data

    resolved_end = end if end is not None else start + len(t_sliced) - 1

    valid_mask = ~(np.isnan(t_sliced) | np.isnan(y_sliced))
    t_sliced = t_sliced[valid_mask]
    y_sliced = y_sliced[valid_mask]

    if len(t_sliced) < 2:
        return None

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            fit_params, fitted_curve, lmfit_result = model.parfunc(y_sliced, t_sliced)
    except Exception:
        logger.warning("Fit failed for model %s", model.name, exc_info=True)
        return None

    params = {}
    for param_name, param_value in zip(model.columns, fit_params):
        if hasattr(param_value, "nominal_value"):
            params[param_name] = param_value.nominal_value
            params[f"{param_name}_error"] = param_value.std_dev
        else:
            params[param_name] = param_value

    result = {
        "time": t_sliced,
        "fitted_power": fitted_curve,
        "original_power": y_sliced,
        "point_start": start,
        "point_end": resolved_end,
        "params": params,
        # kept only to let write_fit_results_to_nomad evaluate the model at a
        # dense, evenly-spaced-in-time grid on demand (see _resample_fit_curve) -
        # not otherwise touched by the app itself.
        "lmfit_result": lmfit_result,
    }
    if len(t_sliced) <= model.n_params:
        result["warning"] = (
            f"Only {len(t_sliced)} point(s) for a {model.n_params}-parameter model "
            f"({model.abbreviated_name}) - the fit has no degrees of freedom and is "
            "not statistically meaningful."
        )
    return result


def _resample_fit_curve(lmfit_result, time_h):
    """Evaluate a fitted model at RESAMPLE_POINTS points evenly spaced in time
    (not a subsample of the original, possibly unevenly-sampled, data points),
    spanning exactly [time_h[0], time_h[-1]] so the curve's endpoints line up
    with fit_range_start/fit_range_end. Returns (time_seconds, power_density)
    numpy arrays, or (None, None) if there's no fit range to resample.

    Uses the model's own declared independent variable name (lmfit exposes it
    as model.independent_vars[0]) rather than hardcoding "t" or "x", since
    fitting_tools.py's models are a mix of both conventions.
    """
    if lmfit_result is None or len(time_h) == 0:
        return None, None
    resample_time_h = np.linspace(time_h[0], time_h[-1], RESAMPLE_POINTS)
    indep_var = lmfit_result.model.independent_vars[0]
    resample_power = lmfit_result.eval(params=lmfit_result.params, **{indep_var: resample_time_h})
    return resample_time_h * 3600, np.asarray(resample_power)


class DataManager:
    """Handles data loading, processing, and management operations"""

    @staticmethod
    def _rows_from_entry(raw_data) -> list[dict]:
        """Convert archive.data into a list of per-row dicts.

        NOMAD returns MPPT data in two shapes:
        - Parallel arrays: {"time": [...], "power_density": [...], ...}
        - Already a list of row dicts: [{"time": 0.0, ...}, ...]
        """
        if isinstance(raw_data, list):
            return raw_data
        time_val = raw_data.get("time")
        if isinstance(time_val, list):
            n = len(time_val)
            power = raw_data.get("power_density") or [None] * n
            voltage = raw_data.get("voltage") or [None] * n
            current = raw_data.get("current_density") or [None] * n
            return [
                {
                    "time": time_val[i],
                    "power_density": power[i],
                    "voltage": voltage[i],
                    "current_density": current[i],
                }
                for i in range(n)
            ]
        return [raw_data]

    def __init__(self, url, token):
        self.url = url
        self.token = token
        self.curves = None
        self.sample_ids = None
        self.entries = None
        self.properties = None

    def load_offline(self, fixture_path) -> bool:
        """Load from a local fixture JSON file (offline / demo mode)."""
        with open(fixture_path) as f:
            fx = json.load(f)
        raw = {
            sid: [(entry[0], entry[1]) for entry in entries]
            for sid, entries in fx["measurements"].items()
        }
        return self._build_from_raw(raw, fx["descriptions"])

    def _build_from_raw(self, raw: dict, descriptions: dict) -> bool:
        mppt_curves_list = []
        description_list = []
        existing_sample_ids = []

        for sample_id, entries in raw.items():
            entry_names_list = []
            entry_description_list = []
            entry_ids_list = []
            sample_curves_list = []

            for mppt_entry in entries:
                raw_data = mppt_entry[0]
                metadata = mppt_entry[1] if isinstance(mppt_entry[1], dict) else {}
                rows_list = self._rows_from_entry(raw_data)
                validated_rows = []
                for row in rows_list:
                    try:
                        v = MPPTRow(
                            time=row.get("time"),
                            power_density=row.get("power_density"),
                            voltage=row.get("voltage"),
                            current_density=row.get("current_density"),
                        )
                        validated_rows.append(v.model_dump())
                    except ValidationError as exc:
                        logger.warning(
                            "Skipping invalid MPPT row for sample %s: %s", sample_id, exc
                        )
                if validated_rows:
                    sample_curves_list.append(pd.DataFrame(validated_rows))
                meta = raw_data if isinstance(raw_data, dict) else {}
                entry_names_list.append(meta.get("name", ""))
                entry_description_list.append(meta.get("description", ""))
                entry_ids_list.append(metadata.get("entry_id"))

            if sample_curves_list:
                mppt_curves_list.append(
                    pd.concat(sample_curves_list, keys=np.arange(len(sample_curves_list)))
                )
                description_list.append(
                    pd.DataFrame(
                        {
                            "entry_names": entry_names_list,
                            "entry_description": entry_description_list,
                            "entry_id": entry_ids_list,
                        }
                    )
                )
                existing_sample_ids.append(sample_id)

        if not mppt_curves_list:
            return False

        sample_ids_series = pd.Series(existing_sample_ids)
        curves = pd.concat(mppt_curves_list, keys=sample_ids_series)
        curves.loc[:, "power_density"] *= -1
        curves.loc[:, "current_density"] *= -1
        curves.loc[:, "time"] *= 1 / 3600
        entries_df = pd.concat(description_list, keys=sample_ids_series)
        properties = pd.DataFrame(
            {
                "description": pd.Series(
                    {sid: descriptions.get(sid, "") for sid in existing_sample_ids}
                ),
                "name": pd.Series(dtype=str),
            }
        )

        self.curves = curves
        self.sample_ids = sample_ids_series
        self.entries = entries_df
        self.properties = properties
        return True

    def get_filtered_batch_ids(self):
        """Return all batch IDs, deduplicated."""
        batch_ids_list_tmp = list(get_batch_ids(self.url, self.token))
        batch_ids_list = []
        for b in batch_ids_list_tmp:
            if "_".join(b.split("_")[:-1]) in batch_ids_list_tmp:
                continue
            batch_ids_list.append(b)
        return batch_ids_list

    def get_mppt_batch_ids(self):
        """Return only batch IDs that contain MPPT data.

        Fast path: direct /entries/archive/query filtered by entry_type — 1 API call.
        Fallback: fetch all batch→sample maps, then query get_all_mppt in chunks of 50.
        """
        # --- Fast path: /entries/query → upload_ids → batch lab_ids (2 API calls) ---
        # get_all_batches_wth_data does the same but its step-1 uses /entries/archive/query
        # which returns empty or 500 for MPPT entries. /entries/query works correctly.
        try:
            query = {
                "owner": "visible",
                "query": {"entry_type": ENTRY_TYPES["mppt"]},
                "pagination": {"page_size": 10000},
            }
            resp = requests.post(
                f"{self.url}/entries/query",
                headers={"Authorization": f"Bearer {self.token}"},
                json=query,
            )
            resp.raise_for_status()
            entries = resp.json().get("data", [])
            logger.debug("get_mppt_batch_ids: %d MPPT entries found", len(entries))

            upload_ids = list({e["upload_id"] for e in entries if "upload_id" in e})
            logger.debug("get_mppt_batch_ids: %d unique uploads", len(upload_ids))

            if upload_ids:
                query2 = {
                    "required": {"data": "*"},
                    "owner": "visible",
                    "query": {"entry_type": ENTRY_TYPES["batch"], "upload_id:any": upload_ids},
                    "pagination": {"page_size": 10000},
                }
                resp2 = requests.post(
                    f"{self.url}/entries/archive/query",
                    headers={"Authorization": f"Bearer {self.token}"},
                    json=query2,
                )
                resp2.raise_for_status()
                batch_ids: set[str] = set()
                for entry in resp2.json().get("data", []):
                    lab_id = entry.get("archive", {}).get("data", {}).get("lab_id", "")
                    if lab_id:
                        batch_ids.add(lab_id)

                if batch_ids:
                    logger.debug("get_mppt_batch_ids: %d batches (fast path)", len(batch_ids))
                    return sorted(batch_ids)
                logger.debug("get_mppt_batch_ids: no batch entries in those uploads, falling back")
            else:
                logger.debug("get_mppt_batch_ids: no upload_ids, falling back")
        except Exception as exc:
            logger.debug("get_mppt_batch_ids: fast path failed (%s), falling back", exc)

        # --- Fallback: batch-entry map + chunked get_all_mppt ---
        logger.debug("get_mppt_batch_ids: using chunked fallback")
        query = {
            "required": {"data": "*"},
            "owner": "visible",
            "query": {"entry_type": ENTRY_TYPES["batch"]},
            "pagination": {"page_size": 10000},
        }
        resp = requests.post(
            f"{self.url}/entries/archive/query",
            headers={"Authorization": f"Bearer {self.token}"},
            json=query,
        )
        resp.raise_for_status()

        batch_to_samples: dict[str, list[str]] = {}
        for entry in resp.json().get("data", []):
            archive_data = entry.get("archive", {}).get("data", {})
            batch_id = archive_data.get("lab_id", "")
            entities = archive_data.get("entities", [])
            sample_ids = [e["lab_id"] for e in entities if "lab_id" in e]
            if batch_id and sample_ids:
                batch_to_samples[batch_id] = sample_ids

        if not batch_to_samples:
            return []

        sample_to_batch = {sid: bid for bid, sids in batch_to_samples.items() for sid in sids}
        all_sample_ids = list(sample_to_batch)
        chunk_size = 50
        batch_ids = set()
        for i in range(0, len(all_sample_ids), chunk_size):
            chunk = all_sample_ids[i : i + chunk_size]
            try:
                mppt_data = get_all_mppt(self.url, self.token, chunk)
                for sid in mppt_data:
                    if sid in sample_to_batch:
                        batch_ids.add(sample_to_batch[sid])
            except Exception as exc:
                logger.debug("get_mppt_batch_ids: chunk failed: %s", exc)
                continue

        return sorted(batch_ids)

    def get_mppt_data_working(self, try_sample_ids):
        """Take list of sample ids and return mppt data as data frames"""
        all_mppt = get_all_mppt(self.url, self.token, try_sample_ids)
        existing_sample_ids = pd.Series(all_mppt.keys())

        if len(existing_sample_ids) == 0:
            return None, None, None

        mppt_curves_list = []
        description_list = []
        for sample_data in all_mppt:
            entry_names_list = []
            entry_description_list = []
            entry_ids_list = []
            sample_curves_list = []
            for mppt_entry in all_mppt.get(sample_data):
                raw_data = mppt_entry[0]
                metadata = mppt_entry[1] if isinstance(mppt_entry[1], dict) else {}
                rows_list = self._rows_from_entry(raw_data)
                validated_rows = []
                for row in rows_list:
                    try:
                        v = MPPTRow(
                            time=row.get("time"),
                            power_density=row.get("power_density"),
                            voltage=row.get("voltage"),
                            current_density=row.get("current_density"),
                        )
                        validated_rows.append(v.model_dump())
                    except ValidationError as exc:
                        logger.warning(
                            "Skipping invalid MPPT row for sample %s: %s", sample_data, exc
                        )
                        continue
                if validated_rows:
                    sample_curves_list.append(pd.DataFrame(validated_rows))
                meta = raw_data if isinstance(raw_data, dict) else {}
                entry_names_list.append(meta.get("name", ""))
                entry_description_list.append(meta.get("description", ""))
                entry_ids_list.append(metadata.get("entry_id"))

            if sample_curves_list:
                mppt_curves_list.append(
                    pd.concat(sample_curves_list, keys=np.arange(len(sample_curves_list)))
                )  # noqa: E501
                description_list.append(
                    pd.DataFrame(
                        {
                            "entry_names": entry_names_list,
                            "entry_description": entry_description_list,
                            "entry_id": entry_ids_list,
                        }
                    )
                )  # noqa: E501

        if mppt_curves_list and description_list:
            return (
                pd.concat(mppt_curves_list, keys=existing_sample_ids),
                existing_sample_ids,
                pd.concat(description_list, keys=existing_sample_ids),
            )  # noqa: E501
        else:
            return None, None, None

    def load_data_from_batches(self, selected_batches):
        """Load MPPT data from selected batches"""
        try:
            try_sample_ids = get_ids_in_batch(self.url, self.token, selected_batches)
            mppt_result = self.get_mppt_data_working(try_sample_ids)

            if mppt_result is None or mppt_result[0] is None:
                return None, "The selected batches don't contain any MPPT measurements"

            curves, sample_ids, entries = mppt_result

            # Process the data
            curves.loc[:, "power_density"] *= -1
            curves.loc[:, "current_density"] *= -1
            curves.loc[:, "time"] *= 1 / 3600

            # Get sample descriptions
            identifiers = get_sample_description(self.url, self.token, list(sample_ids))
            properties = pd.DataFrame({"description": pd.Series(identifiers), "name": pd.Series()})

            return (curves, sample_ids, entries, properties), None

        except Exception as e:
            return None, f"Error loading data: {str(e)}"

    def get_curve_ids_for_sample(self, curves_data, sample_ids, sample_id):
        """Return the list of curve_ids available for one sample (empty if unknown)."""
        if sample_id not in list(sample_ids):
            return []
        try:
            sample_data = curves_data.loc[sample_id]
        except KeyError:
            return []
        if hasattr(sample_data.index, "nlevels") and sample_data.index.nlevels > 1:
            return list(sample_data.index.get_level_values(0).unique())
        return [0]

    def get_raw_curve(self, curves_data, sample_ids, sample_id, curve_id):
        """Return (time, power_density) numpy arrays for one (sample_id, curve_id)."""
        if sample_id not in list(sample_ids):
            return None, None
        try:
            sample_data = curves_data.loc[sample_id]
            if hasattr(sample_data.index, "nlevels") and sample_data.index.nlevels > 1:
                curve_data = sample_data.loc[curve_id]
            else:
                curve_data = sample_data
            return curve_data["time"].values, curve_data["power_density"].values
        except (KeyError, IndexError):
            return None, None

    def get_entry_id(self, entries_data, sample_id, curve_id):
        """Look up the NOMAD entry_id backing one (sample_id, curve_id), or None.

        None for offline/demo data (no live entry) or if the metadata was
        never populated with an entry_id.
        """
        if entries_data is None:
            return None
        try:
            value = entries_data.loc[(sample_id, curve_id), "entry_id"]
        except (KeyError, IndexError):
            return None
        return value if isinstance(value, str) and value else None

    def fit_sample(self, curves_data, sample_ids, sample_id, model, frame_range=None):
        """Fit every curve belonging to one sample with the given model/point range.

        Returns {curve_id: fit_dict}. A curve is omitted if it has too few
        points in range or the fit raises. fit_dict keys: time, fitted_power,
        original_power, point_start, point_end, model, params.
        """
        warnings.filterwarnings(
            "ignore", message="Using UFloat objects with std_dev==0 may give unexpected results."
        )

        results = {}
        for curve_id in self.get_curve_ids_for_sample(curves_data, sample_ids, sample_id):
            t_data, y_data = self.get_raw_curve(curves_data, sample_ids, sample_id, curve_id)
            if t_data is None:
                continue
            fit = fit_curve(t_data, y_data, model, frame_range)
            if fit is not None:
                fit["model"] = model
                results[curve_id] = fit
        return results

    def write_fit_results_to_nomad(self, entries_data, fits_by_key, computed_by):
        """Push a set of accepted fits back into their NOMAD entries.

        fits_by_key: {(sample_id, curve_id): fit_dict} - fit_dict as returned
        by fit_sample (must include "model", "point_start", "point_end",
        "time", "params").
        computed_by: string identifying the app/user, stored in fit_computed_by.

        For each standardized metric (T95/T80/Ts95/Ts80/initial_stabilization_time)
        the current model didn't produce, explicitly removes that field rather
        than leaving it untouched - otherwise a stale value from a previous fit
        with a different model would linger, misrepresenting the current fit.

        Returns a list of {"sample_id", "curve_id", "success", "message"} -
        one entry per (sample_id, curve_id), attempted unconditionally; the
        caller surfaces "message" as-is (NOMAD's own error detail on
        failure, or a local reason when there's no entry_id to write to).
        """
        from hysprint_utils.api_calls import edit_entry

        computed_at = datetime.utcnow().isoformat()
        outcomes = []

        for (sample_id, curve_id), fit in fits_by_key.items():
            entry_id = self.get_entry_id(entries_data, sample_id, curve_id)
            if not entry_id:
                outcomes.append(
                    {
                        "sample_id": sample_id,
                        "curve_id": curve_id,
                        "success": False,
                        "message": "No linked NOMAD entry_id (offline/demo data, or not resolved "
                        "during loading) - nothing to write to.",
                    }
                )
                continue

            model = fit["model"]
            time_h = fit["time"]
            params = fit.get("params", {})

            changes = [
                {"path": "data.results.0.fit_method", "new_value": model.name},
                {"path": "data.results.0.fit_source", "new_value": "manual"},
                {"path": "data.results.0.fit_computed_by", "new_value": computed_by},
                {"path": "data.results.0.fit_computed_at", "new_value": computed_at},
                {
                    "path": "data.results.0.fit_range_start",
                    "new_value": float(time_h[0]) * 3600 if len(time_h) else None,
                },
                {
                    "path": "data.results.0.fit_range_end",
                    "new_value": float(time_h[-1]) * 3600 if len(time_h) else None,
                },
            ]
            # Declare the full desired state for every standardized metric this app
            # can produce - upsert what this model computed, explicitly remove
            # whatever it didn't. Without the "remove" branch, re-fitting a sample
            # with a model that produces fewer metrics (e.g. switching from
            # Biexponential, which writes Ts80, to Linear, which doesn't) would
            # leave the previous fit's Ts80 stale in NOMAD instead of reflecting
            # what this fit actually produced.
            for schema_field, aliases in _ISOS_METRIC_ALIASES.items():
                value = next((params[a] for a in aliases if a in params), None)
                if value is not None:
                    changes.append(
                        {
                            "path": f"data.results.0.{schema_field}",
                            "new_value": float(value) * 3600,
                        }
                    )
                else:
                    changes.append({"path": f"data.results.0.{schema_field}", "action": "remove"})

            # R2 and LEY are computed by every model (unlike the model-specific
            # parameters below), so they get their own typed fields rather than
            # living in the generic fit_parameters bag.
            if "R2" in params:
                changes.append(
                    {"path": "data.results.0.fit_r_squared", "new_value": float(params["R2"])}
                )
            else:
                changes.append({"path": "data.results.0.fit_r_squared", "action": "remove"})
            if "LEY" in params:
                changes.append(
                    {
                        "path": "data.results.0.lifetime_energy_yield",
                        "new_value": float(params["LEY"]),
                    }
                )
            else:
                changes.append({"path": "data.results.0.lifetime_energy_yield", "action": "remove"})

            # Everything else this model actually fit (A, tau, beta, slope,
            # intercept, ...) - always upsert the full list, even if empty, so a
            # re-fit with a model that has fewer/different parameters doesn't
            # leave a previous fit's parameters stale (same reasoning as the
            # ISOS metrics above).
            leftover_units = _LEFTOVER_PARAM_UNITS.get(model.abbreviated_name, {})
            fit_parameters = []
            for column in model.columns:
                if column in _DEDICATED_FIELD_COLUMNS or column not in params:
                    continue
                unit_str, factor = leftover_units.get(column, ("", 1.0))
                entry = {
                    "name": column,
                    "value": float(params[column]) * factor,
                    "unit": unit_str,
                }
                error_raw = params.get(f"{column}_error")
                if error_raw is not None:
                    entry["error"] = float(error_raw) * factor
                fit_parameters.append(entry)
            changes.append({"path": "data.results.0.fit_parameters", "new_value": fit_parameters})

            # Persisted fitted curve: RESAMPLE_POINTS points evenly spaced across
            # the fit range in time (not a subsample of the raw data points),
            # matching the convention agreed with nomad-baseclasses.
            resample_time_s, resample_power = _resample_fit_curve(fit.get("lmfit_result"), time_h)
            if resample_time_s is not None:
                changes.append(
                    {
                        "path": "data.results.0.fitted_time",
                        "new_value": resample_time_s.tolist(),
                    }
                )
                changes.append(
                    {
                        "path": "data.results.0.fitted_power_density",
                        "new_value": resample_power.tolist(),
                    }
                )

            try:
                edit_entry(self.url, self.token, entry_id, changes)
                outcomes.append(
                    {"sample_id": sample_id, "curve_id": curve_id, "success": True, "message": "OK"}
                )
            except requests.HTTPError as exc:
                message = str(exc)
                try:
                    detail = exc.response.json().get("detail")
                    if detail:
                        message = detail if isinstance(detail, str) else str(detail)
                except (ValueError, AttributeError):
                    pass
                outcomes.append(
                    {
                        "sample_id": sample_id,
                        "curve_id": curve_id,
                        "success": False,
                        "message": message,
                    }
                )

        return outcomes

    def get_selected_curve_data(self, curves_data, sample_ids, selected_samples, variable):
        """Get curve data for selected samples"""
        selected_data = []

        for sample_id in selected_samples:
            try:
                if sample_id in list(sample_ids):
                    sample_data = curves_data.loc[sample_id]

                    if hasattr(sample_data.index, "nlevels") and sample_data.index.nlevels > 1:
                        for curve_idx in sample_data.index.get_level_values(0).unique():
                            curve_data = sample_data.loc[curve_idx]
                            if variable in curve_data.columns:
                                selected_data.append(
                                    {
                                        "sample_id": sample_id,
                                        "curve_id": curve_idx,
                                        "time": curve_data["time"].values,
                                        "data": curve_data[variable].values,
                                    }
                                )
                    else:
                        if variable in sample_data.columns:
                            selected_data.append(
                                {
                                    "sample_id": sample_id,
                                    "curve_id": 0,
                                    "time": sample_data["time"].values,
                                    "data": sample_data[variable].values,
                                }
                            )
            except:  # noqa: E722
                continue

        return selected_data
