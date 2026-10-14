# Excel Creator: user manual

## What the app is for

Build the Excel file in which you describe the fabrication sequence of a batch of samples
(substrate cleaning, coatings, evaporation, and so on). The finished file is uploaded to NOMAD
with the Smart Databaser, or by hand. The app builds the empty sheet with the right columns; you
fill in the values in Excel. It does not use NOMAD itself.

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
   - *Add example values on 1st row*: on, the first data row is filled with example values so
     you can see what each column expects; off, the sheet is empty.
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

## Known limits

- The *Nomad ID* formula covers 498 data rows; for more samples copy it down.
- Column names and the allowed processes come from the shared process catalogue
  (`shared/hysprint_utils/process_specs.py`); a new process type has to be added there first.

## Contact

Questions and problems: open an issue on
[nomad-pv-analysis-apps](https://github.com/nomad-hzb/nomad-pv-analysis-apps/issues), or ask a
Data Steward.
