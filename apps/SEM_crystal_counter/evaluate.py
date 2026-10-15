"""Score the grain pipeline against Fiji point annotations (one click per grain).

Annotation files are the Results tables saved from Fiji (see ANNOTATION_GUIDE.md), named
`<image stem>_points.csv` and holding at least X and Y columns in pixels. A `Counter` column
is optional: counter 0 = clear grain, 1 = unsure (unsure points are reported separately).

    python evaluate.py "D:/.../SEM images" "D:/.../annotations" --preset smooth
    python evaluate.py "D:/.../SEM images" "D:/.../annotations" --params p.json

Metrics per image (regions = predicted grains):
    n_true / n_pred   number of annotated grains vs predicted regions
    split_rate        share of predicted regions without any click (over-segmentation)
    merge_rate        share of predicted regions holding 2+ clicks (under-segmentation)
    correct_rate      share of clicks whose region holds exactly that one click
    area_error        relative error of the planimetric mean grain area vs the annotation
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

import grain_core as gc
import numpy as np
import pandas as pd
from run_batch import load_params

logger = logging.getLogger(__name__)


def read_points(path: Path, image_shape: tuple[int, int], full_width: int) -> pd.DataFrame:
    """Fiji Results CSV -> DataFrame[x, y, unsure], restricted to the image above the banner.

    full_width is the TIFF width; a point beyond it means Fiji still had a scale set and saved
    calibrated units instead of pixels.
    """
    table = pd.read_csv(path)
    cols = {c.strip().lower(): c for c in table.columns}
    if "x" not in cols or "y" not in cols:
        raise ValueError(f"{path.name}: needs X and Y columns, found {list(table.columns)}")
    points = pd.DataFrame(
        {
            "x": table[cols["x"]].astype(float),
            "y": table[cols["y"]].astype(float),
            "unsure": table[cols["counter"]].astype(int) > 0 if "counter" in cols else False,
        }
    )
    if len(points) and points["x"].max() > full_width:
        raise ValueError(
            f"{path.name}: X up to {points['x'].max():.0f} but the image is {full_width} px wide. "
            "Coordinates look calibrated; use Analyze > Set Scale > 'Click to Remove Scale' "
            "and measure again (see ANNOTATION_GUIDE.md)."
        )
    return points[points["y"] < image_shape[0]].reset_index(drop=True)


def score(labels: np.ndarray, points: pd.DataFrame, pixel_size_nm: float) -> dict:
    rows = np.clip(points["y"].round().astype(int), 0, labels.shape[0] - 1)
    cols = np.clip(points["x"].round().astype(int), 0, labels.shape[1] - 1)
    hit = labels[rows.to_numpy(), cols.to_numpy()]
    clicks_per_region = np.bincount(hit, minlength=labels.max() + 1)[1:]
    n_pred = int((np.bincount(labels.ravel())[1:] > 0).sum())
    sure = ~points["unsure"].to_numpy()
    single = (hit > 0) & (clicks_per_region[np.maximum(hit - 1, 0)] == 1)  # label 0 = no region
    image_area = labels.size * pixel_size_nm**2
    true_area = image_area / max(len(points), 1)
    pred_area = image_area / max(n_pred, 1)
    return {
        "n_true": len(points),
        "n_true_unsure": int((~sure).sum()),
        "n_pred": n_pred,
        "split_rate": float((clicks_per_region == 0).sum() / max(n_pred, 1)),
        "merge_rate": float((clicks_per_region >= 2).sum() / max(n_pred, 1)),
        "correct_rate": float(single[sure].mean()) if sure.any() else float("nan"),
        "area_error": (pred_area - true_area) / true_area,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("images")
    parser.add_argument("annotations")
    parser.add_argument("--preset", default="smooth", choices=sorted(gc.PRESETS))
    parser.add_argument("--params")
    parser.add_argument(
        "--legacy", action="store_true", help="Also score the old notebook pipeline"
    )
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    params = load_params(args.preset, args.params)
    rows = []
    for ann in sorted(Path(args.annotations).glob("*_points.csv")):
        stem = ann.name.removesuffix("_points.csv")
        image_path = Path(args.images) / f"{stem}.tif"
        if not image_path.exists():
            logger.warning("No image for %s", ann.name)
            continue
        sem = gc.load_sem_tiff(image_path)
        points = read_points(ann, sem.image.shape, sem.image.shape[1])
        result = gc.analyze(sem, params)
        rows.append(
            {"image": stem, "method": "new", **score(result.labels, points, sem.pixel_size_nm)}
        )
        if args.legacy:
            import legacy

            rows.append(
                {
                    "image": stem,
                    "method": "legacy",
                    **score(legacy.segment(sem.image), points, sem.pixel_size_nm),
                }
            )
    if not rows:
        logger.error("No *_points.csv files with matching images found")
        return
    table = pd.DataFrame(rows)
    pd.set_option("display.width", 160)
    logger.info("%s", table.round(3).to_string(index=False))
    logger.info(
        "\nMean over images:\n%s",
        table.groupby("method").mean(numeric_only=True).round(3).to_string(),
    )


if __name__ == "__main__":
    main()
