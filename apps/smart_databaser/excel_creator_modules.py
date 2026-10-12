# excel_creator_modules.py
# Loads the Excel_creator modules smart_databaser reuses (the sheet builders) from the
# sibling apps/Excel_creator folder by file path, without touching sys.path.
#
# Excel_creator is not an installable package (its modules import each other by bare
# name), so this replaces both the old "excel-creator" pyproject dependency, which never
# resolved (the name is not on PyPI), and the notebook's sys.path.insert fallback.

import importlib.util
import sys
from pathlib import Path

EXCEL_CREATOR_DIR = Path(__file__).resolve().parent.parent / "Excel_creator"

# Dependency order: experiment_excel_builder imports the three sheet modules by bare name,
# which resolve against the sys.modules entries registered before it.
_MODULE_NAMES = (
    "sheet_data_entry_guide",
    "sheet_how_to_cite",
    "sheet_experiment",
    "experiment_excel_builder",
)


def _load(name: str):
    existing = sys.modules.get(name)
    if existing is not None:
        return existing
    path = EXCEL_CREATOR_DIR / f"{name}.py"
    if not path.exists():
        raise ImportError(f"smart_databaser needs {path}; apps/Excel_creator must sit next to it")
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        del sys.modules[name]
        raise
    return module


_modules = {name: _load(name) for name in _MODULE_NAMES}

ExperimentExcelBuilder = _modules["experiment_excel_builder"].ExperimentExcelBuilder
add_experiment_sheet = _modules["sheet_experiment"].add_experiment_sheet
