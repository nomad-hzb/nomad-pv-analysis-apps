"""
data_manager.py
Pure-Python data layer for the Hansen unified app.
No widget imports. No global state.
"""

from __future__ import annotations

import io
import logging
import re
import warnings
from typing import Optional

import numpy as np
import pandas as pd
from scipy.optimize import minimize

logger = logging.getLogger(__name__)
# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# SolventDataManager  (db.csv)
# ---------------------------------------------------------------------------

SOLVENT_DB_EXCLUDE = {
    "D",
    "P",
    "H",
    "Name",
    "CAS",
    "SMILES",
    "alias",
    "synonyms",
    "Note",
    "No.",
    "no",
}


class SolventDataManager:
    """Loads and queries db.csv."""

    def __init__(self, csv_path: str = "db.csv"):
        self.csv_path = csv_path
        self.data: pd.DataFrame = pd.DataFrame()
        self._loaded = False

    # ------------------------------------------------------------------
    @property
    def is_loaded(self) -> bool:
        return self._loaded and len(self.data) > 0

    def load(self) -> tuple[bool, str]:
        try:
            raw = pd.read_csv(self.csv_path)
            raw.columns = raw.columns.str.strip()
            raw = raw.dropna(subset=["D", "P", "H"])
            if raw.empty:
                return False, "No rows with D/P/H values found."
            self.data = raw.reset_index(drop=True)
            self._loaded = True
            return True, f"Loaded {len(self.data)} solvents."
        except FileNotFoundError:
            return False, f"File not found: {self.csv_path}"
        except Exception as exc:
            return False, str(exc)

    # ------------------------------------------------------------------
    def search(self, term: str) -> pd.DataFrame:
        """Return rows where name, CAS, or synonyms match term."""
        if not term.strip() or not self.is_loaded:
            return pd.DataFrame()
        t = term.strip().lower()
        mask = pd.Series(False, index=self.data.index)
        for col in ("Name", "CAS", "synonyms"):
            if col in self.data.columns:
                mask |= self.data[col].astype(str).str.lower().str.contains(t, na=False)
        return self.data[mask].copy()

    def all_solvents(self) -> pd.DataFrame:
        """Every solvent of the database (what the pick lists show before anything is typed)."""
        return self.data.copy() if self.is_loaded else pd.DataFrame()

    def get_by_index(self, idx: int) -> Optional[pd.Series]:
        if idx in self.data.index:
            return self.data.loc[idx]
        return None

    @property
    def numeric_columns(self) -> list[str]:
        if not self.is_loaded:
            return []
        exclude = SOLVENT_DB_EXCLUDE
        cols = []
        for c in self.data.columns:
            if c in exclude:
                continue
            if pd.api.types.is_numeric_dtype(self.data[c]):
                cols.append(c)
        return sorted(cols)

    @property
    def all_columns(self) -> list[str]:
        return list(self.data.columns) if self.is_loaded else []


# ---------------------------------------------------------------------------
# InkDataManager  (PlottedInks.xlsx -> Inks sheet)
# ---------------------------------------------------------------------------


class InkDataManager:
    """Loads and queries the Inks sheet from PlottedInks.xlsx."""

    def __init__(self, xlsx_path: str = "PlottedInks.xlsx", sheet: str = "Inks"):
        self.xlsx_path = xlsx_path
        self.sheet = sheet
        self.data: pd.DataFrame = pd.DataFrame()
        self._loaded = False

    @property
    def is_loaded(self) -> bool:
        return self._loaded and len(self.data) > 0

    def load(self) -> tuple[bool, str]:
        try:
            raw = pd.read_excel(self.xlsx_path, sheet_name=self.sheet)
            raw = raw.dropna(subset=["D", "P", "H"])
            if raw.empty:
                return False, "No rows with D/P/H values found."
            raw["formatted_solvents"] = raw["Solvents"].apply(_format_solvents)
            self.data = raw.reset_index(drop=True)
            self._loaded = True
            return True, f"Loaded {len(self.data)} ink data points."
        except Exception as exc:
            return False, str(exc)

    @property
    def solute_list(self) -> list[str]:
        if not self.is_loaded or "Solutes" not in self.data.columns:
            return []
        return sorted(self.data["Solutes"].dropna().unique().tolist())


# ---------------------------------------------------------------------------
# PerovskiteDataManager  (PlottedInks.xlsx -> Sheet2 / Sheet3)
# ---------------------------------------------------------------------------

PEROVSKITE_COLOR_COLS = ["DN", "BP", "heat of Vap", "hov_temp", "mw", "vis_temp", "Viscosity"]

# Sheet3 of PlottedInks.xlsx spells several columns differently from Sheet2 ("Solutes", "bp",
# "Hov Temp", "MW", "Vis Temp"). Matched case-insensitively and mapped to the Sheet2 names, so
# the solute filter, the hover text and the colour options work on both sheets.
PEROVSKITE_COLUMN_ALIASES = {
    "solutes": "Solute",
    "solute": "Solute",
    "solvents": "Solvent",
    "solvent": "Solvent",
    "bp": "BP",
    "hov temp": "hov_temp",
    "hov_temp": "hov_temp",
    "mw": "mw",
    "vis temp": "vis_temp",
    "vis_temp": "vis_temp",
    "heat of vap": "heat of Vap",
    "dn": "DN",
    "viscosity": "Viscosity",
    "stability": "Stability",
}


def normalise_perovskite_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Rename a perovskite sheet's columns to the canonical names (see
    PEROVSKITE_COLUMN_ALIASES); columns without an alias are kept as they are."""
    renames = {}
    for column in df.columns:
        canonical = PEROVSKITE_COLUMN_ALIASES.get(str(column).strip().lower())
        if canonical and canonical != column and canonical not in df.columns:
            renames[column] = canonical
    return df.rename(columns=renames)


class PerovskiteDataManager:
    """Loads and queries perovskite data from PlottedInks.xlsx."""

    def __init__(self, xlsx_path: str = "PlottedInks.xlsx"):
        self.xlsx_path = xlsx_path
        # Two separate datasets: Sheet2 (Solute vs Solvent) and Sheet3
        self.sheet2: pd.DataFrame = pd.DataFrame()
        self.sheet3: pd.DataFrame = pd.DataFrame()
        self._loaded = False

    @property
    def is_loaded(self) -> bool:
        return self._loaded

    def load(self) -> tuple[bool, str]:
        msgs = []
        for attr, sheet in (("sheet2", "Sheet2"), ("sheet3", "Sheet3")):
            try:
                raw = pd.read_excel(self.xlsx_path, sheet_name=sheet)
                raw = raw.dropna(subset=["D", "P", "H"])
                raw = normalise_perovskite_columns(raw)
                setattr(self, attr, raw.reset_index(drop=True))
                msgs.append(f"{sheet}: {len(raw)} rows")
            except Exception as exc:
                msgs.append(f"{sheet}: failed ({exc})")
        self._loaded = not (self.sheet2.empty and self.sheet3.empty)
        return self._loaded, "  |  ".join(msgs)

    def get_sheet(self, sheet_key: str) -> pd.DataFrame:
        """sheet_key: 'Sheet2' or 'Sheet3'"""
        return self.sheet2 if sheet_key == "Sheet2" else self.sheet3

    def solute_list(self, sheet_key: str) -> list[str]:
        df = self.get_sheet(sheet_key)
        if df.empty or "Solute" not in df.columns:
            return []
        return sorted(df["Solute"].dropna().unique().tolist())

    def color_columns(self, sheet_key: str) -> list[str]:
        df = self.get_sheet(sheet_key)
        return [c for c in PEROVSKITE_COLOR_COLS if c in df.columns]


# ---------------------------------------------------------------------------
# Blend optimisation helpers
# ---------------------------------------------------------------------------


def find_optimal_blend(
    target_hsp: list[float],
    selected_df: pd.DataFrame,
    min_percentage: float = 0.02,
) -> tuple[np.ndarray, float, list[float]]:
    """Minimise HSP distance via SLSQP.  Returns (fractions, distance, blend_hsp)."""
    D_vals = selected_df["D"].values
    P_vals = selected_df["P"].values
    H_vals = selected_df["H"].values
    n = len(selected_df)

    if n == 0:
        return np.array([]), float("inf"), [0.0, 0.0, 0.0]

    def objective(x):
        bD = np.dot(x, D_vals)
        bP = np.dot(x, P_vals)
        bH = np.dot(x, H_vals)
        return np.sqrt(
            4 * (bD - target_hsp[0]) ** 2 + (bP - target_hsp[1]) ** 2 + (bH - target_hsp[2]) ** 2
        )

    if n * min_percentage > 1.0:
        min_percentage = 1.0 / n

    constraints = [{"type": "eq", "fun": lambda x: np.sum(x) - 1.0}]
    bounds = [(min_percentage, 1.0)] * n
    x0 = np.full(n, min_percentage)
    x0[0] = 1.0 - (n - 1) * min_percentage

    try:
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", category=RuntimeWarning)
            result = minimize(objective, x0, method="SLSQP", bounds=bounds, constraints=constraints)
        bD = np.dot(result.x, D_vals)
        bP = np.dot(result.x, P_vals)
        bH = np.dot(result.x, H_vals)
        return result.x, float(result.fun), [bD, bP, bH]
    except Exception:
        eq = np.ones(n) / n
        bD, bP, bH = np.dot(eq, D_vals), np.dot(eq, P_vals), np.dot(eq, H_vals)
        dist = objective(eq)
        return eq, float(dist), [bD, bP, bH]


def weighted_average(
    selected: dict,  # {solvent_no: {'data': pd.Series, 'percentage': float}}
    df: pd.DataFrame,
) -> dict[str, Optional[float]]:
    """Compute weighted average of all numeric columns."""
    numeric_cols = [
        c
        for c in df.columns
        if c not in {"No.", "Name", "CAS", "SMILES", "alias", "synonyms", "Note"}
        and pd.api.types.is_numeric_dtype(df[c])
    ]
    results: dict[str, Optional[float]] = {}
    for col in numeric_cols:
        wsum = 0.0
        wtot = 0.0
        for info in selected.values():
            val = info["data"].get(col)
            pct = info["percentage"]
            if val is not None and pd.notna(val):
                try:
                    wsum += float(val) * (pct / 100.0)
                    wtot += pct / 100.0
                except (TypeError, ValueError):
                    pass
        results[col] = (wsum / wtot) if wtot > 0 else None
    return results


# ---------------------------------------------------------------------------
# Sphere geometry helpers (for Inks tab)
# ---------------------------------------------------------------------------


HANSEN_D_WEIGHT = 2.0  # Ra = sqrt(4 dD^2 + dP^2 + dH^2): dD counts twice


def calculate_enclosing_sphere(
    group_df: pd.DataFrame,
    d_scale: float = 1.0,
) -> tuple[np.ndarray, float]:
    """Centre and radius of the sphere around a group of points, in the space whose D axis is
    multiplied by d_scale. With d_scale = HANSEN_D_WEIGHT the radius is the largest Hansen
    distance Ra from the centre, and the sphere is a true Hansen sphere in that space."""
    scale = np.array([d_scale, 1.0, 1.0])
    pts = group_df[["D", "P", "H"]].values.astype(float) * scale
    if len(group_df) == 1:
        return pts[0], 0.1
    center = pts.mean(axis=0)
    dists = np.linalg.norm(pts - center, axis=1)
    return center, float(dists.max()) * 1.05


def create_sphere_mesh(
    center: np.ndarray, radius: float, resolution: int = 20
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    u = np.linspace(0, 2 * np.pi, resolution)
    v = np.linspace(0, np.pi, resolution)
    x = center[0] + radius * np.outer(np.cos(u), np.sin(v))
    y = center[1] + radius * np.outer(np.sin(u), np.sin(v))
    z = center[2] + radius * np.outer(np.ones(resolution), np.cos(v))
    return x, y, z


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


def _format_solvents(s) -> str:
    if pd.isna(s):
        return "No solvents data"
    matches = re.findall(r"([A-Za-z0-9]+)\(([0-9.]+)\)", str(s))
    if not matches:
        return str(s)
    lines = ["<b>Solvents:</b>"]
    for name, frac in matches:
        lines.append(f"&nbsp;&nbsp;&nbsp;{name} ({float(frac) * 100:.0f}%)")
    return "<br>".join(lines)


def export_blend_csv(
    target_hsp: list[float],
    blend_hsp: list[float],
    distance: float,
    results_df: pd.DataFrame,
    selected_df: pd.DataFrame,
    temperature_k: Optional[float] = None,
) -> str:
    """Return CSV string for blend results."""
    summary = {
        "Parameter": [
            "Target_D",
            "Target_P",
            "Target_H",
            "Blend_D",
            "Blend_P",
            "Blend_H",
            "HSP_Distance",
        ],
        "Value": [*target_hsp, *blend_hsp, distance],
    }
    if temperature_k is not None:
        summary["Parameter"] += ["Temperature_K", "Temperature_C"]
        summary["Value"] += [temperature_k, temperature_k - 273.15]
    buf = io.StringIO()
    buf.write("# Summary\n")
    pd.DataFrame(summary).to_csv(buf, index=False)
    buf.write("\n# Solvent Blend\n")
    results_df.to_csv(buf, index=False)
    buf.write("\n# All Selected Solvents\n")
    cols = ["Name", "D", "P", "H"] + (["DN"] if "DN" in selected_df.columns else [])
    selected_df[cols].to_csv(buf, index=False)
    return buf.getvalue()
