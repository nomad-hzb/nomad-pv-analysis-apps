# Excel Creator: user manual

## What the app is for

Build the Excel file in which you describe the fabrication sequence of a batch of samples
(substrate cleaning, coatings, evaporation, and so on). The finished file is uploaded to NOMAD
with the Smart Databaser, or by hand. The app builds the empty sheet with the right columns; you
fill in the values in Excel. It only contacts NOMAD when you open *Optional: prefill from
NOMAD* (see below).

## Step by step

1. **Pick a template.** Choose one in the *Template* list and press *Apply*, or keep the default
   "Empty Template", which holds only *Experiment Info*. Templates are stored in
   `templates/process_templates.json`. A template that cannot be applied (no name, no process
   sequence, or a process the app does not offer) is left out of the list and the reason is
   shown under *Status*.
2. **Adjust the process sequence.** Each row is one process step, in the order of the sheet.
   - The dropdown changes the process type (the first row, *Experiment Info*, is fixed).
     Changing the type resets that row's settings to the defaults of the new type.
   - The number boxes set how many columns of a kind the step gets (for example Solvents,
     Solutes and Steps of a Spin Coating); the checkboxes switch optional blocks on (for
     example Antisolvent, Gas Quenching).
   - *Add Atmospheric Values* (every step except *Experiment Info*) adds the columns for room
     temperature, humidity and the glovebox values.
   - The green **+** inserts a new step (a *Generic Process*) below the row; the red **-**
     removes it.
   - If one batch uses different methods for the same layer (for example spin coating and slot
     die coating), add each method as its own step.
3. **Choose what to generate.**
   - *Add example values on 1st row* (on by default): the first data row is filled with
     example values so you can see what each column expects. Delete that row before uploading
     the file: NOMAD would turn it into a sample. Off, the sheet is empty.
   - *Create README.md for annotations*: also offers a README template for the experiment
     (question, approach with your process list, results, next steps).
4. **Press *Generate Excel*.** A download link appears (`experiment_<date>_<time>.xlsx`). If
   the file cannot be built, the reason is shown under *Status* and no file is offered.

Process types you can choose: Experiment Info, ALD, Annealing, Blade Coating, Cleaning O2-Plasma,
Cleaning UV-Ozone, Co-Evaporation, Dip Coating, Evaporation, Generic Process, Ink Recycling,
Inkjet Printing, Laser Scribing, Screen Printing, Slot Die Coating, Spin Coating, Sputtering.

## The file you get

Three sheets:

- **Experiment Data**: row 1 names the steps, row 2 holds the column names, and the data rows
  start at row 3 (the example row, if you ticked it). The *Nomad ID* column is a formula for
  rows 3 to 500: it joins *Project_Name*, *Batch*, *Subbatch* and *Sample* as
  `HZB_<Project_Name>_<Batch>_<Subbatch>_C-<Sample>` and stays empty while *Project_Name* of
  that row is empty.
  Columns with a fixed list of choices have a dropdown for rows 3 to 1000.
- **Data Entry Guide**: a table per process type (field, description, format, unit, example).
  It is generated from the same catalogue as the columns, so it lists exactly the columns of
  the sheet.
- **How to Cite**: how to cite NOMAD and the code of the apps.

Do not add, rename or move columns: the upload only reads the columns the app created.

## Prefill from NOMAD (optional)

If the samples of the batch already exist in NOMAD (for example created by the In-Situ
Analyser), the sheet can start with them. Press *Optional: prefill from NOMAD* under *Generate
Excel*: a panel opens and lists your 100 newest NOMAD uploads. Pick the upload of the batch; the panel says
how many samples it found and which columns NOMAD has values for. *Generate Excel* then writes
one sample per row, sorted by name:

- its NOMAD lab_id into *Nomad ID* (instead of the formula),
- *Project_Name*, *Batch*, *Subbatch* and *Sample*, read back from a lab_id that has the form
  the formula makes (`HZB_<Project_Name>_<Batch>_<Subbatch>_C-<Sample>`); for any other lab_id
  these stay empty,
- everything NOMAD knows of the sample and its substrate: *Sample dimension*, *Sample area*,
  *Number of pixels*, *Pixel area*, *Substrate material*, *Substrate conductive layer* (the
  first one listed), *Sheet Resistance*, *Transmission* and *Number of junctions*. A column
  NOMAD has no value for stays empty. Sheet resistance and transmission are copied as stored in
  NOMAD; their units are not checked yet.

*Date*, *Variation* and *Notes* are not stored on the sample in NOMAD and stay for you to fill
in, as do all process columns (solvents, solutes, ...): those belong to process entries, not to
the sample. The Ink Recycling variant of *Experiment Info* has fewer columns; there only the
columns it has are filled.

Opening the panel unticks *Add example values on 1st row*, because a prefilled file is meant to
be uploaded. If you tick it again, the samples start in row 4 below the example row. Press the
button again to close the panel: a closed panel means no prefill, and the example row option
goes back to what it was before. The app uses the
NOMAD login of your session; if it cannot reach NOMAD, the panel shows why and the Excel file
can still be generated without prefill.

### Uploading the prefilled file

Upload the generated file into **the same upload** the samples come from. NOMAD links the
processes to the samples of the upload the file is in; in another upload they would point to
samples that do not exist there. The upload must not be published yet.

NOMAD never replaces an entry that already exists in the upload: samples (also those created by
the In-Situ Analyser) and process steps recorded by an earlier Excel are kept as they are, and new
values for them in this file are ignored. Process steps that are new are added, with the dates you
enter in their *Datetime* columns, so steps recorded long after the measurement still sit in the
right place in the sample's history. Measurements find their samples by name and need no new
Excel.

## Fixing a mistake after the upload

Because a second Excel never changes existing entries, correct mistakes in NOMAD itself:

- **One value or one entry: in the NOMAD GUI.** Open the entry (the process step or the sample)
  in NOMAD, change the field in the entry's form and save. This also adds a value that was left
  empty.
- **The same wrong value in many entries: with the Entry Auditor app.** Load the batch, find the
  field (values that differ between entries are listed first in red), and correct the wrong value
  in all entries at once. It shows a preview before anything changes and keeps a backup of every
  entry it changes. It replaces values that are there; it cannot fill a field that is empty in an
  entry (use the NOMAD GUI for that).
- **A whole process step is wrong** (wrong process type or wrong samples): delete that step's
  entry file in the upload in NOMAD, correct the step in the Excel and upload the file again.
  Only the deleted step is created anew; everything else is kept.

## Known limits

- The *Nomad ID* formula covers 498 data rows; for more samples copy it down.
- Column names and the allowed processes come from the shared process catalogue
  (`shared/hysprint_utils/process_specs.py`); a new process type has to be added there first.

## Contact

Questions and problems: open an issue on
[nomad-pv-analysis-apps](https://github.com/nomad-hzb/nomad-pv-analysis-apps/issues), or ask a
Data Steward.
