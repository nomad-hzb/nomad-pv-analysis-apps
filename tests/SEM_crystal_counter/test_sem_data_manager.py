"""Tests for the SEM data manager: loading (demo, upload, NOMAD with fakes), analysis,
corrections, tables and the training log. Never touches the network."""

import json
from pathlib import Path

import data_manager as dm
import numpy as np
import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def demo():
    manager = dm.SemDataManager()
    assert manager.load_offline(FIXTURES / "demo_images.json")
    manager.analyse_all()
    return manager


def test_demo_images_load_and_analyse(demo):
    table = demo.image_table().set_index("image")
    assert list(table.index) == ["DEMO_A_01.tif", "DEMO_A_02.tif", "DEMO_B_01.tif"]
    assert (table["status"] == "analysed").all()
    # the synthetic films have 30 grains each (DEMO_A); allow a little slack
    assert table.loc["DEMO_A_01.tif", "n_grains"] == pytest.approx(30, abs=3)
    assert table.loc["DEMO_A_01.tif", "pixel_size_nm"] == pytest.approx(3.722)


def test_sample_table_groups_images_by_sample(demo):
    samples = demo.sample_table().set_index("sample")
    assert samples.loc["DEMO_A", "n_images"] == 2
    assert samples.loc["DEMO_B", "n_images"] == 1
    assert "magnification_spread" in samples.columns


def test_results_workbook_holds_every_table(demo):
    import io

    import pandas as pd

    sheets = pd.read_excel(io.BytesIO(demo.results_workbook()), sheet_name=None)
    assert list(sheets) == list(dm.SHEETS)
    assert sheets["Cross-sections"].empty  # the demo has top views only
    grains = sheets["Grains"]
    assert {"image", "sample", "area_nm2", "eq_diameter_nm"} <= set(grains.columns)
    assert set(grains["sample"]) == {"DEMO_A", "DEMO_B"}
    assert len(grains) == len(demo.grains_table())
    assert set(sheets["Samples"]["sample"]) == {"DEMO_A", "DEMO_B"}
    assert set(sheets["Images"]["preset"]) <= {"smooth", "striped"}
    settings = sheets["Settings"].set_index("setting")
    assert settings.loc["striped.min_grain_diameter_nm", "value"] == 250.0
    assert "auto_ratio_threshold" in settings.index
    about = sheets["About"].set_index("item")
    assert about.loc["App", "value"].startswith("SEM Crystal Counter ")


def test_uploads_take_the_sample_from_the_file_name(make_tiff, voronoi_film):
    image, _ = voronoi_film
    manager = dm.SemDataManager()
    content = make_tiff(image, b"Image Pixel Size = 5.0 nm")
    manager.add_uploads([("VP999_01.tif", content), ("VP999_01.tif", content), ("bad.tif", b"x")])
    assert manager.names == ["VP999_01.tif", "VP999_01 (2).tif", "bad.tif"]
    assert manager.entries["VP999_01.tif"].sample_id == "VP999"
    assert manager.entries["bad.tif"].error.startswith("could not read")
    manager.analyse_all()
    table = manager.image_table().set_index("image")
    assert table.loc["VP999_01.tif", "status"] == "analysed"
    assert table.loc["bad.tif", "status"].startswith("could not read")


def test_nomad_load_downloads_detector_files(monkeypatch, make_tiff, voronoi_film):
    image, _ = voronoi_film
    tiff = make_tiff(image, b"Image Pixel Size = 5.0 nm")
    monkeypatch.setattr(dm, "get_ids_in_batch", lambda url, token, batches: ["S1", "S2"])
    monkeypatch.setattr(dm, "get_sample_description", lambda url, token, ids: {"S1": "dry"})
    raw = {
        "S1": [({"detector_data": ["sem/S1_a.tif", "sem/S1_b.tif"]}, {"upload_id": "U1"})],
        "S2": [({"detector_data": ["sem/S2_a.tif"]}, {"upload_id": "U2"})],
    }
    monkeypatch.setattr(dm, "get_all_eqe", lambda url, token, ids, eqe_type: raw)
    fetched = []

    def fake_download(url, token, upload_id, path):
        fetched.append((upload_id, path))
        if path.endswith("S1_b.tif"):
            raise OSError("404 not found")
        return tiff

    monkeypatch.setattr(dm, "download_raw_file", fake_download)
    manager = dm.SemDataManager("https://e.test/api", "tok")
    assert manager.load(["B1"]) == 3
    assert fetched == [("U1", "sem/S1_a.tif"), ("U1", "sem/S1_b.tif"), ("U2", "sem/S2_a.tif")]
    entry = manager.entries["S1_a.tif"]
    assert (entry.sample_id, entry.variation, entry.source) == ("S1", "dry", "nomad")
    assert manager.entries["S1_b.tif"].error.startswith("could not load")  # others still load
    assert manager.entries["S2_a.tif"].sem is not None


def test_click_mode_and_edits_are_kept_per_image(demo):
    name = "DEMO_A_01.tif"
    auto = demo.final_result(name)[0].summary["n_grains"]
    demo.set_click_mode(name, True)
    demo.start_clicks_from_automatic(name)
    assert demo.final_result(name)[0].summary["n_grains"] == auto
    entry = demo.entries[name]
    y, x, _ = entry.clicks[0]
    assert demo.toggle_click(name, y + 2, x + 2) == "removed"  # click near a dot removes it
    assert demo.final_result(name)[0].summary["n_grains"] == auto - 1
    assert demo.toggle_click(name, y, x, kind=dm.HOLE) == "added"
    assert demo.final_result(name)[0].summary["n_holes"] == 1
    demo.undo(name)
    assert len(entry.clicks) == auto - 1
    demo.set_click_mode(name, False)  # back to automatic: clicks stay stored but unused
    assert demo.final_result(name)[0].summary["n_grains"] == auto
    assert demo.image_table().set_index("image").loc[name, "corrected"] == ""


def test_merge_edit_reduces_grains_and_shows_as_corrected(demo):
    name = "DEMO_A_02.tif"
    result, _ = demo.final_result(name)
    labels = result.labels
    a = np.argwhere(labels == 1)[len(np.argwhere(labels == 1)) // 2]
    neighbour = next(
        lab
        for lab in range(2, labels.max() + 1)
        if (np.abs(np.argwhere(labels == lab)[:, None] - a).sum(-1).min()) < 60
    )
    b = np.argwhere(labels == neighbour)[0]
    demo.add_edit(name, {"op": "merge", "points": [a.tolist(), b.tolist()]})
    assert demo.final_result(name)[0].summary["n_grains"] == result.summary["n_grains"] - 1
    assert demo.image_table().set_index("image").loc[name, "corrected"] == "edits"
    demo.clear_corrections(name)
    assert demo.final_result(name)[0].summary["n_grains"] == result.summary["n_grains"]


def test_save_review_writes_to_the_shared_training_log(demo, monkeypatch, tmp_path):
    monkeypatch.setattr(dm, "training_log_dir", lambda: tmp_path)
    name = "DEMO_B_01.tif"
    demo.set_click_mode(name, True)
    demo.start_clicks_from_automatic(name)
    folder = demo.save_review(name, note="demo")
    review = json.loads((folder / "review.json").read_text(encoding="utf-8"))
    assert review["grain_source"] == "clicks" and review["note"] == "demo"
    assert (folder / "points.csv").exists()
    demo.set_click_mode(name, False)


def test_training_log_dir_sits_next_to_the_usage_logs(monkeypatch, tmp_path):
    monkeypatch.setenv("HYSPRINT_USAGE_LOG_DIR", str(tmp_path))
    assert dm.training_log_dir() == tmp_path / "sem_training_log"


def test_workbook_with_chosen_sheets_only(demo):
    import io

    import pandas as pd

    sheets = pd.read_excel(
        io.BytesIO(demo.results_workbook(["Samples", "Grains"])), sheet_name=None
    )
    assert list(sheets) == ["Samples", "Grains"]
    with pytest.raises(ValueError):
        demo.results_workbook([])


@pytest.fixture
def mixed(make_tiff, voronoi_film, cross_section):
    """A top view and a synthetic cross-section (film rows 100-300, 5 nm/px), analysed."""
    manager = dm.SemDataManager()
    meta = b"Image Pixel Size = 5.0 nm"
    manager.add_uploads(
        [
            ("VP1_01.tif", make_tiff(voronoi_film[0], meta)),
            ("VP1_cs.tif", make_tiff(cross_section(top_row=100, film_rows=200), meta)),
        ]
    )
    manager.analyse_all()
    return manager


def test_cross_sections_are_recognised_and_kept_apart(mixed):
    assert mixed.entries["VP1_01.tif"].kind == dm.TOP
    assert mixed.entries["VP1_cs.tif"].kind == dm.CROSS
    images = mixed.image_table().set_index("image")
    assert images.loc["VP1_cs.tif", "kind"] == "cross-section"
    assert images.loc["VP1_cs.tif", "thickness_median_nm"] == pytest.approx(1000, rel=0.05)
    # top-view statistics leave the cross-section out
    assert mixed.sample_table()["n_images"].tolist() == [1]
    assert set(mixed.grains_table(dm.TOP)["image"]) == {"VP1_01.tif"}
    cross = mixed.cross_section_table().set_index("image")
    assert list(cross.index) == ["VP1_cs.tif"]
    assert cross.loc["VP1_cs.tif", "film_bottom"] == "automatic"
    assert cross.loc["VP1_cs.tif", "n_grains"] > 0
    profiles = mixed.thickness_profiles()
    assert len(profiles) == 500 and profiles["thickness_nm"].median() == pytest.approx(
        1000, rel=0.05
    )
    samples = mixed.cross_sample_table().set_index("sample")
    assert samples.loc["VP1", "thickness_p10_nm"] <= samples.loc["VP1", "thickness_p90_nm"]


def test_cross_section_corrections_stay_inside_the_film(mixed):
    name = "VP1_cs.tif"
    film = mixed.film(name)
    mixed.set_click_mode(name, True)
    mixed.start_clicks_from_automatic(name)
    mixed.add_click(name, 20, 250)  # a click in the vacuum above the film
    result, _ = mixed.final_result(name)
    assert (result.labels[~film] == 0).all()
    assert result.summary["kind"] == "cross-section"
    mixed.set_click_mode(name, False)


def test_drawn_bottom_and_image_type_change(mixed):
    name = "VP1_cs.tif"
    mixed.set_bottom_line(name, [(250, 0), (250, 499)])  # 50 rows above the real interface
    summary = mixed.final_result(name)[0].summary
    assert summary["bottom_drawn"] and summary["thickness_median_nm"] == pytest.approx(
        750, rel=0.05
    )
    settings = mixed.settings_table().set_index("setting")
    assert f"{name}: film bottom" in settings.index
    assert "cross-section.min_grain_diameter_nm" in settings.index
    mixed.set_bottom_line(name, [])
    assert mixed.final_result(name)[0].summary["thickness_median_nm"] == pytest.approx(
        1000, rel=0.05
    )
    mixed.set_kind(name, dm.TOP)
    entry = mixed.entries[name]
    assert entry.kind == dm.TOP and entry.thickness is None and entry.analysed
    assert mixed.cross_section_table().empty


def test_images_with_drawn_measurements_start_ignored(make_tiff, voronoi_film):
    image = voronoi_film[0].copy()
    image[50:70, 100:180] = 0  # a black label box of the SEM software ...
    image[56:64, 110:170:3] = 255  # ... with white text
    manager = dm.SemDataManager()
    manager.add_uploads([("VP2_01.tif", make_tiff(image, b"Image Pixel Size = 5.0 nm"))])
    entry = manager.entries["VP2_01.tif"]
    assert entry.has_overlay and entry.ignored
    row = manager.image_table().iloc[0]
    assert row["status"] == "ignored" and row["note"] == dm.OVERLAY_NOTE
