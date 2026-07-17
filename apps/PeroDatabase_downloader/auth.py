"""Authentication against a NOMAD server.

Reads a token from NOMAD_CLIENT_ACCESS_TOKEN, verifies it against the
server's /users/me endpoint, and reports who is logged in. The token is
never printed or logged. Failure is non fatal: the app falls back to
public data, so an expired token or a missing one does not stop you.
"""

import os
from dataclasses import dataclass
from typing import Optional

import requests


@dataclass
class AuthResult:
    ok: bool
    token: Optional[str]
    user: Optional[str]
    email: Optional[str]
    message: str


def authenticate(api_url, token=None, timeout=10):
    token = token or os.environ.get("NOMAD_CLIENT_ACCESS_TOKEN")
    if not token:
        return AuthResult(False, None, None, None, "Not signed in. Using public data.")
    try:
        resp = requests.get(
            f"{api_url.rstrip('/')}/users/me",
            headers={"Authorization": f"Bearer {token}"},
            timeout=timeout,
        )
        resp.raise_for_status()
        info = resp.json()
    except Exception:
        return AuthResult(
            False, None, None, None, "Token not valid on this server. Using public data."
        )
    user = info.get("name") or info.get("username") or "Unknown"
    return AuthResult(True, token, user, info.get("email"), f"Authenticated as {user}.")
