# MPPT Analysis: user manual

## What the app is for

Analyse maximum-power-point tracking (MPPT) measurements stored in NOMAD: look at the power
density, voltage and current density over time, clean outliers, fit degradation models to each
measurement and obtain stability figures of merit (T95, T80, Ts95, Ts80, stabilization time, PCE
after 1000 h, lifetime energy yield). You can download everything and, after a second
confirmation, write the fit results back into the NOMAD entries. The maths of the models and the
figures of merit is in [FITTING.md](FITTING.md) in this folder.

## Data it needs

MPPT measurement entries (type `HySprint_SimpleMPPTracking`) of the samples in a batch.
Time is shown in hours. NOMAD stores generated power as negative values; the app detects this per
entry and flips it, so power density is positive for a working cell.

## Step by step

The tabs open one after the other, each after the previous step is done.

1. **Batch Selection.** *Show MPPT Batches* narrows the list to batches that contain MPPT
   measurements. Select one or more batches and click *Load Data*. *Load demo data* (at the top)
   uses a small bundled data set without NOMAD.
2. **Sample Selection.** Every sample lists its measurements (pixels); tick the ones to analyse.
   The sample's own box ticks or unticks all of its measurements. *Name preset* decides how the
   samples are named in tables and plots (sample name, batch, sample description, or a custom
   name you type). Press *Confirm Selection*.
3. **Curve Fitting.**
   - *Model*: Stretched Exp, Linear, Exponential, Biexponential, Logistic+Exp or ERFC+Linear;
     the equation is shown below the list.
   - *Point Range* limits the points used for the fit (by index). Left at its full range, each
     measurement is fitted to its own end.
   - *Apply to all selected measurements*: ticked, one setting is used for all; unticked, pick a
     single *Measurement* and fit only that one.
   - The preview shows the data, the fit and the residuals. The parameter fields hold the
     starting values (the model's guess from the data at first, and the converged values after
     each successful fit); edit them to change the starting point.
   - *Auto Fit & Save* fits from the model's own starting guess; *Fit & Save With These Values*
     starts from the numbers in the fields. Results are kept in the app (not in NOMAD yet).
   - *Outlier cleaning*: *Window (points)* and *Threshold* set a rolling-median filter. *Clean
     all plots* / *Clean this plot* set the outliers to missing values (the raw data is kept and
     the fits of cleaned measurements are discarded); *Restore raw data* undoes it.
   - *Show all fitting results* lists, per measurement, the model, the fit parameters and the
     figures of merit; *Statistical Summary* gives their statistics. A measurement that already
     has a fit or figures of merit in NOMAD is listed with those values and the note "Stored in
     NOMAD" (times converted to hours); a new fit of it shows the new values and a note that NOMAD
     already holds results, so you see an overwrite before you do it. If only the metrics are
     stored, the row says "metrics only, fit details not available".
4. **Visualization** (after at least one fit). Choose the *Variable* (power density, voltage,
   current density) and *Plot style* (each curve separately, all together, by sample, or by
   area with median and quartiles or mean and standard deviation), optionally *Show fitting
   lines*, and press *Generate Plots*. *Histogram of* shows the distribution of chosen fit
   results.
   - **Add fit results to NOMAD** is on this tab. It first shows a warning that it will modify
     existing values in the NOMAD database (fit method, the point range used and the computed
     T95, T80, Ts95, Ts80, stabilization time and more) and cannot be undone from this app; only
     *Confirm - write to NOMAD* writes. Each measurement then reports success or the error, with a
     link to the entry. A figure that is "not reached" is written as an empty field.
5. **Download Results.** *Generate Download Package* builds a zip with
   `MPPT_Analysis_Results.xlsx` (sheets Raw_Curve_Data, Fitted_Curve_Data, Fit_Results,
   Statistical_Summary, Sample_Information; the raw and fitted data can be left out), the plots as
   HTML, PNG or both, and a README.

## What the figures of merit mean

- **T95 / T80**: time until the power falls to 95 % / 80 % of the initial power (the mean of the
  50 highest measured values). The measured curve is used if it reaches the level and stays
  below it; otherwise the fitted model is extrapolated, but only up to ten times the measured
  duration. Beyond that, or if the model never reaches the level, the field is empty.
- **Ts95 / Ts80**: the same, relative to the stabilized power after a burn-in. For models
  without a burn-in dip they equal T95 / T80.
- **Stabilization time**: when the burn-in is over (empty if it lies outside the measurement).
- **PCE after 1000 h**: the measured value if the measurement reaches 1000 h, else the fitted
  value if 1000 h lies within the ten-times horizon, else empty. The app treats power density in
  mW/cm² and PCE in % as the same, which is exact only for 1-sun illumination.
- **Lifetime energy yield**: the energy integrated up to T80, in kWh/m². Values written by app versions
  before the unit fix (see FITTING.md) used a different scaling.

## Known limits

- The fits and cleaning live in the browser session only until you write them to NOMAD or
  download them.
- Writing to NOMAD overwrites the earlier fit results of the entry.

## Contact

Questions and problems: open an issue on
[nomad-pv-analysis-apps](https://github.com/nomad-hzb/nomad-pv-analysis-apps/issues).
