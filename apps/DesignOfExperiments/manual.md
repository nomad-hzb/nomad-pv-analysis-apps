# Design of Experiments: user manual

## What the app is for

Generate a set of experimental conditions (a design) for materials experiments: you define the
variables and their ranges, choose an algorithm and a number of runs, and get a table of
conditions that covers the space well, with quality scores, plots and exports. The app does not
use NOMAD. Every design is tied to a random seed; note the seed with your results so the design
can be regenerated.

The app has three tabs: **Setup & Variables**, **Results & Visualization** (its title shows
the number of runs after a design exists) and **Export**.

## Tab 1: Setup & Variables

1. **Algorithm.** Choose it in the list; a short description appears under it (see the table
   below).
2. **Sample Size.** A slider and a number box. The slider runs from the recommended minimum
   (the number of variables + 1, at least 4) up to 100; the number box takes any value, also
   above 100, and is used as typed. Around 10 runs per variable is a common choice for fitting a
   model to the results (for example Bayesian optimisation in Global_analyzer); fewer is fine for
   a first screening. Orthogonal arrays and definitive screening designs fix their own size
   and ignore this value.
3. **Random Seed.** The same seed and the same settings give the same design. *New Seed* picks a
   random one (1 to 2 147 483 647); you can also type one.
4. **Advanced Options** (fold-out, depends on the algorithm):
   - Latin Hypercube Sampling: *Optimization* None, Random-CD or Lloyd.
   - Sobol and Halton: *Apply scrambling* (on by default).
   - Orthogonal Arrays: *Levels for continuous variables* 2, 3, 5 or 7.
   - Augment Existing Design: upload your existing design as a CSV with one column per variable
     (same names; extra columns are ignored, so this app's export or a Global_analyzer table
     works). Only the new runs are listed.
   - The other algorithms have no advanced options.
5. **Design Options** (fold-out; with the defaults the design is unchanged):
   - *Centre points* (0 to 50): extra runs with every variable in the middle of its range
     (geometric middle for log variables; categorical variables cycle through their
     categories). They show the measurement scatter and curvature.
   - *Replicates of each run* (1 to 10).
   - *Blocks (days / lots)* (1 to 20): the runs are split into random, near-equal groups, one
     per day or precursor lot, shown in a `block` column. Use the block as a categorical
     parameter in the analysis.
   - *Randomize run order (uses the seed)*: random order within each block; the order is in a
     `run_order` column, and `experiment_id` keeps the original row number.
6. **Variables.** Two empty rows are there at the start; *Add Variable* adds one, the red
   **x** removes one, *Clear All* starts over. Per row:
   - *Name*: starts with a letter, then letters, digits, `_` or `-`, at most 50 characters.
   - *Type*:
     - *continuous*: any value between Min and Max; tick *log* for quantities spanning
       decades (the samples are then spread evenly over the decades; needs Min > 0).
     - *discrete*: Min, Max and Step (for example 1, 5, 1 gives 1, 2, 3, 4, 5).
     - *categorical*: a comma-separated list of at least two different labels, for example
       `DMF,DMSO,GBL`.
   - *Description* (optional): goes into the exported protocol.
   - A row with a red border has Min >= Max. A number that is not a number gets a red border
     when you press Enter. Comma and dot are both accepted as the decimal separator.
7. **Generate Samples.** If a variable has a problem, no design is generated and the problems
   are listed under the button (a variable is never dropped silently). On success the app
   switches to Tab 2. *Regenerate* picks a new seed and generates again.
   Notes about the design (its real size, a subsampled grid, unequal level counts, warnings from
   the algorithm) appear in the box *About this design*.
8. **Quality metrics** (bottom of Tab 1), computed on the design points themselves (before
   centre points and replicates are added):
   - *Minimum Distance* and *Mean Distance* (in the normalised unit hypercube; higher means more
     spread out), *Distance Uniformity* (lower is more even).
   - *Overall Coverage* and the coverage per variable.
   - *Max Correlation* and *Mean Correlation* between numeric variables (near 0 is ideal).

## Tab 2: Results & Visualization

- The bar at the top shows the seed, the number of runs and the algorithm. *New Design* picks a
  new seed and regenerates.
- *Generated Samples* shows up to the first 50 rows (the index starts at 1). The full table is in
  the export. Whole-number columns are shown without decimals.
- *Plot Type*: Scatter Plot Matrix, Parallel Coordinates, Distribution Plots, 3D Scatter Plot
  (needs 3 numeric variables), Correlation Heatmap (needs 2 numeric variables) and
  Space-Filling Quality (distance histogram, coverage, uniformity and a 2D scatter). Plots that
  need numeric variables ignore categorical ones. *Export Plot* gives a download link below the
  plot (a self-contained HTML file).
- *Summary statistics*: per variable its type, minimum, maximum and number of different values.

## Tab 3: Export

- **Export Table**, choose a *Format* and click *Export Table*:
  - *CSV (Samples)*: `doe_samples.csv`, one row per run.
  - *JSON (Configuration)*: `doe_configuration.json` with the variable definitions, algorithm,
    number of samples, seed, time stamp and the samples.
  - *Excel (All Data)*: `doe_complete.xlsx` with the sheets Samples, Variables and Metrics.
- **Readable Protocol**: *Export Protocol* creates a numbered, step-by-step text for the lab with
  the exact values of every run. It follows the run order of the design; tick *Randomize run
  order* in the design options (Tab 1) before generating if you want a random order.

## The algorithms

| Algorithm | Good for | Notes |
|---|---|---|
| Latin Hypercube Sampling | General screening, response surfaces | Every variable is sampled evenly over its range. A good default. |
| Sobol Sequences | Sensitivity analysis, computer experiments | Very even coverage; sizes that are powers of 2 work best. |
| Halton Sequences | Optimisation studies | Like Sobol, based on prime numbers; avoids clustering. |
| Random Sampling | Baseline | No structure; points can cluster, especially for few runs. |
| Uniform Grid Sampling | Mapping a whole response surface | All combinations at regular steps. If the number of runs is not a full grid, a random subset of the next larger grid is used; the notes say which sizes give a full grid. Grows very fast with more variables. |
| Maximin Distance Design | Expensive experiments | Picks points from a Latin hypercube candidate set that maximise the smallest distance between two points. Categories count as equally different. |
| Orthogonal Arrays | Screening many factors at few levels | Taguchi-type arrays (L4, L8, L9, L16, L25, L27, ...): every pair of levels of two variables appears equally often. Up to 7 levels; size fixed by the variables and levels. |
| Definitive Screening Design | Screening up to 24 numeric variables, with curvature | Three levels per variable, about 2 x variables + 1 runs. Numeric variables only. |
| Augment Existing Design | The next round of experiments | Adds runs as far as possible from an uploaded design and from each other. |

Unless you have a reason otherwise, use Latin Hypercube Sampling. For many variables, avoid the
Uniform Grid.

## Known limits

- Plots, metrics and the correlation use numeric variables; categorical variables are treated
  as unordered levels.
- The table on Tab 2 shows only 50 rows; use the export for the rest.
- Excel export needs `openpyxl`.

## Contact

Questions and problems: open an issue on
[nomad-pv-analysis-apps](https://github.com/nomad-hzb/nomad-pv-analysis-apps/issues).
