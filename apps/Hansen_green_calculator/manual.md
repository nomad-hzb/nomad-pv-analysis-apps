# Hansen Solubility Parameter Tool Suite: user manual

## What the app is for

Work with Hansen solubility parameters (HSP) of solvents: explore the solvent database in 3D and
in 2D, find the mixture of chosen solvents that comes closest to a target HSP, calculate the
average properties of a mixture, and look at the HSP of inks and of perovskite solutes and
solvents. The app does not use NOMAD; it works on two data files that sit in the app's folder.

## Data it uses

- `db.csv`: the solvent database (name, CAS number, the Hansen parameters D, P and H, and
  properties such as molar volume, boiling point, viscosity, heat of vaporisation, molar mass,
  donor number, SMILES and synonyms). Used by the first four tabs. Without it these tabs show a
  message.
- `PlottedInks.xlsx`: the sheet *Inks* (tab *Inks*) and the sheets *Sheet2* and *Sheet3* (tab
  *Perovskite*).

Every tab has a line "Data used in this tab" with a link to the file on GitHub.

Hansen parameters: D (dispersion), P (polar) and H (hydrogen bonding), in MPa^0.5. The distance
between two materials is Ra = sqrt(4 (D1-D2)^2 + (P1-P2)^2 + (H1-H2)^2); the dispersion
difference counts twice. For the same reason the D axis of the plots is drawn as 2 x D, so that
distances in the plot are Hansen distances.

## The tabs

### 3D Solvent Space

All solvents of the database in HSP space. Type in *Search* (name, CAS number or synonym) to
highlight matching compounds; the first ten matches are listed below the plot. *Colour by* colours
the points by any numeric column (for example boiling point).

### 2D Properties

A scatter plot of any numeric column against another (*X axis*, *Y axis*, *Colour*).

- **Click a point** to add that solvent to the table below the plot; selected points are drawn in
  orange-red. *Reset table* empties the selection.
- *Download CSV* saves the table. If *Only the plotted values* is ticked, the table and the CSV
  hold only the name and the plotted columns; otherwise every column.
- *Show Correlation Matrix* draws a matrix of plots of every pair of columns (over 100 plots). It
  warns that it is slow and can make the browser slow; wait until it appears.

### Blend Optimiser

Finds the mixture of the solvents you choose that is closest to a target HSP.

1. *Search* and pick solvents in *Results* (the full list is shown until you type), *Add Solvent*;
   *Remove* takes a selected one out.
2. Set the target *δD*, *δP* and *δH* with the sliders.
3. *Min % each* is the smallest share any chosen solvent may have (default 2 %). If it is too
   large for the number of solvents it is reduced to an equal share.
4. *Optimise Blend* finds the fractions (they add to 100 %) that minimise the distance Ra to
   the target, shows the percentages per solvent and a 3D plot with the solvents, the target and
   the resulting blend (*Colour by* colours the solvents). The achieved HSP of the blend is the
   fraction-weighted average of the solvents' D, P and H.
5. *Save CSV* downloads the target, the blend, the distance and the composition.

### Mixture Calculator

Weighted average properties of a mixture you define. Add solvents and type the percentage of each;
the status line shows the total, which must be 100 % (within 0.5 %). *Calculate* shows the
average of every numeric property of the database (D, P, H, molar volume, boiling point, and so
on) weighted by the percentages; solvents without a value for a property are left out of that
property's average. *Clear* empties the mixture, *Save CSV* downloads the composition and the
averages.

### Inks

The inks of the sheet *Inks* in 3D HSP space, coloured by solute. *Show Solute Volumes* draws, for
each solute, the sphere that encloses its inks (a sphere in the Hansen space, in which the dispersion
axis is counted twice).

### Perovskite

The perovskite solutes and solvents of *Sheet2* or *Sheet3* (*Dataset*) in 3D HSP space. *Colour by*
chooses the colouring and *Solutes* filters which solutes are shown (Ctrl or Cmd to select several;
*Select All* and *Clear*).

## Known limits

- The data are what the two files contain; add or correct values in the files themselves.
- The Hansen parameters are tabulated values for pure substances; the blend values are linear
  averages by volume fraction, which is the usual approximation.

## Contact

Questions and problems: open an issue on
[nomad-pv-analysis-apps](https://github.com/nomad-hzb/nomad-pv-analysis-apps/issues).
