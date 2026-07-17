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
        if not (0.0 <= v <= 180.0):
            raise ValueError(f"Contact angle must be in [0, 180], got {v}")
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

PRESET_SOLVENTS: list[dict] = [
    {"name": "Solvent 1", "polar": 18.00, "dispersive": 29.00},
    {"name": "Solvent 2", "polar": 2.30, "dispersive": 25.50},
    {"name": "Water", "polar": 51.00, "dispersive": 21.80},
    {"name": "Ethanol", "polar": 8.10, "dispersive": 21.40},
    {"name": "Isopropanol (IPA)", "polar": 8.00, "dispersive": 20.93},
    {"name": "Acetone", "polar": 10.00, "dispersive": 16.35},
    {"name": "Diiodomethane", "polar": 0.00, "dispersive": 50.80},
    {"name": "Formamide", "polar": 18.70, "dispersive": 39.50},
    {"name": "Ethylene glycol", "polar": 11.00, "dispersive": 29.00},
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
    def envelope_xy(
        material: Material,
        correction_exp: float = 2.0,
    ) -> tuple[np.ndarray, np.ndarray]:
        phi = np.linspace(0, np.pi / 2, WettingCalculator.N_POINTS)
        R = WettingCalculator._r_base(phi, material.polar, material.dispersive)
        theta_rad = np.radians(material.theta)
        correction = (2.0 / (1.0 + np.cos(theta_rad))) ** correction_exp
        R = R * correction
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
