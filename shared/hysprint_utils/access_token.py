import ast
import getpass
import logging
import os
from pathlib import Path

from hysprint_utils.api_calls import SESSION

# Usage logging moved to usage_tracking; re-exported so existing imports keep working.
from hysprint_utils.usage_tracking import log_button_usage, log_notebook_usage  # noqa: F401

logger = logging.getLogger(__name__)


TOKEN_FILE_NAME = "nomad_secrets.py"
"""The local token file: one line NOMAD_TOKEN = "...", at the repo root or an app folder."""

LEGACY_TOKEN_FILE_NAME = "secrets.py"
"""Its old name, still read: at the repo root it shadows the stdlib secrets module (numpy and
plotly then fail with "cannot import name randbits"), so a warning asks to rename it."""


def _search_dirs(start: Path) -> list[Path]:
    """start and its parents up to the repo root (the first folder with bootstrap.py or .git),
    inclusive. Outside a checkout only start itself: a token file further up belongs to
    something else."""
    dirs = []
    for directory in [start, *start.parents]:
        dirs.append(directory)
        if (directory / "bootstrap.py").is_file() or (directory / ".git").exists():
            return dirs
    return [start]


def _read_token_assignment(path: Path) -> str | None:
    """The string assigned to NOMAD_TOKEN in path, read as data: nothing in the file runs."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, UnicodeDecodeError, SyntaxError) as error:
        logger.warning("Could not read the token file %s: %s", path, error)
        return None
    for node in tree.body:
        if (
            isinstance(node, ast.Assign)
            and any(isinstance(t, ast.Name) and t.id == "NOMAD_TOKEN" for t in node.targets)
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
        ):
            return node.value.value.strip() or None
    logger.warning('%s has no NOMAD_TOKEN = "..." line', path)
    return None


def _load_token_from_secrets_file() -> str | None:
    """NOMAD_TOKEN from the nearest token file (nomad_secrets.py, or the old secrets.py)
    between the current folder and the repo root."""
    for directory in _search_dirs(Path.cwd()):
        for name in (TOKEN_FILE_NAME, LEGACY_TOKEN_FILE_NAME):
            path = directory / name
            if not path.is_file():
                continue
            if name == LEGACY_TOKEN_FILE_NAME:
                logger.warning(
                    "Reading the token from %s: please rename it to %s (secrets.py shadows "
                    "the Python module of the same name)",
                    path,
                    TOKEN_FILE_NAME,
                )
            token = _read_token_assignment(path)
            if token:
                return token
    return None


def get_token(url, name=None):
    token = os.environ.get("NOMAD_CLIENT_ACCESS_TOKEN")
    if token:
        return token

    token = _load_token_from_secrets_file()
    if token:
        return token

    user = name if name is not None else input("Username")
    print("Password:")
    password = getpass.getpass()

    # get token from the api:
    response = SESSION.post(
        f"{url}/auth/token", data=dict(username=user, password=password), timeout=60
    )
    if response.status_code == 401:
        raise Exception(response.json()["detail"])
    return response.json()["access_token"]
