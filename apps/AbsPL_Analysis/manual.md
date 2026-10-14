# AbsPL Analysis: user manual

## What the app is for

Explore absolute photoluminescence (AbsPL) measurements stored in NOMAD: compare quasi-Fermi level
splitting (QFLS), luminescence quantum yield and the other results across the samples of one or more
batches, plot the luminescence spectra, and export the tables. The app only reads from NOMAD; it
writes nothing back.

## Data it needs

Entries of type `HySprint_AbsPLMeasurement` that belong to samples of a batch. Each entry can hold
several results; every result becomes one row of the table. Per row the app shows these values, as
stored in NOMAD and without conversion (empty when the measurement did not record them):

| Column | Meaning |
|---|---|
| `luminescence_quantum_yield` | luminescence quantum yield |
| `quasi_fermi_level_splitting` | QFLS (eV) |
| `quasi_fermi_level_splitting_het` | the second QFLS value NOMAD stores for the measurement |
| `i_voc` | implied open-circuit voltage (iVoc) as stored |
| `bandgap` | band gap (eV) |
| `derived_jsc` | the derived short-circuit current density as stored |
| `sample_id`, `variation`, `name` | sample, its description in NOMAD, and the measurement name |

Spectra: `wavelength` (nm), `luminescence_flux_density` and `raw_spectrum_counts`.

## Step by step

1. **Choose batches.** Pick one or more batches in the list (type in *Search Batch* to narrow it).
   *Show only batches with EQE data* keeps only the batches that have AbsPL entries (the button
   label says EQE, it filters for AbsPL). Click *Load Data*.
2. **Check the load message.** It tells how many rows were loaded, or that no AbsPL measurement
   was found in the batches. *Load demo data* loads a small bundled data set without NOMAD.
3. **Data Summary** shows count, mean, spread and quartiles of every numeric column.
4. **Data Filtering.** Choose a column and a minimum and maximum, then *Apply Filter*. Rows outside
   the range are removed; filters add up. The message says how many rows were removed and how many
   remain. *Reset Filters* restores everything; *Show Data* lists the first 10 rows.
   Filters affect every plot, table and export below.
5. **Plotting Tools.** Choose X axis, Y axis, *Color by* (none, `sample_id`, `variation` or `name`)
   and the plot type, then *Generate Plot*.
   - *Scatter plot*: Y against X; hovering shows the name and the sample.
   - *Box plot*: distribution of the Y column, split by the *Color by* choice (all rows together
     when it is None). The X axis is not used.
6. **Spectral Plot.** Choose the variations (the first five are preselected), the data column,
   a linear or log Y scale and optionally *Normalize spectra*, then *Generate Spectral Plot*.
   One line per measurement; lines of one variation share a colour. Normalising divides each
   spectrum by its own maximum. The range slider under the plot zooms the wavelength axis.
7. **Advanced Analysis** (button *Show / Hide Advanced Features*):
   - *Data Table*: choose columns and *Update Table* (first 20 rows). *Export CSV* downloads
     the current (filtered) data as `abspl_data_<time>.csv`. *Export Pivot Table* downloads a table
     with one column per group (for example per variation) and the chosen value in the rows,
     as `abspl_pivot_<value>_by_<group>_<time>.csv`. Groups of different sizes keep every
     measurement; the shorter columns are padded with empty cells.
   - *Statistics*: choose a column and *Calculate Statistics* for the overall summary, and, when
     grouped, the summary per group and a box plot per group.

## Known limits

- The numbers are shown as stored in NOMAD: the app does not recompute QFLS, quantum yield or
  band gap from the spectra.
- A measurement without a spectrum in the chosen data column is skipped in the spectral plot.
- A row that fails validation is logged and left out of the table.

## Contact

Questions and problems: open an issue on
[nomad-pv-analysis-apps](https://github.com/nomad-hzb/nomad-pv-analysis-apps/issues).
