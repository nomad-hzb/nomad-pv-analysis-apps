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


def test_merging_everything_into_one_region_does_not_crash(make_tiff, voronoi_film):
    image, _ = voronoi_film
    sem = load_sem_tiff(make_tiff(image, b"Image Pixel Size = 5.0 nm"))
    result = analyze(sem, Params(merge_threshold=100.0))  # every boundary counts as weak
    assert result.summary["n_grains"] == 1


def test_featureless_image_does_not_crash(make_tiff):
    rng = np.random.default_rng(0)
    image = rng.normal(128, 3, size=(120, 160)).clip(0, 255).astype(np.uint8)
    sem = load_sem_tiff(make_tiff(image, b"Image Pixel Size = 5.0 nm"))
    result = analyze(sem, Params(min_grain_diameter_nm=400.0))
    assert result.summary["n_grains"] <= 1


def test_auto_preset_picks_smooth_for_plain_grains(make_tiff, voronoi_film):
    from grain_core import AUTO_RATIO_THRESHOLD, analyze_auto

    image, truth = voronoi_film
    sem = load_sem_tiff(make_tiff(image, b"Image Pixel Size = 5.0 nm"))
    result = analyze_auto(sem)
    assert result.summary["preset"] == "smooth"
    assert result.summary["preset_ratio"] <= AUTO_RATIO_THRESHOLD
    assert abs(result.summary["n_grains"] - truth.max()) <= 0.2 * truth.max()


def test_summarize_samples_drops_flagged_images_when_others_exist():
    cols = [
        "grains_per_um2",
        "mean_area_planimetric_nm2",
        "mean_area_ml_nm2",
        "median_area_nm2",
        "mean_eq_diameter_nm",
        "mean_intercept_nm",
        "boundary_length_per_um2",
    ]
    images = pd.DataFrame(
        {
            "sample": ["A", "A", "B"],
            "n_grains": [50, 4, 3],
            "reliable": [True, False, False],
            **{c: [1.0, 100.0, 7.0] for c in cols},
        }
    )
    out = summarize_samples(images).set_index("sample")
    assert out.loc["A", "mean_area_planimetric_nm2_mean"] == pytest.approx(1.0)
    assert out.loc["A", "n_images_flagged"] == 1
    assert out.loc["B", "n_images"] == 1  # nothing reliable: keep what there is


def test_overlay_toggles_outlines_and_seeds(make_tiff, voronoi_film):
    from grain_core import overlay

    image, _ = voronoi_film
    sem = load_sem_tiff(make_tiff(image, b"Image Pixel Size = 5.0 nm"))
    result = analyze(sem, PRESETS["smooth"])
    plain = overlay(result, show_outlines=False)
    assert np.array_equal(plain[..., 0], image)  # nothing drawn
    assert not np.array_equal(overlay(result), plain)
    seeded = overlay(result, show_seeds=True, show_outlines=False)
    assert (seeded == (255, 40, 40)).all(axis=-1).any()


def _two_grain_result(make_tiff):
    """A 60x80 film with a dark vertical groove at x=40: two grains, split correctly."""
    from grain_core import Result, measure_grains

    image = np.full((60, 80), 150, dtype=np.uint8)
    image[:, 39:42] = 60
    sem = load_sem_tiff(make_tiff(image, b"Image Pixel Size = 5.0 nm"))
    labels = np.where(np.arange(80) < 40, 1, 2)[None, :].repeat(60, axis=0).astype(np.int32)
    bmap = (image < 100).astype(float)
    seeds = np.zeros_like(labels)
    seeds[30, 20], seeds[30, 60] = 1, 2
    grains = measure_grains(labels, 5.0)
    return Result(sem, Params(), image / 255.0, bmap, seeds, labels, labels, grains, {})


def test_apply_edits_merges_two_clicked_grains(make_tiff):
    from grain_core import apply_edits

    result = _two_grain_result(make_tiff)
    edited, warnings = apply_edits(result, [{"op": "merge", "points": [[10, 10], [10, 70]]}])
    assert warnings == []
    assert edited.summary["n_grains"] == 1
    assert edited.summary["n_edits"] == 1


def test_apply_edits_split_follows_the_groove(make_tiff):
    from grain_core import apply_edits

    result = _two_grain_result(make_tiff)
    merged, _ = apply_edits(result, [{"op": "merge", "points": [[10, 10], [10, 70]]}])
    resplit, warnings = apply_edits(merged, [{"op": "split", "point": [30, 70]}])
    assert warnings == []
    assert resplit.summary["n_grains"] == 2
    left, right = resplit.labels[30, 10], resplit.labels[30, 70]
    assert left != right
    assert (resplit.labels[:, :38] == left).all() and (resplit.labels[:, 43:] == right).all()


def test_apply_edits_reports_edits_that_no_longer_apply(make_tiff):
    from grain_core import apply_edits

    result = _two_grain_result(make_tiff)
    edited, warnings = apply_edits(result, [{"op": "merge", "points": [[10, 10], [20, 20]]}])
    assert len(warnings) == 1 and "same grain" in warnings[0]
    assert edited.summary["n_grains"] == 2
    assert edited.summary["n_edits_skipped"] == 1


def test_training_log_round_trip(make_tiff, tmp_path):
    from grain_core import apply_edits
    from training_log import find_review, load_reviews, save_review

    result = _two_grain_result(make_tiff)
    edits = [{"op": "merge", "points": [[10, 10], [10, 70]]}]
    edited, warnings = apply_edits(result, edits)
    folder = save_review(tmp_path, edited, edits, warnings, raw_n_grains=2, note="test")
    reviews = load_reviews(tmp_path)
    assert len(reviews) == 1 and reviews[0].folder == folder
    assert reviews[0].meta["edits"] == edits
    assert reviews[0].meta["n_grains_before_edits"] == 2
    assert reviews[0].meta["n_grains_after_edits"] == 1
    assert np.array_equal(reviews[0].labels, edited.labels)
    assert find_review(tmp_path, result.sem) is not None
    save_review(tmp_path, edited, edits)  # saving again replaces, not duplicates
    assert len(load_reviews(tmp_path)) == 1


def test_params_files_with_removed_keys_still_load():
    old = '{"denoise": "gaussian", "seed_method": "hminima", "hminima_h": 0.1, "compactness": 0.01,'
    old += ' "min_grain_diameter_nm": 250.0}'
    params = Params.model_validate_json(old)
    assert params.min_grain_diameter_nm == 250.0
    assert not hasattr(params, "seed_method")
