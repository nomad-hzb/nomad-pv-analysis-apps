# ISA Previewer: user manual

## What the app is for

Open and look at the measurement files (h5 files) of the in-situ analysis (ISA) setup that are
stored in NOMAD uploads: the PL, optical, GIWAXS and logging data of a run. There are five
notebooks that share this app and this manual. The **ISA Previewer** is the starting point;
the others go deeper into one kind of data and are usually opened with a link from it:

| Notebook | Title | What it shows |
|---|---|---|
| `isa_previewer.ipynb` | ISA Previewer | The overview of an h5 file (the slider row, the heatmaps and 1D plots for GIWAXS and optical data), the logging data and the export. |
| `optical_analysis.ipynb` | ISA Optical Analysis | The optical data of the file. |
| `giwaxs_analysis.ipynb` | ISA GIWAXS Analysis | Cuts through the GIWAXS images and the comparison of cuts. |
| `timely_teller.ipynb` | ISA Timely Teller | Compares the runs of a whole upload with each other. |
| `video_visualizer.ipynb` | ISA Video Visualizer | Renders combined videos of the runs of a whole upload. |

The app reads files from the uploads on the Oasis; it does not change them. The only notebook
that writes is the Video Visualizer: it saves its videos as new files in a new folder of the
upload (see below), next to the h5 files, and changes nothing that is already there.
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
   Tracer*, *Open Peak Analyzer*, *Open Timely Teller* and *Open Video Visualizer*. A notebook
   does not link to itself, and
   a link only appears if the file can be used there (for example the optical analysis and the
   Thickness Tracer need optical or reflectance data, the GIWAXS analysis needs the detector
   images). The link opens the other notebook in a new tab **with this file already selected**
   (the file and the screen width are passed in the link). The notebooks can also be opened on
   their own from the app dashboard; then they start with an empty selection.

**Timely Teller** works on a whole upload: you select only the upload (there are no sample or
measurement lists), and the tool scans the upload's folder for h5 files and compares them.

## Video Visualizer

The Video Visualizer also works on a whole upload: select only the upload, and the video tool
appears below the list. It makes one video per run you pick, from top to bottom:

1. **Runs.** The ISA h5 files of the upload (other h5 files, for example raw spectrometer files,
   are left out). Ctrl or Shift + click picks several; *Select all* picks every run. Only pick
   the runs you need: every run takes a while to render.
2. **Modes.** The measurement modes the picked runs hold (GIWAXS, XRF, XAS, XEOL, OceanHDX, ...)
   and the optical channels (PL, Absorbance, Reflectance). Tick any combination. The first
   ticked measurement mode sets the pace: each of its frames stays on screen for as long as it
   lasted in the experiment (a pause in the measurement holds the frame, very dense frames are
   skipped), and the other modes show their latest frame at the same time. A video needs at
   least one measurement mode; a run that holds none of the ticked ones gets no video.
3. **One section per ticked mode** with its own options, freely combinable:
   - *Heatmap*, drawn with a *Time line* at the current time, *Build up over time* (the heatmap
     fills from left to right and its time axis ends at the end time of the video) and *CIF
     references* (diffraction modes);
   - *1D curve* of the current frame, optionally with *CIF reference strips* (diffraction
     modes);
   - *Detector image* (GIWAXS, when the run holds the detector images), on a *Logarithmic colour
     scale* or, unticked, a linear one;
   - *Mask a q range* (diffraction modes): the q range from *q min* to *q max* is blanked out,
     for example the carbon dome of the heating stage;
   - *Summed frames*: each frame of the heatmap, the 1D curve and the detector image is summed
     with the following ones, this many in all (1 = no summing). Summing stops at the end of
     the run and where the incidence angle changes.
   An option that needs data none of the picked runs holds is greyed out.
   When Absorbance or Reflectance is ticked, a *Reference window* (start and end, in the time
   unit below) sets the time their spectra are taken relative to; left empty, each channel uses
   the window its label names (1 to 6 s after the channel's first spectrum).
4. **CIF references.** Shown when a reference option is ticked: drop one or more .cif files and
   tick the ones to show.
5. **Time.** One *Time unit* for the start and end time, the heatmap time axes and the title of
   the video. An empty *End* means the end of each run. *Playback speed* sets how many times
   faster than real time the video plays, *Output fps* the frame rate of the video file (30 by
   default, at most 60). It does not change how fast the video plays; with cameras, camera fps
   × playback speed shows every camera frame.
6. **Include cameras.** Adds the two camera recordings of the experiment; the fields hold the
   full paths of the two camera folders.
7. **Create videos** starts the rendering. The videos go into a new folder of the upload named
   `Videos_<date>_<time>`, one file per run. The progress bar shows the frames of the current
   video together with the memory and CPU use, and the log at the bottom shows what happens and
   which run (if any) could not be rendered. **Stop** ends after the current frame; the video is
   kept up to there. Picking another upload while a video renders stops it the same way.

Every video carries a title line (sample, frame, time, Berlin time). The panels are arranged
automatically: the more you tick, the smaller each panel gets.

## Known limits

- Large h5 files take a while to open; each new selection closes the previous one to free memory.
- The notebooks need access to the upload folders on the Oasis; they do not work on a computer
  without them.
- If a file cannot be opened, the message under the lists names it and gives the reason.
- Video Visualizer: runs with optical data only (no GIWAXS, XRF, ... mode) cannot be rendered
  yet, since a video needs a measurement mode to set its pace. Many ticked modes make the
  panels small.

## Contact

Questions and problems: open an issue on
[nomad-pv-analysis-apps](https://github.com/nomad-hzb/nomad-pv-analysis-apps/issues).
