"""Tests for cross-section recognition and thickness, on a synthetic cross-section."""

import cross_section as cs
import numpy as np
import pytest
from grain_core import load_sem_tiff


def test_cross_sections_are_recognised(cross_section, make_tiff, voronoi_film):
    image, px = cross_section(), 5.0
    side = load_sem_tiff(make_tiff(image, f"Image Pixel Size = {px} nm".encode()))
    top_view = load_sem_tiff(make_tiff(voronoi_film[0], b"Image Pixel Size = 5.0 nm"))
    assert cs.is_cross_section(side)
    assert not cs.is_cross_section(top_view)


def test_thickness_of_a_synthetic_film(cross_section, make_tiff):
    image = cross_section(top_row=100, film_rows=200)
    sem = load_sem_tiff(make_tiff(image, b"Image Pixel Size = 5.0 nm"))
    result = cs.measure_thickness(sem)
    assert np.median(result.top) == pytest.approx(100, abs=3)
    assert np.median(result.bottom) == pytest.approx(300, abs=3)
    assert result.summary["thickness_median_nm"] == pytest.approx(1000, rel=0.03)
    assert result.summary["top_roughness_rms_nm"] < 20


def test_overlay_marks_top_and_bottom(cross_section, make_tiff):
    image = cross_section()
    sem = load_sem_tiff(make_tiff(image, b"Image Pixel Size = 5.0 nm"))
    rgb = cs.overlay(cs.measure_thickness(sem))
    assert rgb.shape == (*image.shape, 3)
    assert (rgb == (255, 60, 60)).all(axis=-1).any() and (rgb == (40, 210, 255)).all(axis=-1).any()


def test_thickness_needs_a_pixel_size(cross_section, make_tiff):
    image = cross_section()
    with pytest.raises(ValueError, match="pixel size"):
        cs.measure_thickness(load_sem_tiff(make_tiff(image)))


def test_measurement_overlay_is_detected():
    from grain_core import has_measurement_overlay

    rng = np.random.default_rng(1)
    image = rng.normal(130, 10, (300, 400)).clip(1, 254).astype(np.uint8)
    assert not has_measurement_overlay(image)
    image[50:70, 100:180] = 0  # a black label box ...
    image[56:64, 110:170:3] = 255  # ... with white text in it
    assert has_measurement_overlay(image)
    dark_void = rng.normal(130, 10, (300, 400)).clip(1, 254).astype(np.uint8)
    dark_void[100:140, 100:160] = 0  # a saturated void: black, but no text
    assert not has_measurement_overlay(dark_void)


def test_drawn_bottom_line_replaces_the_automatic_one(cross_section, make_tiff):
    image = cross_section(top_row=100, film_rows=200)
    sem = load_sem_tiff(make_tiff(image, b"Image Pixel Size = 5.0 nm"))
    drawn = [(250, 0), (250, 499)]  # a line 50 rows above the real interface
    result = cs.measure_thickness(sem, bottom_line=drawn)
    assert (result.bottom == 250).all() and result.summary["bottom_drawn"]
    assert result.summary["thickness_median_nm"] == pytest.approx(750, rel=0.03)
    assert cs.line_from_points([(10, 5)], 20) is None  # one point is not a line


def test_cross_section_grains_stay_inside_the_film(cross_section, make_tiff):
    image = cross_section(top_row=100, film_rows=200)
    sem = load_sem_tiff(make_tiff(image, b"Image Pixel Size = 5.0 nm"))
    result, thick = cs.analyze_cross_section(sem)
    film = cs.film_mask(thick)
    assert result.summary["n_grains"] > 0
    assert (result.labels[~film] == 0).all()
    assert result.summary["kind"] == "cross-section"
    assert {"width_nm", "height_nm"} <= set(result.grains.columns)
