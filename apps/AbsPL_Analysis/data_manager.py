"""
data_manager.py
Handles all data loading, filtering, and transformation logic.
No widget dependencies -- safe to reuse with any GUI framework.
"""

import io
import logging

import pandas as pd
from hysprint_utils.api_calls import (
    get_all_eqe as _get_all_abspl,
)
from hysprint_utils.api_calls import (
    get_ids_in_batch,
    get_sample_description,
)
from hysprint_utils.config import ENTRY_TYPES
from hysprint_utils.error_handler import ErrorHandler
from hysprint_utils.schemas import SampleMeta
from pydantic import ValidationError, field_validator

logger = logging.getLogger(__name__)
MEASUREMENT_TYPE = ENTRY_TYPES["abspl"]
CATEGORY_COLUMNS = ["sample_id", "variation", "name"]


# ---------------------------------------------------------------------------
# Pydantic model
# ---------------------------------------------------------------------------


class AbsPlRow(SampleMeta):
    """
    One row of AbsPL data as returned by the NOMAD API.

    Scalar fields are optional floats -- None means the measurement was not
    recorded, which is different from zero.
    Array fields (wavelength, spectra) coerce numpy arrays and other
    iterables to plain Python lists so they serialise cleanly to a DataFrame.
    """

    # scalar measurement results
    luminescence_quantum_yield: float | None = None
    quasi_fermi_level_splitting: float | None = None
    quasi_fermi_level_splitting_het: float | None = None
    i_voc: float | None = None
    bandgap: float | None = None
    derived_jsc: float | None = None

    # array measurement results
    wavelength: list[float] | None = None
    luminescence_flux_density: list[float] | None = None
    raw_spectrum_counts: list[float] | None = None

    @field_validator(
        "wavelength",
        "luminescence_flux_density",
        "raw_spectrum_counts",
        mode="before",
    )
    @classmethod
    def coerce_to_list(cls, v):
        """Accept numpy arrays, tuples, or any iterable; pass None through."""
        if v is None:
            return None
        if isinstance(v, list):
            return v
        try:
            return list(v)
        except TypeError:
            return None


class AbsPlDataManager:
    """Manages AbsPL data: loading, filtering, and export."""

    def __init__(self, url: str, token: str):
        self.url = url
        self.token = token
        self.data: pd.DataFrame | None = None
        self.original_data: pd.DataFrame | None = None
        self._filter_log: list[str] = []

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def is_loaded(self) -> bool:
        return self.data is not None

    @property
    def numeric_columns(self) -> list[str]:
        if not self.is_loaded:
            return []
        return self.data.select_dtypes(include=["float64", "int64"]).columns.tolist()

    @property
    def category_columns(self) -> list[str]:
        return CATEGORY_COLUMNS

    @property
    def all_columns(self) -> list[str]:
        return self.numeric_columns + self.category_columns

    @property
    def filter_summary(self) -> str:
        if not self.is_loaded:
            return ""
        pct = 100 * len(self.data) / len(self.original_data)
        return f"{len(self.data)} rows remaining ({pct:.1f}% of {len(self.original_data)} original)"

    # ------------------------------------------------------------------
    # Data loading
    # ------------------------------------------------------------------

    def load(self, batch_ids: list[str]) -> bool:
        """Load AbsPL data for the given batch IDs. Returns True on success."""
        sample_ids = get_ids_in_batch(self.url, self.token, list(batch_ids))
        descriptions = get_sample_description(self.url, self.token, list(sample_ids))
        raw = _get_all_abspl(self.url, self.token, sample_ids, eqe_type=MEASUREMENT_TYPE)
        if not raw:
            return False
        return self._build_from_raw(raw, descriptions)

    def load_offline(self, fixture_path) -> bool:
        """Load from a local fixture JSON file (offline / demo mode)."""
        import json

        with open(fixture_path) as f:
            fx = json.load(f)
        return self._build_from_raw(fx["measurements"], fx["descriptions"])

    def _build_from_raw(self, raw: dict, descriptions: dict) -> bool:
        rows = []
        for sample_id, entries in raw.items():
            for entry in entries:
                for result in entry[0].get("results", []):
                    try:
                        validated = AbsPlRow(
                            **result,
                            sample_id=sample_id,
                            variation=descriptions.get(sample_id, ""),
                            name=entry[0].get("name", ""),
                        )
                        rows.append(validated.model_dump())
                    except ValidationError as e:
                        ErrorHandler.log_error("Validation failed for sample %s" % sample_id, e)

        if not rows:
            return False

        self.data = pd.DataFrame(rows)
        self.original_data = self.data.copy()
        self._filter_log = []
        return True

    # ------------------------------------------------------------------
    # Filtering
    # ------------------------------------------------------------------

    def apply_filter(self, column: str, min_val: float, max_val: float) -> tuple[bool, str]:
        """
        Apply a range filter on a numeric column.
        Returns (success, message).
        """
        if not self.is_loaded:
            return False, "No data loaded."
        if column not in self.data.columns:
            return False, f"Column '{column}' not found."
        if min_val > max_val:
            return (
                False,
                f"Min ({min_val:.4g}) cannot be greater than max ({max_val:.4g}).",
            )

        prev_len = len(self.data)
        self.data = self.data[(self.data[column] >= min_val) & (self.data[column] <= max_val)]
        removed = prev_len - len(self.data)
        self._filter_log.append(f"{column} in [{min_val:.4g}, {max_val:.4g}]")
        return True, f"Removed {removed} rows. {self.filter_summary}"

    def reset_filters(self) -> None:
        """Restore original data, clearing all filters."""
        if not self.is_loaded:
            return
        self.data = self.original_data.copy()
        self._filter_log = []

    # ------------------------------------------------------------------
    # Column helpers
    # ------------------------------------------------------------------

    def get_column_range(self, column: str) -> tuple[float, float]:
        """Return (min, max) for a column in current data."""
        return float(self.data[column].min()), float(self.data[column].max())

    def get_variations(self) -> list:
        if not self.is_loaded:
            return []
        return self.data["variation"].unique().tolist()

    def get_available_spectral_columns(self) -> list[str]:
        """Return spectral data columns that have at least some non-null data."""
        if not self.is_loaded:
            return []
        result = []
        for col in ["luminescence_flux_density", "raw_spectrum_counts"]:
            if col in self.data.columns and self.data[col].notna().any():
                result.append(col)
        return result

    # ------------------------------------------------------------------
    # Export
    # ------------------------------------------------------------------

    def to_csv_string(self) -> str:
        """Return current data as a CSV string."""
        buf = io.StringIO()
        self.data.to_csv(buf)
        return buf.getvalue()

    def get_pivot_table(self, value_col: str, group_by_col: str) -> pd.DataFrame:
        """Return a pivot DataFrame with group_by_col values as columns."""
        pivot = pd.DataFrame()
        for group_val in self.data[group_by_col].unique():
            subset = self.data[self.data[group_by_col] == group_val]
            pivot[group_val] = subset[value_col].reset_index(drop=True)
        return pivot

    def pivot_to_csv_string(self, value_col: str, group_by_col: str) -> str:
        """Return pivot table as a CSV string."""
        buf = io.StringIO()
        self.get_pivot_table(value_col, group_by_col).to_csv(buf)
        return buf.getvalue()
