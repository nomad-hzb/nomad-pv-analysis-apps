# File Uploader: user manual

## What the app is for

Add measurement files to the samples of a batch in NOMAD. You pick a batch, choose the files from
your computer, assign them to samples, check the measurement type of each file, and upload. The
app renames every file to the NOMAD convention, so you do not have to rename them by hand.

## Before you start

You need write access to the uploads of the samples. The upload is **not reversible**: files that
have been uploaded and processed can only be removed in NOMAD itself.

## Step by step

1. **Select the batch.** Type in *Search Batch* to narrow the list, select one batch, and click
   *Load Data*. The samples of the batch appear as one button each, labelled `sample id
   [description]`.
2. **Choose the files.** Click *Click to add files* and select your measurement files (several
   at once). They are read in the background; a status line shows files that are still being
   read, or that failed or timed out. A new selection replaces the file list; files you have
   already assigned to a sample stay assigned.
   A `.json` file in the JV-scan format is split by sample: each sample in it becomes one file
   `<sample>.<sample>-<file>.jv.json`.
3. **Assign files to samples.**
   - Select one or more files in the *Files* list and click a sample button: the sample's panel
     opens and the files are added to it. Or open the panel first and use *Add Files* for the
     files selected in the list. *Remove* takes selected files out of the sample again.
   - A sample button turns darker gray once its panel has been opened.
   - *Auto-match files to samples by number* assigns every unassigned file to the sample whose ID
     ends with the number in the file name (`S8.txt` and `S8_1.txt` go to a sample ending in 8;
     a number after a leading `S` is preferred, otherwise the last number in the name is used).
     Files without a number, with no matching sample, or matching several samples, are left for
     you and the reason is printed. *Reset all assignments* returns all files to the list; it
     does not change anything already uploaded.
4. **Check the file types.** Each assigned file has a dropdown with its measurement type. The
   app proposes it from the file name (a whole word of the name such as `jv`, `eqe`, `mppt`,
   `sem`, `xrd`, `abspl`, `nmr`, `trpl`, `trspv`, `pli`, or the photoelectron types `xps`,
   `nups`, `he-ups`, `cfsys`, which are all stored as `pes`) and, if the name gives no hint,
   from the first lines of the file for some formats. If nothing is recognised the type is
   `hy` (generic). *Override all types* sets one type for all files at once. Change single
   files with their dropdown.
5. **Upload.** Click *Upload and process Data (not reversible)*.
   - The app first checks that every assigned file has been read completely; if not, it lists
     the files and does not upload (wait and click again, or unassign them).
   - It then finds the NOMAD upload of each sample, builds one zip per upload, uploads it and
     waits until NOMAD has processed it. A progress bar shows the uploads; every upload ends
     with "processed" or "FAILED" and the reason. "Done!" is shown only if all succeeded.
   - Samples without a NOMAD entry are reported and their files are not uploaded.

## How files are named

`<sample id>.<original name>.<type>.<extension>`, for example `DG_MMB_24_0_C-19.my_scan.jv.txt`.
For JV files the time the file was last modified (as seconds since 1970) is put in front of
the original name, so that two files with the same name stay apart.

## Known limits

- The batch list, the file chooser and the upload depend on your browser; the file chooser
  starts in the folder the browser chooses.
- Only one batch can be loaded at a time.
- Large files take a while to read; a file that does not settle within 30 seconds is marked as
  failed.

## Contact

Questions and problems: open an issue on
[nomad-pv-analysis-apps](https://github.com/nomad-hzb/nomad-pv-analysis-apps/issues), or ask a
Data Steward.
