"""
Data management functions for MPPT Analysis App
"""

import json
import logging
import math
import warnings
from datetime import datetime

import numpy as np
import pandas as pd
import requests
from pydantic import BaseModel, ValidationError, field_validator

from hysprint_utils.api_calls import (
    REQUEST_TIMEOUT,
    get_all_mppt,
    get_ids_in_batch,
    get_sample_description,
)
from hysprint_utils.config import ENTRY_TYPES

logger = logging.getLogger(__name__)

# StabilityFiguresOfMerit field name -> fitting_tools.py model column names that
# feed it. Column names aren't consistent across models (T80 vs t80, tS vs Ts...),
# so write-back has to alias-match rather than assume one spelling.
# T95/T80/Ts95/Ts80 definitions: Khenkin et al., "Consensus statement for
# stability assessment and reporting for perovskite photovoltaics based on
# ISOS procedures", Nature Energy 5, 35-49 (2020). DOI: 10.1038/s41560-019-0529-5
_ISOS_METRIC_ALIASES = {
    "T95": ["T95", "t95"],
    "T80": ["T80", "t80"],
    "Ts95": ["Ts95", "ts95"],
    "Ts80": ["Ts80", "ts80"],
    "initial_stabilization_time": ["tS", "ts"],
}
_ISOS_ALIAS_COLUMNS = {alias for aliases in _ISOS_METRIC_ALIASES.values() for alias in aliases}
# model.columns entries that go to their own dedicated schema field, not the
# generic fit_parameters bag: the ISOS metrics above, plus R2 -> fit_r_squared,
# LEY -> lifetime_energy_yield, and PCE_after_1000_h (same name both sides).
_DEDICATED_FIELD_COLUMNS = _ISOS_ALIAS_COLUMNS | {"R2", "LEY", "PCE_after_1000_h"}


def _has_value(value):
    """True if a fitting_tools.py metric was actually produced - excludes
    both None (never computed by this model) and NaN (computed, but the
    fit never reaches the target threshold within a scientifically
    meaningful extrapolation - see crossing_time()'s docstring in
    fitting_tools.py) - neither should be written to NOMAD as a value.

    Deliberately writes "action": "remove" (an empty field) rather than a
    literal NaN for both cases: standard JSON has no NaN, and the requests
    library used by hysprint_utils.api_calls.edit_entry refuses to
    serialize one at all (raises before the request is even sent) - sending
    one would need a shared hysprint_utils change with its own sign-off,
    for an outcome not even confirmed to be accepted server-side. An empty
    field is also NOMAD's own native way to represent "no value" for a
    scalar quantity - the same convention this app already relies on for
    T80_linear when it's inapplicable (see erfc_params in fitting_tools.py)."""
    if value is None:
        return False
    try:
        return bool(math.isfinite(float(value)))
    except (TypeError, ValueError):
        return False


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
        "LEY_1000h": ("kWh/m^2", 1.0),
        "A": ("mW/cm^2", 1.0),
        "tau": ("s", 3600.0),
        "beta": ("", 1.0),
    },
    "Linear": {
        "LEY_1000h": ("kWh/m^2", 1.0),
        "slope": ("mW/cm^2/s", 1.0 / 3600.0),
        "intercept": ("mW/cm^2", 1.0),
    },
    "Exponential": {
        "LEY_1000h": ("kWh/m^2", 1.0),
        "amplitude": ("mW/cm^2", 1.0),
        "decay": ("s", 3600.0),
    },
    "Biexponential": {
        "LEY_1000h": ("kWh/m^2", 1.0),
        "A1": ("mW/cm^2", 1.0),
        "tau1": ("s", 3600.0),
        "A2": ("mW/cm^2", 1.0),
        "tau2": ("s", 3600.0),
    },
    "Logistic+Exp": {
        "LEY_1000h": ("kWh/m^2", 1.0),
        "A": ("mW/cm^2", 1.0),
        "tau": ("s", 3600.0),
        "L": ("mW/cm^2", 1.0),
        "k": ("1/s", 1.0 / 3600.0),
        "x0": ("s", 3600.0),
    },
    "ERFC+Linear": {
        "LEY_1000h": ("kWh/m^2", 1.0),
        "PCE0": ("mW/cm^2", 1.0),
        "k": ("mW/cm^2/s", 1.0 / 3600.0),
        "t0": ("s", 3600.0),
        "b": ("s", 3600.0),
        "T80_linear": ("s", 3600.0),
    },
}

# fit_method as written to NOMAD (fit_model.name) -> fit_model.abbreviated_name
_MODEL_ABBREVIATION = {
    "Stretched Exponential": "Stretched Exp",
    "Logistic + Exponential": "Logistic+Exp",
    "ERFC + Linear": "ERFC+Linear",
}


def stored_fit_from_archive(raw_data) -> dict | None:
    """The fit metrics already saved in an MPPT entry (results[0]), or None.

    An entry counts when results[0] has a fit_method or any figure of merit this app writes
    (T80, T95, Ts80, Ts95, stabilization time, LEY, R2). The processed archive of the HZB SE
    Oasis currently returns the metrics but not fit_method or fit_parameters."""
    if not isinstance(raw_data, dict):
        return None
    results = raw_data.get("results")
    first = results[0] if isinstance(results, list) and results else None
    if not isinstance(first, dict):
        return None
    written = {"fit_method", "fit_r_squared", "lifetime_energy_yield", *_ISOS_METRIC_ALIASES}
    return first if any(_has_value_or_text(first.get(key)) for key in written) else None


def _has_value_or_text(value) -> bool:
    return bool(value) if isinstance(value, str) else _has_value(value)


def stored_fit_row(stored: dict) -> dict:
    """One results-table row for a fit stored in NOMAD, in the units the app shows (times in
    hours, like a fit made in this session). The inverse of _build_fit_changes."""
    method = stored.get("fit_method") or ""
    abbreviation = _MODEL_ABBREVIATION.get(method, method)
    row: dict = {"model": abbreviation or "unknown"}
    for schema_field, aliases in _ISOS_METRIC_ALIASES.items():
        if _has_value(stored.get(schema_field)):
            row[aliases[0]] = float(stored[schema_field]) / 3600
    for column, schema_field in (
        ("R2", "fit_r_squared"),
        ("LEY", "lifetime_energy_yield"),
        ("PCE_after_1000_h", "PCE_after_1000_h"),
    ):
        if _has_value(stored.get(schema_field)):
            row[column] = float(stored[schema_field])
    units = _LEFTOVER_PARAM_UNITS.get(abbreviation, {})
    for param in stored.get("fit_parameters") or []:
        name = param.get("name")
        if not name or not _has_value(param.get("value")):
            continue
        factor = units.get(name, ("", 1.0))[1]
        row[name] = float(param["value"]) / factor
        if _has_value(param.get("error")):
            row[f"{name}_error"] = float(param["error"]) / factor
    start, end = stored.get("fit_range_start"), stored.get("fit_range_end")
    if _has_value(start) and _has_value(end):
        row["max_time_h"] = float(end) / 3600
    who, when = stored.get("fit_computed_by"), stored.get("fit_computed_at")
    detail = ", ".join(str(x) for x in (who, str(when)[:16] if when else None) if x)
    if not method:
        detail = "metrics only, fit details not available"
    row["note"] = "Stored in NOMAD" + (f" ({detail})" if detail else "")
    return row


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


OUTLIER_WINDOW = 11  # points in the rolling-median window (odd)
OUTLIER_THRESHOLD = 6.0  # deviation from the rolling median, in robust standard deviations


def find_outliers(y_data, window=OUTLIER_WINDOW, threshold=OUTLIER_THRESHOLD):
    """Boolean mask of isolated spikes/dips in y_data (Hampel filter).

    A point is an outlier when it deviates from the rolling median of its
    centred `window` by more than `threshold` robust standard deviations
    (1.4826 x the median absolute deviation of all such deviations). A slow
    trend such as burn-in decay follows its own rolling median and survives;
    only points that break away from their neighbours are flagged.

    The first and last window//2 points are never flagged: their window is
    one-sided, so the genuine steep start of a decay would look like a spike.
    Curves shorter than three windows are returned unflagged.
    """
    y = np.asarray(y_data, dtype=float)
    mask = np.zeros(len(y), dtype=bool)
    half = int(window) // 2
    if int(window) < 3 or len(y) < 3 * int(window):
        return mask

    series = pd.Series(y)
    median = series.rolling(int(window), center=True, min_periods=1).median()
    deviation = (series - median).abs()
    sigma = 1.4826 * deviation.median()
    if not sigma > 0:  # quantised/flat data: fall back to the mean deviation
        sigma = deviation.mean()
    if not sigma > 0:
        return mask

    mask = np.array(deviation > threshold * sigma)
    mask[:half] = False
    mask[len(y) - half :] = False
    return mask


def remove_outliers(y_data, window=OUTLIER_WINDOW, threshold=OUTLIER_THRESHOLD):
    """Copy of y_data with its outliers (see find_outliers) set to NaN, so the
    array keeps its length and stays aligned with the time axis. Returns
    (cleaned, n_removed)."""
    y = np.array(y_data, dtype=float)
    mask = find_outliers(y, window, threshold)
    y[mask] = np.nan
    return y, int(mask.sum())


def mask_removed_points(values, raw_power, cleaned_power):
    """Copy of `values` (e.g. voltage) with NaN at the points the outlier cleaning removed
    from power_density: NaN in cleaned_power where raw_power was a real number. Points that
    were already NaN in the raw data are left as they were."""
    values = np.array(values, dtype=float)
    removed = np.isnan(np.asarray(cleaned_power, dtype=float)) & ~np.isnan(
        np.asarray(raw_power, dtype=float)
    )
    if len(removed) == len(values):
        values[removed] = np.nan
    return values


def fit_curve(t_data, y_data, model, frame_range=None, initial_values=None):
    """Slice to frame_range (point indices), fit with model, return a result
    dict or None if there aren't enough valid points to fit at all.

    frame_range: (start, end) - end is the last index to include, or None for
    "to the end of the array". point_start/point_end in the result reflect
    the requested range (not shrunk by any NaN rows dropped internally), since
    that's what the user actually configured.

    initial_values: optional {param_name: value} seeding the optimizer's
    starting point (overriding model's own default_guess for just the given
    names). The fit still runs and can converge away from these - they are a
    better starting guess, not fixed values. None/{} uses the model's own
    defaults unchanged.

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

    if initial_values:  # a NaN seed (e.g. a guess made on NaN data) can only abort the fit
        initial_values = {k: v for k, v in initial_values.items() if np.isfinite(v)}

    valid_mask = ~(np.isnan(t_sliced) | np.isnan(y_sliced))
    t_sliced = t_sliced[valid_mask]
    y_sliced = y_sliced[valid_mask]

    if len(t_sliced) < 2:
        return None

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            fit_params, fitted_curve, lmfit_result = model.parfunc(
                y_sliced, t_sliced, initial_values
            )
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

    @staticmethod
    def _entry_frame(raw_data, sample_id) -> pd.DataFrame | None:
        """One MPPT entry's valid rows as a DataFrame in the app's convention (power and
        current density positive for a generating cell, time in hours), or None when the
        entry has no usable row.

        NOMAD stores generated power as negative; the sign is detected per entry (median
        power below zero) instead of being flipped unconditionally, so an entry or demo
        file already in the positive convention is not turned upside down."""
        validated_rows = []
        for row in DataManager._rows_from_entry(raw_data):
            try:
                validated = MPPTRow(
                    time=row.get("time"),
                    power_density=row.get("power_density"),
                    voltage=row.get("voltage"),
                    current_density=row.get("current_density"),
                )
                validated_rows.append(validated.model_dump())
            except ValidationError as exc:
                logger.warning("Skipping invalid MPPT row for sample %s: %s", sample_id, exc)
        if not validated_rows:
            return None
        frame = pd.DataFrame(validated_rows)
        if frame["power_density"].median() < 0:
            frame["power_density"] *= -1
            frame["current_density"] *= -1
        frame["time"] *= 1 / 3600
        return frame

    def _assemble_curves(self, raw: dict):
        """{sample_id: [(archive_data, metadata), ...]} -> (curves, sample_ids, entries), or
        None when nothing has usable rows.

        The single loader behind both the live and the offline path. An entry without usable
        rows contributes no curve, no name and no entry_id, so curve k always belongs to
        entry k (previously the labels were appended anyway and every later curve was written
        back to the previous entry), and a sample with no curve is not in sample_ids (pandas
        silently truncates concat keys that do not match)."""
        curves_by_sample = []
        entries_by_sample = []
        sample_order = []
        for sample_id, entries in raw.items():
            frames, names, descriptions, entry_ids, upload_ids = [], [], [], [], []
            stored_fits = []
            for mppt_entry in entries:
                raw_data = mppt_entry[0]
                metadata = mppt_entry[1] if isinstance(mppt_entry[1], dict) else {}
                frame = self._entry_frame(raw_data, sample_id)
                if frame is None:
                    continue
                meta = raw_data if isinstance(raw_data, dict) else {}
                frames.append(frame)
                names.append(meta.get("name", ""))
                descriptions.append(meta.get("description", ""))
                entry_ids.append(metadata.get("entry_id"))
                upload_ids.append(metadata.get("upload_id"))
                stored_fits.append(stored_fit_from_archive(raw_data))
            if not frames:
                continue
            curves_by_sample.append(pd.concat(frames, keys=np.arange(len(frames))))
            entries_by_sample.append(
                pd.DataFrame(
                    {
                        "entry_names": names,
                        "entry_description": descriptions,
                        "entry_id": entry_ids,
                        "upload_id": upload_ids,
                        "stored_fit": pd.Series(stored_fits, dtype=object),
                    }
                )
            )
            sample_order.append(sample_id)
        if not curves_by_sample:
            return None
        sample_ids = pd.Series(sample_order)
        return (
            pd.concat(curves_by_sample, keys=sample_ids),
            sample_ids,
            pd.concat(entries_by_sample, keys=sample_ids),
        )

    def _build_from_raw(self, raw: dict, descriptions: dict) -> bool:
        assembled = self._assemble_curves(raw)
        if assembled is None:
            return False
        curves, sample_ids_series, entries_df = assembled
        properties = pd.DataFrame(
            {
                "description": pd.Series(
                    {sid: descriptions.get(sid, "") for sid in sample_ids_series}
                ),
                "name": pd.Series(dtype=str),
            }
        )
        self.curves = curves
        self.sample_ids = sample_ids_series
        self.entries = entries_df
        self.properties = properties
        return True

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
                timeout=REQUEST_TIMEOUT,
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
                    timeout=REQUEST_TIMEOUT,
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
            timeout=REQUEST_TIMEOUT,
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
        assembled = self._assemble_curves(all_mppt) if all_mppt else None
        return assembled if assembled is not None else (None, None, None)

    def load_data_from_batches(self, selected_batches):
        """Load MPPT data from selected batches"""
        try:
            try_sample_ids = get_ids_in_batch(self.url, self.token, selected_batches)
            mppt_result = self.get_mppt_data_working(try_sample_ids)

            if mppt_result is None or mppt_result[0] is None:
                return None, "The selected batches don't contain any MPPT measurements"

            curves, sample_ids, entries = mppt_result

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

    def get_stored_fit(self, entries_data, sample_id, curve_id):
        """The fit already stored in NOMAD for one (sample_id, curve_id), or None."""
        if entries_data is None or "stored_fit" not in entries_data.columns:
            return None
        try:
            value = entries_data.loc[(sample_id, curve_id), "stored_fit"]
        except (KeyError, IndexError):
            return None
        return value if isinstance(value, dict) else None

    def get_curve_label(self, entries_data, sample_id, curve_id):
        """Human label of one measurement: the NOMAD entry name (the pixel) without
        the sample id prefix, or "Curve N" when the entry has no name."""
        name = ""
        if entries_data is not None:
            try:
                value = entries_data.loc[(sample_id, curve_id), "entry_names"]
                name = value if isinstance(value, str) else ""
            except (KeyError, IndexError):
                name = ""
        name = name.strip()
        if name.startswith(sample_id):
            name = name[len(sample_id) :].strip(" _-")
        return name or f"Curve {curve_id}"

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

    def get_curve(self, curves_data, sample_ids, sample_id, curve_id, cleaned=None):
        """Like get_raw_curve, but with power_density taken from `cleaned`
        ({(sample_id, curve_id): array with NaN at removed points}) when that
        curve has been cleaned. The raw data itself is never modified."""
        t_data, y_data = self.get_raw_curve(curves_data, sample_ids, sample_id, curve_id)
        if t_data is not None and cleaned and (sample_id, curve_id) in cleaned:
            y_data = cleaned[(sample_id, curve_id)]
        return t_data, y_data

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

    def get_upload_id(self, entries_data, sample_id, curve_id):
        """Look up the NOMAD upload_id backing one (sample_id, curve_id), or None.

        Same availability caveats as get_entry_id - only used to build a
        link to the entry in the NOMAD GUI, never for API calls.
        """
        if entries_data is None:
            return None
        try:
            value = entries_data.loc[(sample_id, curve_id), "upload_id"]
        except (KeyError, IndexError):
            return None
        return value if isinstance(value, str) and value else None

    def _entry_gui_url(self, upload_id, entry_id):
        """Build a link to this entry's fitted results in the NOMAD GUI.

        Derived from self.url (URL_BASE + API_ENDPOINT, e.g.
        "https://nomad-hzb-se.helmholtz-berlin.de/nomad-oasis/api/v1") rather than importing
        URL_BASE separately, since the GUI mount point is the same
        "/nomad-oasis" prefix with "/api/v1" swapped for "/gui" - avoids a
        second, possibly-diverging way to name the same server.
        """
        if not upload_id or not entry_id:
            return None
        api_suffix = "/api/v1"
        api_root = self.url.rstrip("/")
        if not api_root.endswith(api_suffix):
            return None
        gui_root = api_root[: -len(api_suffix)] + "/gui"
        return (
            f"{gui_root}/user/uploads/upload/id/{upload_id}/entry/id/{entry_id}/data/data/results/0"
        )

    def fit_sample(
        self,
        curves_data,
        sample_ids,
        sample_id,
        model,
        frame_range=None,
        initial_values=None,
        curve_ids=None,
        cleaned=None,
    ):
        """Fit the curves of one sample with the given model/point range.

        curve_ids: restrict the fit to these curves; None fits every curve of the sample.

        cleaned: optional outlier-cleaned power_density, see get_curve.

        initial_values: optional {param_name: value}, passed through to every
        curve's fit_curve() call unchanged - each curve still gets its own
        independent optimization from that shared starting point (see
        fit_curve's docstring), it isn't forced to the same final result.

        Returns {curve_id: fit_dict}. A curve is omitted if it has too few
        points in range or the fit raises. fit_dict keys: time, fitted_power,
        original_power, point_start, point_end, model, params.
        """
        warnings.filterwarnings(
            "ignore", message="Using UFloat objects with std_dev==0 may give unexpected results."
        )

        results = {}
        available = self.get_curve_ids_for_sample(curves_data, sample_ids, sample_id)
        for curve_id in (
            available if curve_ids is None else [c for c in available if c in curve_ids]
        ):
            t_data, y_data = self.get_curve(curves_data, sample_ids, sample_id, curve_id, cleaned)
            if t_data is None:
                continue
            fit = fit_curve(t_data, y_data, model, frame_range, initial_values)
            if fit is not None:
                fit["model"] = model
                results[curve_id] = fit
        return results

    def _build_fit_changes(self, fit, computed_by, computed_at):
        """The edit_entry `changes` list that writes one fit into its NOMAD entry."""
        model = fit["model"]
        time_h = fit["time"]
        params = fit.get("params", {})

        changes = [
            {"path": "data/results/0/fit_method", "new_value": model.name},
            {"path": "data/results/0/fit_source", "new_value": "manual"},
            {"path": "data/results/0/fit_computed_by", "new_value": computed_by},
            {"path": "data/results/0/fit_computed_at", "new_value": computed_at},
            {
                "path": "data/results/0/fit_range_start",
                "new_value": float(time_h[0]) * 3600 if len(time_h) else None,
            },
            {
                "path": "data/results/0/fit_range_end",
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
            if _has_value(value):
                changes.append(
                    {
                        "path": f"data/results/0/{schema_field}",
                        "new_value": float(value) * 3600,
                    }
                )
            else:
                changes.append({"path": f"data/results/0/{schema_field}", "action": "remove"})

        # R2, LEY, and PCE_after_1000_h are computed by every model (unlike
        # the model-specific parameters below), so they get their own typed
        # fields rather than living in the generic fit_parameters bag.
        if _has_value(params.get("R2")):
            changes.append(
                {"path": "data/results/0/fit_r_squared", "new_value": float(params["R2"])}
            )
        else:
            changes.append({"path": "data/results/0/fit_r_squared", "action": "remove"})
        if _has_value(params.get("LEY")):
            changes.append(
                {
                    "path": "data/results/0/lifetime_energy_yield",
                    "new_value": float(params["LEY"]),
                }
            )
        else:
            changes.append({"path": "data/results/0/lifetime_energy_yield", "action": "remove"})
        if _has_value(params.get("PCE_after_1000_h")):
            changes.append(
                {
                    "path": "data/results/0/PCE_after_1000_h",
                    "new_value": float(params["PCE_after_1000_h"]),
                }
            )
        else:
            changes.append({"path": "data/results/0/PCE_after_1000_h", "action": "remove"})

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
            if not _has_value(params[column]):
                continue  # NaN/inf (e.g. T80_linear when k is 0) cannot be sent as JSON
            unit_str, factor = leftover_units.get(column, ("", 1.0))
            entry = {
                "name": column,
                "value": float(params[column]) * factor,
                "unit": unit_str,
            }
            error_raw = params.get(f"{column}_error")
            if _has_value(error_raw):
                entry["error"] = float(error_raw) * factor
            fit_parameters.append(entry)
        changes.append({"path": "data/results/0/fit_parameters", "new_value": fit_parameters})

        # Persisted fitted curve: RESAMPLE_POINTS points evenly spaced across
        # the fit range in time (not a subsample of the raw data points),
        # matching the convention agreed with nomad-baseclasses.
        resample_time_s, resample_power = _resample_fit_curve(fit.get("lmfit_result"), time_h)
        if resample_time_s is not None:
            changes.append(
                {
                    "path": "data/results/0/fitted_time",
                    "new_value": resample_time_s.tolist(),
                }
            )
            changes.append(
                {
                    "path": "data/results/0/fitted_power_density",
                    "new_value": resample_power.tolist(),
                }
            )

        return changes

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

        Returns a list of {"sample_id", "curve_id", "success", "message",
        "nomad_url"} - one entry per (sample_id, curve_id), attempted
        unconditionally; the caller surfaces "message" as-is (NOMAD's own
        error detail on failure, or a local reason when there's no entry_id
        to write to). "nomad_url" links to the entry's fitted results in the
        NOMAD GUI on success, None otherwise (e.g. upload_id unavailable).
        """
        from hysprint_utils.api_calls import edit_entry

        computed_at = datetime.utcnow().isoformat()
        outcomes = []
        written_entry_ids: set[str] = set()

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
                        "nomad_url": None,
                    }
                )
                continue
            if entry_id in written_entry_ids:
                # An entry that references several samples is indexed under each of them;
                # write it once, the same fit would otherwise overwrite itself.
                outcomes.append(
                    {
                        "sample_id": sample_id,
                        "curve_id": curve_id,
                        "success": True,
                        "message": "Same NOMAD entry already written for another sample.",
                        "nomad_url": None,
                    }
                )
                continue
            written_entry_ids.add(entry_id)
            upload_id = self.get_upload_id(entries_data, sample_id, curve_id)

            try:
                changes = self._build_fit_changes(fit, computed_by, computed_at)
                edit_entry(self.url, self.token, entry_id, changes)
                outcomes.append(
                    {
                        "sample_id": sample_id,
                        "curve_id": curve_id,
                        "success": True,
                        "message": "OK",
                        "nomad_url": self._entry_gui_url(upload_id, entry_id),
                    }
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
                        "nomad_url": None,
                    }
                )
            except (requests.RequestException, ValueError, TypeError, OverflowError) as exc:
                # A network error, or a value that cannot be sent: report this entry as
                # failed and carry on, instead of aborting with earlier entries already
                # written and no word to the user about the rest.
                logger.exception("Writing the fit of %s / %s failed", sample_id, curve_id)
                outcomes.append(
                    {
                        "sample_id": sample_id,
                        "curve_id": curve_id,
                        "success": False,
                        "message": f"{type(exc).__name__}: {exc}",
                        "nomad_url": None,
                    }
                )

        return outcomes

    def get_selected_curve_data(
        self,
        curves_data,
        sample_ids,
        selected_samples,
        variable,
        selected_curves=None,
        cleaned=None,
    ):
        """Get curve data for selected samples.

        selected_curves: optional [(sample_id, curve_id)]; when given, only those
        measurements are returned.
        cleaned: optional outlier-cleaned power_density, see get_curve; replaces
        the data of cleaned curves when variable is power_density, and blanks
        (NaN) the same points in every other variable.
        """
        selected_data = []
        wanted = None if selected_curves is None else set(selected_curves)

        for sample_id in selected_samples:
            try:
                if sample_id in list(sample_ids):
                    sample_data = curves_data.loc[sample_id]

                    if hasattr(sample_data.index, "nlevels") and sample_data.index.nlevels > 1:
                        for curve_idx in sample_data.index.get_level_values(0).unique():
                            if wanted is not None and (sample_id, curve_idx) not in wanted:
                                continue
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
                        if wanted is not None and (sample_id, 0) not in wanted:
                            continue
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

        if cleaned:
            for item in selected_data:
                key = (item["sample_id"], item["curve_id"])
                if key not in cleaned:
                    continue
                if variable == "power_density":
                    item["data"] = cleaned[key]
                else:
                    # Voltage / current density: blank the same points the power
                    # cleaning removed, so every variable shows the same clean curve.
                    _, raw_power = self.get_raw_curve(curves_data, sample_ids, *key)
                    item["data"] = mask_removed_points(item["data"], raw_power, cleaned[key])
        return selected_data
