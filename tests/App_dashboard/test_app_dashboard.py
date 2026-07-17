import os

from data_manager import (
    CATEGORIES,
    URL_BASE,
    VOILA_PATH_TEMPLATE,
    AppEntry,
    build_voila_url,
    get_current_user,
    get_uploads_path,
)

_ENTRY = AppEntry(
    "XRD_peak_finder", "xy_visualizer.ipynb", "XRD Peak Finder", "desc", "fa-mountain"
)


def test_get_current_user_reads_env_var(monkeypatch):
    monkeypatch.setenv("NOMAD_CLIENT_USER", "edgar")
    assert get_current_user() == "edgar"


def test_get_current_user_empty_when_unset(monkeypatch):
    monkeypatch.delenv("NOMAD_CLIENT_USER", raising=False)
    assert get_current_user() == ""


def test_get_uploads_path_derives_upload_id_from_cwd(monkeypatch):
    monkeypatch.setattr(
        os, "getcwd", lambda: "/home/jovyan/uploads/analysis-tools-mr60amaQRZ/App_dashboard"
    )
    assert get_uploads_path() == "uploads/analysis-tools-mr60amaQRZ"


def test_build_voila_url_matches_expected_nomad_structure():
    url = build_voila_url(_ENTRY, "edgar", "uploads/analysis-tools-mr60amaQRZ-Ta21fXdf64Q")

    assert url == (
        VOILA_PATH_TEMPLATE.format(user="edgar")
        + "/uploads/analysis-tools-mr60amaQRZ-Ta21fXdf64Q/XRD_peak_finder/xy_visualizer.ipynb"
    )
    assert url.startswith("/nomad-oasis/north/user/edgar/voila/voila/render/")


def test_categories_cover_every_app_folder_exactly_once():
    apps_dir = os.path.join(os.path.dirname(__file__), "..", "..", "apps")
    all_folders = {
        name
        for name in os.listdir(apps_dir)
        if os.path.isdir(os.path.join(apps_dir, name)) and name != "App_dashboard"
    }

    listed_folders = [entry.folder for entries in CATEGORIES.values() for entry in entries]

    assert len(listed_folders) == len(set(listed_folders)), (
        "duplicate app folder in dashboard registry"
    )
    assert set(listed_folders) == all_folders


def test_url_base_has_no_trailing_slash():
    assert not URL_BASE.endswith("/")
