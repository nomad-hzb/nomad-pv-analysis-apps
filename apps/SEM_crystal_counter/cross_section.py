"""Cross-section SEM images: recognition, film top and bottom interface, thickness.

Widget-free like grain_core. A cross-section shows, from the top: vacuum (dark, smooth), the
film (grainy), the bottom interface (the first horizontal line under the film: a dark gap or
the top of a bright layer), then the layers below.

Checked against the thickness bars measured in the SEM software on 10 cross-sections (19
bars, see evaluate_cross_section.py): mean error 4%. The largest differences (up to 23%) are
spots where the bar starts at the front, cleaved grain while grains just behind it reach
higher; this method measures to the highest visible film surface.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from grain_core import SemImage
from scipy import ndimage as ndi
from scipy.signal import find_peaks
from skimage import filters

CROSS_SECTION_RATIO = 0.6
"""An image is a cross-section when the texture of its top 10% rows is below this fraction of
the texture of its most textured rows (90th percentile): vacuum is smooth, top views are grainy
up to the first row. On the 72 reference images top views gave >= 0.90, cross-sections
<= 0.31. Comparing with the most textured rows, not the lower half, keeps it working when the
substrate below the film is smooth."""

TEXTURE_LEVEL = 0.5
"""Film top: first row whose local texture exceeds this fraction between the vacuum's and the
film's (95th percentile) texture. Stable between 0.45 and 0.55 on the reference images."""

MIN_THICKNESS_NM = 150.0
"""The bottom interface is searched at least this far below the film top."""


def local_std(image: np.ndarray, size: int = 5) -> np.ndarray:
    """Local standard deviation (texture) in a size x size window."""
    image = image.astype(float)
    mean = ndi.uniform_filter(image, size)
    return np.sqrt(np.maximum(ndi.uniform_filter(image**2, size) - mean**2, 0))


def cross_section_ratio(image: np.ndarray) -> float:
    """Texture of the top 10% rows relative to the most textured rows (low = cross-section)."""
    rows = np.median(local_std(image), axis=1)
    n = len(rows)
    return float(np.median(rows[: max(n // 10, 3)]) / max(np.percentile(rows, 90), 1e-6))


def is_cross_section(sem: SemImage) -> bool:
    return cross_section_ratio(sem.image) < CROSS_SECTION_RATIO


def film_top(img: np.ndarray, pixel_size_nm: float) -> np.ndarray:
    """Row of the film top per column.

    The first row below the vacuum where the image becomes textured (the film is grainy; the
    vacuum and the out-of-focus film behind the cleaved edge are smooth), snapped to the
    sharpest dark-to-bright edge within 20 nm. Columns without clear texture fall back to where
    the vacuum's darkness ends.
    """
    std = ndi.gaussian_filter1d(local_std(img * 255), sigma=3, axis=1)
    n_vac = max(int(0.08 * img.shape[0]), 5)
    quiet = np.median(std[:n_vac])
    level = quiet + TEXTURE_LEVEL * (np.percentile(std, 95) - quiet)
    smooth = filters.gaussian(img, 1.5)
    vacuum = np.median(smooth[:n_vac])
    bright = vacuum + 0.4 * (np.percentile(smooth, 75) - vacuum)
    gy = ndi.gaussian_filter1d(ndi.sobel(smooth, axis=0), sigma=3, axis=1)
    win = max(int(20 / pixel_size_nm), 3)
    top = np.empty(img.shape[1], dtype=int)
    for x in range(img.shape[1]):
        rough = np.flatnonzero(std[n_vac:, x] > level)
        if len(rough):
            y = n_vac + rough[0]
        else:
            lit = np.flatnonzero(smooth[n_vac:, x] > bright)
            y = n_vac + lit[0] if len(lit) else img.shape[0] - 1
        lo, hi = max(y - win, 0), min(y + win, img.shape[0])
        top[x] = lo + int(np.argmax(gy[lo:hi, x]))
    return ndi.median_filter(top, size=9)


def bottom_interface(img: np.ndarray, top: np.ndarray, pixel_size_nm: float) -> np.ndarray:
    """Row of the bottom interface per column: the first strong horizontal edge (bright or
    dark) that runs across the image at least MIN_THICKNESS_NM below the film top, refined
    per column within 40 nm."""
    smooth = filters.gaussian(img, 1.5)
    gy = np.abs(ndi.sobel(smooth, axis=0))
    gy_x = ndi.gaussian_filter1d(gy, sigma=6, axis=1)  # favour edges that continue sideways
    profile = np.median(gy_x, axis=1)
    start = min(int(np.median(top) + MIN_THICKNESS_NM / pixel_size_nm), img.shape[0] - 2)
    peaks, props = find_peaks(profile[start:], prominence=0)
    if not len(peaks):
        return np.full(img.shape[1], img.shape[0] - 1)
    prominence = props["prominences"]
    y0 = start + int(peaks[prominence >= 0.3 * prominence.max()][0])
    win = max(int(40 / pixel_size_nm), 3)
    lo, hi = max(y0 - win, 0), min(y0 + win, img.shape[0])
    return ndi.median_filter(lo + np.argmax(gy_x[lo:hi], axis=0), size=31)


@dataclass
class CrossSectionResult:
    sem: SemImage
    top: np.ndarray  # row of the film top per column
    bottom: np.ndarray  # row of the bottom interface per column
    thickness_nm: np.ndarray  # per column
    summary: dict = field(default_factory=dict)


def measure_thickness(sem: SemImage) -> CrossSectionResult:
    """Film top, bottom interface and thickness per column, with summary statistics."""
    if sem.pixel_size_nm is None:
        raise ValueError(f"{sem.name}: pixel size unknown")
    px = sem.pixel_size_nm
    img = sem.image.astype(float) / 255
    top = film_top(img, px)
    bottom = bottom_interface(img, top, px)
    thickness = (bottom - top).astype(float) * px
    valid = thickness[thickness > 0]
    summary = {
        "image": sem.name,
        "pixel_size_nm": px,
        "thickness_median_nm": float(np.median(valid)) if len(valid) else float("nan"),
        "thickness_mean_nm": float(np.mean(valid)) if len(valid) else float("nan"),
        "thickness_p10_nm": float(np.percentile(valid, 10)) if len(valid) else float("nan"),
        "thickness_p90_nm": float(np.percentile(valid, 90)) if len(valid) else float("nan"),
        "thickness_min_nm": float(valid.min()) if len(valid) else float("nan"),
        "thickness_max_nm": float(valid.max()) if len(valid) else float("nan"),
        "top_roughness_rms_nm": float(np.std(top) * px),
        "width_measured_nm": float(len(thickness) * px),
    }
    return CrossSectionResult(sem, top, bottom, thickness, summary)


def overlay(result: CrossSectionResult) -> np.ndarray:
    """RGB uint8: the image with the film top (red) and the bottom interface (cyan)."""
    rgb = np.repeat(result.sem.image[..., None], 3, axis=2).astype(np.uint8)
    xs = np.arange(rgb.shape[1])
    for rows, color in ((result.top, (255, 60, 60)), (result.bottom, (40, 210, 255))):
        for dy in (0, 1):
            rgb[np.clip(rows + dy, 0, rgb.shape[0] - 1), xs] = color
    return rgb
