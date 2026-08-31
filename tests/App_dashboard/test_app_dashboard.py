import os

from data_manager import (
    CATEGORIES,
    JUPYTER_PATH_TEMPLATE,
    LEARNING_FOLDER,
    PROJECTS,
    URL_BASE,
    VOILA_PATH_TEMPLATE,
    AppEntry,
    build_jupyter_url,
    build_voila_url,
    get_current_user,
    get_upload_id,
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


def test_get_uploads_path_derives_upload_id_and_container_from_cwd(monkeypatch):
    upload_dir = "analysis_apps_restructuring-WxUahazkSNy-bSE9GaZyZQ"
    monkeypatch.setattr(
        os, "getcwd", lambda: f"/home/jovyan/uploads/{upload_dir}/apps/App_dashboard"
    )
    assert get_uploads_path() == f"uploads/{upload_dir}/apps"


def test_build_voila_url_matches_expected_nomad_structure():
    uploads_path = "uploads/analysis_apps_restructuring-WxUahazkSNy-bSE9GaZyZQ/apps"
    url = build_voila_url(_ENTRY, "edgar", uploads_path)

    assert url == (
        VOILA_PATH_TEMPLATE.format(user="edgar")
        + f"/{uploads_path}/XRD_peak_finder/xy_visualizer.ipynb"
    )
    assert url.startswith("/nomad-oasis/north/user/edgar/voila/voila/render/")


def test_categories_cover_every_app_folder_exactly_once():
    apps_dir = os.path.join(os.path.dirname(__file__), "..", "..", "apps")
    all_folders = {
        name
        for name in os.listdir(apps_dir)
        if os.path.isdir(os.path.join(apps_dir, name)) and name != "App_dashboard"
    }

    listed_folders = [
        entry.folder
        for entries in CATEGORIES.values()
        for entry in entries
        if not entry.external_url
    ]

    assert len(listed_folders) == len(set(listed_folders)), (
        "duplicate app folder in dashboard registry"
    )
    assert set(listed_folders) == all_folders


def test_url_base_has_no_trailing_slash():
    assert not URL_BASE.endswith("/")


def test_build_voila_url_uses_upload_id_when_set():
    uploads_path = "uploads/analysis_apps_restructuring-WxUahazkSNy-bSE9GaZyZQ/apps"
    entry = AppEntry(
        "", "image_cropper.ipynb", "Image Cropper", "desc", "fa-crop", upload_id="abc123"
    )

    url = build_voila_url(entry, "edgar", uploads_path)

    assert url == (VOILA_PATH_TEMPLATE.format(user="edgar") + "/uploads/abc123/image_cropper.ipynb")


def test_projects_apps_all_have_upload_ids_and_unique_names():
    for project in PROJECTS:
        assert project.apps, f"project {project.name!r} has no apps"
        for app in project.apps:
            assert app.upload_id, f"app {app.name!r} in project {project.name!r} has no upload_id"
        names = [app.name for app in project.apps]
        assert len(names) == len(set(names)), f"duplicate app name in project {project.name!r}"


def test_build_your_own_entry_links_straight_to_the_prompt_doc():
    entries = CATEGORIES["Build Your Own"]
    assert len(entries) == 1
    assert entries[0].external_url == (
        "https://raw.githubusercontent.com/nomad-hzb/nomad-pv-analysis-apps/main/"
        "NOMAD_DATA_ACCESS_PROMPT.md"
    )


def test_get_upload_id_derives_from_cwd(monkeypatch):
    upload_dir = "analysis_apps_restructuring-WxUahazkSNy-bSE9GaZyZQ"
    monkeypatch.setattr(
        os, "getcwd", lambda: f"/home/jovyan/uploads/{upload_dir}/apps/App_dashboard"
    )
    assert get_upload_id() == upload_dir


def test_build_jupyter_url_matches_expected_nomad_structure():
    url = build_jupyter_url(LEARNING_FOLDER, "edgar", "abc123")

    assert url == (
        JUPYTER_PATH_TEMPLATE.format(user="edgar") + f"/uploads/abc123/{LEARNING_FOLDER.path}"
    )
    assert url.startswith("/nomad-oasis/north/user/edgar/voila/lab/tree/")


def test_build_jupyter_url_never_hardcodes_an_upload_id():
    """Regression test: LEARNING_FOLDER must resolve against *this* dashboard's own
    upload (via get_upload_id(), the same way Voila links do), not a fixed ID from some
    other upload -- that mismatch is exactly what caused the original 404."""
    url_a = build_jupyter_url(LEARNING_FOLDER, "edgar", "upload-one")
    url_b = build_jupyter_url(LEARNING_FOLDER, "edgar", "upload-two")
    assert "upload-one" in url_a
    assert "upload-two" in url_b


def test_learning_folder_opens_the_first_notebook_and_it_exists_in_repo():
    assert LEARNING_FOLDER.path.endswith(".ipynb"), (
        "LEARNING_FOLDER should point at a specific notebook so JupyterLab opens it "
        "directly, not just the bare folder"
    )

    repo_root = os.path.join(os.path.dirname(__file__), "..", "..")
    assert os.path.isfile(os.path.join(repo_root, LEARNING_FOLDER.path)), (
        f"missing learning notebook: {LEARNING_FOLDER.path}"
    )
