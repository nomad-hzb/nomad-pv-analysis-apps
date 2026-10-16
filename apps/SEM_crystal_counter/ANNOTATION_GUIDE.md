# Annotating grains in ImageJ / Fiji

The goal is one click inside every grain. `evaluate.py` uses these clicks to score the
automatic segmentation:
- count error and mean grain size error
- grains the algorithm split in two (a region with no click)
- grains it merged (a region with two or more clicks)

You do not need to trace boundaries.

## What counts as a grain

- One grain is one region enclosed by the **outer** boundary groove.
- Stripes, terraces or steps *inside* a grain (as in VP401 and VP412) are **not** boundaries.
  A striped grain gets one click.
- Click grains that are cut by the image edge too.
- Do not click inside the info banner at the bottom.
- If you cannot decide whether something is one grain or two, use the "unsure" counter
  (step 3). Unsure points are reported separately and do not count against the algorithm.

## Steps

1. **Open the image.** File > Open, then pick for example `VP317_01.tif`. If ImageJ asks about
   the format, accept the default. The image may open as "8-bit Color"; that is fine.

2. **Make sure coordinates are in pixels.** Analyze > Set Scale, click
   **"Click to Remove Scale"**, then OK. The window title bar should then show the size as
   "1024x768 pixels", not nm or µm.

3. **Choose the Multi-point tool.** Right-click (or long-click) the point tool in the toolbar
   (the cross-hair icon) and pick **Multi-point**. Then double-click the same icon to open
   its options:
   - Type: **Dot** (or Circle), Color: something visible (yellow or cyan), Size: Medium
   - Tick **"Label points"** so you can see the numbering
   - **Counter**: leave it at **0** for normal grains. When you meet an unsure grain, switch
     the Counter dropdown to **1**, click it, then switch back to 0.

4. **Click once inside each grain.**
   - Zoom: `+` and `-` keys (or the mouse wheel with Ctrl). Pan: hold the **space bar** and
     drag.
   - Undo a wrong point: **Alt + click** on it. Do not use Ctrl+Z, which can clear all
     points.
   - Work in a fixed order (for example row by row from the top left) so you do not miss
     grains.
   - Do not click on the image with another tool while points are active, or you lose
     the selection. To be safe, save regularly (step 6).

5. **Save the points as a table.** Analyze > **Measure** (Ctrl+M). A Results window opens
   with one row per point and columns including **X**, **Y** and **Counter**. In the
   Results window choose File > Save As, and name it exactly after the image:
   `VP317_01_points.csv`.

6. **Save a backup you can reopen.** Edit > Selection > Add to Manager (Ctrl+T), then in the
   ROI Manager choose More > Save, giving `VP317_01_points.roi`. To continue later, open the
   image and drag the `.roi` file onto ImageJ.

Put all `*_points.csv` files in one folder, for example
`D:\Seafile\JointLab-TEAM-Inkjet\SEM images\annotations\`.

## Which images, in which order

| Image | Why | Expected effort |
|---|---|---|
| VP317_01 | smooth, large grains (easy) | about 10 min, about 40-60 grains |
| VP352_03 | smooth, small grains plus faint boundaries | about 20 min |
| VP401_05 | striped grains (the hard case) | about 20-25 min |
| VP412_05 | striped, second sample (if you have time) | about 20-25 min |

## Using the result

```
cd apps/SEM_crystal_counter
python evaluate.py "D:/Seafile/JointLab-TEAM-Inkjet/SEM images" "D:/Seafile/JointLab-TEAM-Inkjet/SEM images/annotations" --legacy
```

`--legacy` also scores the old notebook pipeline for comparison. Run this from
`apps/SEM_crystal_counter`, not the repo root, because the root `secrets.py` breaks numpy
there.

## Other dev tools in this folder

- `run_batch.py <folder> --out <dir>` runs every TIFF and writes overlays, per-grain CSVs,
  per-image and per-sample summaries, and `report.html` (a gallery of all overlays).
- `streamlit run tuner.py --server.address localhost -- <image folder> [<annotation folder> [<log folder>]]`
  opens the live tuning page.
  - Each image starts from the preset chosen for it automatically.
  - Only the three settings that matter most are open. The rest sit under "Advanced
    settings".
  - Every slider has a tooltip.
  - **Auto** and **Reset** buttons get you back to tuned values.
  - The grain outlines, seeds and your clicks can each be switched on and off.
  - With an annotation folder, F1 and the grain-count/size error update live for images you
    annotated.
  - Under "Overlay and editing" there are two ways to get grains:
    - **Automatic detection**: fix mistakes by clicking to **merge** two grains or **split**
      one. The edits survive slider changes, and Undo/Clear are there.
    - **My clicks (one per grain)**, for images where the automatic result is not good
      enough. Click the centre of every grain and the program finds the borders. Clicking on a
      dot removes it.
      - You can start from the automatic grain centres and only fix what is wrong, or load your
        ImageJ clicks for that image.
      - Saving stores the clicks as `points.csv` in the same format as ImageJ, so this doubles
        as annotation for later tuning.
  - **Save as reviewed** stores the final grain map, your edits and the settings in the
    training log (default `~/sem_grain_training_log`, see `training_log.py`). Save also when
    nothing needed fixing: confirmed results are training data too.
  - Install the dev extras first:
    `pip install streamlit opencv-python-headless streamlit-image-coordinates`.
