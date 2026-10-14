"""
data_manager.py
---------------
Pure Python / Pydantic layer for the Wetting Envelope app.
No widget imports. No global state.
"""

from __future__ import annotations

import csv
import logging
from pathlib import Path

import numpy as np
from pydantic import BaseModel, ValidationError, field_validator

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Domain models
# ---------------------------------------------------------------------------


class Material(BaseModel):
    name: str
    polar: float
    dispersive: float
    theta: float = 0.0

    @field_validator("polar", "dispersive", mode="before")
    @classmethod
    def coerce_float(cls, v):
        return float(v)

    @field_validator("theta", mode="before")
    @classmethod
    def clamp_theta(cls, v):
        v = float(v)
        # at 180 degrees the envelope is infinite (2 / (1 + cos 180) divides by zero)
        if not (0.0 <= v <= MAX_THETA):
            raise ValueError(f"Contact angle must be in [0, {MAX_THETA:g}], got {v}")
        return v


class Solvent(BaseModel):
    name: str
    polar: float
    dispersive: float

    @field_validator("polar", "dispersive", mode="before")
    @classmethod
    def coerce_float(cls, v):
        return float(v)


# ---------------------------------------------------------------------------
# Preset library
# ---------------------------------------------------------------------------

# The preset libraries are CSV files next to this module (open them on GitHub, edit them in a
# spreadsheet): solvent_presets.csv (name, polar, dispersive, literature_total, source,
# reference_url, note) and material_presets.csv (name, polar, dispersive, theta, source,
# reference_url, note). Polar and dispersive parts of a solvent add up to its surface tension in
# mN/m; a row whose parts do not match its literature_total is flagged in the app.
_APP_DIR = Path(__file__).resolve().parent
SOLVENT_PRESETS_FILE = "solvent_presets.csv"
MATERIAL_PRESETS_FILE = "material_presets.csv"
GITHUB_BLOB_URL = (
    "https://github.com/nomad-hzb/nomad-pv-analysis-apps/blob/main/apps/Wetting_envelope"
)

# Contact angles up to this are accepted (180 gives an infinite envelope).
MAX_THETA = 179.0


PRESET_LOAD_ERRORS: list[str] = []


def load_presets(filename: str) -> list[dict]:
    """The rows of a preset CSV as dicts: the numeric columns as floats, empty cells as None.

    A file that is missing or cannot be read gives no presets (the app still starts, the values
    can be typed in) and the reason is kept in PRESET_LOAD_ERRORS for the app to show."""
    numeric = {"polar", "dispersive", "theta", "literature_total"}
    rows = []
    try:
        with open(_APP_DIR / filename, encoding="utf-8", newline="") as handle:
            for raw in csv.DictReader(handle):
                row = {}
                for key, value in raw.items():
                    value = (value or "").strip()
                    row[key] = (float(value) if key in numeric else value) if value else None
                rows.append(row)
    except (OSError, ValueError) as exc:
        logger.error("Could not read the presets in %s: %s", filename, exc)
        PRESET_LOAD_ERRORS.append(f"{filename}: {exc}")
        return []
    return rows


PRESET_MATERIALS: list[dict] = load_presets(MATERIAL_PRESETS_FILE)
PRESET_SOLVENTS: list[dict] = load_presets(SOLVENT_PRESETS_FILE)
DATA_FILE_URL = f"{GITHUB_BLOB_URL}/{SOLVENT_PRESETS_FILE}"
MATERIALS_FILE_URL = f"{GITHUB_BLOB_URL}/{MATERIAL_PRESETS_FILE}"


def solvent_preset_note(name: str) -> str:
    """One line for the app under the solvent preset: where the values come from and whether
    they add up to the literature total."""
    preset = get_preset_solvent(name)
    if preset is None:
        return ""
    total = preset["polar"] + preset["dispersive"]
    source = preset.get("source") or "the split has no recorded source"
    note = f"Polar + dispersive = {total:.1f} mN/m; {source}."
    literature = preset.get("literature_total")
    if literature is not None:
        note += f" Literature total {literature:g} mN/m."
        if abs(total - literature) > 1.0:
            note += " These values do not add up to it: check them before relying on this liquid."
    if preset.get("note"):
        note += f" {preset['note']}."
    return note


# Names used by the preset dropdowns as a sentinel for "nothing selected"
_NO_SELECTION = "-- select preset --"

PRESET_MATERIAL_OPTIONS: list[str] = [_NO_SELECTION] + [m["name"] for m in PRESET_MATERIALS]
PRESET_SOLVENT_OPTIONS: list[str] = [_NO_SELECTION] + [s["name"] for s in PRESET_SOLVENTS]


def get_preset_material(name: str) -> dict | None:
    return next((m for m in PRESET_MATERIALS if m["name"] == name), None)


def get_preset_solvent(name: str) -> dict | None:
    return next((s for s in PRESET_SOLVENTS if s["name"] == name), None)


# ---------------------------------------------------------------------------
# Calculation helpers
# ---------------------------------------------------------------------------


class WettingCalculator:
    N_POINTS: int = 1000

    @staticmethod
    def _r_base(phi: np.ndarray, sigma_s_p: float, sigma_s_d: float) -> np.ndarray:
        cos_phi = np.cos(phi)
        sin_phi = np.sin(phi)
        numerator = np.sqrt(cos_phi * sigma_s_d) + np.sqrt(sin_phi * sigma_s_p)
        denominator = cos_phi + sin_phi
        return (numerator / denominator) ** 2

    @staticmethod
    def envelope_xy(material: Material) -> tuple[np.ndarray, np.ndarray]:
        """The boundary of the liquids that wet the material with at most its contact angle.

        OWRK: gamma_L (1 + cos theta) = 2 (sqrt(gs_d gl_d) + sqrt(gs_p gl_p)). In polar
        coordinates (x = dispersive, y = polar part of the liquid) this is
        R = R_base(phi) * (2 / (1 + cos theta))**2, with the exponent exactly 2 (it used to
        be an adjustable "correction exponent", which traced another angle than the label)."""
        phi = np.linspace(0, np.pi / 2, WettingCalculator.N_POINTS)
        R = WettingCalculator._r_base(phi, material.polar, material.dispersive)
        theta_rad = np.radians(material.theta)
        R = R * (2.0 / (1.0 + np.cos(theta_rad))) ** 2
        return R * np.cos(phi), R * np.sin(phi)


# ---------------------------------------------------------------------------
# State container
# ---------------------------------------------------------------------------


class WettingDataManager:
    def __init__(self) -> None:
        self.materials: list[Material] = []
        self.solvents: list[Solvent] = []

    def add_material(
        self, name: str, polar: float, dispersive: float, theta: float = 0.0
    ) -> tuple[bool, str]:
        try:
            self.materials.append(
                Material(name=name, polar=polar, dispersive=dispersive, theta=theta)
            )
            return True, f"Added '{name}'."
        except ValidationError as e:
            return False, str(e)

    def add_solvent(self, name: str, polar: float, dispersive: float) -> tuple[bool, str]:
        try:
            self.solvents.append(Solvent(name=name, polar=polar, dispersive=dispersive))
            return True, f"Added '{name}'."
        except ValidationError as e:
            return False, str(e)

    def remove_material(self, index: int) -> None:
        if 0 <= index < len(self.materials):
            self.materials.pop(index)

    def remove_solvent(self, index: int) -> None:
        if 0 <= index < len(self.solvents):
            self.solvents.pop(index)

    def clear(self) -> None:
        self.materials.clear()
        self.solvents.clear()

    @property
    def has_data(self) -> bool:
        return bool(self.materials)
