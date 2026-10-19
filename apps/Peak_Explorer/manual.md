# Peak Explorer: user manual

## What the app is for

Look at a series of spectra (for example photoluminescence over time, or GIWAXS intensity over
time), find the peaks in them, fit peak models to every spectrum of the series, and follow the
fitted peak parameters over time. Results go to an Excel file, or back into the h5 file the data
came from. The app does not use NOMAD.

## Data it needs

Two sources, both offered in the *Data Loading* box:

- **An h5 file from the ISA Previewer.** Open Peak Explorer through the link in the ISA Previewer;
  the file is handed over and shown as *File:*. The dropdown *Measurement* picks what to load from
  it: PL raw, PL binned & bgs, GIWAXS, GIWAXS Diamond integration, Transmission raw/binned,
  Absorbance raw/binned. If the app is opened without that link, or the file no longer exists,
  only the CSV upload is used.
- **A CSV file** ("Click to upload CSV file"), in one of two layouts:
  - *PL measurement export*: some metadata lines, then a header line that contains the word
    "Wavelength" followed by the time stamps, then one row per wavelength.
  - *Simple table*: wavelengths in the first row, time stamps in the first column, intensities
    in between.

  A row with a cell that is not a number is skipped together with its wavelength. Time stamps are
  shifted to start at zero.

## Step by step

1. **Load** the data. The status box at the top tells what was loaded (number of time points,
   wavelengths, ranges).
2. **Look at it.** *Time Control* (slider or index box) moves through the spectra; the heatmap
   (time against wavelength or energy) and the *Current Spectrum* plot follow. *Heatmap Colors*
   sets the colour range of the heatmap.
3. **Remove a background** (optional, *Background* section). Choose a method and press *Apply
   Background*; *Remove Background* restores the data.
   - *Manual*: the mean of a number of curves, starting at a time index, is subtracted from all
     spectra.
   - *Linear*, *Polynomial*, *Exponential*: type the parameters, or press *Auto-Fit Background* to
     fit them to the **current spectrum**, using only the points outside the windows of
     your peak models (centre +/- 3 widths); define the peaks first so the background is fitted
     between them. Without peak models, all points are used.
   - *Custom*: upload a two-column file (wavelength, intensity).

   One background is subtracted from every spectrum. Loading new data or switching the h5
   measurement forgets the background and removes the fit results.
4. **Define the peak models.** Either *Auto-Detect Peaks* (it replaces the models with the peaks
   found in the current spectrum inside the selected wavelength range; the three numbers set the
   minimum height, the minimum prominence and the minimum distance in data points, 0 = automatic)
   or *Add Model* and type the start values. Model types: Gaussian, Voigt, Lorentzian, Skewed
   Gaussian, Skewed Voigt, Linear, Polynomial. Per model: Center, Height (the maximum of the peak,
   not its area), Sigma (and Gamma for the Voigt types; the skewness for Skewed Gaussian). *Fix*
   keeps the value above it; *Bounds* sets minimum and maximum (empty = no bound). *Center bound*
   is the default window of +/- that value around each start centre.
5. **Fit.** *Fit Current* fits the shown spectrum and gives R squared; the start values are
   replaced by the fitted ones only when R squared is above 0.5, otherwise use *Update from Fit*
   if you want them. *Fit All Spectra* fits the whole series, *Fit Range* the time indices
   between *Start* and *End*. With *Fit sequential* each fit starts from the previous result
   (slower, one process); without it the spectra are fitted in parallel from the same start
   values.
6. **Inspect.** *Time Series Analysis* plots the fitted parameters against time. *Fit
   Visualisation* shows each fitted spectrum (slider *Spectrum*), optionally with the individual
   peaks.
7. **Export.**
   - *Export Results* downloads an Excel file with the sheets Peak_Parameters,
     Standard_Errors and Fitting_Quality. For the peak types it lists per peak the fitted values,
     the area (integral under the curve), height, FWHM and the 10 % width, and the model type.
     Fitting_Quality has success, chi-squared, reduced chi-squared, AIC, BIC, RMSE, MAE and
     maximum residual per spectrum.
   - *Save into h5* writes the same results into the h5 file the data came from, in a group
     under `fitting_results`, with the measurement, the units, the models and the fit settings
     as attributes. Only data loaded from an h5 file can be saved this way, and only fits made
     for the data and unit that are currently shown. **This modifies the h5 file in place.**

## nm and eV

The button *nm <-> eV* switches the wavelength axis to energy and back, with E = hc / lambda
and hc = 1239.84 eV nm. A PL spectrum is a density per wavelength interval, so its intensity is
multiplied by lambda squared / hc on the way to eV (and back by E squared / hc). The integral of
the spectrum is the same in both units, and fitted peak positions, widths and areas in eV are
correct. Transmission and absorbance are not rescaled. The button is shown only for data on a
wavelength axis, so not for GIWAXS (q in 1/Å). For a CSV file the app cannot know
which one it is: the checkbox *CSV intensity is a PL spectrum*, shown once a CSV is loaded,
decides (on by default).
The start values of the peak models are converted too (centre, sigma, Voigt gamma, and the
height of PL data); bounds typed in the old unit are cleared. An applied background is
converted along with the data. Fit results are removed on every conversion.

## Known limits

- Absorbance is computed with the natural logarithm, so values are 2.303 times the optical
  density in log10.
- The background is global: one curve, fitted on the current spectrum, is subtracted from every
  spectrum.
- Polynomial models have no parameter bounds.
- CSV import replaces NaN/inf cells by 0.

## Contact

Questions and problems: open an issue on
[nomad-pv-analysis-apps](https://github.com/nomad-hzb/nomad-pv-analysis-apps/issues).
