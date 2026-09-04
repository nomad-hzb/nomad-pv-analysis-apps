"""Tests for the ISA Previewer's own logic: config consistency, path handling, link gating,
measurement listing and section assembly. Nothing here talks to NOMAD or opens an h5."""

import os

import pytest


# ---------------------------------------------------------------------------
# config consistency
# ---------------------------------------------------------------------------
def test_link_order_covers_every_link_exactly_once(cfg):
    """Every variant renders LINK_ORDER, so a link missing from it would never appear."""
    assert sorted(cfg.LINK_ORDER) == sorted(cfg.APP_LINKS)
    assert len(cfg.LINK_ORDER) == len(set(cfg.LINK_ORDER))


def test_every_variant_section_has_a_builder(cfg, gui):
    """A section name with no builder would raise KeyError only once a file is opened."""
    known = set(gui.SECTION_NAMES)
    for name, variant in cfg.VARIANTS.items():
        assert set(variant.sections) <= known, f"variant {name} names an unknown section"


def test_analysis_variants_accept_a_file_from_the_main_previewer(cfg):
    """The two analysis variants take a head start from a link, the main previewer does not."""
    assert cfg.VARIANTS["main"].select_from_store is False
    assert cfg.VARIANTS["giwaxs"].select_from_store is True
    assert cfg.VARIANTS["optical"].select_from_store is True


# ---------------------------------------------------------------------------
# standing on their own: opened from the dashboard rather than from a link
# ---------------------------------------------------------------------------
def test_stored_path_is_ignored_once_the_file_is_gone(dm, monkeypatch, tmp_path):
    """The IPython store is an on-disk database, so a stale entry outlives its file."""
    monkeypatch.setattr(dm, "_read_stored", lambda _name: str(tmp_path / "deleted.h5"))

    assert dm.get_stored_h5_path() is None


def test_stored_path_is_used_while_the_file_is_there(dm, monkeypatch, tmp_path):
    existing = tmp_path / "run.h5"
    existing.write_bytes(b"")
    monkeypatch.setattr(dm, "_read_stored", lambda _name: str(existing))

    assert dm.get_stored_h5_path() == str(existing)


def test_preselect_leaves_the_selection_empty_with_nothing_stored(dm, gui, monkeypatch):
    """Opened cold from the dashboard, an analysis notebook starts on its own selectors."""
    monkeypatch.setattr(dm, "get_stored_h5_path", lambda: None)
    called = []
    monkeypatch.setattr(dm, "upload_id_from_path", lambda path: called.append(path))

    gui.preselect_from_store(_Select(), _Select(), _Select(), _IntText())

    assert called == []


class _Select:
    """Minimal stand-in for widgets.Select: enough to notice if preselect touches it."""

    def __init__(self):
        self.options = []
        self.value = None


class _IntText:
    def __init__(self):
        self.value = 0


# ---------------------------------------------------------------------------
# upload folder <-> upload id
# ---------------------------------------------------------------------------
def test_upload_id_from_path_takes_the_part_after_the_last_dash(dm):
    path = os.path.join("/home/jovyan/uploads", "my-run-2026-AbCdEfGhIjKlMnOpQrStUv", "run.h5")
    assert dm.upload_id_from_path(path) == "AbCdEfGhIjKlMnOpQrStUv"


def test_upload_id_from_path_returns_none_outside_an_upload_folder(dm):
    """A folder name with no dash is not an upload folder, so there is no id to report."""
    assert dm.upload_id_from_path(os.path.join("/tmp", "somewhere", "run.h5")) is None


# ---------------------------------------------------------------------------
# links
# ---------------------------------------------------------------------------
def test_build_notebook_url_addresses_a_sibling_in_this_app(dm, cfg, monkeypatch):
    monkeypatch.setattr(dm, "get_own_upload_folder", lambda: "apps-upload-AAAAAAAAAAAAAAAAAAAAAA")
    monkeypatch.setattr(dm, "get_container", lambda: "apps")

    url = dm.build_notebook_url(cfg.APP_LINKS["giwaxs_analysis"], "someone")

    assert url == (
        "/nomad-oasis/north/user/someone/voila/voila/render"
        "/uploads/apps-upload-AAAAAAAAAAAAAAAAAAAAAA/apps/giwaxs_analysis.ipynb"
    )


def test_build_notebook_url_addresses_another_app_folder(dm, cfg, monkeypatch):
    monkeypatch.setattr(dm, "get_own_upload_folder", lambda: "apps-upload-AAAAAAAAAAAAAAAAAAAAAA")
    monkeypatch.setattr(dm, "get_container", lambda: "apps")

    url = dm.build_notebook_url(cfg.APP_LINKS["peak_analyzer"], "someone")

    assert url.endswith("/apps/Peak_Explorer/peak_analyzer.ipynb")


def test_build_notebook_url_uses_an_upload_override_without_the_container(dm, cfg, monkeypatch):
    """A target in another upload need not mirror this repo's apps/<AppFolder> layout."""
    monkeypatch.setattr(dm, "get_own_upload_folder", lambda: "apps-upload-AAAAAAAAAAAAAAAAAAAAAA")
    monkeypatch.setattr(dm, "get_container", lambda: "apps")
    link = cfg.AppLink(
        label="Elsewhere",
        folder="",
        notebook="other.ipynb",
        upload_id="team-BBBBBBBBBBBBBBBBBBBBBB",
    )

    url = dm.build_notebook_url(link, "someone")

    assert url.endswith("/uploads/team-BBBBBBBBBBBBBBBBBBBBBB/other.ipynb")
    assert "/apps/" not in url


def test_available_links_drops_links_whose_dataset_is_missing(dm, cfg, monkeypatch):
    """Only the reflectance based link survives an h5 that holds nothing else."""
    reflectance = cfg.APP_LINKS["thickness"].requires_h5_dataset
    monkeypatch.setattr(dm, "h5_has_dataset", lambda _path, dataset: dataset == reflectance)
    monkeypatch.setattr(dm, "build_notebook_url", lambda link, _user: f"/url/{link.notebook}")

    labels = [label for label, _url in dm.available_links("run.h5", "someone")]

    assert labels == [cfg.APP_LINKS["thickness"].label, cfg.APP_LINKS["peak_analyzer"].label]


def test_available_links_keeps_config_order(dm, cfg, monkeypatch):
    monkeypatch.setattr(dm, "h5_has_dataset", lambda _path, _dataset: True)
    monkeypatch.setattr(dm, "build_notebook_url", lambda link, _user: f"/url/{link.notebook}")

    labels = [label for label, _url in dm.available_links("run.h5", "someone")]

    assert labels == [cfg.APP_LINKS[key].label for key in cfg.LINK_ORDER]


# ---------------------------------------------------------------------------
# measurement listing
# ---------------------------------------------------------------------------
def test_list_h5_measurements_returns_nothing_for_the_placeholder(dm, cfg):
    """Selecting "---" must not fire a query that cannot succeed."""
    assert dm.list_h5_measurements("url", "token", cfg.PLACEHOLDER_OPTION, "upload") == []
    assert dm.list_h5_measurements("url", "token", "", "upload") == []


def test_list_h5_measurements_skips_non_h5_and_unmounted_uploads(dm, monkeypatch):
    measurements = [
        ({"data_file": ["run.h5", "notes.txt"], "description": "first"}, {"upload_id": "mounted"}),
        ({"data_file": ["other.h5"]}, {"upload_id": "elsewhere"}),
    ]
    monkeypatch.setattr(dm, "get_specific_data_of_sample", lambda *a, **k: measurements)
    monkeypatch.setattr(
        dm,
        "resolve_h5_path",
        lambda upload_id, name: f"/uploads/{upload_id}/{name}" if upload_id == "mounted" else None,
    )

    options = dm.list_h5_measurements("url", "token", "SAMPLE_1 [a run]", "mounted")

    assert options == [("first---run.h5", "/uploads/mounted/run.h5")]


def test_sample_id_from_option_strips_the_description(dm):
    assert dm.sample_id_from_option("SAMPLE_1 [a run]") == "SAMPLE_1"
    assert dm.sample_id_from_option("SAMPLE_1") == "SAMPLE_1"


# ---------------------------------------------------------------------------
# section assembly
# ---------------------------------------------------------------------------
class _FakePreviewer:
    """Stands in for PERFECTPREVIEWER: display_cuts finds nothing, comparison returns two."""

    def display_widgets(self, xrd=True, optical=False):
        return {"giwaxs_content": "giwaxs", "ui": "ui", "optical_content": "optical"}

    def display_optical_data(self):
        return "optical_data"

    def display_logging(self):
        return "logging"

    def display_cuts(self):
        return None

    def display_comparison(self):
        return ("comparison_1", "comparison_2")

    def display_export(self):
        return "export"


@pytest.fixture
def fake_previewer():
    return _FakePreviewer()


def test_build_sections_follows_the_variant_order(gui, cfg, fake_previewer):
    variant = cfg.VARIANTS["main"]

    assert gui.build_sections(fake_previewer, variant) == [
        "giwaxs",
        "ui",
        "optical",
        "logging",
        "export",
    ]


def test_build_sections_skips_a_section_with_nothing_to_show(gui, cfg, fake_previewer):
    """display_cuts returns None for an h5 without detector images; the variant still works."""
    variant = cfg.VARIANTS["giwaxs"]

    assert gui.build_sections(fake_previewer, variant) == ["comparison_1", "comparison_2"]


def test_overview_widgets_passes_the_variant_flags_through(gui, cfg, monkeypatch):
    seen = {}

    class _Recording(_FakePreviewer):
        def display_widgets(self, xrd=True, optical=False):
            seen.update(xrd=xrd, optical=optical)
            return super().display_widgets(xrd=xrd, optical=optical)

    gui.overview_widgets(_Recording(), cfg.VARIANTS["main"])

    assert seen == {"xrd": True, "optical": True}
