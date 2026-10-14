# NOMAD field extractor (PeroDatabase downloader): user manual

## What the app is for

Pull chosen fields out of many NOMAD entries at once and download them as one CSV table. The
default is the public perovskite solar cell database on the central NOMAD, but any entry type on
the HZB Oasis works as well. You choose the columns in the app; no code is needed. The app only
reads from NOMAD.

## Data it needs

Nothing to prepare. Public data on the central NOMAD needs no login. For the HZB Oasis your token
(`NOMAD_CLIENT_ACCESS_TOKEN`, set on the Oasis for you) is used, so the extraction includes the
entries you may see. The token is never displayed.

## Step by step

1. **Server.** The *Server* list switches between the central public NOMAD (`nomad-lab.eu`, the
   default) and the HZB SE Oasis. The banner under it says who you are logged in as, or that you
   are using public data (no token, a token this server does not accept, or a server that could
   not be reached). Switching the server clears the earlier results and sets that server's
   default entry type.
2. **Which entries (entry type).** The entry type is the population to extract from. The default
   is `PerovskiteSolarCell` on the central NOMAD and blank (all entries) on the Oasis. The list
   suggests types the server reports (*Reload types* asks again); you can type one by hand, and
   blank always means every type.
   Why an entry type and not the field itself: NOMAD's search index does not list every field,
   and fields in repeating sections such as the band gap are usually missing from it, so the app
   takes all entries of the type and reads the value out of each entry's archive.
3. **Pick or type the fields.**
   - The *Catalog* list holds common solar-cell fields. Choosing one fills *Path* and *Name*;
     *Add field* turns it into a column. You start with no columns and add what you want.
   - You can also type any path by hand (for example
     `results.properties.optoelectronic.solar_cell.fill_factor`). *Test path* checks whether it
     exists in a small sample of the chosen population and in what share of it.
   - Two columns cannot have the same name. A field is removed again with its *remove* button.
   - A path you add that is not in the catalog yet is saved to the catalog file, so it is in the
     list next time.
4. **Extract and download.** Press *Extract*. The progress bar follows the real progress. When
   it is done you see, for each field, in how many percent of the rows it has a value, and a
   preview of the first 15 rows. Choose *All rows* or *Only rows with every selected field*; the
   download link says how many rows it holds. An extraction of more than 100 000 entries is
   refused: choose an entry type to narrow it down.

The *Debug log* at the bottom (folded) lists what the app asked the server; open it when
something does not work.

## About units

NOMAD stores values in SI units, which is not always what you expect. Band gaps, for example, are
stored in joules, so the catalog entry converts them to eV and says so in the column name (the
column is called `band_gap (eV)`). Fields you add by hand are saved without conversion; check the
stored unit before you rely on a number.

## The catalog file

The selectable fields are listed in `fields_catalog.json` in this app's folder. Each entry has a
label, a column name and a path, and optionally `unit_label` and `scale` for a unit conversion,
and `list_mode` set to `join` to keep all values of a list in one cell (used for DOI and
elements). Removing a column in the app does not remove it from the file; to clean up a wrong
entry, edit the file. More details for developers are in
[README.md](README.md).

## Known limits

- Reading each entry's archive takes time for large populations.
- The Oasis in the server list is always the HZB SE Oasis, whichever Oasis the app runs on.

## Contact

Questions and problems: open an issue on
[nomad-pv-analysis-apps](https://github.com/nomad-hzb/nomad-pv-analysis-apps/issues).
