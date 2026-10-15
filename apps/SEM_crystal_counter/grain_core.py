"""Grain segmentation for top-view SEM images of dense polycrystalline films.

Widget-free core: numpy in, numpy/pandas out. Every size parameter is in nm and is converted
to pixels with the pixel size read from the TIFF metadata, so one parameter set works across
magnifications.

Pipeline (see `analyze`):
    load_sem_tiff -> preprocess -> boundary_map -> find_seeds -> watershed
    -> merge_regions -> measure (+ intercept_grain_size as an independent cross-check)

A "grain" is a region enclosed by the outer grain-boundary groove; terraces or stripes inside
a grain are not boundaries (the merge step removes them).
"""

from __future__ import annotations

import io
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd
from PIL import Image
from pydantic import BaseModel, Field
from scipy import ndimage as ndi
from scipy.signal import find_peaks
from skimage import filters, graph, measure, restoration, segmentation
from skimage.feature import peak_local_max
from skimage.graph import rag_boundary

logger = logging.getLogger(__name__)

_PIXEL_SIZE_RE = re.compile(r"Image Pixel Size = ([0-9.]+) ?(pm|nm|\xb5m|um|mm)")
_UNIT_TO_NM = {"pm": 1e-3, "nm": 1.0, "\xb5m": 1e3, "um": 1e3, "mm": 1e6}


class Params(BaseModel):
    """All tunable parameters. Sizes in nm, everything else dimensionless.

    Removed after a sensitivity study on the annotated images (2026-10-15): the denoise method
    choice (gaussian/none only ever lowered F1), the h-minima seed method and compactness (no
    consistent effect). Old params files that still hold these keys load; the keys are ignored.
    """

    # Preprocessing
    background_sigma_nm: float = Field(
        1000.0, description="Gaussian sigma of the subtracted background (0 = off)"
    )
    denoise_strength: float = Field(
        0.8, description="NLM h as a multiple of the estimated noise sigma"
    )
    # Boundary map
    ridge_sigmas_nm: list[float] = Field([8.0], description="Scales of the dark-ridge filter")
    clip_bright_percentile: float = Field(
        90.0,
        description="Cap pixels above this percentile (bright rims) before ridge filter; 100=off",
    )
    ridge_weight: float = Field(
        1.0, description="Weight of the ridge response vs the gradient magnitude"
    )
    # Seeds and watershed
    boundary_threshold: float = Field(
        1.0, description="Multiplier on the Otsu threshold of the boundary map"
    )
    min_grain_diameter_nm: float = Field(
        100.0, description="Smallest grain to resolve; sets seed spacing"
    )
    # Region merging
    merge_threshold: float = Field(
        0.3, description="Merge neighbours whose boundary is weaker than this x the median boundary"
    )
    merge_sigma_nm: float = Field(
        16.0, description="Ridge scale of the map used to judge boundary strength"
    )
    # Measurement
    min_grain_area_nm2: float = Field(
        1500.0, description="Regions smaller than this are merged into a neighbour"
    )
    intercept_spacing_nm: float = Field(
        50.0, description="Spacing of the test lines for the intercept method"
    )


# Tuned 2026-10-15 by F1 against point annotations of VP317_01, VP352_03 (smooth) and
# VP401_05, VP412_05 (striped); see evaluate.py. The defaults of Params are the smooth preset.
PRESETS: dict[str, Params] = {
    "smooth": Params(),
    "striped": Params(ridge_sigmas_nm=[8.0, 24.0], min_grain_diameter_nm=300.0),
}


@dataclass
class SemImage:
    image: np.ndarray  # uint8 grayscale, banner removed
    pixel_size_nm: float | None
    name: str
    banner_rows: int = 0
    meta: dict = field(default_factory=dict)


def load_sem_tiff(source: str | Path | bytes, name: str | None = None) -> SemImage:
    """Load an SEM TIFF from a path or raw bytes, crop the info banner, read the pixel size.

    Zeiss SmartSEM files carry `Image Pixel Size = <v> <unit>` in their CZ_SEM tag; we search the
    raw bytes for it so that the same code works for uploads and NOMAD downloads. The banner is
    found as the all-black frame line that separates it from the image; if there is none the
    image is used uncropped.
    """
    if isinstance(source, (str, Path)):
        raw = Path(source).read_bytes()
        name = name or Path(source).name
    else:
        raw = bytes(source)
        name = name or "upload"
    image = np.asarray(Image.open(io.BytesIO(raw)).convert("L"))

    pixel_size_nm = None
    meta: dict = {}
    match = _PIXEL_SIZE_RE.search(raw.decode("latin-1"))
    if match:
        pixel_size_nm = float(match.group(1)) * _UNIT_TO_NM[match.group(2)]
        meta["pixel_size_raw"] = match.group(0)
    else:
        logger.warning("%s: no 'Image Pixel Size' in metadata; sizes stay in pixels", name)

    cut = _banner_start(image)
    banner_rows = image.shape[0] - cut
    return SemImage(image[:cut].copy(), pixel_size_nm, name, banner_rows, meta)


def _banner_start(image: np.ndarray) -> int:
    """Row index where the info banner (incl. its black frame line) starts, or the height."""
    height = image.shape[0]
    black = np.flatnonzero(image.max(axis=1) == 0)
    black = black[black > height // 2]
    return int(black[0]) if black.size else height


def _px(nm: float, pixel_size_nm: float) -> float:
    return nm / pixel_size_nm


def preprocess(image: np.ndarray, pixel_size_nm: float, params: Params) -> np.ndarray:
    """Flatten slow intensity variations (charging) and denoise. Returns float in ~0..1."""
    img = image.astype(np.float64) / 255.0
    if params.background_sigma_nm > 0:
        background = filters.gaussian(img, _px(params.background_sigma_nm, pixel_size_nm))
        img = img - background + background.mean()
    sigma = _noise_sigma(img)
    img = restoration.denoise_nl_means(
        img,
        h=params.denoise_strength * sigma,
        sigma=sigma,
        patch_size=5,
        patch_distance=6,
        fast_mode=True,
    )
    lo, hi = np.percentile(img, (0.5, 99.5))
    return np.clip((img - lo) / max(hi - lo, 1e-9), 0, 1)


def _noise_sigma(img: np.ndarray) -> float:
    """Gaussian noise sigma (Immerkaer 1996); avoids the PyWavelets dependency of estimate_sigma."""
    kernel = np.array([[1, -2, 1], [-2, 4, -2], [1, -2, 1]], dtype=np.float64)
    response = ndi.convolve(img, kernel)[1:-1, 1:-1]
    return float(np.sqrt(np.pi / 2) * np.abs(response).mean() / 6)


def _normalize(arr: np.ndarray) -> np.ndarray:
    lo, hi = np.percentile(arr, (1, 99.5))
    return np.clip((arr - lo) / max(hi - lo, 1e-12), 0, 1)


def clip_bright(img: np.ndarray, params: Params) -> np.ndarray:
    """Cap bright edge rims so their flanks do not look like dark ridges."""
    if params.clip_bright_percentile >= 100:
        return img
    return np.minimum(img, np.percentile(img, params.clip_bright_percentile))


def boundary_map(img: np.ndarray, pixel_size_nm: float, params: Params) -> np.ndarray:
    """0..1 map that is high on grain boundaries: dark-ridge response plus gradient magnitude."""
    img = clip_bright(img, params)
    sigmas = [max(_px(s, pixel_size_nm), 1.0) for s in params.ridge_sigmas_nm]
    ridge = _normalize(filters.sato(img, sigmas=sigmas, black_ridges=True))
    grad = _normalize(filters.sobel(filters.gaussian(img, sigmas[0])))
    return params.ridge_weight * ridge + (1 - params.ridge_weight) * grad


def find_seeds(bmap: np.ndarray, pixel_size_nm: float, params: Params) -> np.ndarray:
    """Labelled seed image, one seed per (candidate) grain interior."""
    r_min = max(_px(params.min_grain_diameter_nm, pixel_size_nm) / 2, 1.0)
    threshold = filters.threshold_otsu(bmap) * params.boundary_threshold
    interior = bmap < threshold
    interior_labels = measure.label(interior)
    sizes = np.bincount(interior_labels.ravel())
    keep = sizes >= np.pi * r_min**2 / 4
    keep[0] = False
    interior = keep[interior_labels]
    dist = ndi.distance_transform_edt(interior)
    peaks = peak_local_max(
        dist,
        min_distance=max(int(r_min), 1),
        threshold_abs=r_min / 2,
        labels=measure.label(interior),
    )
    seeds = np.zeros(bmap.shape, dtype=np.int32)
    seeds[tuple(peaks.T)] = np.arange(1, len(peaks) + 1)
    return seeds


def watershed(bmap: np.ndarray, seeds: np.ndarray, params: Params) -> np.ndarray:
    return segmentation.watershed(bmap, seeds).astype(np.int32)


def merge_regions(
    labels: np.ndarray, img: np.ndarray, pixel_size_nm: float, params: Params
) -> np.ndarray:
    """Merge neighbours separated by weak boundaries, then absorb regions below the min area.

    Boundary strength is the mean of a dark-ridge map along the shared edge. The threshold is
    relative to the median edge strength of the over-segmentation, so faint but real boundaries
    are judged against the image's own contrast rather than against its deepest pores.
    """
    if len(np.unique(labels)) < 2:
        return segmentation.relabel_sequential(labels)[0]
    sigma = max(_px(params.merge_sigma_nm, pixel_size_nm), 1.0)
    strength = filters.sato(clip_bright(img, params), sigmas=[sigma], black_ridges=True)
    rag = rag_boundary(labels, strength)
    weights = [d["weight"] for _, _, d in rag.edges(data=True)]
    if not weights:
        return segmentation.relabel_sequential(labels)[0]
    threshold = params.merge_threshold * float(np.median(weights))
    labels = labels.copy()
    for _ in range(3):  # shared boundaries change after a merge, so re-evaluate a few times
        n_before = len(np.unique(labels))
        if n_before < 2:  # rag_boundary fails without any boundary left
            break
        # cut_threshold numbers its output from 0, which regionprops treats as background
        labels = graph.cut_threshold(labels, rag_boundary(labels, strength), threshold) + 1
        if len(np.unique(labels)) == n_before:
            break
    min_area_px = params.min_grain_area_nm2 / pixel_size_nm**2
    return _absorb_small(labels, strength, min_area_px)


def _absorb_small(labels: np.ndarray, strength: np.ndarray, min_area_px: float) -> np.ndarray:
    """Merge each region below min_area_px into the neighbour with the weakest shared boundary."""
    labels = segmentation.relabel_sequential(labels)[0]
    for _ in range(10):
        areas = np.bincount(labels.ravel())
        small = np.flatnonzero((areas > 0) & (areas < min_area_px))
        if small.size == 0 or np.count_nonzero(areas) < 2:
            break
        rag = rag_boundary(labels, strength)
        lut = np.arange(areas.size)
        for lab in small:
            if lab in rag and rag[lab]:
                lut[lab] = min(rag[lab], key=lambda n, lab=lab: rag[lab][n]["weight"])
        for _ in range(lut.size):  # resolve chains a->b->c
            nxt = lut[lut]
            if np.array_equal(nxt, lut):
                break
            lut = nxt
        if np.array_equal(lut, np.arange(areas.size)):
            break
        labels = segmentation.relabel_sequential(lut[labels])[0]
    return labels


def measure_grains(labels: np.ndarray, pixel_size_nm: float) -> pd.DataFrame:
    """Per-grain table in nm. Edge grains are flagged; interior grains get a Miles-Lantuejoul
    weight that corrects the bias against large grains (which touch the border more often)."""
    height, width = labels.shape
    rows = []
    for region in measure.regionprops(labels):
        minr, minc, maxr, maxc = region.bbox
        touches_edge = minr == 0 or minc == 0 or maxr == height or maxc == width
        bw, bh = maxc - minc, maxr - minr
        ml_weight = (
            np.nan if touches_edge else (width * height) / max((width - bw) * (height - bh), 1)
        )
        area_nm2 = region.area * pixel_size_nm**2
        perimeter_nm = region.perimeter * pixel_size_nm
        rows.append(
            {
                "grain_id": region.label,
                "area_nm2": area_nm2,
                "eq_diameter_nm": region.equivalent_diameter_area * pixel_size_nm,
                "feret_max_nm": region.feret_diameter_max * pixel_size_nm,
                "major_axis_nm": region.axis_major_length * pixel_size_nm,
                "minor_axis_nm": region.axis_minor_length * pixel_size_nm,
                "aspect_ratio": region.axis_major_length / max(region.axis_minor_length, 1e-9),
                "perimeter_nm": perimeter_nm,
                "circularity": 4 * np.pi * area_nm2 / max(perimeter_nm**2, 1e-9),
                "solidity": region.solidity,
                "orientation_deg": np.degrees(region.orientation),
                "centroid_x_px": region.centroid[1],
                "centroid_y_px": region.centroid[0],
                "touches_edge": touches_edge,
                "ml_weight": ml_weight,
            }
        )
    return pd.DataFrame(rows)


def intercept_grain_size(bmap: np.ndarray, pixel_size_nm: float, params: Params) -> float:
    """Mean linear intercept (nm) from boundary-map peaks along horizontal and vertical lines.

    Independent of the segmentation, so a large disagreement with it flags an image for review.
    """
    spacing = max(int(_px(params.intercept_spacing_nm, pixel_size_nm)), 1)
    min_gap = max(int(_px(params.min_grain_diameter_nm, pixel_size_nm) / 2), 1)
    threshold = filters.threshold_otsu(bmap) * params.boundary_threshold
    smooth = filters.gaussian(bmap, 1.0)
    crossings, length = 0, 0
    for profile in [*smooth[spacing // 2 :: spacing], *smooth.T[spacing // 2 :: spacing]]:
        peaks, _ = find_peaks(profile, height=threshold, distance=min_gap, prominence=0.1)
        crossings += len(peaks)
        length += len(profile)
    return length * pixel_size_nm / crossings if crossings else float("nan")


MIN_GRAINS_FOR_STATS = 20
"""Images holding fewer grains (edge grains counted as half) give no usable mean: at 50kX a
film with 500-1000 nm grains shows only about 5. They are flagged and left out of the
per-sample statistics."""


def summarize(
    grains: pd.DataFrame, labels: np.ndarray, pixel_size_nm: float, intercept_nm: float
) -> dict:
    """Image-level statistics. Planimetric (Jeffries) density: interior + half the edge grains."""
    image_area_um2 = labels.size * pixel_size_nm**2 / 1e6
    if grains.empty:
        return {"n_grains": 0, "image_area_um2": image_area_um2}
    interior = grains[~grains["touches_edge"]]
    n_edge = int(grains["touches_edge"].sum())
    n_planimetric = len(interior) + 0.5 * n_edge
    w = interior["ml_weight"]
    a = interior["area_nm2"]
    mean_area_ml = float((w * a).sum() / w.sum()) if len(interior) else float("nan")
    boundary = segmentation.find_boundaries(labels, mode="inner")
    boundary_um = boundary.sum() * pixel_size_nm / 2 / 1e3  # inner boundaries count both sides
    return {
        "n_grains": len(grains),
        "n_interior": len(interior),
        "n_edge": n_edge,
        "image_area_um2": image_area_um2,
        "grains_per_um2": n_planimetric / image_area_um2,
        "mean_area_planimetric_nm2": image_area_um2 * 1e6 / n_planimetric,
        "mean_area_ml_nm2": mean_area_ml,
        "median_area_nm2": float(a.median()) if len(interior) else float("nan"),
        "area_weighted_mean_area_nm2": float((a**2).sum() / a.sum())
        if len(interior)
        else float("nan"),
        "mean_eq_diameter_nm": float(interior["eq_diameter_nm"].mean())
        if len(interior)
        else float("nan"),
        "mean_intercept_nm": intercept_nm,
        "boundary_length_per_um2": boundary_um / image_area_um2,
        "n_planimetric": n_planimetric,
        "reliable": n_planimetric >= MIN_GRAINS_FOR_STATS,
    }


@dataclass
class Result:
    sem: SemImage
    params: Params
    pre: np.ndarray
    bmap: np.ndarray
    seeds: np.ndarray
    raw_labels: np.ndarray
    labels: np.ndarray
    grains: pd.DataFrame
    summary: dict


def analyze(sem: SemImage, params: Params, pre: np.ndarray | None = None) -> Result:
    """Run the full pipeline. `pre` may pass an already preprocessed image (same params)."""
    if sem.pixel_size_nm is None:
        raise ValueError(f"{sem.name}: pixel size unknown; set it explicitly before analysis")
    px = sem.pixel_size_nm
    if pre is None:
        pre = preprocess(sem.image, px, params)
    bmap = boundary_map(pre, px, params)
    seeds = find_seeds(bmap, px, params)
    raw_labels = watershed(bmap, seeds, params)
    labels = merge_regions(raw_labels, pre, px, params)
    grains = measure_grains(labels, px)
    summary = summarize(grains, labels, px, intercept_grain_size(bmap, px, params))
    summary.update({"image": sem.name, "pixel_size_nm": px, "n_seeds": int(seeds.max())})
    return Result(sem, params, pre, bmap, seeds, raw_labels, labels, grains, summary)


def merge_at(labels: np.ndarray, first: tuple[int, int], second: tuple[int, int]) -> str | None:
    """Merge the grains under two clicked (y, x) points, in place. Returns a warning or None."""
    a, b = int(labels[first]), int(labels[second])
    if a == b:
        return f"merge at {first} and {second}: both clicks are in the same grain"
    labels[labels == b] = a
    return None


def split_at(labels: np.ndarray, bmap: np.ndarray, point: tuple[int, int]) -> str | None:
    """Split the grain under a clicked (y, x) point, in place, so that the click becomes a grain
    of its own. Returns a warning or None.

    The watershed runs on the boundary map inside that grain only, between two markers: the
    click and the grain pixel farthest from it. It therefore divides along the strongest
    groove between them. A region holding three merged grains needs a second split click.
    """
    region = int(labels[point])
    mask = labels == region
    ys, xs = np.nonzero(mask)
    far = np.argmax((ys - point[0]) ** 2 + (xs - point[1]) ** 2)
    markers = np.zeros(labels.shape, dtype=np.int32)
    markers[ys[far], xs[far]] = 1
    markers[point] = 2
    parts = segmentation.watershed(bmap, markers, mask=mask)
    new_part = parts == 2
    if not new_part.any() or new_part.sum() == mask.sum():
        return f"split at {point}: no boundary found inside this grain"
    labels[new_part] = labels.max() + 1
    return None


def apply_edits(result: Result, edits: list[dict]) -> tuple[Result, list[str]]:
    """Replay manual edits on a result and re-measure.

    Edits are recorded as clicked image positions, not grain ids:
        {"op": "merge", "points": [[y1, x1], [y2, x2]]}
        {"op": "split", "point": [y, x]}
    so they still apply after a parameter change renumbers the grains. Edits that no longer
    make sense (both merge clicks in one grain, a split with no boundary) are skipped and
    reported.
    """
    if not edits:
        return result, []
    labels = result.labels.copy()
    warnings = []
    for edit in edits:
        if edit["op"] == "merge":
            first, second = (tuple(map(int, pt)) for pt in edit["points"])
            warning = merge_at(labels, first, second)
        elif edit["op"] == "split":
            warning = split_at(labels, result.bmap, tuple(map(int, edit["point"])))
        else:
            warning = f"unknown edit {edit!r}"
        if warning:
            warnings.append(warning)
    labels = segmentation.relabel_sequential(labels)[0]
    px = result.sem.pixel_size_nm
    grains = measure_grains(labels, px)
    summary = summarize(grains, labels, px, result.summary.get("mean_intercept_nm", float("nan")))
    summary.update({k: v for k, v in result.summary.items() if k not in summary})
    summary.update({"n_edits": len(edits), "n_edits_skipped": len(warnings)})
    edited = Result(
        result.sem,
        result.params,
        result.pre,
        result.bmap,
        result.seeds,
        result.raw_labels,
        labels,
        grains,
        summary,
    )
    return edited, warnings


AUTO_RATIO_THRESHOLD = 3.0
"""Grain-count ratio smooth/striped above which an image is treated as striped. On the 47
reference images smooth films gave 1.6-2.6 and striped films 3.2-27.8: grains with internal
terraces fall apart under the smooth preset, while plain grains barely change."""


def analyze_auto(sem: SemImage) -> Result:
    """Analyze with both presets and keep the one that fits the film type.

    Both presets share the preprocessing, so this costs less than two full runs. The chosen
    preset and the ratio are recorded in the summary so a borderline call is visible.
    """
    smooth, striped = PRESETS["smooth"], PRESETS["striped"]
    pre = preprocess(sem.image, sem.pixel_size_nm, smooth) if sem.pixel_size_nm else None
    results = {"smooth": analyze(sem, smooth, pre), "striped": analyze(sem, striped, pre)}
    ratio = results["smooth"].summary["n_grains"] / max(results["striped"].summary["n_grains"], 1)
    chosen = "striped" if ratio > AUTO_RATIO_THRESHOLD else "smooth"
    result = results[chosen]
    result.summary.update({"preset": chosen, "preset_ratio": ratio})
    return result


def overlay(result: Result, show_seeds: bool = False, show_outlines: bool = True) -> np.ndarray:
    """RGB uint8: image with grain outlines (interior green, edge grains orange) and seeds."""
    rgb = np.repeat(result.sem.image[..., None], 3, axis=2).astype(np.uint8)
    if show_outlines:
        edge_ids = (
            set(result.grains.loc[result.grains["touches_edge"], "grain_id"])
            if len(result.grains)
            else set()
        )
        bounds = segmentation.find_boundaries(result.labels, mode="inner")
        on_edge = np.isin(result.labels, list(edge_ids)) & bounds
        rgb[bounds & ~on_edge] = (40, 230, 60)
        rgb[on_edge] = (255, 150, 0)
    if show_seeds:
        ys, xs = np.nonzero(result.seeds)
        draw_dots(rgb, ys, xs, (255, 40, 40), radius=1)
    return rgb


def draw_dots(rgb: np.ndarray, ys, xs, color: tuple, radius: int = 2) -> None:
    """Paint square dots in place (clipped to the image)."""
    ys, xs = np.asarray(ys, dtype=int), np.asarray(xs, dtype=int)
    for dy in range(-radius, radius + 1):
        for dx in range(-radius, radius + 1):
            rgb[np.clip(ys + dy, 0, rgb.shape[0] - 1), np.clip(xs + dx, 0, rgb.shape[1] - 1)] = (
                color
            )


def sample_name(image_name: str) -> str:
    """'VP317_01.tif' -> 'VP317'. Used to group images per sample when no NOMAD id is known."""
    stem = Path(image_name).stem
    return stem.rsplit("_", 1)[0] if "_" in stem else stem
