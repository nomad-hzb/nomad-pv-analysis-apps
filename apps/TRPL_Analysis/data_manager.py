"""
TRPL Data Manager
=================
Pure Python, no widget imports.  Handles API calls, Pydantic validation,
filtering, and export.  All data state lives on the instance.
"""

from __future__ import annotations

import logging
from typing import Optional

import pandas as pd
import requests
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
from pydantic import ValidationError, field_validator

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
                    data_file = ".".join(data_file.split(".")[1:-2])

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
