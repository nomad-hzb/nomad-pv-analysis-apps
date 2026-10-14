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
    raw_token: Optional[str] = None
    """The token that was tried, kept even when it could not be verified, so a later server
    switch tries it again instead of staying anonymous for the whole session."""
    reachable: bool = True
    """False when the server could not be reached (as opposed to refusing the token)."""


def authenticate(api_url, token=None, timeout=10):
    token = token or os.environ.get("NOMAD_CLIENT_ACCESS_TOKEN")
    if not token:
        return AuthResult(False, None, None, None, "Not signed in. Using public data.", None)
    try:
        resp = requests.get(
            f"{api_url.rstrip('/')}/users/me",
            headers={"Authorization": f"Bearer {token}"},
            timeout=timeout,
        )
        resp.raise_for_status()
        info = resp.json()
    except requests.HTTPError as exc:
        status = exc.response.status_code if exc.response is not None else None
        if status in (401, 403):
            return AuthResult(
                False, None, None, None, "Token not valid on this server. Using public data.", token
            )
        return AuthResult(
            False,
            None,
            None,
            None,
            f"The server answered with an error ({status}) when checking the token. "
            "Using public data for now.",
            token,
            reachable=False,
        )
    except Exception:  # noqa: BLE001 - timeouts, DNS, connection errors
        return AuthResult(
            False,
            None,
            None,
            None,
            "Could not reach the server to check the token. Using public data for now.",
            token,
            reachable=False,
        )
    user = info.get("name") or info.get("username") or "Unknown"
    return AuthResult(True, token, user, info.get("email"), f"Authenticated as {user}.", token)
