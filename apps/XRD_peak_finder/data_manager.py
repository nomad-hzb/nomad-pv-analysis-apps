"""
data_manager.py — XY Visualizer
Pure Python, no widget imports. Holds app state and validates API data.
"""

from __future__ import annotations

import logging
import re
from typing import Optional

import numpy as np
import pandas as pd
from hysprint_utils.api_calls import (
    get_all_batches_wth_data,
    get_ids_in_batch,
    get_sample_description,
)
from hysprint_utils.api_calls import (
    get_all_eqe as get_all_xrd,
)
from hysprint_utils.config import ENTRY_TYPES
from hysprint_utils.error_handler import ErrorHandler
from hysprint_utils.schemas import SampleMeta
from pydantic import ValidationError, field_validator

logger = logging.getLogger(__name__)
MEASUREMENT_TYPE = ENTRY_TYPES["xrd"]


# ---------------------------------------------------------------------------
# Pydantic model
# ---------------------------------------------------------------------------


class XRDRow(SampleMeta):
    """One XRD measurement entry."""

    angle: Optional[list[float]] = None
    intensity: Optional[list[float]] = None
    meas_index: int = 0  # disambiguates multiple measurements per sample

    @field_validator("angle", "intensity", mode="before")
    @classmethod
    def coerce_to_list(cls, v):
        if v is None:
            return None
        if isinstance(v, np.ndarray):
            return v.tolist()
        return list(v) if not isinstance(v, list) else v


# ---------------------------------------------------------------------------
# XY file parser (kept here so it is widget-free and testable)
# ---------------------------------------------------------------------------


def parse_xy_file(file_content: str, filename: str) -> tuple[list[float], list[float], dict]:
    """Parse a .xy text file and return (x_data, y_data, metadata)."""
    lines = file_content.strip().split("\n")
    metadata: dict = {}

    if lines and lines[0].startswith("'Id:"):
        metadata_line = lines[0].strip("'")
        pattern = r'(\w+):\s*"([^"]*)"'
        matches = re.findall(pattern, metadata_line)
        metadata = dict(matches)

    x_data: list[float] = []
    y_data: list[float] = []
    for line in lines[1:]:
        if line.strip():
            try:
                parts = line.split()
                if len(parts) >= 2:
                    x_data.append(float(parts[0]))
                    y_data.append(float(parts[1]))
            except ValueError:
                continue

    return x_data, y_data, metadata


# ---------------------------------------------------------------------------
# Data manager
# ---------------------------------------------------------------------------


class XRDDataManager:
    """Holds all loaded XRD data. No widget imports."""

    def __init__(self, url: str, token: str) -> None:
        self._url = url
        self._token = token
        # data dict: key -> {angle, intensity, variation, name, sample_id}
        self.data: dict = {}
        self.original_data: dict = {}

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def is_loaded(self) -> bool:
        return bool(self.data)

    @property
    def sample_keys(self) -> list[str]:
        return list(self.data.keys())

    # ------------------------------------------------------------------
    # Load from API
    # ------------------------------------------------------------------

    def load(self, batch_ids: list[str]) -> bool:
        """Fetch XRD measurements for the given batch IDs. Returns True on success."""
        sample_ids = get_ids_in_batch(self._url, self._token, batch_ids)
        descriptions = get_sample_description(self._url, self._token, list(sample_ids))
        raw = get_all_xrd(self._url, self._token, sample_ids, eqe_type=MEASUREMENT_TYPE)
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
        result: dict = {}
        for sample_id, sample_data in raw.items():
            for i, xrd_entry in enumerate(sample_data):
                payload = xrd_entry[0]
                df_raw = pd.DataFrame(payload.get("data", {}))
                if df_raw.empty or df_raw.shape[1] < 2:
                    ErrorHandler.log_error(
                        "Sample %s entry %d: unexpected data shape -- skipping"
                        % (sample_id, i)
                    )
                    continue

                angle_raw = df_raw.iloc[:, 0].to_numpy()
                intensity_raw = df_raw.iloc[:, 1].to_numpy()

                try:
                    validated = XRDRow(
                        sample_id=sample_id,
                        variation=descriptions.get(sample_id, ""),
                        name=payload.get("name", ""),
                        angle=angle_raw,
                        intensity=intensity_raw,
                        meas_index=i,
                    )
                except ValidationError as exc:
                    ErrorHandler.log_error(
                        "Validation failed for sample %s entry %d" % (sample_id, i), exc
                    )
                    continue

                key = sample_id if len(sample_data) == 1 else f"{sample_id}_meas_{i + 1}"
                result[key] = {
                    "angle": validated.angle,
                    "intensity": validated.intensity,
                    "variation": validated.variation,
                    "name": validated.name,
                    "sample_id": sample_id,
                }

        if not result:
            return False

        self.data = result
        self.original_data = {k: dict(v) for k, v in result.items()}
        return True

    # ------------------------------------------------------------------
    # Load from uploaded .xy file (content already decoded as str)
    # ------------------------------------------------------------------

    def load_xy_file(self, filename: str, file_content: str) -> bool:
        """Parse and store a single .xy file. Returns True on success."""
        x_data, y_data, metadata = parse_xy_file(file_content, filename)
        if not x_data:
            logger.error("No data parsed from %s", filename)
            return False

        self.data[filename] = {
            "angle": x_data,
            "intensity": y_data,
            "variation": "",
            "name": filename,
            "sample_id": filename,
            "file_metadata": metadata,
        }
        self.original_data[filename] = dict(self.data[filename])
        return True

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def get_entry(self, key: str) -> dict:
        return self.data[key]

    def get_batches_with_data(self) -> list[str]:
        """Return batch IDs that actually contain XRD measurements."""
        return get_all_batches_wth_data(self._url, self._token, MEASUREMENT_TYPE)

    def to_csv_string(self) -> str:
        """Export all loaded data as a CSV string."""
        rows = []
        for key, entry in self.data.items():
            angle = entry.get("angle") or []
            intensity = entry.get("intensity") or []
            for a, i in zip(angle, intensity):
                rows.append(
                    {
                        "key": key,
                        "sample_id": entry.get("sample_id", ""),
                        "variation": entry.get("variation", ""),
                        "name": entry.get("name", ""),
                        "angle": a,
                        "intensity": i,
                    }
                )
        if not rows:
            return ""
        return pd.DataFrame(rows).to_csv()
