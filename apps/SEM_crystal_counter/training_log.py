"""Log of reviewed segmentations, kept as training data for better initial guesses later.

Every time a user saves an image as reviewed, one folder is written (an older review of the
same image is replaced):

    <log dir>/<image stem>__<image sha256[:12]>/
        labels.png     final grain map after manual edits, 16-bit, 0 = no grain (lossless)
        points.csv     only when the grains came from clicks: X, Y (pixels) per grain centre,
                       the same columns as an ImageJ/Fiji Results table
        review.json    image name + sha256, pixel size, automatic preset choice and ratio,
                       the parameters used, the edit list, grain counts before and after the
                       edits, summary statistics, user, time

The SEM image itself is not copied; it is identified by name and fingerprint.

What the log is for:
- Dense ground truth: labels.png is a complete, user-approved segmentation. evaluate.py can
  score against it like the point annotations, and a model (for example Cellpose) can be
  fine-tuned on image + labels pairs.
- Better presets: the parameters people end up with, and how many edits each image still
  needed, show which settings to change for which kind of image.
"""

from __future__ import annotations

import getpass
import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import grain_core as gc
import numpy as np
from PIL import Image

LOG_VERSION = 1


def image_fingerprint(image: np.ndarray) -> str:
    """sha256 of the (banner-cropped) pixel data plus its shape."""
    digest = hashlib.sha256(np.ascontiguousarray(image).tobytes())
    digest.update(str(image.shape).encode())
    return digest.hexdigest()


def save_review(
    log_dir: str | Path,
    result: gc.Result,
    edits: list[dict],
    edit_warnings: list[str] | None = None,
    raw_n_grains: int | None = None,
    note: str = "",
    points: list[tuple[float, float]] | None = None,
) -> Path:
    """Write (or replace) the review of one image. `result` is the edited result; `points`
    are the (y, x) grain-centre clicks when the grains came from clicks."""
    sha = image_fingerprint(result.sem.image)
    folder = Path(log_dir) / f"{Path(result.sem.name).stem}__{sha[:12]}"
    folder.mkdir(parents=True, exist_ok=True)
    labels = result.labels
    if labels.max() > np.iinfo(np.uint16).max:
        raise ValueError("more than 65535 grains cannot be stored as a 16-bit PNG")
    Image.fromarray(labels.astype(np.uint16)).save(folder / "labels.png")
    points_file = folder / "points.csv"
    if points:
        lines = ["X,Y"] + [f"{x:.1f},{y:.1f}" for y, x in points]
        points_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
    elif points_file.exists():  # a re-save without clicks must not keep stale ones
        points_file.unlink()
    summary = {k: _jsonable(v) for k, v in result.summary.items()}
    review = {
        "log_version": LOG_VERSION,
        "image": result.sem.name,
        "image_sha256": sha,
        "image_shape": list(result.sem.image.shape),
        "pixel_size_nm": result.sem.pixel_size_nm,
        "preset": summary.get("preset"),
        "preset_ratio": summary.get("preset_ratio"),
        "params": result.params.model_dump(),
        "grain_source": "clicks" if points else "automatic",
        "n_clicks": len(points) if points else 0,
        "edits": edits,
        "edit_warnings": edit_warnings or [],
        "n_grains_before_edits": raw_n_grains,
        "n_grains_after_edits": int(len(np.unique(labels[labels > 0]))),
        "summary": summary,
        "note": note,
        "user": getpass.getuser(),
        "saved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    (folder / "review.json").write_text(json.dumps(review, indent=2), encoding="utf-8")
    return folder


@dataclass
class Review:
    folder: Path
    meta: dict
    labels: np.ndarray


def load_reviews(log_dir: str | Path) -> list[Review]:
    """All reviews in a log folder, for training or evaluation."""
    reviews = []
    for meta_path in sorted(Path(log_dir).glob("*/review.json")):
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        labels = np.asarray(Image.open(meta_path.parent / "labels.png")).astype(np.int32)
        reviews.append(Review(meta_path.parent, meta, labels))
    return reviews


def find_review(log_dir: str | Path, sem: gc.SemImage) -> Review | None:
    """The saved review of exactly this image (matched by fingerprint), if any."""
    sha = image_fingerprint(sem.image)
    folder = Path(log_dir) / f"{Path(sem.name).stem}__{sha[:12]}"
    if not (folder / "review.json").exists():
        return None
    meta = json.loads((folder / "review.json").read_text(encoding="utf-8"))
    if meta.get("image_sha256") != sha:
        return None
    labels = np.asarray(Image.open(folder / "labels.png")).astype(np.int32)
    return Review(folder, meta, labels)


def _jsonable(value):
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return None if np.isnan(value) else float(value)
    if isinstance(value, float) and np.isnan(value):
        return None
    if isinstance(value, np.bool_):
        return bool(value)
    return value
