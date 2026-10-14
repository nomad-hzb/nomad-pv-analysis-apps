# NMR Analysis: user manual

## What the app is for

Look at nuclear magnetic resonance (NMR) spectra stored in NOMAD: overlay the spectra of several
samples, and for one spectrum at a time find its peaks and integrate it over a range of chemical
shift. The app only reads from NOMAD; it writes nothing back.

## Data it needs

NMR measurement entries (type `HySprint_Simple_NMR`) of the samples in a batch, with the chemical
shift axis (ppm) and the intensity. A sample with one spectrum is called by its sample id; a
sample measured more than once (a repeat, another nucleus or solvent) is listed as
`<sample id> #1`, `#2`, ... so that every spectrum can be shown and integrated. In the lists and
plots a spectrum is labelled with the sample's description and id, and with the entry name when
the sample has several.

## Step by step

1. **Select the batches.** *Shown NMR batches* narrows the list to batches that have NMR
   measurements (this can take a moment). Select one or more and click *Load Data*. *Load demo
   data* uses a small bundled data set without NOMAD. The message says how many spectra were
   loaded.
2. **Overlay – All NMR Spectra.** All loaded spectra in one plot (chemical shift in ppm, high
   values on the left, as usual for NMR).
   - *Y-axis Offset* shifts each successive spectrum up by this amount (0 means they lie on
     top of each other).
   - *Spectrum Colors*: one colour picker per spectrum.
3. **Single Spectrum Analyzer.** Choose a spectrum in *Sample*.
   - *Min Peak Height* (0.01 to 1): peaks are found on the spectrum scaled to 0 to 1 and are
     those higher than this value. They are marked with a red x and listed under *Peak Detection
     Results* with their chemical shift and intensity.
   - *Range Start (ppm)* and *Range End (ppm)* (in either order) set the integration range; it
     is shaded yellow in the plot. *Integrate Range* shows, under *Integration Results*, the
     start, end, the integral (trapezoidal rule over the range, along increasing ppm, so the
     sign does not depend on how the entry stores the axis) and the average intensity of the
     points in the range. If no data point lies in the range, a message says so.
   - *Spectrum Color* changes the colour of this plot.

## Known limits

- The plots draw at most about 4000 points per spectrum (the highest and lowest point of every
  section are kept, so peak tops stay); the peaks and integrals always use the full data.
- Peaks are found without baseline correction, and nothing can be exported or written back.

## Contact

Questions and problems: open an issue on
[nomad-pv-analysis-apps](https://github.com/nomad-hzb/nomad-pv-analysis-apps/issues).
