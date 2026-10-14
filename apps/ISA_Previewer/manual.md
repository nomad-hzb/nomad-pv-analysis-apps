# ISA Previewer: user manual

## What the app is for

Open and look at the measurement files (h5 files) of the in-situ analysis (ISA) setup that are
stored in NOMAD uploads: the PL, optical, GIWAXS and logging data of a run. There are four
notebooks that share this app and this manual. The **ISA Previewer** is the starting point;
the others go deeper into one kind of data and are usually opened with a link from it:

| Notebook | Title | What it shows |
|---|---|---|
| `isa_previewer.ipynb` | ISA Previewer | The overview of an h5 file (the slider row, the heatmaps and 1D plots for GIWAXS and optical data), the logging data and the export. |
| `optical_analysis.ipynb` | ISA Optical Analysis | The optical data of the file. |
| `giwaxs_analysis.ipynb` | ISA GIWAXS Analysis | Cuts through the GIWAXS images and the comparison of cuts. |
| `timely_teller.ipynb` | ISA Timely Teller | Compares the runs of a whole upload with each other. |

The app reads files from the uploads on the Oasis; it does not change them or write to NOMAD.
The plots and tables inside each section come from the shared ISA analysis library
(`insitu_analyser`); this manual describes how to open a file and how the notebooks fit together.

## Data it needs

Uploads that contain ISA measurement entries (`HySprint_Process` entries with an h5 data file).
These uploads usually have no batch entry, which is why the app selects by upload name and not by
batch. The upload has to be available in your own file area on the Oasis; an h5 file whose
upload is not mounted for you is left out of the lists.

## Step by step

1. **Uploads.** All uploads with ISA measurements that you may see are listed. Type in *Filter* to
   narrow the list (case does not matter), then select one.
2. **Samples.** The samples of that upload, shown as `<sample id> [<description>]`. Select one
   (the first entry `---` means nothing selected).
3. **Measurements.** The h5 files attached to that sample, shown as
   `<description>---<file name>`. Selecting one opens it; a spinner shows while the file is read
   and the sections appear below. Selecting another file replaces the previous one.
4. **Pixel width** (default 1680) is the width of your screen in pixels; it sets the size of all
   figures. Changing it rebuilds the open file at the new width.
5. **Sections.** What is shown below depends on the notebook (see the table above). A section
   that has nothing to show for the chosen file is left out.
6. **Links.** Below the sections there is a row of links to the other notebooks for this file:
   *Open Heatmap Analysis*, *Open Optical Analysis*, *Open GIWAXS Analysis*, *Open Thickness
   Tracer*, *Open Peak Analyzer* and *Open Timely Teller*. A notebook does not link to itself, and
   a link only appears if the file can be used there (for example the optical analysis and the
   Thickness Tracer need optical or reflectance data, the GIWAXS analysis needs the detector
   images). The link opens the other notebook in a new tab **with this file already selected**
   (the file and the screen width are passed in the link). The notebooks can also be opened on
   their own from the app dashboard; then they start with an empty selection.

**Timely Teller** works on a whole upload: you select only the upload (there are no sample or
measurement lists), and the tool scans the upload's folder for h5 files and compares them.

## Known limits

- Large h5 files take a while to open; each new selection closes the previous one to free memory.
- The notebooks need access to the upload folders on the Oasis; they do not work on a computer
  without them.
- If a file cannot be opened, the message under the lists names it and gives the reason.

## Contact

Questions and problems: open an issue on
[nomad-pv-analysis-apps](https://github.com/nomad-hzb/nomad-pv-analysis-apps/issues).
