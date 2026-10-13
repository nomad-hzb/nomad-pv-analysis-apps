"""
data_manager.py
---------------
Pure Python / Pydantic layer for the Wetting Envelope app.
No widget imports. No global state.
"""

from __future__ import annotations

import logging

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

PRESET_MATERIALS: list[dict] = [
    {"name": "Material 1", "polar": 5.43, "dispersive": 40.00, "theta": 0.0},
    {"name": "Material 2", "polar": 0.23, "dispersive": 48.43, "theta": 0.0},
    {"name": "PTFE", "polar": 0.00, "dispersive": 18.00, "theta": 0.0},
    {"name": "Polypropylene (PP)", "polar": 0.00, "dispersive": 30.10, "theta": 0.0},
    {"name": "Polyethylene (PE)", "polar": 0.00, "dispersive": 33.20, "theta": 0.0},
    {"name": "Polystyrene (PS)", "polar": 1.10, "dispersive": 42.00, "theta": 0.0},
    {"name": "PMMA", "polar": 6.60, "dispersive": 35.90, "theta": 0.0},
    {"name": "Nylon 6,6", "polar": 11.80, "dispersive": 36.40, "theta": 0.0},
    {"name": "PET", "polar": 6.20, "dispersive": 35.60, "theta": 0.0},
    {"name": "Glass (SiO2)", "polar": 62.00, "dispersive": 22.00, "theta": 0.0},
]

# Contact angles up to this are accepted (180 gives an infinite envelope).
MAX_THETA = 179.0

# Polar and dispersive parts add up to the liquid's surface tension. Ethanol and ethylene glycol
# follow the Accu Dyne Test table of surface tension components
# (https://www.accudynetest.com/surface_tension_print.html: ethanol 21.4 = 18.8 + 2.6, ethylene
# glycol 48 = 29 + 19). Isopropanol and acetone still hold their earlier values, which do not add
# up to the literature totals (23.0 and 25.2 mN/m, surface-tension.de, 20 C): they need a
# published split from one source. "Solvent 1/2" are unnamed placeholders.
PRESET_SOLVENTS: list[dict] = [
    {"name": "Solvent 1", "polar": 18.00, "dispersive": 29.00},
    {"name": "Solvent 2", "polar": 2.30, "dispersive": 25.50},
    {"name": "Water", "polar": 51.00, "dispersive": 21.80},
    {"name": "Ethanol", "polar": 2.60, "dispersive": 18.80},
    {"name": "Isopropanol (IPA)", "polar": 8.00, "dispersive": 20.93},
    {"name": "Acetone", "polar": 10.00, "dispersive": 16.35},
    {"name": "Diiodomethane", "polar": 0.00, "dispersive": 50.80},
    {"name": "Formamide", "polar": 18.70, "dispersive": 39.50},
    {"name": "Ethylene glycol", "polar": 19.00, "dispersive": 29.00},
    {"name": "Toluene", "polar": 1.40, "dispersive": 28.50},
    {"name": "Hexane", "polar": 0.00, "dispersive": 18.40},
    {"name": "Chloroform", "polar": 3.80, "dispersive": 23.70},
]

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
