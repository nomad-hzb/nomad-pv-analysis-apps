from __future__ import annotations

import logging

import pandas as pd
from hysprint_utils.api_calls import (
    get_all_eqe,
    get_ids_in_batch,
    get_sample_description,
)
from hysprint_utils.config import ENTRY_TYPES
from hysprint_utils.error_handler import ErrorHandler
from hysprint_utils.schemas import SampleMeta  # noqa: F401  (available for import by callers)
from pydantic import BaseModel, field_validator

logger = logging.getLogger(__name__)

MEASUREMENT_TYPE = ENTRY_TYPES["eqe"]

# ---------------------------------------------------------------------------
# Pydantic model
# ---------------------------------------------------------------------------


class EQECurveData(BaseModel):
    """Represents one EQE sweep (one row in eqe_data from the API)."""

    photon_energy_array: list[float] | None = None
    wavelength_array: list[float] | None = None
    eqe_array: list[float] | None = None
    light_bias: float | None = None
    bandgap_eqe: float | None = None
    integrated_jsc: float | None = None
    integrated_j0rad: float | None = None
    voc_rad: float | None = None
    urbach_energy: float | None = None
    urbach_energy_fit_std_dev: float | None = None

    @field_validator("photon_energy_array", "wavelength_array", "eqe_array", mode="before")
    @classmethod
    def coerce_to_list(cls, v):
        if v is None:
            return None
        return list(v) if not isinstance(v, list) else v


# ---------------------------------------------------------------------------
# Data manager
# ---------------------------------------------------------------------------


class EQEDataManager:
    """Holds all app state; no widget imports anywhere in this file."""

    def __init__(self):
        # Multi-index DataFrames -- set by load()
        self.curves: pd.DataFrame | None = (
            None  # 4-level: (sample_id, entry_idx, curve_idx, point_idx)
        )
        self.params: pd.DataFrame | None = None  # 3-level: (sample_id, entry_idx, curve_idx)
        self.entries: pd.DataFrame | None = None  # 2-level: (sample_id, entry_idx)
        self.properties: pd.DataFrame | None = None  # 1-level: sample_id
        self.sample_ids: pd.Series | None = None

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def is_loaded(self) -> bool:
        return self.curves is not None

    # ------------------------------------------------------------------
    # Loading
    # ------------------------------------------------------------------

    def load(self, url: str, token: str, batch_ids) -> bool:
        """Fetch data from the API and populate all DataFrames. Returns True on success."""
        try_sample_ids = get_ids_in_batch(url, token, batch_ids)
        raw = get_all_eqe(url, token, try_sample_ids)
        if not raw:
            return False
        descriptions = get_sample_description(url, token, list(raw.keys()))
        return self._build_from_raw(raw, descriptions)

    def load_offline(self, fixture_path) -> bool:
        """Load from a local fixture JSON file (offline / demo mode)."""
        import json

        with open(fixture_path) as f:
            fx = json.load(f)
        return self._build_from_raw(fx["measurements"], fx["descriptions"])

    def _build_from_raw(self, raw: dict, descriptions: dict) -> bool:
        existing_sample_ids = pd.Series(list(raw.keys()))
        if len(existing_sample_ids) == 0:
            return False

        curve_dfs: list[pd.DataFrame] = []
        param_rows: list[dict] = []
        entry_rows: list[dict] = []
        curve_keys: list[tuple] = []
        entry_keys: list[tuple] = []

        for sample_id, api_entries in raw.items():
            for entry_idx, eqe_entry in enumerate(api_entries):
                entry_data = eqe_entry[0]
                entry_keys.append((sample_id, entry_idx))
                entry_rows.append(
                    {
                        "entry_names": entry_data.get("name", ""),
                        "entry_description": entry_data.get("description", ""),
                    }
                )

                for curve_idx, measurement in enumerate(entry_data.get("eqe_data", [])):
                    try:
                        validated = EQECurveData(**measurement)
                        curve_dfs.append(
                            pd.DataFrame(
                                {
                                    "photon_energy_array": validated.photon_energy_array,
                                    "wavelength_array": validated.wavelength_array,
                                    "eqe_array": validated.eqe_array,
                                }
                            )
                        )
                        param_rows.append(
                            {
                                "light_bias": validated.light_bias,
                                "bandgap_eqe": validated.bandgap_eqe,
                                "integrated_jsc": validated.integrated_jsc,
                                "integrated_j0rad": validated.integrated_j0rad,
                                "voc_rad": validated.voc_rad,
                                "urbach_energy": validated.urbach_energy,
                                "urbach_energy_fit_std_dev": validated.urbach_energy_fit_std_dev,
                                "plot": False,
                                "name": "",
                            }
                        )
                        curve_keys.append((sample_id, entry_idx, curve_idx))
                    except Exception as exc:
                        ErrorHandler.log_error(
                            "Validation failed for %s / entry %s / curve %s"
                            % (sample_id, entry_idx, curve_idx),
                            exc,
                        )

        if not curve_dfs:
            return False

        param_mi = pd.MultiIndex.from_tuples(
            curve_keys, names=["sample_id", "entry_idx", "curve_idx"]
        )
        self.params = pd.DataFrame(param_rows, index=param_mi)
        self.curves = pd.concat(curve_dfs, keys=param_mi)

        entry_mi = pd.MultiIndex.from_tuples(entry_keys, names=["sample_id", "entry_idx"])
        self.entries = pd.DataFrame(entry_rows, index=entry_mi)

        self.sample_ids = existing_sample_ids
        self.properties = pd.DataFrame(
            {
                "description": pd.Series(descriptions, dtype=str),
                "name": pd.Series(dtype=str),
            }
        )
        return True

    # ------------------------------------------------------------------
    # Mutation helpers (called by gui_components after user confirms)
    # ------------------------------------------------------------------

    def apply_names_and_selection(
        self,
        sample_id: str,
        sample_name: str,
        selections: list[bool],
        curve_names: list[str],
    ) -> None:
        """Write confirmed names + visibility flags back to the DataFrames."""
        self.properties.loc[sample_id, "name"] = sample_name

        # params.loc[sample_id] has a 2-level (entry_idx, curve_idx) index.
        # Assigning a same-length list aligns by position.
        sub_index = self.params.loc[sample_id].index  # noqa: F841
        self.params.loc[sample_id, "plot"] = pd.array(selections, dtype=bool)
        self.params.loc[sample_id, "name"] = pd.array(curve_names, dtype=str)

    # ------------------------------------------------------------------
    # Summary helpers
    # ------------------------------------------------------------------

    def get_overview_table(self) -> pd.DataFrame:
        """Return a multi-level summary table (min/mean/std/max per sample)."""
        stat_cols = [
            "bandgap_eqe",
            "integrated_jsc",
            "integrated_j0rad",
            "voc_rad",
            "urbach_energy",
            "light_bias",
        ]
        columns = pd.MultiIndex.from_product([stat_cols, ["min", "mean", "mean std", "max"]])
        overview = pd.DataFrame(columns=columns)

        for col in stat_cols:
            for sid in self.sample_ids:
                series = self.params.loc[sid, col]
                overview.loc[sid, (col, "min")] = series.min()
                overview.loc[sid, (col, "mean")] = series.mean()
                overview.loc[sid, (col, "mean std")] = series.std()
                overview.loc[sid, (col, "max")] = series.max()
            all_series = self.params.loc[:, col]
            overview.loc["All Data", (col, "min")] = all_series.min()
            overview.loc["All Data", (col, "mean")] = all_series.mean()
            overview.loc["All Data", (col, "mean std")] = all_series.std()
            overview.loc["All Data", (col, "max")] = all_series.max()

        return overview

    def to_csv_dict(self) -> dict[str, str]:
        """Return a {filename: csv_string} dict for all four DataFrames."""
        return {
            "eqe_curve.csv": self.curves.to_csv(),
            "eqe_params.csv": self.params.to_csv(),
            "eqe_properties.csv": self.properties.to_csv(),
            "eqe_entries.csv": self.entries.to_csv(),
        }
