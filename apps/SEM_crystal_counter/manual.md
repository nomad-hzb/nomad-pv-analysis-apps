# SEM Crystal Counter: user manual

## What the app is for

Measure the grain size of perovskite films from top-view SEM images:
- count the grains;
- measure every grain in nm;
- summarise each sample over all its images.

When the automatic result is not good enough, you can correct it by hand, and save the
corrected image as training data. The app only reads from NOMAD; it writes nothing back.

## Data it needs

- **Top-view SEM images as Zeiss TIFFs.** The pixel size is read from the TIFF metadata
  (`Image Pixel Size`), so there is no scale bar to measure. The info banner below the image is
  removed automatically. An image without a pixel size cannot be analysed.
- **From NOMAD:** SEM entries (type `HySprint_SEM`) of the samples in the selected batches. Every
  image file listed in an entry is downloaded.
- **Or uploaded directly,** without NOMAD. The sample is taken from the file name:
  `VP317_01.tif` belongs to sample `VP317`.
- **Cross-section images are not supported.**

## What counts as a grain

A grain is the region inside the deep, dark groove that surrounds it. Stripes, terraces or
faceted domains *inside* a grain do not make it several grains. Dark pinholes or voids are
holes, not grains. In click mode you can mark them as holes, and their area is then reported
separately.

## Step by step

1. **Get images.** Choose one of:
   - *From NOMAD*: select batches and click *Load Data*. *Show only batches with SEM images*
     shortens the list.
   - *Upload TIFFs*: choose the files, then *Add and analyse*.
   - *Load demo data*: three synthetic images, no NOMAD needed.

   New images are analysed right away, and a progress bar shows how far it is (a few seconds
   per image).
2. **Results tab.**
   - *Images*: one row per image with the sample, the preset used, the number of grains, the mean
     equivalent diameter, the planimetric mean grain area, grains per µm², the hole area
     fraction, and whether the image is reliable.
   - *Samples*: per sample, the mean and spread over its images, plus `magnification_spread`.
   - Two plots: the grain-size distribution per sample, and the mean diameter per sample with
     the spread between images as error bars.
   - *Download results (Excel)*: one file with the sheets *About* (what each sheet holds),
     *Samples*, *Images*, *Grains* (every grain of every image) and *Settings* (every
     parameter used, for reproducibility).
   - *Preset* and *Re-analyse all with this preset*: force smooth or striped for every image.
     Normally leave it on automatic.
3. **Review and correct tab.** Pick an image. If the outlines are wrong:
   - *Automatic detection*: a click *merges two grains* (click both) or *splits a grain*
     (click where the second grain is; the new border follows the darkest groove).
   - *My clicks (one per grain)*: click the centre of **every** grain and the program finds
     the borders. A grain without a dot is absorbed by its neighbours. Switching to this mode
     starts from the automatic grains, so you only add missing ones and remove wrong ones
     (click on a dot to remove it). Set *A click: adds a hole* to mark pinholes.
   - *Undo* and *Clear corrections* work on the current mode. Corrections are kept per image,
     and the tables and plots update with them.
   - *Save as reviewed* stores the image's final grain map, your clicks or edits, and the
     settings in the training log. Please also save images that needed no correction:
     confirmed results are training data too.

## How the numbers are computed

- **Film type (preset).** Grains with internal terraces fall apart under the *smooth*
  settings. If the smooth settings find more than 3x the grains of a fixed reference setting,
  the image is treated as *striped*. The choice and the ratio are listed per image.
- **Grain boundaries.** The image is flattened (slow brightness changes removed), denoised,
  and searched for dark grooves (a ridge filter, with bright edge rims capped first). The image
  is then split into regions from seed points (watershed). Neighbouring regions with a weak
  shared boundary are merged, and tiny regions are absorbed.
- **Sizes** are in nm via the pixel size:
  - area;
  - equivalent diameter (the diameter of a circle with the same area);
  - Feret diameter, axes, perimeter, circularity and solidity.
- **Grains cut by the image edge** (orange outlines) are left out of the size averages, and the
  remaining grains are weighted to correct for large grains being cut more often
  (Miles-Lantuejoul). For the grain density, edge grains count half (planimetric method).
- **Reliability.** An image with fewer than 20 grains gives no usable mean. It is marked and
  left out of the sample statistics when the sample has other images. This happens with
  large-grain films at high magnification: use 20-30 kX images for grain statistics.
- **Magnification spread** (Samples table): how much a sample's mean grain area differs between
  magnifications. A sample's grains do not change with zoom, so a large spread means some
  images are segmented less well.
- **Holes** (click mode only) are left out of the grain statistics, and the densities use the
  film area without them.

## Accuracy

Checked against hand annotations of 10 images:
- **Smooth films:** about 73% of grains match one to one (F1 0.73), and the mean grain size
  is typically within 15%.
- **Striped films:** F1 about 0.56, and the mean size is typically within 20%, occasionally off
  by about 30% on a single image.

On striped films two hand annotations of the same image by the same person agree no better
(F1 0.59), so per-sample means over several images are the robust result there. When a single
image matters, check it in the review tab and correct it, or use click mode.

## Known limits

- The pixel size must be in the TIFF metadata (Zeiss SmartSEM format).
- Loading many images keeps them all in memory (about 10 MB per image). Remove images you no
  longer need with *Remove all images*.
- Corrections live in the app session until you *Save as reviewed*. Reloading the page loses
  unsaved corrections.

## Contact

Questions and problems: open an issue on
[nomad-pv-analysis-apps](https://github.com/nomad-hzb/nomad-pv-analysis-apps/issues).
