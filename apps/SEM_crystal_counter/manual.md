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
   - *Download results (Excel)*: one file with the ticked sheets: *About* (what each sheet
     holds), *Samples*, *Images*, *Grains* (every grain of every image, the largest sheet) and
     *Settings* (every parameter used, for reproducibility). All are ticked by default.
   - *Preset* and *Re-analyse all with this preset*: force smooth or striped for every image.
     Normally leave it on automatic.
3. **Review and correct tab.** One image at a time.
   - **Moving between images:** *◀ Previous* / *Next ▶*, with a counter such as *17 / 85*, or
     pick the image from the list.
   - **Ignore this image:** leaves the image out of every result, e.g. a cross-section that
     was loaded with the top views. Untick it to use the image again.
   - **What the colours mean:** green outline = grain fully inside the image (counted); orange
     outline = grain cut by the image border (left out of the size averages, counted as half a
     grain for the density). Blue dots = your grain clicks, red = holes, magenta = the first
     point of a merge or cut.
   - **Zoom:** drag a box over the image, or use the scroll wheel. *Whole image* (or a
     double-click) zooms out again. While an editing action is selected, the first click of a
     double-click also counts as a click; *Undo* removes it.
   - **Correcting automatic grains** (*Grains from: Automatic detection*), with *A click*:
     - *merges two grains*: click one grain (marked magenta), then its neighbour; the border
       between them is removed.
     - *cuts along a line*: click a start point and an end point; every grain the straight
       line crosses from one border to the other is cut along it. A line that does not cross a
       grain completely does nothing, and a message says so.
   - **Placing grains yourself** (*Grains from: My clicks (one per grain)*): click the centre of
     **every** grain and the program finds the borders. A grain without a dot is absorbed by
     its neighbours. Switching to this mode starts from the automatic grains, so you only add
     missing ones and remove wrong ones. *A click* then *adds a grain*, *adds a hole* (pinholes
     or voids, whose area is reported separately) or *removes a dot*. **Ctrl+click** removes
     a dot in any of these modes.
   - *Undo* and *Clear corrections* work on the current mode. Corrections are kept per image,
     and the tables and plots update with them.
   - **Detection settings for this image** (collapsed): the three settings that matter most,
     for images where the automatic grains are systematically wrong. *Apply to this image*
     re-analyses it (a few seconds); *Apply to all images* does it for every image that is not
     ignored; *Back to the preset* undoes it. Corrections made before are kept, but check them,
     because the grains may have changed. The Images table marks such images "own settings".
     - *Smallest grain diameter*: the most important one. Raise it when grains fall apart into
       small pieces; lower it when neighbouring grains are glued together.
     - *Merge threshold*: higher merges more (removes false borders such as stripes inside
       grains).
     - *Boundary threshold*: lower gives fewer grains, higher gives more.
   - *Save as reviewed* stores the image's final grain map, your clicks or edits, and the
     settings in the training log (see below). Please also save images that needed no
     correction: confirmed results are useful too.

## Training data: what happens with saved reviews

Every *Save as reviewed* writes one folder per image to the team's training log
(`shared/log/sem_training_log/` of the app's upload). It holds:
- the final grain map;
- your clicks (in the same format as an ImageJ point annotation) or your merge/cut edits;
- the settings used, your user name and the time.

Nothing is trained automatically while you work. The collected reviews are used by the
developers to check and retune the automatic detection and, once enough images are reviewed,
to train a model for it. So the more images are reviewed, the better later versions get.
Saving the same image again replaces its earlier review.

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
