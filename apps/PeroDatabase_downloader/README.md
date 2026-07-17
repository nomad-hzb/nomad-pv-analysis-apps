# NOMAD field extractor

A small Voila app for pulling selected fields out of NOMAD entries and
downloading them as a CSV. Adding or removing columns is a UI action, not
a code edit.

## Run it

```bash
pip install -r requirements.txt
voila nomad_extractor.ipynb
```

The notebook holds a single command. All logic lives in the modules.

## Server and authentication

The **Server** dropdown switches between NOMAD servers, listed in
`config.py`. It defaults to the public central NOMAD (`nomad-lab.eu`), with
the HZB Oasis as the other option. Each server carries a default scope (see
below). A token authenticates across Oasis instances; central public data
needs none, so if your Oasis token is not accepted on central the app just
uses public data and says so quietly. The banner names who is logged in
when a token verifies, for example on the Oasis. The token is never
displayed.

## Which entries (entry type)

The entry type is the population, and it has a per server default set in
`config.py`. Central defaults to `PerovskiteSolarCell`, the perovskite
database, which is almost certainly what you want there and keeps the query
from spanning all of NOMAD (millions of entries). The HZB Oasis defaults to
blank, meaning every entry. You can change it: the dropdown suggests types
the server reports, you can type one by hand, and blank always means all
types. The app does not auto-pick the largest type, since on an Oasis full
of measurements that is rarely the population you want.

This anchor matters because NOMAD's search index does not list every field.
Fields in repeating sections, such as `band_gap`, are usually not
searchable, so bounding on the field itself would miss almost all entries
that hold it. Bounding on entry type finds them all, and the value is read
from each entry's archive.

## How to use it

1. **Which entries (entry type).** The population, defaulting per server
   (perovskite database on central, everything on the HZB Oasis). Change it
   with the dropdown, type one by hand, or leave blank for all types.

2. **Pick or type fields.** The Catalog dropdown lists common solar cell
   fields. Selecting one fills the Path and Name boxes, and **Add field**
   turns it into a column. You start empty and add only what you want. You
   can also type any path by hand, for example
   `results.properties.optoelectronic.solar_cell.fill_factor`, and press
   **Test path** to check whether it resolves in a sample of the chosen
   population. Duplicate column names are rejected.

3. **Extract and download.** Press **Extract**. The app pulls every entry
   of the chosen type and reads your fields from each. The progress bar
   turns blue the moment you press the button and then tracks a true
   percentage. Afterwards you see per field coverage and a preview, and you
   can download either every row or only rows that have all selected
   fields.

## The catalog

`fields_catalog.json` is the menu behind the dropdown, and it is
persistent. When you add a path that is not already in it, that path is
written back to the file, so it stays in the dropdown after you close and
reopen the app. Paths picked from the dropdown are already in the file and
are not rewritten. Removing a column does not remove it from the catalog.
To prune a bad or mistyped entry, edit the file directly.

Each item is a label, a column name, and a path, with optional extras:

```json
{ "label": "Band gap (converted to eV)", "column": "band_gap",
  "path": "results.properties.electronic.band_gap.value",
  "unit_label": "eV", "scale": 6.241509074460763e18 }
```

`list_mode` set to `join` keeps every value of a list field in one cell,
which is why the DOI and Elements entries use it. `scale` and `unit_label`
handle unit conversion, described next. Hand added paths are saved with a
plain label and no conversion, so add `scale` or `unit_label` by editing
the file if a new field needs them.

## A note on units

NOMAD stores values in SI, which is not always what you expect. Band gaps
are stored in Joules, so the catalog applies a Joule to eV factor and
labels the column. Verify a stored unit before adding a `scale`, since
applying a factor to an already correct value produces nonsense. Short
circuit current density is a likely next candidate, since it is stored in
A/m2 and you probably want mA/cm2, a factor of 0.1.

## File layout

| File | Role |
| --- | --- |
| `config.py` | Constants and the `FieldSpec` column definition |
| `auth.py` | Reads and verifies the token, reports who is logged in |
| `fields_catalog.json` | Editable menu of selectable fields |
| `nomad_client.py` | Single API request, nothing else |
| `schema.py` | Extract by path, flatten, validate |
| `data_manager.py` | Field derived query, full extraction, coverage |
| `gui_components.py` | The ipywidgets interface |
| `app.py` | Wires the data manager to the GUI |
| `nomad_extractor.ipynb` | One launch command |

The business logic in `data_manager.py` and below has no dependency on
widgets, so moving to Dash later means rewriting only `gui_components.py`.

## Why entry type and not the field itself

NOMAD only indexes schema quantities for search, and repeating sections
such as `band_gap` are usually left out. So a query for "entries that have
a band gap value" returns only the small searchable subset, while the same
value is present and readable in the archive of tens of thousands of solar
cell entries. Bounding the population on `entry_type` (built in
`DataManager.build_query`) sidesteps this: it returns all entries of the
type, and the list aware accessor in `schema.py` reads the value out of the
array in each. This is why band gap now matches the counts from a direct
archive extraction rather than the searchable handful.
