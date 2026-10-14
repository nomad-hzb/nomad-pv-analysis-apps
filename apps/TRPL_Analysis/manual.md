# TRPL Analysis: user manual

## What the app is for

Analyse time-resolved photoluminescence (TRPL) decay traces stored in NOMAD: subtract the
background, convert the counts to a rate, estimate the initial carrier density from your
measurement settings, fit the decay with a sum of exponentials, and plot the differential
lifetime against time and against carrier density. The app only reads from NOMAD; it writes
nothing back.

## Data it needs

TRPL measurement entries (type `HySprint_TimeResolvedPhotoluminescence`) of the samples in a batch, with the
time axis and the counts per time bin. If the batch has no registered samples, the app looks for
TRPL entries in the same upload as the batch. Time is taken in seconds (NOMAD stores it in SI
units) and the width of a time bin is derived from the time axis itself. The measurement
settings (repetition rate, power, integration time and so on) are not stored with the data: you
enter them in the app.

## Step by step

1. **Select the batches.** *Show TRPL batches* keeps only batches with TRPL data. Select one or
   more and click *Load Data*. *Load demo data* loads a small bundled data set without NOMAD.
   The message says how many measurements were loaded.
2. **Physical Parameters** (the same for all traces):
   - *λ laser [m]* (default 705e-9) and *Spot Diameter [cm]* (default 2.72e-4);
   - *Thickness [nm]*: **required**. If it is 0, *Run Analysis* stops with a message asking you
     to enter it;
   - *BD ratio* (default 0.21), a factor in the initial carrier density (see step 4);
   - *Denoise*: how the background is estimated. 0 means no background subtraction. A positive
     number *n* takes the mean of the first *n* time bins; a negative number *-n* takes the mean
     of the last *n* bins (trailing zeros removed).
3. **Per-trace table.** One row per measurement (sample and data file) with *Rep. Rate [Hz]*
   (default 10000), *Power [µW]* (default 0.4), *ND* (neutral density filter, default 0, the
   power is attenuated by 10^-ND), *Int. Time [s]* (default 10) and *Num. Exp.* (the number of
   exponentials of the fit, default 3). The *Set All ...* fields above the table copy one value
   into the whole column.
4. **Run Analysis.** For every trace:
   - the counts per bin are divided by bin width, integration time and repetition rate to get
     a PL rate in counts per second, and the background (noise level) is subtracted;
   - the initial carrier density n0 = (pulse energy / spot area / photon energy) x BD ratio /
     thickness, with the pulse energy from power, ND filter and repetition rate;
   - the decay after its maximum is smoothed (Savitzky-Golay) and fitted with the chosen number
     of exponentials on the points that lie more than ten times above the noise level;
   - the differential lifetime is tau_diff = -2 dt / d ln(PL) from the fitted curve (PL varies as
     the square of the carrier density), and the carrier density along the decay is
     n0 x sqrt(PL / PL_max).
   Three plots appear: the traces (PL rate in counts per second against time in ns, log scale, with
   the noise level of each trace as a dashed line), the differential lifetime against time, and
   the differential lifetime against carrier density (both axes logarithmic). A trace that cannot
   be fitted (for example too few points above the noise) is reported with the reason and does not
   stop the others.

## Known limits

- The results are plots only; there is no export of the fitted values.
- The analysis uses your entered settings for every trace of a row; check the table before running.
- Pressing *Run Analysis* again repeats the whole analysis with the current entries.

## Contact

Questions and problems: open an issue on
[nomad-pv-analysis-apps](https://github.com/nomad-hzb/nomad-pv-analysis-apps/issues).
