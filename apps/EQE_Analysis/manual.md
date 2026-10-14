# EQE Analysis: user manual

## What the app is for

Look at external quantum efficiency (EQE) measurements stored in NOMAD: compare the EQE curves
of several samples, group repeated measurements, compare the values NOMAD has derived from them
(band gap, integrated Jsc, J0rad, Voc rad, Urbach energy) in a boxplot, and download the data
as CSV. The app only reads from NOMAD; it writes nothing back and does not recompute any of the
derived values.

## Data it needs

EQE measurement entries (type `HySprint_EQEmeasurement`) of the samples in a batch. Per curve
the app uses the photon energy, wavelength and EQE arrays and the values stored with the curve:
band gap (eV), integrated Jsc, integrated J0rad, Voc rad, Urbach energy and the light bias.
Values the measurement did not record are left empty.

## Step by step

1. **Select the batches.** Type in *Search Batch* to narrow the list, select one or more
   batches and click *Load Data*. *Show EQE batches* keeps only the batches that have EQE
   measurements. *Load demo data* loads a small bundled data set without NOMAD.
   Samples with no valid EQE curve are left out.
2. **Dataset Names** (tab). At the top two tables: a summary per sample (minimum, mean,
   standard deviation and maximum of band gap, Jsc, J0rad, Voc rad, Urbach energy and light
   bias, plus a row "All Data") and the values of every single curve.
   Below, one row per sample:
   - the checkbox includes or excludes all curves of that sample from the plots;
   - the name field is the name used in the plots. *name preset* fills it from the sample name,
     the batch, the sample description, or empty for a custom name. Curves of samples with the
     same name are grouped together in the plots.
3. **EQE Curves** (tab), press *Refresh plot* after changing a setting:
   - *group curves with same name*: curves with the same label are drawn as one group, either by
     their median with the quartiles, or by their average with the standard deviation (*group
     type*). Unticked, every curve is drawn on its own.
   - the x axis is the photon energy (eV) or the wavelength (nm);
   - *curve label* is the sample name, the sample name with the curve's name, or the curve's
     name only;
   - *width px* and *height px* set the size of the plot.
4. **Boxplot** (tab): choose the value (band gap, Jsc, J0rad, Voc rad, Urbach energy), the label
   style and the size. One box per label, built from the curves of the samples you included.
   The plot updates when you change the value.
5. **Download** (tab): *Prepare CSV downloads* gives four links: `eqe_curve.csv` (all curve
   points), `eqe_params.csv` (the values per curve), `eqe_properties.csv` (sample names and
   descriptions) and `eqe_entries.csv` (entry names and descriptions).

Names and the included samples are applied when you open the *EQE Curves* or *Boxplot* tab.

## Known limits

- The Jsc and J0rad axis labels say A/cm² as stored in NOMAD; the app does not convert units.
- Only the curves of included samples are in the plots and in the boxplot; the CSV downloads
  contain everything that was loaded (`eqe_params.csv` has the include flag and the name per curve).

## Contact

Questions and problems: open an issue on
[nomad-pv-analysis-apps](https://github.com/nomad-hzb/nomad-pv-analysis-apps/issues).
