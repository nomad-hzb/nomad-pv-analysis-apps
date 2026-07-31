# Schema coverage gaps

What this is: for every process type this app models, which of its own generated Excel
columns (`apps/Excel_creator/sheet_experiment.py`) have **no** autofill source in
`field_mappings.json` (`PROCESS_TYPE_FIELD_PATHS`) or `data_manager._DERIVED_FIELDS`.
This is about **autofill coverage**, not correctness - an unmapped field is still a
normal, manually-editable Excel column; it just never gets filled in automatically from
a template/override batch. Not a schema audit of the raw NOMAD archive either - only
columns this app already generates are in scope (see field_mappings.json's own `_readme`
for why: a column with no Excel header is noise to map, not a real gap).

Generated 2026-07-31 by diffing a "maximal config" (every optional numeric field capped
at 5, every boolean checkbox on - see script below) against `field_mappings.json` +
`_DERIVED_FIELDS`. Regenerate by running the script at the bottom whenever
`field_mappings.json` or `sheet_experiment.py` changes materially - this file is a
snapshot, not a live view.

## Summary

| Process type | Excel columns | Covered | Unmapped |
|---|---:|---:|---:|
| Experiment Info | 17 | 7 | 10 |
| ALD | 27 | 16 | 11 |
| Annealing | 15 | 4 | 11 |
| Blade Coating | 76 | 63 | 13 |
| Cleaning O2-Plasma | 29 | 18 | 11 |
| Cleaning UV-Ozone | 27 | 16 | 11 |
| Co-Evaporation | 64 | 53 | 11 |
| Dip Coating | 23 | 11 | 12 |
| Evaporation | 26 | 15 | 11 |
| Generic Process | 12 | 9 | 3 |
| Ink Recycling | 59 | 0 | 59 |
| Inkjet Printing | 88 | 77 | 11 |
| Laser Scribing | 21 | 10 | 11 |
| Slot Die Coating | 66 | 55 | 11 |
| Spin Coating | 91 | 79 | 12 |
| Sputtering | 23 | 12 | 11 |

## The universal 8-11: present on almost every process type

The same handful of column names show up as "unmapped" on nearly every process type.
Splitting these by whether they're actually worth fixing:

**Deliberately manual, not a gap** - `Datetime`, `Operator`, `Notes`. Confirmed in
field_mappings.json's own readme: "'Notes' was deliberately left unmapped for
consistency with every other process type in this file, none of which autofill Notes."
Datetime/Operator are per-entry administrative metadata (who ran this, when it was
entered into the spreadsheet) - there's no reason to expect these on a NOMAD process
step at all, and no process type currently maps them.

**Works for Generic Process only, unconfirmed elsewhere** - `Room temperature [°C]`,
`rel. humidity [%]`, and the 6 `GB start/end oxygen/water/temperature` columns. For
Generic Process these ARE covered, but via a different mechanism than a normal
`field_mappings.json` path: `hysprint_batch_parser.py`'s `map_generic_parameters()`
stores every Generic Process column (except Notes/Name) as a flat `process_parameters`
list rather than fixed archive attributes, and `data_manager._DERIVED_FIELDS` searches
that list by column name - live-verified against real batches HZB_ThNa_1_1/HZB_QuNa_1_1.
**Nobody has confirmed whether these same 8 fields exist as real archive attributes on
any OTHER process type** (Spin Coating, Evaporation, ...) - if a future real batch shows
non-Generic-Process atmosphere data for one of these columns, that's the next place to
look; don't assume they're mappable there without checking first.

## Confirmed permanently unmappable (do not attempt)

- **Spin Coating: `Spin Delay [s]`** - per field_mappings.json's readme, confirmed via
  direct read of `map_spin_coating()`: NOMAD's own parser never reads this column into
  any archive attribute. There is nothing to map; this is an upstream parser gap, not a
  gap in this app.

## Real, worth-investigating gaps

- **Ink Recycling: 0/59 covered.** Entirely separate mapper file
  (`nomad_hysprint.parsers.file_parser.ink_recycling_mappers.map_ink_recycling`), never
  fetched/mapped. Biggest single opportunity if Ink Recycling autofill is ever needed -
  fetch that file the same way `solar_cell_batch_mapping.py` was fetched for everything
  else.
- **Blade Coating: `Nozzle shape`, `Nozzle size [mm²]`** (13 unmapped vs. the usual 11) -
  these ARE mapped for Spin Coating/Slot Die Coating's own Gas Quenching block
  (`quenching.nozzle_shape`/`quenching.nozzle_size`), just never extended to Blade
  Coating specifically. Likely the same paths apply; not yet verified against a real
  Blade Coating batch with Gas Quenching data.
- **Dip Coating: `Layer thickness [nm]`** - already fixed for Spin Coating/Slot Die
  Coating/Blade Coating/Inkjet Printing (`layer[0].layer_thickness`); Dip Coating's
  identical solvent/solute block gap was deliberately left unfixed per the readme
  ("pending a real batch to verify against") - the same edit pattern (and probably the
  same `Layer thickness [nm]` path) likely applies here too.
- **Experiment Info: `Number of pixels`, `Pixel area [cm^2]`** - newly exposed as
  ordinary per-sample Experiment Info fields (previously gated behind an unreachable
  per-child-row UI that was removed in an earlier round - see data_manager.py git
  history around `PixelFieldSpec`'s removal). No `field_mappings.json` entry exists for
  either yet. Worth mapping once there's a real batch to verify the archive path
  against, following this file's live-verification discipline.

## Not real gaps (already explained by design, listed here so they don't get "fixed" by mistake)

- **Experiment Info: `Batch`, `Date`, `Project_Name`, `Subbatch`** - deliberately never
  autofilled even when other Experiment Info fields are (`EXPERIMENT_INFO_NEVER_AUTOFILLED`
  in data_manager.py) - copying them from a source batch would mislabel the new
  experiment as the source one, and Subbatch is purely computed.
- **Experiment Info: `Nomad ID`, `Sample`, `Variation`** - always computed at
  Excel-generation time (`generate_full_workbook`) or via the matrix, never sourced from
  an archive.
- **Evaporation: `Organic`** - shows as "covered" in this report (via
  `_DERIVED_FIELDS._derive_evaporation_organic`), not because it has a real archive path
  - the real archive encodes it implicitly (which of `organic_evaporation`/
  `inorganic_evaporation` is populated), not as its own attribute. Do not add a direct
  `field_mappings.json` path for it.

## Reproduction script

```python
import sys, os, json

ROOT = "<repo root>"
sys.path.insert(0, os.path.join(ROOT, "apps", "smart_databaser"))
sys.path.insert(0, os.path.join(ROOT, "apps", "Excel_creator"))
sys.path.insert(0, os.path.join(ROOT, "shared"))

import data_manager as dm
from openpyxl import Workbook
from sheet_experiment import add_experiment_sheet


def maximal_config(process_type: str) -> dict:
    config = dm.default_config_for(process_type)
    for key, _label, applicable_types, min_val, max_val in dm.NUMERIC_CONFIG_FIELDS:
        if process_type in applicable_types:
            config[key] = min(max_val, 5)  # cap - see this file's own header comment
    for key, _label, applicable_types in dm.BOOLEAN_CONFIG_FIELDS:
        if process_type in applicable_types:
            config[key] = True
    if process_type != "Experiment Info":
        config[dm.ATMOSPHERIC_CONFIG_KEY] = True
    return config


mappings = dm.PROCESS_TYPE_FIELD_PATHS
report = {}
for process_type in dm.AVAILABLE_PROCESSES:
    workbook = Workbook()
    seq = [{"process": "Experiment Info"}]
    if process_type != "Experiment Info":
        seq.append({"process": process_type, "config": maximal_config(process_type)})
    add_experiment_sheet(workbook, seq, is_testing=False)
    column_map = dm.build_column_map(workbook.active)
    target_index = 0 if process_type == "Experiment Info" else 1
    excel_keys = sorted({k for (i, k) in column_map if i == target_index})
    covered = set(mappings.get(process_type, {})) | set(dm._DERIVED_FIELDS.get(process_type, {}))
    unmapped = [k for k in excel_keys if k not in covered]
    report[process_type] = {
        "total_excel_columns": len(excel_keys),
        "covered": len(covered & set(excel_keys)),
        "unmapped": unmapped,
    }

print(json.dumps(report, indent=2))
```
