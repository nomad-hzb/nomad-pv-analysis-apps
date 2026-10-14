# JV Analysis: user manual

## What the app is for

Analyse current-voltage (JV) measurements of solar cells stored in NOMAD: group the samples by the
conditions you tested, filter out bad cells, compare the parameters (Voc, Jsc, FF, PCE and more) in
boxplots, histograms and JV curves, and download the plots and the data. The app only reads from
NOMAD; it writes nothing back.

## Data it needs

JV measurement entries of the samples in one or more batches. The status of a measurement
(light `L1`, `L2`, ... or dark `D1`, `D2`, ...) is read from the measurement name, for example
`JV_FiNa_1B_L1.txt` gives `L1` and `device_A_D1_dark.txt` gives `D1`. The cell and the scan
direction (forward or reverse) come from the entry.

## Step by step

The tabs are used from left to right.

1. **Authenticate.** The app uses your NOMAD token from the environment
   (`NOMAD_CLIENT_ACCESS_TOKEN`). *Connection Settings* shows
   which Oasis it talks to and has the *Authenticate* button. On the Oasis this happens
   without you doing anything.
2. **Select Upload.** Select one or several batches and click *Load Data*. *Load demo data*
   loads a small bundled data set without NOMAD. Problems with single entries are listed after
   loading.
3. **Add Variable Names.** The table lists every sample (shown as `batch&variation`). Type the
   condition each one stands for (for example "1000 rpm"); samples with the same text are
   grouped together in the plots. The *Defaults* list chooses what the boxes start with: the batch name,
   the sample's variation, or nothing (*all*). Click *Confirm variables*. A sample left empty falls back to
   its variation, or "Unknown". Below the table, *Other Measurements* lists the other
   measurements the samples have in NOMAD as links.
4. **Select Filters.**
   - *Direction*: Both, Reverse or Forward scans.
   - *Filter Conditions*: rows of parameter, comparison and value (for example `PCE(%)` `<` `40`).
     *Add Filter* / *Remove Filter* change the rows. *Load Preset* loads the chosen preset:
     *Default* is PCE < 40, FF < 89, FF > 24, Voc < 2, Jsc > -30; *Preset 2* is FF < 15 and
     PCE >= 10.
   - *Positive current (flips JV to 1st quadrant)* changes the sign of the current in the JV
     curves and in the downloaded curve data.
   - *Sample Selection* (fold-out): untick samples to leave them out; *Select All* and *Clear
     All* work on all of them (after *Clear All* nothing is plotted until you tick samples
     again); the counts of the selection update as you tick. Samples are kept apart by batch, and
     cells by their full name (C1 and C2 are different cells).
   - *Apply Filter* applies the rows, the direction and the selection. *Skip (no filters)*
     keeps every measurement; removing all rows and clicking *Apply Filter* does the same.
     The rows you filtered out are kept as "omitted data" for the omitted plots below.
5. **Select Plots.** Each row is one plot: *Plot Type*, then *Option 1* and *Option 2*. *Add
   Plot Type* / *Remove Plot Type* change the rows, *Load Preset* fills them from a preset
   (for example "Separated Boxplots", "Advanced Analysis"). Press *Plot Selection*; filters must
   have been applied first.
   - **Boxplot**: Option 1 is the parameter (Voc, Jsc, FF, PCE, Voc x FF, R_ser, R_shu, V_mpp,
     J_mpp, P_mpp, or "The big 4: Voc, Jsc, FF, PCE" for four plots at once), Option 2 what to
     group by: Batch, Variable, Sample, Cell, Scan Direction, Status, Status and Variable, Cell
     and Variable. *Split by direction* separates forward and reverse. The two combined options
     draw one plot per condition (for example one per variable with L1/L2/L3 inside).
     Dark measurements (status D...) are left out of the *Status and Variable* and *Cell and
     Variable* plots.
   - **Boxplot (omitted)**: the same, built from the rows your filters removed. Titles say
     "(omitted data)".
   - **Histogram**: the distribution of one parameter.
   - **JV Curve**: Option 1 chooses which curves: all cells, only working cells, rejected cells,
     best device overall / by batch / by variable (together or separate), or separated by cell or
     by substrate. For the best-device choices, Option 2 shows or hides a summary of the
     parameters.
   - **Correlation Matrix**: a heatmap or scatter matrix of the parameters, of the filtered data
     or all data.
   - *Sort order* orders the categories alphabetically, by mean or by median, or by a *Custom*
     list (comma-separated; parentheses group aliases and the first one is shown; categories not
     listed are left out of the plot).
   - *Color Scheme* picks the palette; *Sampling* "sequential" takes the first colours of it,
     "even" spreads the colours over the whole palette.
6. **Save Results.** Available after the plots have been made:
   - *Plots*: a zip with every plot as HTML, and as PNG where the image export works.
   - *JV Data (CSV)* and *JV Curves (CSV)*: all data or only the filtered data.
   - *Excel summary*: a workbook (`collected_data.xlsx`) with the full data in the sheet
     *All_data* and further analysis sheets.
   - *Everything together*: one zip with the plots and the workbook.

   If a download does not start, click the button that appears and check the pop-up blocker.

## Known limits

- Plots, the Excel summary and the zip are built when you press *Plot Selection*; after
  changing filters, plot again.
- PNG images are skipped when the image export is not available on the server; the HTML plots
  are always included.

## Contact

Questions and problems: open an issue on
[nomad-pv-analysis-apps](https://github.com/nomad-hzb/nomad-pv-analysis-apps/issues).
