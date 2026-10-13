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
    upload_dir = "test-upload-session-abc123"
    monkeypatch.setattr(
        os, "getcwd", lambda: f"/home/jovyan/uploads/{upload_dir}/apps/App_dashboard"
    )
    assert get_uploads_path() == f"uploads/{upload_dir}/apps"


def test_get_uploads_path_keeps_a_repo_subdirectory_inside_the_upload(monkeypatch):
    """A repo cloned inside an upload sits one level deeper than an unpacked one.

    `git clone` adds the repo directory, so the cwd is
    uploads/<upload_id>/nomad-pv-analysis-apps/apps/<AppFolder>. Walking a fixed two
    levels up used to return the repo folder as the upload ID, dropping the real upload
    from every dashboard link.
    """
    upload_dir = "dashboard_test-ne_Y0arITbmweei7SZW5ug"
    monkeypatch.setattr(
        os,
        "getcwd",
        lambda: f"/home/jovyan/uploads/{upload_dir}/nomad-pv-analysis-apps/apps/App_dashboard",
    )

    assert get_upload_id() == upload_dir
    assert get_uploads_path() == f"uploads/{upload_dir}/nomad-pv-analysis-apps/apps"


def test_get_uploads_path_uses_the_rightmost_uploads_segment(monkeypatch):
    """An upload literally named 'uploads' must not shadow the real mount point."""
    monkeypatch.setattr(os, "getcwd", lambda: "/home/jovyan/uploads/uploads/apps/App_dashboard")

    assert get_upload_id() == "uploads"
    assert get_uploads_path() == "uploads/uploads/apps"


def test_build_voila_url_matches_expected_nomad_structure():
    uploads_path = "uploads/test-upload-session-abc123/apps"
    url = build_voila_url(_ENTRY, "edgar", uploads_path)

    assert url == (
        VOILA_PATH_TEMPLATE.format(user="edgar")
        + f"/{uploads_path}/XRD_peak_finder/xy_visualizer.ipynb"
    )
    assert url.startswith("/nomad-oasis/north/user/edgar/voila/voila/render/")


def test_categories_cover_every_app_folder_without_repeating_a_notebook():
    """Every app folder appears, and no notebook is registered twice.

    Uniqueness is per (folder, notebook), not per folder: one app may expose several
    notebooks as separate cards. ISA_Previewer does, with its previewer plus the GIWAXS,
    optical analysis and timely teller notebooks that share its codebase.
    """
    apps_dir = os.path.join(os.path.dirname(__file__), "..", "..", "apps")
    all_folders = {
        name
        for name in os.listdir(apps_dir)
        if os.path.isdir(os.path.join(apps_dir, name)) and name != "App_dashboard"
    }

    listed = [
        (entry.folder, entry.notebook)
        for entries in CATEGORIES.values()
        for entry in entries
        if not entry.external_url
    ]

    assert len(listed) == len(set(listed)), "duplicate notebook in dashboard registry"
    assert {folder for folder, _ in listed} == all_folders


def test_url_base_has_no_trailing_slash():
    assert not URL_BASE.endswith("/")


def test_build_voila_url_uses_upload_id_when_set():
    uploads_path = "uploads/test-upload-session-abc123/apps"
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
    upload_dir = "test-upload-session-abc123"
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


# --- per-deployment app selection (D1) -----------------------------------------------------


def _names(selection):
    return {
        category: [e.folder or e.name for e in entries]
        for category, entries in selection.categories.items()
    }


def test_no_setting_means_no_change():
    from data_manager import parse_name_list, select_dashboard

    selection = select_dashboard(CATEGORIES, parse_name_list(None), parse_name_list(""))
    assert selection.categories == CATEGORIES
    assert selection.show_learning and selection.show_projects


def test_hide_one_app_by_folder_name_ignoring_case_and_spaces():
    from data_manager import parse_name_list, select_dashboard

    selection = select_dashboard(
        CATEGORIES, hide=parse_name_list(" xps-automated , Sem_crystal_counter")
    )
    folders = {e.folder for entries in selection.categories.values() for e in entries}
    assert "XPS-Automated" not in folders
    assert "LCC_Calculator" in folders  # others untouched


def test_hide_every_app_of_a_category_leaves_it_empty():
    from data_manager import select_dashboard

    category = "Data Management"
    hide = {e.folder.lower() for e in CATEGORIES[category]}
    selection = select_dashboard(CATEGORIES, hide=hide)
    assert selection.categories[category] == []
    assert selection.categories["Build Your Own"] == CATEGORIES["Build Your Own"]


def test_allow_list_shows_only_the_named_apps():
    from data_manager import parse_name_list, select_dashboard

    selection = select_dashboard(CATEGORIES, show=parse_name_list("JV-Analysis,File_Uploader"))
    folders = [e.folder for entries in selection.categories.values() for e in entries]
    assert sorted(folders) == ["File_Uploader", "JV-Analysis"]
    assert not selection.show_learning and not selection.show_projects


def test_learning_and_projects_can_be_hidden_or_allowed_by_name():
    from data_manager import select_dashboard

    assert not select_dashboard(CATEGORIES, hide={"learning"}).show_learning
    assert not select_dashboard(CATEGORIES, hide={"projects"}).show_projects
    allowed = select_dashboard(CATEGORIES, show={"learning"})
    assert allowed.show_learning and not allowed.show_projects


def test_unknown_name_warns_and_changes_nothing(caplog):
    from data_manager import select_dashboard

    with caplog.at_level("WARNING"):
        selection = select_dashboard(CATEGORIES, hide={"jv-analyzis"})
    assert selection.categories == CATEGORIES
    assert "jv-analyzis" in caplog.text


def test_default_project_cards_only_use_full_upload_folder_names():
    """A bare 22-character id cannot be opened (404); such cards are hidden by default."""
    for project in PROJECTS:
        for app in project.apps:
            assert "-" in app.upload_id and len(app.upload_id.rsplit("-", 1)[1]) == 22, app.name


def test_urls_are_percent_encoded():
    entry = AppEntry("My App", "a b#c(1).ipynb", "x", "d", "fa-x")
    url = build_voila_url(entry, "edgar", "uploads/up-1/apps")
    assert url.endswith("/uploads/up-1/apps/My%20App/a%20b%23c%281%29.ipynb")


def test_the_oasis_prefix_comes_from_the_api_endpoint():
    import data_manager as dm_module

    assert dm_module.OASIS_PREFIX == dm_module.API_ENDPOINT.split("/api/")[0]
    assert dm_module.VOILA_PATH_TEMPLATE.startswith(dm_module.OASIS_PREFIX + "/north/user/")
