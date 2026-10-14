# XRD Peak Finder: user manual

## What the app is for

Look at X-ray diffraction (XRD) patterns: stored in NOMAD, or from local `.xy` files. For every
pattern the app finds the peaks, gives their position, height and area, and you can overlay
several patterns with a vertical offset and export all data as CSV. The app only reads from
NOMAD; it writes nothing back.

## Data it needs

One of two sources, which can be mixed:

- **NOMAD**: XRD measurement entries (type `HySprint_XRD_XY`) of the samples in a batch. A sample
  with several measurements appears once per measurement (`<sample>_meas_1`, `_meas_2`, ...).
- **Local files**: text files ending in `.xy`: optionally a first line starting with `'Id:` that
  holds metadata such as `Id` and `Operator`, then one line per point with the angle (2θ, degrees)
  and the intensity separated by blanks. A file without that first line is read from its first
  line on. Lines that cannot be read are skipped.

## Step by step

1. **Load data.**
   - *Option 1*: select batches (*Show XRD batches* keeps only batches that have XRD data; it can
     take a few minutes) and click *Load Data*.
   - *Option 2*: *Upload .xy files* (one or several).
   - *Load demo data* loads a small bundled data set without NOMAD.
2. **Look at each pattern.** Every loaded sample gets its own plot (intensity against 2θ in
   degrees; for files the title shows the file name and the `Id` and `Operator` from the file)
   with its own peak controls:
   - *Min Height*: peaks lower than this intensity are ignored (starts at 10 % of the maximum);
   - *Prominence*: how far a peak must rise above its surroundings (starts at 5 % of the
     maximum);
   - peaks must be at least 5 data points apart;
   - *Show Peaks* switches the markers and the filled peak areas on and off.
   Under the plot, the detected peaks are listed with their position (2θ in degrees), the
   intensity at the maximum and the area (intensity x degrees). The area is the integral over the
   peak (to where it has fallen to 1 % of its prominence on each side) above a straight baseline between its two ends.
   Where two peaks overlap, both areas end at the lowest point between them, so no part of the
   pattern is counted twice.
3. **Overlay.** Tick *Include in overlay* for the samples you want to compare. The *Overlay Plot*
   shows them in one plot; *Stagger Offset* shifts each successive pattern up by that amount so
   they do not lie on top of each other (the slider's range follows the intensity of the data,
   and its step is 1 % of the range).
4. **Export CSV.** *Export CSV* downloads `xrd_data.csv` with every loaded pattern, one row per
   point: `sample_id`, `variation`, `name`, `angle`, `intensity`. If any sample has several
   measurements, a `measurement` column names each one.

## Known limits

- The peak controls only change the display and the peak list; the exported CSV holds the raw
  patterns, not the peaks.
- Peaks are found on the data as loaded (no smoothing or background subtraction).

## Contact

Questions and problems: open an issue on
[nomad-pv-analysis-apps](https://github.com/nomad-hzb/nomad-pv-analysis-apps/issues).
