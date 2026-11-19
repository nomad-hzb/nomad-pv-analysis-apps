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


# NORTH gives a tool a NOMAD token that expires 24 hours after the container starts (seen on
# HZB SE, 2026-11-19); after that every request answers 401 "Expired token." until the server
# is stopped and the tool launched again. Restarting the kernel or the tab does not help.


def is_expired_token(response) -> bool:
    """True when a NOMAD response refuses the request because the token has expired."""
    if response is None or getattr(response, "status_code", None) != 401:
        return False
    try:
        return "expired" in (response.text or "").lower()
    except Exception:  # noqa: BLE001 - an unreadable body is simply not this case
        return False


def hub_control_panel_url() -> str:
    """The JupyterHub control panel of this NORTH tool ('' outside NORTH).

    JupyterHub gives every server JUPYTERHUB_BASE_URL (e.g. "/nomad-oasis/north/"); without
    it, NOMAD's NORTH lives at "<Oasis path>/north/". Both are put on the Oasis host from
    hysprint_utils.config, so the link follows the deployment instead of naming HZB SE."""
    if not os.environ.get("NOMAD_CLIENT_ACCESS_TOKEN"):
        return ""
    from hysprint_utils import config

    base = os.environ.get("JUPYTERHUB_BASE_URL", "").strip()
    if not base:
        oasis_path = config.API_ENDPOINT.rstrip("/").removesuffix("/v1").removesuffix("/api")
        base = f"{oasis_path}/north/"
    parts = [config.URL_BASE.rstrip("/"), base.strip("/"), "hub/home"]
    return "/".join(part for part in parts if part)


def expired_token_hint() -> str:
    """What to do about an expired token, as one message for the user."""
    url = hub_control_panel_url()
    if url:
        return (
            "This is an error and we are working on it. For now, please manually reset the "
            f"container: open {url} , press Stop My Server, wait until it has stopped, then "
            "launch the tool again."
        )
    return (
        "Your NOMAD token has expired. Put a new one into nomad_secrets.py "
        '(NOMAD_TOKEN = "...") and run the app again.'
    )
