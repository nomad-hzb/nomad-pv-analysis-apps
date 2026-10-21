"""Score the cross-section thickness against measurements made in the SEM software.

Some cross-sections are saved twice: once clean and once with measurement bars drawn by the
SEM software (H = height, V = width). The script finds such pairs (consecutive files with at
least 90% identical pixels), extracts the vertical bars from the difference, and compares the
thickness measured on the clean image at each bar's position with the bar's length.

Only thickness bars are compared: bars at least 60% as long as the longest bar of the same
image. Shorter vertical bars measure void heights.

    python evaluate_cross_section.py "D:/.../SEM images/side"
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

import cross_section as cs
import grain_core as gc
import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

END_CAP_PX = 2  # a drawn bar is about 2 px longer than the distance it measures


def find_pairs(folder: Path) -> list[tuple[Path, Path]]:
    """(clean, measured) pairs: consecutive files showing the same field of view."""
    files = sorted(folder.glob("*.tif"))
    pairs = []
    for a, b in zip(files, files[1:]):
        x, y = gc.load_sem_tiff(a).image, gc.load_sem_tiff(b).image
        if x.shape == y.shape and (np.abs(x.astype(int) - y.astype(int)) < 3).mean() > 0.9:
            # the measured one has more pure-white pixels (bars, label text)
            clean, measured = (a, b) if (x == 255).sum() <= (y == 255).sum() else (b, a)
            pairs.append((clean, measured))
    return pairs


def extract_bars(clean: np.ndarray, measured: np.ndarray) -> list[dict]:
    """Vertical measurement bars: long vertical runs of white pixels the overlay added."""
    overlay = (measured == 255) & (clean != 255)
    runs = {}
    for x in range(overlay.shape[1]):
        col = np.concatenate([overlay[:, x], [False]]).astype(int)
        edges = np.diff(np.concatenate([[0], col]))
        starts, stops = np.flatnonzero(edges == 1), np.flatnonzero(edges == -1)
        if len(starts):
            lengths = stops - starts
            i = int(np.argmax(lengths))
            if lengths[i] >= 40:
                runs[x] = (int(starts[i]), int(stops[i]) - 1)
    bars = []
    xs = np.array(sorted(runs))
    for group in np.split(xs, np.flatnonzero(np.diff(xs) > 1) + 1) if len(xs) else []:
        top = min(runs[x][0] for x in group)
        bottom = max(runs[x][1] for x in group)
        bars.append({"x": float(np.mean(group)), "y_top": top, "y_bottom": bottom})
    return bars


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("folder")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    rows = []
    for clean_path, measured_path in find_pairs(Path(args.folder)):
        clean, measured = gc.load_sem_tiff(clean_path), gc.load_sem_tiff(measured_path)
        bars = extract_bars(clean.image, measured.image)
        if not bars:
            continue
        result = cs.measure_thickness(clean)
        px = clean.pixel_size_nm
        longest = max(b["y_bottom"] - b["y_top"] for b in bars)
        for bar in bars:
            length = bar["y_bottom"] - bar["y_top"]
            if length < 0.6 * longest:
                continue  # a void height, not a thickness
            x = int(round(bar["x"]))
            rows.append(
                {
                    "image": clean_path.stem,
                    "x": x,
                    "bar_nm": (length + 1 - END_CAP_PX) * px,
                    "measured_nm": float(result.thickness_nm[x]),
                }
            )
    if not rows:
        logger.error("No measured pairs with thickness bars found in %s", args.folder)
        return
    table = pd.DataFrame(rows)
    table["error"] = (table["measured_nm"] - table["bar_nm"]) / table["bar_nm"]
    pd.set_option("display.width", 160)
    logger.info("%s", table.round(3).to_string(index=False))
    logger.info(
        "\n%d thickness bars: mean |error| %.1f%%, max %.0f%%, bias %+.1f%%",
        len(table),
        100 * table["error"].abs().mean(),
        100 * table["error"].abs().max(),
        100 * table["error"].mean(),
    )


if __name__ == "__main__":
    main()
