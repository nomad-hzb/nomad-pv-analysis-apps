# Smart Databaser: user manual

## What the app is for

Fill in the description of a batch of samples (who made it, which processes in which order, with
which settings) and turn it into the experiment Excel file that NOMAD reads, with much less typing
than in a blank spreadsheet: you can copy a past batch as a starting point, mark the values that
differ between samples, and get guided to the fields that are still missing. The finished file can
be downloaded and/or uploaded straight into one of your NOMAD uploads. The Excel file has the same
columns as the one from the Excel Creator.

## Data it needs

Nothing to start with. To copy from a past experiment the app reads the process entries of an
existing batch in NOMAD. To upload, you need an upload that **already exists** in NOMAD: the app
never creates an upload itself (create it in the NOMAD web interface first).

## The workflow, top to bottom

### 1. Sample Setup

Set the *Total samples* and the number of *Variation Subbatch*es (groups of samples that share the
same variation, for example one spin speed), then click *Apply Sample Setup*. The samples are
divided as evenly as possible (15 samples in 4 subbatches give 4, 4, 4, 3); change the number of
one subbatch below the fields and apply again for a different split. Applying again adds or
removes samples as needed (the highest-numbered ones are removed first). The *Subbatch* column of
the Excel file is always the subbatch number, counted from 1, and is never typed by hand. A default
setup is applied when the page opens.

### 2. Whole-experiment Template (optional)

Search and select a **past batch** and click *Replicate Experiment*: its process steps **replace**
your current process sequence and are filled in with its values (if a value differed between that
batch's samples, the first sample's value is used). This can take a while for batches with many
steps. Everything stays editable afterwards, and picking another batch replaces the sequence again.
The same batch is the source for the *Adopt from template batch* button of a single process (see
below).

*Fill all Date/Operator fields* writes today's date and time into every date field and your user
name into every Operator field of the whole experiment at once (it overwrites what is there).

### 3. Process Sequence

One row per process, in the order of the Excel file. The first row, *Experiment Info*, is fixed;
the others are chosen with the dropdown (the process types are the same as in the Excel Creator).
- **+** adds a process below the row and **-** removes it; the arrow folds the process fields in or
  out. The percentage next to the type shows how many fields of that process are filled.
- The number boxes and checkboxes next to the type (for example the number of solvents, solutes
  and spin steps of a spin coating, or antisolvent / gas quenching) decide which fields the process
  has, as in the Excel Creator.
- Under each process are its fields. A field with a **\*** is required (it counts toward the
  completion bar and the review). *Today* and *Me* fill in the date or your name. Characters that
  would break IDs and file names (`\ / : * ? " < > |`) are not accepted in a value: the field gets
  a red border and the value is not saved. A red **outlier** mark means an autofilled value
  differs a lot from the other samples at the same step; check it, it is not necessarily wrong.
- **Varies**: tick the box in front of a field if its value is different for each sample. The
  field then moves into the *Varying Fields* table (step 4) and is never autofilled.
- *Adopt from template batch* fills this one process from the batch chosen in the template (if the
  batch has the process several times, you choose which one under *Material*). *Override from
  batch...* fills this process from any other batch and shows "Overridden from batch ..."; *Clear
  override* takes it back. If an action fails, your earlier values are restored.

The *Experiment Info* fields describe the whole batch (for example *Project_Name* and *Batch*).
Both of those are part of every sample's Nomad ID.

### 4. Varying Fields

A table with one row per sample and one column per field marked as varying, plus the sample, its
subbatch and a **Variation** column. Every cell is editable; the small arrow-down button in a
column header copies the first row's value into all rows. For large tables the display can
occasionally look empty or stale: click *Refresh Table*.

The **Variation** column is not filled in while you type. Under the table you can:
- type a *custom format* with `\1`, `\2`, `\3`, ... for the first, second, third varying column (the
  legend shows which is which, for example `Den=\1_Sol-\2`), then *Apply Formula* (leave it empty
  for the automatic label);
- *Automatically fill up Variation* (re)computes the column under the format that is active. A
  Variation value you typed yourself is never overwritten.

### 5. Nudge Review

*Start Nudge Review* guides you through the fields that are **missing** (processes with the most
gaps first) and then those flagged as **outliers**: *Confirm & Next* writes the value shown (also
confirming an outlier as correct), *Skip* goes on. At the end a summary lists what is still
missing per process. The completion bar above the finish buttons shows how many required fields are
filled, with an encouraging message.

### 6. Finish

Choose the *Target upload* (your own uploads are listed) and then one of:
- *Download only*: the Excel file is downloaded;
- *Upload only*: the file is put into the chosen upload and NOMAD processes it (the app waits for
  the result and reports a failure);
- *Download + Upload*: both.

Before any of these, the *Batch* and *Project_Name* fields must be filled in: without them the file's
Nomad IDs would be wrong, so all three buttons refuse, with a message. After that the nudge review
opens first and the action runs when you click *Continue with ...* (the checkbox *Skip nudge review*
is for testing only). The file is named
`<date>_<time>_<Project_Name>_<Batch>_experiment_file.xlsx`; the ending `experiment_file.xlsx` is
what NOMAD's parser recognises, and the time and names keep two experiments of one day from
replacing each other in the same upload. If the automatic download does not start (a download
blocker), the message contains a link.

At the bottom, the fold-out *Debug: Batch Field Mapping* is a diagnostic tool for developers (it
shows how the fields of a batch's process step are mapped); you do not need it.

## Settings for administrators

Which fields count as required is set in `config/required_fields.json` (by exception: every field
is required unless listed, globally or per process type); `config/alias_groups.json` lists fields that
count as one unit for the completion bar (for example the rotation speed fields of single-step
and multi-step spin coating, which have different names). There is no setting in the app for
these.

## Known limits

- The process types and columns come from the shared process catalogue, as in the Excel Creator.
- Copying from a batch needs the data of that batch to be completely processed in NOMAD; just
  after an upload, wait for NOMAD to finish before copying from it.
- The app only knows the uploads of your own account.

## Contact

Questions and problems: open an issue on
[nomad-pv-analysis-apps](https://github.com/nomad-hzb/nomad-pv-analysis-apps/issues), or ask a
Data Steward.
