# Wetting Envelope: user manual

## What the app is for

Predict which liquids wet a surface. For each material (a substrate or layer) you give its surface
energy split into a polar and a dispersive part; the app draws its **wetting envelope**. A liquid
whose own polar and dispersive surface tension components lie inside the envelope of a material wets
that material (its contact angle is below the chosen angle). You can add liquids as points and see
at a glance which one wets which material. The app does not use NOMAD.

## Step by step

1. **Materials.** Pick a *Preset* or type the values yourself:
   - *Name*;
   - *Polar* and *Dispersive*: the polar and dispersive components of the material's surface
     energy, in mN/m;
   - *θ (°)*: the contact angle the envelope is drawn for (default 0, which is complete wetting;
     it must be between 0 and 179 degrees).

   Click *Add Material*. The added materials are listed under *Active materials*; the **x** removes
   one. The presets come from `material_presets.csv` (a link under the heading); for most of them
   the source of the values is not recorded yet, so check a preset before relying on it.
2. **Solvents.** Pick a *Preset* or enter *Name*, *Polar* and *Dispersive* (mN/m) and click *Add
   Solvent*. When you pick a preset, a note under it tells where the value comes from and links to
   its reference and to `solvent_presets.csv`. Some solvent values (for example isopropanol,
   acetone and hexane) have no recorded source yet and say so.
3. **Plot.** Set the plot *Title* and click *Plot* (add at least one material first). Each material
   is a curve in the plane *Dispersive component* (x) against *Polar component* (y), both in mN/m;
   each solvent is a point. A solvent inside the curve of a material wets it at that material's
   contact angle. *Clear All* removes all materials, solvents and the plot.

## How the envelope is calculated

With the OWRK model, a liquid with the surface tension components γL_d (dispersive) and γL_p (polar)
makes the contact angle θ on a solid with the components γS_d and γS_p when

γL (1 + cos θ) = 2 (sqrt(γS_d γL_d) + sqrt(γS_p γL_p)), where γL = γL_d + γL_p.

The curve is the set of liquids for which the angle is exactly the chosen θ. In polar coordinates
around the origin, with the angle φ running from 0 to 90 degrees from the dispersive axis, it is
R(φ) = [(sqrt(γS_d cos φ) + sqrt(γS_p sin φ)) / (cos φ + sin φ)]² x [2 / (1 + cos θ)]².
For θ = 0 this is the envelope of complete wetting. The curve is built from 1000 points.

## Known limits

- The envelope assumes the OWRK model (two components, no acid-base terms).
- A contact angle of 180 degrees is not possible (the envelope would be infinite); the largest
  value is 179.
- Values come from the preset files or from you; the app does not check them against a
  reference.
- The presets are in `material_presets.csv` and `solvent_presets.csv` in this app's folder and
  can be extended there.

## Contact

Questions and problems: open an issue on
[nomad-pv-analysis-apps](https://github.com/nomad-hzb/nomad-pv-analysis-apps/issues).
