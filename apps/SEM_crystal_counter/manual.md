# SEM Crystal Counter: user manual

## What the app is for

Measure the grain size of perovskite films from top-view SEM images:
- count the grains;
- measure every grain in nm;
- summarise each sample over all its images.

From cross-section SEM images it measures the film thickness (and how uneven it is) and the
grains inside the film.

When the automatic result is not good enough, you can correct it by hand, and save the
corrected image as training data. The app only reads from NOMAD; it writes nothing back.

## Data it needs

- **Top-view or cross-section SEM images as Zeiss TIFFs.** The pixel size is read from the TIFF metadata
  (`Image Pixel Size`), so there is no scale bar to measure. The info banner below the image is
  removed automatically. An image without a pixel size cannot be analysed.
- **From NOMAD:** SEM entries (type `HySprint_SEM`) of the samples in the selected batches. Every
  image file listed in an entry is downloaded.
- **Or uploaded directly,** without NOMAD. The sample is taken from the file name:
  `VP317_01.tif` belongs to sample `VP317`.
- **Top view or cross-section** is recognised automatically when an image loads (a
  cross-section has dark, smooth vacuum above the film). You can change it per image.
- **Images with measurements drawn in** by the SEM software (black label boxes with white text,
  measurement bars) are recognised and **ignored by default**: the drawn bars spoil the
  detection, and such images are usually copies of a clean image. The Images table notes it;
  untick *Ignore this image* in the review to use one anyway.

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
   - The *Samples* table and the plots use top views only; the *Images* table lists every
     image with its type.
   - *Download results (Excel)*: one file with the ticked sheets: *About* (what each sheet
     holds), *Samples*, *Images*, *Grains* (every grain of every image, the largest sheet),
     *Cross-sections*, *Cross-section samples*, *Thickness profiles* (see below) and *Settings*
     (every parameter used, for reproducibility). All are ticked by default.
   - *Preset* and *Re-analyse all with this preset*: force smooth or striped for every image.
     Normally leave it on automatic.
3. **Cross-sections tab.**
   - *Cross-sections*: one row per image: the film thickness (median over the image columns,
     and the 10th and 90th percentiles: 80% of the film width lies between them), the RMS
     roughness of the film top, whether the film bottom was found automatically or drawn, and
     the grains inside the film with their median *width* (horizontal extent) and *height*
     (vertical extent).
   - *Per sample*: the thickness of every column of all the sample's cross-sections pooled,
     and the median grain width and height.
   - *Film thickness distribution*, per image or per sample: how much of the film width has
     which thickness. A uniform film gives one narrow peak; a wide peak or several peaks mean an
     uneven film.
   - *Film thickness along each cross-section*: the thickness at every position.
   - The Excel sheet *Thickness profiles* holds the film top, bottom and thickness of every
     image column.
4. **Review and correct tab.** One image at a time.
   - **Moving between images:** *◀ Previous* / *Next ▶*, with a counter such as *17 / 85*, or
     pick the image from the list.
   - **Image type:** *top view* or *cross-section*, recognised automatically. Changing it
     re-analyses the image and drops its corrections.
   - **Ignore this image:** leaves the image out of every result, e.g. a blurred image. Images
     with measurements drawn in start ignored. Untick it to use the image again.
   - **What the colours mean:** green outline = grain fully inside the image (counted); orange
     outline = grain cut by the image border (left out of the size averages, counted as half a
     grain for the density). Blue dots = your grain clicks, red = holes, magenta = the first
     point of a merge or cut, yellow = the ruler. On cross-sections: red line = film top, cyan
     line = film bottom, purple = the film bottom you are drawing.
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
   - **Ruler** (*A click: measures a distance*, in every mode): click two points and the
     distance is shown below the image in nm, with its horizontal and vertical parts. A third
     click starts a new measurement; *Undo* removes the ruler. The grains are not changed.
   - **Scale bar:** below the image, about a tenth of the visible width, rounded to 1, 2 or 5 x
     10ⁿ nm. It follows the zoom.
   - **Film bottom of a cross-section** (*A click: draws the film bottom*, cross-sections
     only): when the automatic bottom line (cyan) catches a lower layer such as ITO or glass,
     click a few points along the real bottom of the perovskite film, then press *Use the drawn
     bottom*. The line runs straight between your points and flat beyond the outer ones;
     everything below it is ignored, and the image is re-analysed. *Undo* removes the last
     point; *Automatic bottom* goes back to the detected line.
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
- **Cross-sections.** The film top is the first row below the vacuum where the image becomes
  grainy, snapped to the sharpest dark-to-bright edge nearby. The film bottom is the first
  strong horizontal edge running across the image at least 150 nm below the top (or your drawn
  line). The thickness is measured at every image column. Grains are found with the top-view
  method inside the film only; the vacuum and the layers below are never grains, and
  corrections cannot reach outside the film. Densities and hole area are relative to the film
  area.

## Accuracy

Checked against hand annotations of 10 images:
- **Smooth films:** about 73% of grains match one to one (F1 0.73), and the mean grain size
  is typically within 15%.
- **Striped films:** F1 about 0.56, and the mean size is typically within 20%, occasionally off
  by about 30% on a single image.

**Cross-sections:** the thickness was checked against 19 thickness bars measured in the SEM
software on 10 images: mean difference 4%. The largest differences (up to 23%) are spots where
the bar starts at the front, cleaved grain while grains just behind it reach higher; the app
measures to the highest visible film surface. The grains inside the film were checked against
hand annotations of 4 cross-sections: F1 0.58-0.78 (mean 0.71), mean grain area typically
within 17%.

On striped films two hand annotations of the same image by the same person agree no better
(F1 0.59), so per-sample means over several images are the robust result there. When a single
image matters, check it in the review tab and correct it, or use click mode.

## Known limits

- The pixel size must be in the TIFF metadata (Zeiss SmartSEM format).
- Loading many images keeps them all in memory (about 10 MB per image). Remove images you no
  longer need with *Remove all images*.
- Uploaded files are grouped into samples by their name: `cs_VP352_01.tif` belongs to
  sample `cs_VP352`, not `VP352`. Images from NOMAD use the NOMAD sample.
- A cross-section whose film bottom has no clear horizontal edge (or catches a lower layer)
  needs the bottom drawn by hand; check the cyan line on every cross-section.
- Corrections live in the app session until you *Save as reviewed*. Reloading the page loses
  unsaved corrections.

## Contact

Questions and problems: open an issue on
[nomad-pv-analysis-apps](https://github.com/nomad-hzb/nomad-pv-analysis-apps/issues).
