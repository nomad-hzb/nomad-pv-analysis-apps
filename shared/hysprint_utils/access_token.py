import getpass
import logging
import os
from pathlib import Path

import requests

# Usage logging moved to usage_tracking; re-exported so existing imports keep working.
from hysprint_utils.usage_tracking import log_button_usage, log_notebook_usage  # noqa: F401

logger = logging.getLogger(__name__)


def _load_token_from_secrets_file() -> str | None:
    """Walk up from cwd looking for secrets.py that defines NOMAD_TOKEN."""
    current = Path.cwd()
    for directory in [current, *current.parents]:
        secrets_path = directory / "secrets.py"
        if secrets_path.is_file():
            try:
                namespace: dict = {}
                exec(secrets_path.read_text(encoding="utf-8"), namespace)  # noqa: S102
                token = namespace.get("NOMAD_TOKEN", "")
                if isinstance(token, str) and token.strip():
                    return token.strip()
            except Exception:
                pass
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
    response = requests.get(f"{url}/auth/token", params=dict(username=user, password=password))
    if response.status_code == 401:
        raise Exception(response.json()["detail"])
    return response.json()["access_token"]
