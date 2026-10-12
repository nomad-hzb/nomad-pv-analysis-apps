"""
data_manager.py – NMR Plotter
Pure Python / Pydantic. Zero widget imports.
"""

from __future__ import annotations

import logging

import pandas as pd
from pydantic import ValidationError, field_validator

from hysprint_utils.api_calls import (
    get_all_eqe as _get_all_nmr,
)
from hysprint_utils.api_calls import (
    get_ids_in_batch,
    get_sample_description,
)
from hysprint_utils.config import ENTRY_TYPES
from hysprint_utils.error_handler import ErrorHandler
from hysprint_utils.schemas import SampleMeta

logger = logging.getLogger(__name__)
MEASUREMENT_TYPE = ENTRY_TYPES["nmr"]


# ---------------------------------------------------------------------------
# Pydantic model
# ---------------------------------------------------------------------------


class NMRRow(SampleMeta):
    """One row of NMR data (one spectrum per sample entry)."""

    name: str = ""
    chemical_shift: list[float] | None = None
    intensity: list[float] | None = None

    @field_validator("chemical_shift", "intensity", mode="before")
    @classmethod
    def coerce_to_list(cls, v):
        if v is None:
            return None
        return list(v) if not isinstance(v, list) else v


# ---------------------------------------------------------------------------
# Data manager
# ---------------------------------------------------------------------------


class NMRDataManager:
    """Loads, validates, and holds NMR data. No widget state."""

    def __init__(self) -> None:
        self.data: pd.DataFrame | None = None
        self.original_data: pd.DataFrame | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def is_loaded(self) -> bool:
        return self.data is not None and not self.data.empty

    @property
    def sample_ids(self) -> list[str]:
        if not self.is_loaded:
            return []
        return list(self.data["sample_id"].unique())

    @property
    def measurement_ids(self) -> list[str]:
        """One id per NMR entry, in load order. A sample with a single measurement uses its
        sample_id; a sample measured more than once (repeat, other nucleus, other solvent)
        gets "<sample_id> #1", "<sample_id> #2", ... so every measurement can be picked,
        plotted and integrated, not just the first."""
        if not self.is_loaded:
            return []
        return list(self.data["measurement_id"])

    def load(self, url: str, token: str, batch_ids: tuple[str, ...]) -> bool:
        """Fetch NMR data for the given batch IDs. Returns True on success."""
        sample_ids = get_ids_in_batch(url, token, batch_ids)
        descriptions = get_sample_description(url, token, list(sample_ids))
        raw = _get_all_nmr(url, token, sample_ids, eqe_type=MEASUREMENT_TYPE)
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
        rows: list[dict] = []
        for sample_id, sample_entries in raw.items():
            for nmr_entry in sample_entries:
                entry_data = nmr_entry[0]
                try:
                    validated = NMRRow(
                        sample_id=sample_id,
                        variation=descriptions.get(sample_id, ""),
                        name=entry_data.get("name", ""),
                        chemical_shift=entry_data.get("data", {}).get("chemical_shift"),
                        intensity=entry_data.get("data", {}).get("intensity"),
                    )
                    rows.append(validated.model_dump())
                except ValidationError as exc:
                    ErrorHandler.log_error("Validation failed for sample %s" % sample_id, exc)

        if not rows:
            return False

        frame = pd.DataFrame(rows)
        counts = frame.groupby("sample_id")["sample_id"].transform("size")
        position = frame.groupby("sample_id").cumcount() + 1
        frame["measurement_id"] = [
            sid if n == 1 else f"{sid} #{k}"
            for sid, n, k in zip(frame["sample_id"], counts, position)
        ]
        self.data = frame
        self.original_data = self.data.copy()
        return True

    def get_sample_label(self, sample_id: str) -> str:
        """Return display label: variation (sample_id) if variation differs."""
        if not self.is_loaded:
            return sample_id
        row = self.data[self.data["sample_id"] == sample_id]
        if row.empty:
            return sample_id
        variation = row["variation"].iloc[0]
        if variation and variation != sample_id:
            return f"{variation} ({sample_id})"
        return sample_id

    def get_measurement_label(self, measurement_id: str) -> str:
        """Display label of one measurement: the sample label, plus the entry name (or its
        number) when the sample has several measurements."""
        row = self.data[self.data["measurement_id"] == measurement_id]
        if row.empty:
            return measurement_id
        sample_id = row["sample_id"].iloc[0]
        label = self.get_sample_label(sample_id)
        if measurement_id == sample_id:
            return label
        name = row["name"].iloc[0]
        suffix = name if name else measurement_id[len(sample_id) :].strip()
        return f"{label} - {suffix}"

    def get_spectrum(self, measurement_id: str) -> tuple[list[float], list[float]]:
        """Return (chemical_shift, intensity) of one measurement (see measurement_ids)."""
        row = self.data[self.data["measurement_id"] == measurement_id].iloc[0]
        return row["chemical_shift"], row["intensity"]
