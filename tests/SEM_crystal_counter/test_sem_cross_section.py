"""Tests for cross-section recognition and thickness, on a synthetic cross-section."""

import cross_section as cs
import numpy as np
import pytest
from grain_core import load_sem_tiff
from scipy.spatial import cKDTree


def _cross_section(top_row=100, film_rows=200, px=5.0, seed=0):
    """Vacuum (dark, smooth) / grainy film / bright interface line / smooth substrate."""
    rng = np.random.default_rng(seed)
    height, width = 420, 500
    img = np.full((height, width), 60.0) + rng.normal(0, 1, (height, width))
    bottom = top_row + film_rows
    # Voronoi grains: no grain edges lined up across the width (those would look like an
    # interface, which real grains never do)
    centres = rng.uniform((0, 0), (film_rows, width), size=(40, 2))
    yy, xx = np.mgrid[:film_rows, :width]
    _, nearest = cKDTree(centres).query(np.column_stack([yy.ravel(), xx.ravel()]))
    film = rng.uniform(110, 170, size=40)[nearest.reshape(film_rows, width)]
    img[top_row:bottom] = film + rng.normal(0, 8, film.shape)
    img[bottom : bottom + 4] = 220
    img[bottom + 4 :] = 140 + rng.normal(0, 1, (height - bottom - 4, width))
    return np.clip(img, 0, 255).astype(np.uint8), px


def test_cross_sections_are_recognised(make_tiff, voronoi_film):
    image, px = _cross_section()
    side = load_sem_tiff(make_tiff(image, f"Image Pixel Size = {px} nm".encode()))
    top_view = load_sem_tiff(make_tiff(voronoi_film[0], b"Image Pixel Size = 5.0 nm"))
    assert cs.is_cross_section(side)
    assert not cs.is_cross_section(top_view)


def test_thickness_of_a_synthetic_film(make_tiff):
    image, px = _cross_section(top_row=100, film_rows=200, px=5.0)
    sem = load_sem_tiff(make_tiff(image, b"Image Pixel Size = 5.0 nm"))
    result = cs.measure_thickness(sem)
    assert np.median(result.top) == pytest.approx(100, abs=3)
    assert np.median(result.bottom) == pytest.approx(300, abs=3)
    assert result.summary["thickness_median_nm"] == pytest.approx(1000, rel=0.03)
    assert result.summary["top_roughness_rms_nm"] < 20


def test_overlay_marks_top_and_bottom(make_tiff):
    image, _ = _cross_section()
    sem = load_sem_tiff(make_tiff(image, b"Image Pixel Size = 5.0 nm"))
    rgb = cs.overlay(cs.measure_thickness(sem))
    assert rgb.shape == (*image.shape, 3)
    assert (rgb == (255, 60, 60)).all(axis=-1).any() and (rgb == (40, 210, 255)).all(axis=-1).any()


def test_thickness_needs_a_pixel_size(make_tiff):
    image, _ = _cross_section()
    with pytest.raises(ValueError, match="pixel size"):
        cs.measure_thickness(load_sem_tiff(make_tiff(image)))
