"""
TRPL Data Manager
=================
Pure Python, no widget imports.  Handles API calls, Pydantic validation,
filtering, and export.  All data state lives on the instance.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd
import requests
import scipy.optimize
import scipy.signal
from pydantic import ValidationError, field_validator

from hysprint_utils.api_calls import (
    get_all_eqe as _get_all_trpl,
)
from hysprint_utils.api_calls import (
    get_ids_in_batch,
    get_sample_description,
)
from hysprint_utils.config import ENTRY_TYPES
from hysprint_utils.error_handler import ErrorHandler
from hysprint_utils.schemas import SampleMeta

logger = logging.getLogger(__name__)
# Measurement type constant -- imported by gui_components.py
MEASUREMENT_TYPE = ENTRY_TYPES["trpl"]


# ---------------------------------------------------------------------------
# Pydantic model
# ---------------------------------------------------------------------------
class TRPLRow(SampleMeta):
    """One TRPL measurement entry as returned by the API."""

    # Raw time-series arrays from the API
    counts: Optional[list[float]] = None
    time: Optional[list[float]] = None
    ns_per_bin: Optional[float] = None

    # Metadata
    data_file: Optional[str] = None

    # Per-measurement physical parameters – set by the user in the GUI,
    # so they start as None and are filled in during processing.
    repetition_rate: Optional[float] = None
    laser_power: Optional[float] = None
    nd: Optional[float] = None
    integration_time: Optional[float] = None

    # Derived columns added by process_trpl_data; absent until then.
    noise: Optional[float] = None
    n0s: Optional[float] = None
    fluences: Optional[float] = None
    counts_no_noise: Optional[list[float]] = None
    counts_no_noise_normalized: Optional[list[float]] = None

    @field_validator(
        "counts", "time", "counts_no_noise", "counts_no_noise_normalized", mode="before"
    )
    @classmethod
    def coerce_to_list(cls, v):
        if v is None:
            return None
        return list(v) if not isinstance(v, list) else v


# ---------------------------------------------------------------------------
# Data manager
# ---------------------------------------------------------------------------
class TRPLDataManager:
    """Loads, validates, filters, and exports TRPL data."""

    def __init__(self, url: str, token: str) -> None:
        self._url = url
        self._token = token
        self.data: pd.DataFrame = pd.DataFrame()
        self.original_data: pd.DataFrame = pd.DataFrame()

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------
    @property
    def is_loaded(self) -> bool:
        return not self.data.empty

    @property
    def numeric_columns(self) -> list[str]:
        return list(self.data.select_dtypes(include="number").columns)

    @property
    def category_columns(self) -> list[str]:
        return [
            c for c in ["sample_id", "variation", "name", "data_file"] if c in self.data.columns
        ]

    @property
    def filter_summary(self) -> str:
        if not self.is_loaded:
            return "No data loaded."
        n_orig = len(self.original_data)
        n_curr = len(self.data)
        return f"Showing {n_curr} of {n_orig} measurements."

    # ------------------------------------------------------------------
    # Loading
    # ------------------------------------------------------------------
    def load(self, batch_ids: list[str]) -> bool:
        """Fetch TRPL data for the given batches. Returns True on success."""
        sample_ids = get_ids_in_batch(self._url, self._token, batch_ids)
        if sample_ids:
            descriptions = get_sample_description(self._url, self._token, list(sample_ids))
            raw = _get_all_trpl(self._url, self._token, sample_ids, eqe_type=MEASUREMENT_TYPE)
        else:
            raw, descriptions = {}, {}

        if not raw:
            logger.info("Sample-based search returned nothing; trying upload-based search.")
            raw = self._fetch_trpl_by_upload(batch_ids)
            if raw:
                descriptions = get_sample_description(self._url, self._token, list(raw.keys()))

        if not raw:
            return False
        return self._build_from_raw(raw, descriptions)

    def _fetch_trpl_by_upload(self, batch_ids: list[str]) -> dict:
        """Fetch TRPL entries from the same uploads as the given batches.

        Used when the batch entry has no registered entities so the normal
        sample-reference path returns nothing.
        """
        headers = {"Authorization": f"Bearer {self._token}"}
        resp = requests.post(
            f"{self._url}/entries/archive/query",
            headers=headers,
            json={
                "required": {"metadata": {"upload_id": "*"}},
                "owner": "visible",
                "query": {
                    "results.eln.lab_ids:any": batch_ids,
                    "entry_type": ENTRY_TYPES["batch"],
                },
                "pagination": {"page_size": 100},
            },
        )
        resp.raise_for_status()
        upload_ids = list({u["upload_id"] for u in resp.json()["data"]})
        if not upload_ids:
            return {}

        resp = requests.post(
            f"{self._url}/entries/archive/query",
            headers=headers,
            json={
                "required": {"data": "*", "metadata": "*"},
                "owner": "visible",
                "query": {"entry_type": MEASUREMENT_TYPE, "upload_id:any": upload_ids},
                "pagination": {"page_size": 10000},
            },
        )
        resp.raise_for_status()

        res: dict = {}
        for ldata in resp.json()["data"]:
            try:
                lab_id = ldata["archive"]["data"]["samples"][0]["lab_id"]
            except (KeyError, IndexError):
                continue
            if lab_id not in res:
                res[lab_id] = []
            res[lab_id].append((ldata["archive"]["data"], ldata["archive"]["metadata"]))
        return res

    def load_offline(self, fixture_path) -> bool:
        """Load from a local fixture JSON file (offline / demo mode)."""
        import json

        with open(fixture_path) as f:
            fx = json.load(f)
        return self._build_from_raw(fx["measurements"], fx["descriptions"])

    def _build_from_raw(self, raw: dict, descriptions: dict) -> bool:
        rows: list[dict] = []
        for sample_id, sample_entries in raw.items():
            for entry in sample_entries:
                props = entry[0].get("trpl_properties", {})
                data_file = entry[0].get("data_file")
                if data_file:
                    middle = ".".join(data_file.split(".")[1:-2])
                    data_file = middle or data_file  # "S001_trpl.txt" used to become ""

                try:
                    validated = TRPLRow(
                        sample_id=sample_id,
                        variation=descriptions.get(sample_id, ""),
                        name=entry[0].get("name", ""),
                        data_file=data_file,
                        counts=props.get("counts"),
                        time=props.get("time"),
                        ns_per_bin=props.get("ns_per_bin"),
                    )
                    rows.append(validated.model_dump())
                except ValidationError as exc:
                    ErrorHandler.log_error("Validation failed for sample %s" % sample_id, exc)

        if not rows:
            return False

        self.data = pd.DataFrame(rows)
        self.original_data = self.data.copy()
        return True

    # ------------------------------------------------------------------
    # Filtering
    # ------------------------------------------------------------------
    def apply_filter(
        self,
        column: str,
        min_val: float,
        max_val: float,
    ) -> tuple[bool, str]:
        """Filter data to [min_val, max_val] on a numeric column."""
        if min_val > max_val:
            return False, f"min ({min_val}) cannot be greater than max ({max_val})."
        if column not in self.data.columns:
            return False, f"Column '{column}' not found."
        mask = self.data[column].between(min_val, max_val)
        self.data = self.data[mask].reset_index(drop=True)
        return True, self.filter_summary

    def reset_filters(self) -> None:
        """Restore original unfiltered data."""
        self.data = self.original_data.copy()

    # ------------------------------------------------------------------
    # Export / aggregation
    # ------------------------------------------------------------------
    def to_csv_string(self) -> str:
        """Return the current DataFrame as a CSV string (excluding array columns)."""
        scalar_cols = [c for c in self.data.columns if not isinstance(self.data[c].iloc[0], list)]
        return self.data[scalar_cols].to_csv()

    def get_pivot_table(self, value_col: str, group_col: str) -> pd.DataFrame:
        """Pivot scalar data: rows = sample index, columns = group_col values."""
        return self.data.pivot_table(
            values=value_col,
            index=self.data.index,
            columns=group_col,
            aggfunc="mean",
        )


# ---------------------------------------------------------------------------
# Analysis (pure numpy, no widgets): units, noise floor, carrier density, differential lifetime
# ---------------------------------------------------------------------------

# NOMAD stores a quantity declared with a unit in SI base units, so the TRPL `time` (schema
# unit ns) arrives in seconds: the demo fixture steps by 1e-9. This is the ONE place that
# unit is decided; every analysis step below works in seconds. (The old code divided the same
# vector by 1e12 in the analysis, as if it were picoseconds, and multiplied it by 1e9 for the
# plot, as if it were seconds: one of the two was always wrong by twelve orders of magnitude.)
TIME_TO_SECONDS = 1.0

HC_J_M = 1.98645e-25  # Planck constant x speed of light [J m]
UW_TO_W = 1e-6
NM_TO_CM = 1e-7


def time_in_seconds(time) -> np.ndarray:
    """The measurement's time axis in seconds (see TIME_TO_SECONDS)."""
    return np.asarray(time, dtype=float) * TIME_TO_SECONDS


def bin_width_seconds(time_s: np.ndarray) -> float:
    """Width of one time bin in seconds, from the time axis itself. The stored `ns_per_bin`
    is not used: it was passed on as if it were seconds (1e9 too large)."""
    steps = np.diff(np.asarray(time_s, dtype=float))
    steps = steps[steps > 0]
    return float(np.median(steps)) if steps.size else float("nan")


def calculate_noise(counts, denoise_value: int) -> float:
    """Background counts per bin: the mean of the first `denoise_value` bins (positive) or of
    the last |denoise_value| bins with trailing zeros removed (negative); 0 for no denoising."""
    counts = np.asarray(counts, dtype=float)
    if denoise_value < 0:
        return float(np.mean(np.trim_zeros(counts, trim="b")[denoise_value:]))
    if denoise_value > 0:
        return float(np.mean(counts[:denoise_value]))
    return 0.0


def rate_from_counts(count, integration_time_s: float, bin_s: float, rep_rate_hz: float):
    """Counts (per bin) to counts per second: count / (bin width x integration time x rep rate)."""
    return np.asarray(count, dtype=float) / (bin_s * integration_time_s * rep_rate_hz)


def calculate_n0(
    power_uw: float,
    rep_rate_hz: float,
    nd: float,
    spot_diameter_cm: float,
    thickness_nm: float,
    wavelength_m: float,
    bd_ratio: float,
) -> tuple[float, float]:
    """(n0 [cm^-3], fluence [photons/cm^2 per pulse]) for the units the GUI asks for.

    Power in microwatts, spot diameter in cm, thickness in nm, laser wavelength in m. The ND
    filter attenuates the power by 10^-ND. The old code left the power in microwatts and
    divided by the thickness as if it were in cm, which made n0 (and the x axis of
    'differential lifetime vs carrier density') 1e7 too small; ND was collected and never used."""
    power_w = power_uw * UW_TO_W * 10.0 ** (-nd)
    pulse_energy_j = power_w / rep_rate_hz
    spot_area_cm2 = np.pi * (spot_diameter_cm / 2.0) ** 2
    photon_energy_j = HC_J_M / wavelength_m
    fluence = pulse_energy_j / spot_area_cm2 / photon_energy_j
    n0 = fluence * bd_ratio / (thickness_nm * NM_TO_CM)
    return float(n0), float(fluence)


def exponential_sum(x, *params):
    """sum_i a_i exp(-b_i x) for params = (a_1, b_1, a_2, b_2, ...)."""
    total = 0.0
    for amplitude, rate in zip(params[0::2], params[1::2]):
        total = total + amplitude * np.exp(-rate * x)
    return total


def _smoothing_window(n_points: int, wanted: int = 51, polyorder: int = 3) -> int | None:
    """Odd Savitzky-Golay window <= n_points and > polyorder, or None when the trace is too
    short to smooth (a fixed 51 raised for any trace with fewer points after its maximum, so
    one short trace stopped the whole analysis and the 5-point demo could never run)."""
    window = min(wanted, n_points)
    if window % 2 == 0:
        window -= 1
    return window if window > polyorder else None


def differential_lifetime(
    time_s: np.ndarray,
    counts_no_noise: np.ndarray,
    noise_rate: float,
    n0: float,
    num_exponentials: int,
):
    """Fit the decay after its maximum and return (t, tau_diff, carrier_density).

    The data already has its background subtracted, so the model is the exponential sum alone;
    the old code added the background back to the model, which bent the fit onto the noise level
    and made tau_diff diverge at late times. tau_diff = -2 dt / dln(PL) (PL scales with n^2),
    taken from the fitted curve; carrier density = n0 sqrt(PL / PL_max).

    Raises ValueError for a trace that cannot be fitted (too few usable points)."""
    time_s = np.asarray(time_s, dtype=float)
    pl = np.asarray(counts_no_noise, dtype=float)
    peak = int(np.argmax(pl))
    t = time_s[peak:] - time_s[peak]
    pl = pl[peak:]
    window = _smoothing_window(len(pl))
    smooth = scipy.signal.savgol_filter(pl, window, 3) if window else pl
    mask = smooth > 10 * noise_rate
    if mask.sum() <= 2 * num_exponentials:
        raise ValueError(
            f"only {int(mask.sum())} usable point(s) after the peak for a "
            f"{num_exponentials}-exponential fit"
        )

    # Work in milliseconds so the rate constants are of order 1, as in the original notebook.
    x = 1e3 * t
    p0 = [1.0, 1e4] * num_exponentials
    lower = (1e-12,) * (2 * num_exponentials)
    upper = (np.inf,) * (2 * num_exponentials)
    params, _ = scipy.optimize.curve_fit(
        exponential_sum, x[mask], pl[mask], maxfev=100000, p0=p0, bounds=(lower, upper)
    )
    fit = exponential_sum(x, *params)
    tau_diff = -2 * (np.diff(t) / np.diff(np.log(fit)))
    density = np.sqrt(fit / np.max(fit)) * n0
    return t + time_s[peak], tau_diff, density


@dataclass
class TraceResult:
    sample_id: str
    label: str
    time_s: np.ndarray | None = None
    tau_diff_s: np.ndarray | None = None
    density_cm3: np.ndarray | None = None
    n0_cm3: float | None = None
    fluence: float | None = None
    noise_rate: float | None = None
    error: str = ""


class AnalysisInputError(ValueError):
    """An input the user has to fill in before the analysis can run (shown without a traceback)."""


def analyse_traces(data: pd.DataFrame, global_params: dict, row_params: list[dict]):
    """Run the whole TRPL analysis. Returns (processed frame, [TraceResult per row]).

    The processed frame has the columns the plots read: `time_s`, `counts` (counts/s),
    `counts_no_noise`, `counts_no_noise_normalized`, `noise` (counts/s), `n0s`, `fluences`.
    A trace that fails (too short, a fit that does not converge) is reported in its
    TraceResult.error and does not stop the others."""
    thickness = global_params["thickness"]
    if not thickness:
        raise AnalysisInputError(
            "The film thickness is not set. Enter it (in nm) in the 'Thickness [nm]' field of "
            "the parameter panel above, then click Run Analysis again."
        )
    frame = data.copy()
    denoise = int(global_params["denoise"])
    rows_out = []
    results: list[TraceResult] = []

    for (_, row), params in zip(frame.iterrows(), row_params):
        sample_id = str(row.get("sample_id", ""))
        label = f"{sample_id} – {row.get('data_file', '') or ''}".strip(" –")
        result = TraceResult(sample_id=sample_id, label=label)
        results.append(result)
        try:
            time_s = time_in_seconds(row["time"])
            counts = np.asarray(row["counts"], dtype=float)
            bin_s = bin_width_seconds(time_s)
            if not np.isfinite(bin_s):
                raise ValueError("the time axis has fewer than two distinct points")
            rate = rate_from_counts(counts, params["integration_time"], bin_s, params["rep_rate"])
            noise_rate = float(
                rate_from_counts(
                    calculate_noise(counts, denoise),
                    params["integration_time"],
                    bin_s,
                    params["rep_rate"],
                )
            )
            subtracted = rate - noise_rate
            peak = np.amax(subtracted) if np.amax(subtracted) > 0 else 1.0
            n0, fluence = calculate_n0(
                params["power"],
                params["rep_rate"],
                params.get("nd") or 0.0,
                global_params["spot_diameter"],
                thickness,
                global_params["lambda_laser"],
                global_params["bd_ratio"],
            )
            rows_out.append(
                dict(
                    time_s=time_s,
                    counts=rate,
                    counts_no_noise=subtracted,
                    counts_no_noise_normalized=subtracted / peak,
                    noise=noise_rate,
                    n0s=n0,
                    fluences=fluence,
                )
            )
            result.noise_rate, result.n0_cm3, result.fluence = noise_rate, n0, fluence
            result.time_s, result.tau_diff_s, result.density_cm3 = differential_lifetime(
                time_s, subtracted, noise_rate, n0, int(params["num_exponentials"])
            )
        except Exception as exc:  # noqa: BLE001 - reported per trace, the others carry on
            logger.warning("TRPL analysis failed for %s: %s", label, exc)
            result.error = str(exc)
            if len(rows_out) < len(results):
                rows_out.append({})

    columns = {
        key: [r.get(key) for r in rows_out]
        for key in (
            "time_s",
            "counts",
            "counts_no_noise",
            "counts_no_noise_normalized",
            "noise",
            "n0s",
            "fluences",
        )
    }
    for key, values in columns.items():
        frame[key] = values
    return frame, results
