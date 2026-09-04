# data_manager.py
# NOMAD queries and path resolution for the ISA Previewer. No widget imports.
#
# Two identifiers are in play and are easy to confuse:
#   * the API upload id, 22 characters, what every NOMAD query wants
#   * the upload folder name, "<slug>-<upload_id>", what the filesystem under
#     /home/jovyan/uploads actually contains
# resolve_h5_path is the only place that converts between them.

import logging
import os

import config
import h5py
from insitu_analyser.utils.nomad_api_calls import (
    get_sample_description,
    get_samples_in_upload,
    get_specific_data_of_sample,
    get_uploads_with_entry_type,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Where this app is running
# ---------------------------------------------------------------------------
def get_own_upload_folder() -> str:
    """The folder name of the upload this app is installed in ("<slug>-<upload_id>").

    Under a NOMAD north tool the cwd is <uploads_root>/<upload_folder>/<container>/<AppFolder>,
    so this app sits two levels below its upload, not directly inside it the way the old
    per upload previewer notebooks did.
    """
    return os.path.basename(os.path.dirname(os.path.dirname(os.getcwd())))


def get_uploads_root() -> str:
    """The directory holding every upload folder mounted for this user."""
    return os.path.dirname(os.path.dirname(os.path.dirname(os.getcwd())))


def get_container() -> str:
    """The folder holding all app folders. This repo's upload mirrors the repo, so "apps"."""
    return os.path.basename(os.path.dirname(os.getcwd()))


def find_upload_folder(upload_id: str) -> str | None:
    """Map an API upload id to the mounted folder name that ends with it.

    Returns None when that upload is not mounted for this user, which is normal: an h5 can
    be referenced from an upload the current user cannot see on disk. Callers skip those
    rather than building a path that cannot be opened.
    """
    root = get_uploads_root()
    try:
        candidates = sorted(os.listdir(root))
    except OSError:
        logger.warning("Uploads root %s is not readable", root)
        return None
    for folder in candidates:
        if upload_id in folder:
            return folder
    logger.warning("No mounted upload folder for upload_id %s under %s", upload_id, root)
    return None


def upload_id_from_path(h5_path: str) -> str | None:
    """The API upload id of the upload an already resolved h5 path points into.

    The inverse of find_upload_folder, needed when a file arrives from the IPython store
    rather than from the selectors: the selection has to be rebuilt around it. Upload
    folders are named "<slug>-<upload_id>", so the id is the part after the last dash.
    """
    folder = os.path.basename(os.path.dirname(os.path.abspath(h5_path)))
    upload_id = folder.rsplit("-", 1)[-1]
    if upload_id == folder:
        logger.warning("Path %s is not inside an upload folder", h5_path)
        return None
    return upload_id


def get_current_user() -> str:
    """The NOMAD user the north tool runs as, which every Voila link path contains."""
    return os.environ.get("NOMAD_CLIENT_USER", "")


# ---------------------------------------------------------------------------
# Links to the sibling notebooks
# ---------------------------------------------------------------------------
def build_notebook_url(link: config.AppLink, user: str) -> str:
    """Absolute Voila path that opens one linked notebook.

    Built from where this app is running plus the target's folder, so nothing Oasis specific
    is hardcoded. insitu_analyser's own PERFECTPREVIEWER.link_* methods keep doing the
    opposite (a hardcoded path per Oasis) on purpose, so the per upload notebooks already
    deployed on CE-AME are unaffected by anything here.
    """
    base = config.VOILA_PATH_TEMPLATE.format(user=user)
    if link.upload_id:
        # A target in a different upload is addressed by that upload alone: it does not
        # necessarily mirror this repo's apps/<AppFolder> layout.
        path = f"uploads/{link.upload_id}"
    else:
        path = f"uploads/{get_own_upload_folder()}/{get_container()}"
    folder = f"{link.folder}/" if link.folder else ""
    return f"{base}/{path}/{folder}{link.notebook}"


def available_links(h5_path: str, user: str) -> list[tuple[str, str]]:
    """The (label, url) links worth offering for one h5, in config.LINK_ORDER.

    Every variant offers every link; a link whose requires_h5_dataset is missing from this
    file is dropped, since the notebook behind it would open on nothing.
    """
    links = []
    for key in config.LINK_ORDER:
        link = config.APP_LINKS[key]
        if link.requires_h5_dataset and not h5_has_dataset(h5_path, link.requires_h5_dataset):
            logger.debug("Link %s hidden: %s has no %s", key, h5_path, link.requires_h5_dataset)
            continue
        links.append((link.label, build_notebook_url(link, user)))
    return links


# ---------------------------------------------------------------------------
# Selection: upload -> sample -> measurement
# ---------------------------------------------------------------------------
def list_uploads_with_measurements(url: str, token: str) -> list[tuple[str, str]]:
    """Every visible upload that holds at least one ISA measurement entry.

    Returned as (label, upload_id) pairs sorted by label, ready to become Select options.

    The query lives in insitu_analyser (get_uploads_with_entry_type); this only puts it in
    the shape a Select wants. It replaces the batch selector the previewer used to open
    with, because ISA writes a sample and a substrate archive per run but never a
    HySprint_Batch (see isa_inducer.upload_sample_json), so a batch query returns nothing
    for exactly the uploads this app exists for.
    """
    uploads = get_uploads_with_entry_type(url, token, config.MEASUREMENT_ENTRY_TYPE)
    return sorted(((name, upload_id) for upload_id, name in uploads.items()), key=lambda o: o[0])


def list_samples_in_upload(url: str, token: str, upload_id: str) -> list[str]:
    """Sample options for one upload, as "<lab_id> [<description>]" strings.

    get_sample_description prepends config.PLACEHOLDER_OPTION itself, so the returned list
    always starts with a "nothing selected" entry.
    """
    sample_ids = get_samples_in_upload(url, token, upload_id)
    if not sample_ids:
        logger.info("Upload %s holds no samples", upload_id)
        return [config.PLACEHOLDER_OPTION]
    return get_sample_description(url, token, sample_ids)


def sample_id_from_option(option: str) -> str:
    """The bare lab_id out of a "<lab_id> [<description>]" option."""
    return option.split(" [")[0]


def list_h5_measurements(
    url: str, token: str, sample_option: str, upload_id: str
) -> list[tuple[str, str]]:
    """Every h5 file attached to one sample, as (label, absolute path) pairs.

    Passing upload_id scopes the sample lookup: without it, the same lab_id existing in two
    uploads makes get_entryid raise instead of returning a file list. Measurements
    themselves are still found across uploads, through entry references.

    Files whose upload is not mounted for this user are skipped rather than turned into a
    path that cannot be opened.
    """
    if not sample_option or sample_option == config.PLACEHOLDER_OPTION:
        return []

    sample_id = sample_id_from_option(sample_option)
    measurements = get_specific_data_of_sample(
        url,
        token,
        sample_id,
        config.MEASUREMENT_ENTRY_TYPE,
        with_meta=True,
        upload_id=upload_id,
    )

    options: list[tuple[str, str]] = []
    for data, metadata in measurements:
        for file_name in data.get("data_file", []):
            if not file_name.endswith(config.H5_SUFFIX):
                continue
            path = resolve_h5_path(metadata["upload_id"], file_name)
            if path is None:
                continue
            description = data.get("description", "")
            options.append((f"{description}---{file_name}", path))

    logger.info("Sample %s has %d selectable h5 files", sample_id, len(options))
    return options


def resolve_h5_path(upload_id: str, file_name: str) -> str | None:
    """Absolute path of one h5 file inside a mounted upload, or None if not mounted.

    Always absolute. The old notebooks built a path relative to the upload they lived in
    ("../<folder>/<file>") and the two analysis notebooks then rebuilt an absolute one by
    splitting the stored path into components; one absolute path from the start removes
    both, and works from an app folder that no longer sits inside the data upload.
    """
    folder = find_upload_folder(upload_id)
    if folder is None:
        return None
    return os.path.join(get_uploads_root(), folder, file_name)


# ---------------------------------------------------------------------------
# Reading the opened h5
# ---------------------------------------------------------------------------
def h5_has_dataset(h5_path: str, dataset: str) -> bool:
    """Whether an h5 holds a given dataset or group. Decides which links are offered."""
    try:
        with h5py.File(h5_path, "r") as h5:
            return dataset in h5
    except OSError:
        logger.warning("Could not open %s to check for %s", h5_path, dataset)
        return False


def sample_name_in_h5(h5_path: str) -> str | None:
    """The sample name stored in an h5, used to preselect the sample it belongs to."""
    try:
        with h5py.File(h5_path, "r") as h5:
            if "sample_name" not in h5:
                return None
            return h5["sample_name"][()].decode("utf-8")
    except OSError:
        logger.warning("Could not read sample_name from %s", h5_path)
        return None


# ---------------------------------------------------------------------------
# Handover from the main previewer
# ---------------------------------------------------------------------------
def get_stored_h5_path() -> str | None:
    """The h5 path the main previewer put into the IPython store, if it still exists.

    The store is how a linked notebook receives its file (Peak_Explorer reads it the same
    way). None means nothing usable was handed over, which is not an error: every variant
    also stands on its own through the selectors, so it simply starts empty.

    The existence check matters because the store is an on-disk database, not session state.
    Without it a notebook opened cold from the dashboard would silently reopen whatever file
    some previewer session stored days ago, possibly one that has since been removed.
    """
    path = _read_stored("h5_path")
    if not path:
        return None
    if not os.path.exists(path):
        logger.info("Stored h5 path %s no longer exists; starting on an empty selection", path)
        return None
    return path


def get_stored_screenwidth() -> int | None:
    """The screen width the main previewer put into the IPython store, if any."""
    value = _read_stored("screenwidth")
    return int(value) if value is not None else None


def store_for_linked_notebooks(h5_path: str, screenwidth: int) -> None:
    """Publish the current selection so a linked notebook opens on the same file."""
    ipython = _get_ipython()
    if ipython is None:
        logger.warning("No IPython kernel; linked notebooks will not receive the selection")
        return
    ipython.user_ns["h5_path"] = os.path.abspath(h5_path)
    ipython.user_ns["screenwidth"] = screenwidth
    for name in ("h5_path", "screenwidth"):
        ipython.run_line_magic("store", name)


def _read_stored(name: str):
    ipython = _get_ipython()
    if ipython is None:
        return None
    try:
        ipython.run_line_magic("store", f"-r {name}")
    except Exception:
        logger.exception("Reading %s from the IPython store failed", name)
        return None
    return ipython.user_ns.get(name)


def _get_ipython():
    from IPython import get_ipython

    return get_ipython()
