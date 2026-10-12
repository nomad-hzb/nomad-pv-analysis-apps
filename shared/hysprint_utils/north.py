"""Where this notebook runs inside a NOMAD NORTH tool: the user and the upload it lives in.

Under a NORTH tool the working directory is .../uploads/<upload_id>/.../<AppFolder>. The
helpers below read that from the cwd at call time, anchored on the "uploads" mount rather
than a fixed number of levels, because how deep the repo sits inside the upload depends on
how it was deployed (unpacked at the top: <upload_id>/apps/<AppFolder>; `git clone` inside
the upload: <upload_id>/nomad-pv-analysis-apps/apps/<AppFolder>).
"""

import os

UPLOADS_DIR_NAME = "uploads"


def get_current_user() -> str:
    """The NOMAD username of the person running this notebook, or '' if unknown."""
    return os.environ.get("NOMAD_CLIENT_USER", "")


def _cwd_parts() -> list[str]:
    """The current working directory as path segments, separator-agnostic."""
    return [part for part in os.getcwd().replace("\\", "/").split("/") if part]


def _uploads_index(parts: list[str]) -> int | None:
    """Index of the NOMAD 'uploads' mount in parts, or None if cwd is not under one.

    The leftmost match wins: the mount lives at a fixed prefix (/home/jovyan/uploads), so a
    later segment of the same name is an upload or folder that happens to be called
    "uploads". Needs at least <upload_id>/<AppFolder> after it to be usable.
    """
    for index, part in enumerate(parts):
        if part == UPLOADS_DIR_NAME and index + 2 < len(parts):
            return index
    return None


def get_upload_id() -> str:
    """This app's own NOMAD upload ID, read from the working directory."""
    parts = _cwd_parts()
    index = _uploads_index(parts)
    if index is None:
        # Not under an uploads mount (local dev, tests): best-effort fixed-depth guess.
        return os.path.basename(os.path.dirname(os.path.dirname(os.getcwd())))
    return parts[index + 1]


def get_uploads_path() -> str:
    """'uploads/<upload_id>/.../<container>' for the current working directory.

    <container> is the folder holding all app folders ("apps" for this repo). Everything
    between the upload ID and the app folder is kept, so a repo cloned into a subdirectory
    of the upload keeps that subdirectory in the path.
    """
    parts = _cwd_parts()
    index = _uploads_index(parts)
    if index is None:
        container = os.path.basename(os.path.dirname(os.getcwd()))
        return f"{UPLOADS_DIR_NAME}/{get_upload_id()}/{container}"
    # From 'uploads' up to, but not including, this app's own folder.
    return "/".join(parts[index:-1])
