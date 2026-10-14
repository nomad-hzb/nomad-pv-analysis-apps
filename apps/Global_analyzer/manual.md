# Global Analyzer (HySprint Data Analysis Tool): user manual

## What the app is for

Bring the process data and the measurement results of many samples together and look for what
matters: plot any result against any process parameter, filter out bad samples, find
correlations, see which process parameters drive a result (Random Forest), get suggestions for the
next experiments (Bayesian optimization), and try a few first-look tools (PCA, Pareto front,
outlier detection, process drift, ANOVA). The app only reads from NOMAD. The Random Forest and
Bayesian optimization tabs link to the Design of Experiments app for planning the next batch.

## Data it needs

Batches of samples in NOMAD. For each sample the app reads the process steps (the *process
metadata*: spin speeds, temperatures, materials and so on) and the measurement results it finds:
JV, EQE, MPP tracking (and simple MPP tracking), SEM, AbsPL and XRD. The *Parameter Summary* tab
lists which result types were found and which parameters exist. Alternatively you can upload
your own table (see *Analysis Data*).

## Step by step

### 1. Select batches

Open *Step 1: Select Batches*, filter the list by user (*Filter by user*) or by text (*Search
Batch*), select one or more batches and click *Load Data*. The status line says what was loaded.
All tabs below use the loaded data.

### 2. Parameter Summary

Overview of the loaded data: the result types and the parameters that exist.

### 3. Filters

One set of filters for **every tab after this one**. They only take effect when you click
**Confirm filters**; a note next to the button says when changes are still pending.

- *Filter rows*: choose a column, an operator (`>=`, `>`, `<=`, `<`, `==`, `!=`) and a value, and
  *Add Filter*. Values are compared in the column's own units (a fill factor is 0 to 1, not 0 to
  100). In Plotting the filter applies to the plotted rows (for example each pixel); in the
  analysis tabs it applies to the per-sample rows built on the Analysis Data tab. A filter on a
  column that a plot does not contain is skipped and listed with that plot.
- *Exclude specific samples*: removes samples entirely, whatever their values (for example a
  known contaminated one). All samples are included by default.

### 4. Plotting

- *Plot Presets* (fold-out) create a ready-made plot with one click: JV Efficiency vs Datetime,
  Efficiency vs Voc, Efficiency vs Fill Factor, Efficiency by Batch.
- Otherwise choose, for the **X axis**, the **Y axis** and the **Color**, a *Data Source* (process
  metadata or a result type), a *Material* (for steps that exist for several materials or
  layers) and a *Parameter*. *Show Only Varying Parameters* hides parameters that are the same for
  all samples. *Group by subbatch* groups the cells of one subbatch (for example `_C-1`, `_C-2`).
- *Plot Type*: Scatter, or Boxplot (needs a categorical X axis; with a numeric X axis the app
  falls back to a scatter plot with a message, unless you tick *Bin numeric X into groups* and
  choose the number of *Bins*).
- *Data Display*: *All Points* (every measurement is a point, for example every pixel), or *Mean*,
  *Max*, *Min*, *Median* per sample.
- *Color Scale* chooses the colour map or a single colour.
- *Create Plot* draws it, with statistics below it. Clicking a point shows a link to that
  sample's entry in NOMAD. *Download CSV* saves the plotted data. *Show plot data for debugging*
  prints the table behind the plot.

### 5. Analysis Data (the tabs marked with a link symbol share it)

Analysis Data, Correlations, Random Forest, Bayesian Optimization and Experimental all read the
same table, built on this tab from the loaded data and your filters. One row is one sample, or one
measurement under *All Points*.

- *Layer selection*: a process step logged once per layer (for example Spin Coating of the
  electron transport layer, the active layer, ...) has one row per layer; choose which layer's
  row is used. No dropdown means that step has one row per sample.
- *Aggregate pixels via* All Points, Mean, Median or Max: how repeated measurements of a result
  (for example several JV pixels) are combined. *All Points* keeps every measurement as its own
  row, so the rows of one sample share the same process values; the sample counts then are
  measurements, not independent samples.
- *Variable Selection*: tick the result columns (the **targets**), the process-metadata columns
  (the **supporting variables**) and the categorical parameters to use. Targets are always
  results; supporting variables are always process metadata. Click *Recalculate* after changing
  anything. *Show data used for analysis* previews the table and downloads it as CSV.
- *Use your own data (optional)*: upload a CSV (one row per sample, one column per parameter or
  result; the CSV exported from this tab works as it is). It replaces the loaded data for the
  five linked tabs until you load NOMAD batches again. A missing `sample_id` column is generated;
  text columns become options for ANOVA; a column named `datetime` enables Process Drift.

### 6. Correlations

*Find Correlations* correlates the ticked results with the ticked process parameters. *Min unique
values* leaves out parameters with few different values (constants and flags). *One point per
sample* averages repeated rows of a sample first, so each sample counts once. *Format* is a
heatmap or a scatter matrix. A strong correlation is a hint, not proof. *Download CSV* saves the
table.

### 7. Random Forest

Choose a *Target* (a result) and click *Run Random Forest*. The model predicts the target from the
ticked process parameters, and the bars show how much each parameter matters. It is checked on
samples it has not seen (cross-validation that keeps all pixels of a sample together), and the R²
shown is measured on those samples only. The importance is how much that R² drops when one
parameter's values are shuffled; two strongly correlated parameters share their importance, and
such pairs are listed. Partial dependence plots show how the prediction changes with one of the
top parameters. The text on the tab explains it in more detail.

### 8. Bayesian Optimization

Choose a *Target* and *Goal* (maximize or minimize), the number of *Suggestions*, optionally *Log
scale target* and *Correct for batch offsets*, and click *Suggest Next Experiments*. A Gaussian
process is fitted to your samples; 8192 candidates inside the search space are scored by expected
improvement and a batch of suggestions is picked (Kriging Believer method), with the predicted
value and its range. A model check plot (leave-one-sample-out) tells how far the model can be
trusted. Optional parts: *Search space* (range, integer or fixed value per parameter),
*Constraints* (up to two other results that must stay within a limit) and *Second objective*
(trade off against another result). It is a single-shot suggester: it does not remember earlier
rounds, so run it again after each new batch of measurements. The fold-out *How are the
suggestions calculated?* has the details.

### 9. Experimental

First-look tools that may change. PCA (which process parameters vary together, colored by a
column), Pareto Front (the best trade-off between two results), Outlier Detection (Isolation
Forest on parameters and results, with a *Contamination* share), Process Drift (does a parameter
trend over time) and ANOVA (does a result differ between groups of a categorical parameter).

## Known limits

- Every statistic is computed per sample where it matters, but with *All Points* the rows are
  pixels: look at the sample counts the tabs report.
- Random Forest, Bayesian optimization and the experimental tools need enough samples; they say
  so when there are too few.
- Nothing is written back to NOMAD.

## Contact

Questions and problems: open an issue on
[nomad-pv-analysis-apps](https://github.com/nomad-hzb/nomad-pv-analysis-apps/issues).
