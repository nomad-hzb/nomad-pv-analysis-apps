"""Shared test fixtures.  Never reads real CSV / Excel files."""
import importlib.util
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

_APP_DIR = Path(__file__).parent.parent.parent / "apps" / "Hansen_green_calculator"
_SHARED_DIR = _APP_DIR.parent.parent / "shared"

if str(_SHARED_DIR) not in sys.path:
    sys.path.insert(0, str(_SHARED_DIR))

sys.modules.pop("data_manager", None)
_spec = importlib.util.spec_from_file_location("dm_hansen", _APP_DIR / "data_manager.py")
_dm = importlib.util.module_from_spec(_spec)
sys.modules["dm_hansen"] = _dm
sys.modules["data_manager"] = _dm
_spec.loader.exec_module(_dm)

from data_manager import SolventDataManager, InkDataManager, PerovskiteDataManager  # noqa: E402


# ---------------------------------------------------------------------------
# Minimal solvent rows (matches db.csv shape)
# ---------------------------------------------------------------------------

SOLVENT_ROWS = [
    {"No.": 1, "Name": "Acetone",       "CAS": "67-64-1",  "D": 15.5, "P": 10.4, "H": 7.0, "DN": 17.0, "BP": 56.0,  "mw": 58.08},
    {"No.": 2, "Name": "Ethanol",        "CAS": "64-17-5",  "D": 15.8, "P": 8.8,  "H": 19.4,"DN": 20.0, "BP": 78.4,  "mw": 46.07},
    {"No.": 3, "Name": "Chloroform",     "CAS": "67-66-3",  "D": 17.8, "P": 3.1,  "H": 5.7, "DN": None, "BP": 61.2,  "mw": 119.38},
    {"No.": 4, "Name": "DMSO",           "CAS": "67-68-5",  "D": 18.4, "P": 16.4, "H": 10.2,"DN": 29.8, "BP": 189.0, "mw": 78.13},
    {"No.": 5, "Name": "Toluene",        "CAS": "108-88-3", "D": 18.0, "P": 1.4,  "H": 2.0, "DN": None, "BP": 110.6, "mw": 92.14},
]


@pytest.fixture
def solvent_df():
    return pd.DataFrame(SOLVENT_ROWS)


@pytest.fixture
def loaded_solvent_dm(solvent_df):
    """SolventDataManager with data pre-loaded (no CSV access)."""
    sdm = SolventDataManager.__new__(SolventDataManager)
    sdm.csv_path = "fake.csv"
    sdm.data = solvent_df.copy()
    sdm._loaded = True
    return sdm


# ---------------------------------------------------------------------------
# Minimal ink rows (PlottedInks.xlsx – Inks sheet)
# ---------------------------------------------------------------------------

INK_ROWS = [
    {"D": 15.5, "P": 10.4, "H": 7.0, "Solutes": "PbI2",  "Solvents": "DMSO(0.5)-DMF(0.5)", "Researcher": "Alice"},
    {"D": 18.4, "P": 16.4, "H": 10.2,"Solutes": "PbI2",  "Solvents": "DMSO(1.0)",            "Researcher": "Bob"},
    {"D": 15.8, "P": 8.8,  "H": 19.4,"Solutes": "MAPbI3","Solvents": "GBL(1.0)",              "Researcher": "Alice"},
]


@pytest.fixture
def ink_df():
    import re
    df = pd.DataFrame(INK_ROWS)

    def _fmt(s):
        if pd.isna(s):
            return "No solvents data"
        matches = re.findall(r"([A-Za-z0-9]+)\(([0-9.]+)\)", str(s))
        if not matches:
            return str(s)
        lines = ["<b>Solvents:</b>"]
        for n, f in matches:
            lines.append(f"&nbsp;&nbsp;&nbsp;{n} ({float(f)*100:.0f}%)")
        return "<br>".join(lines)

    df["formatted_solvents"] = df["Solvents"].apply(_fmt)
    return df


@pytest.fixture
def loaded_ink_dm(ink_df):
    idm = InkDataManager.__new__(InkDataManager)
    idm.xlsx_path = "fake.xlsx"
    idm.sheet = "Inks"
    idm.data = ink_df.copy()
    idm._loaded = True
    return idm


# ---------------------------------------------------------------------------
# Minimal perovskite rows (Sheet2 / Sheet3)
# ---------------------------------------------------------------------------

PEROV_ROWS = [
    {"D": 15.5, "P": 10.4, "H": 7.0,  "Solute": "MAPbI3", "Solvent": "DMSO",  "Stability": "Stable",     "DN": 29.8},
    {"D": 18.4, "P": 16.4, "H": 10.2, "Solute": "MAPbI3", "Solvent": "DMF",   "Stability": "Semi-stable","DN": 26.6},
    {"D": 20.0, "P": 5.0,  "H": 4.0,  "Solute": "FAPbI3", "Solvent": "Toluene","Stability": "Not stable", "DN": None},
]


@pytest.fixture
def perov_df():
    return pd.DataFrame(PEROV_ROWS)


@pytest.fixture
def loaded_perov_dm(perov_df):
    pdm = PerovskiteDataManager.__new__(PerovskiteDataManager)
    pdm.xlsx_path = "fake.xlsx"
    pdm.sheet2 = perov_df.copy()
    pdm.sheet3 = perov_df.copy()
    pdm._loaded = True
    return pdm
