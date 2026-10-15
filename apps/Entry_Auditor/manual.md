# Entry Auditor: user manual

## What the app is for

Check how consistently the fields of your NOMAD entries are filled in (for example the
spelling of a material, solvent or tool name, or a concentration, across all the samples of a batch), and correct a
wrong value in all entries at once instead of editing every entry by hand.

**Corrections change entries in NOMAD.** Read the section on corrections before you use them.

## Data it needs

The batches you select. For every sample in them the app reads the entries of 24 types: Batch,
Basic Sample, ALD, Annealing, Blade Coating, Chemical, Cleaning, Deposition, Dip Coating,
Electrode, Environment, Evaporation, Experimental Plan, Ink, Inkjet Printing, Laser Scribing,
Process, Sample, Slot Die Coating, Solution, Spin Coating, SpinCoating Recipe, Storage and
Substrate. Text and number fields are audited (a number is shown as text, for example a
concentration of 1.42); yes/no flags are not; identifiers and NOMAD's own schema references are left
out.

## Tab *Audit*

1. **Select batches.** Select one or several batches (Ctrl- or Cmd-click for more than one) and
   click *Load Data*. A progress bar shows the entry types being read; the status line then says
   how many samples were found in how many entry types. *Load demo data* uses a small bundled
   data set (without NOMAD, so no corrections are possible). The fold-out *Debug log* lists the
   counts per entry type.
2. **Audit Results.** Each entry type with data gets a block with the number of entries, the
   number of unique samples and the number of auditable fields. *Show table* / *Hide table*, or
   *Expand all* and *Collapse all* for every block at once.
3. **The table.** One row per field, one column per entry, ordered by sample and then by file
   name. A field whose value **differs between entries** is shown in red on a red background and
   listed first, because that is usually what you look for ("this value is spelled differently
   here"). Fields with the same value everywhere are shown in black. Empty values are shown as
   `-`. *Add NOMAD links* turns each value into a link to the sample in NOMAD.
4. **Correct values** (below the table, see next section).

## Corrections

The corrections form works on one field of one entry type:

1. Choose the *Field* (clicking a field name in the table selects it), then in *Change name* the
   wrong value (the list shows the values that occur in the data), in *Sample* either all
   entries with that value or one specific entry, and type the correct value under *To*.
2. Click *Preview correction*. Nothing is changed yet. The app checks every affected entry and
   lists which ones **will change**, which are skipped because the value is not at this path
   (they are left alone) and which have errors.
3. Check the list, then *Confirm: change N* (or *Cancel*). Each entry is changed only at the one
   field you chose, in the entry's own file, and the changed file goes back into the entry's own
   upload. The app then reads each entry back to verify the new value: the result line gives
   how many were updated and verified, skipped, failed and (if NOMAD was still processing) written
   but not confirmed. Check unconfirmed ones in NOMAD before correcting again.
4. Before an entry is changed, its original file is saved as
   `entry_auditor_backups/<upload id>/<file path>.<time stamp>` next to the app, so a wrong
   correction can be put back by hand. Every correction is also appended to a log
   (`entry_auditor_correction_log.txt`).

The table is updated with the new values of the entries that were confirmed.

## Tab *Corrections*

Lists every correction made so far (the wrong value and the value it was corrected to), read from
the correction log. *Refresh* reloads it and *Export CSV* gives a `corrections.csv`.

## Known limits

- Text and number fields are audited, and a correction replaces whole values (it does not search
  inside longer texts). A number field only accepts a number as its corrected value and is
  written back as a number. A field with more than 50 different values is not listed. A field that only some entries
  have (for example the fourth solute) is listed too; the other entries count as empty.
- A correction needs write access to the uploads of the entries; entries you cannot change are
  reported as errors.
- The demo data cannot be corrected.

## Contact

Questions and problems: open an issue on
[nomad-pv-analysis-apps](https://github.com/nomad-hzb/nomad-pv-analysis-apps/issues).
