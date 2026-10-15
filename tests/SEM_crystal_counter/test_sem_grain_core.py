"""Tests for the SEM grain pipeline: loading, measurement, segmentation, scoring."""

import numpy as np
import pandas as pd
import pytest
from evaluate import score
from grain_core import PRESETS, Params, analyze, load_sem_tiff, measure_grains, sample_name
from run_batch import summarize_samples


def _with_banner(height=100, width=120, banner_start=60):
    image = np.full((height, width), 128, dtype=np.uint8)
    image[banner_start : banner_start + 2] = 0  # black frame line
    image[banner_start + 2 :] = 255
    return image


def test_load_reads_pixel_size_and_crops_banner(make_tiff):
    data = make_tiff(_with_banner(), b"\x00Image Pixel Size = 2.233 nm\r\n")
    sem = load_sem_tiff(data, name="VP317_01.tif")
    assert sem.pixel_size_nm == pytest.approx(2.233)
    assert sem.image.shape == (60, 120)
    assert sem.banner_rows == 40


@pytest.mark.parametrize(
    ("text", "expected"), [(b"5.583 nm", 5.583), (b"1.2 \xb5m", 1200.0), (b"800 pm", 0.8)]
)
def test_load_converts_units(make_tiff, text, expected):
    sem = load_sem_tiff(make_tiff(_with_banner(), b"Image Pixel Size = " + text))
    assert sem.pixel_size_nm == pytest.approx(expected)


def test_load_without_metadata_or_banner(make_tiff):
    sem = load_sem_tiff(make_tiff(np.full((50, 60), 100, dtype=np.uint8)))
    assert sem.pixel_size_nm is None
    assert sem.image.shape == (50, 60)


def test_analyze_refuses_unknown_pixel_size(make_tiff):
    sem = load_sem_tiff(make_tiff(np.full((50, 60), 100, dtype=np.uint8)))
    with pytest.raises(ValueError, match="pixel size"):
        analyze(sem, Params())


def test_measure_grains_in_nm_and_edge_flags():
    labels = np.zeros((100, 100), dtype=np.int32)
    labels[20:40, 20:40] = 1  # interior 20x20 px
    labels[0:10, 50:60] = 2  # touches the top edge
    grains = measure_grains(labels, pixel_size_nm=2.0).set_index("grain_id")
    assert grains.loc[1, "area_nm2"] == pytest.approx(400 * 4.0)
    assert not grains.loc[1, "touches_edge"]
    assert grains.loc[1, "ml_weight"] > 1
    assert grains.loc[2, "touches_edge"]
    assert np.isnan(grains.loc[2, "ml_weight"])


def test_pipeline_recovers_synthetic_grains(make_tiff, voronoi_film):
    image, truth = voronoi_film
    sem = load_sem_tiff(make_tiff(image, b"Image Pixel Size = 5.0 nm"), name="synthetic_01.tif")
    result = analyze(sem, PRESETS["smooth"])
    n_true = truth.max()
    assert abs(result.summary["n_grains"] - n_true) <= 0.2 * n_true

    centroids = pd.DataFrame(
        [(np.argwhere(truth == lab).mean(axis=0)) for lab in range(1, n_true + 1)],
        columns=["y", "x"],
    )
    centroids["unsure"] = False
    metrics = score(result.labels, centroids, 5.0)
    assert metrics["correct_rate"] >= 0.8
    assert abs(metrics["area_error"]) <= 0.2


def test_score_counts_splits_and_merges():
    labels = np.array([[1, 1, 2, 2], [3, 3, 4, 4]], dtype=np.int32)
    points = pd.DataFrame({"x": [0, 1, 2], "y": [0, 0, 1], "unsure": [False, False, False]})
    metrics = score(labels, points, 1.0)
    assert metrics["n_pred"] == 4
    assert metrics["merge_rate"] == pytest.approx(1 / 4)  # region 1 holds two clicks
    assert metrics["split_rate"] == pytest.approx(2 / 4)  # regions 2 and 3 hold none
    assert metrics["correct_rate"] == pytest.approx(1 / 3)


def test_sample_name_groups_replicates():
    assert sample_name("VP317_01.tif") == "VP317"
    assert sample_name("cs_VP352_07.tif") == "cs_VP352"
    assert sample_name("single.tif") == "single"


def test_summarize_samples_uses_images_as_replicates():
    images = pd.DataFrame(
        {
            "sample": ["A", "A", "B"],
            "n_grains": [10, 20, 5],
            "grains_per_um2": [1.0, 3.0, 2.0],
            "mean_area_planimetric_nm2": [1.0, 3.0, 2.0],
            "mean_area_ml_nm2": [1.0, 3.0, 2.0],
            "median_area_nm2": [1.0, 3.0, 2.0],
            "mean_eq_diameter_nm": [1.0, 3.0, 2.0],
            "mean_intercept_nm": [1.0, 3.0, 2.0],
            "boundary_length_per_um2": [1.0, 3.0, 2.0],
        }
    )
    out = summarize_samples(images).set_index("sample")
    assert out.loc["A", "n_images"] == 2
    assert out.loc["A", "n_grains_total"] == 30
    assert out.loc["A", "grains_per_um2_mean"] == pytest.approx(2.0)


def test_read_points_parses_fiji_results(tmp_path):
    from evaluate import read_points

    csv = tmp_path / "img_points.csv"
    csv.write_text(" ,X,Y,Counter,Count\n1,10,20,0,1\n2,30,40,1,1\n3,50,700,0,2\n")
    points = read_points(csv, (689, 1024), 1024)
    assert list(points["x"]) == [10, 30]  # the banner click (y=700) is dropped
    assert list(points["unsure"]) == [False, True]


def test_read_points_rejects_calibrated_units(tmp_path):
    from evaluate import read_points

    csv = tmp_path / "img_points.csv"
    csv.write_text(" ,X,Y\n1,1500.5,20\n")
    with pytest.raises(ValueError, match="Remove Scale"):
        read_points(csv, (689, 1024), 1024)
