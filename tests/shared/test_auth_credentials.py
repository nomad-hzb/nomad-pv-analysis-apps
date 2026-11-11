"""Login credentials go in the POST body, never in the URL (S3)."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "shared"))

from hysprint_utils import access_token, api_calls, auth_manager  # noqa: E402


class _Resp:
    status_code = 200
    ok = True

    def raise_for_status(self):
        pass

    def json(self):
        return {"access_token": "tok"}


@pytest.fixture
def seen(monkeypatch):
    calls = []

    def post(url, **kwargs):
        calls.append(("post", url, kwargs))
        return _Resp()

    def get(url, **kwargs):
        calls.append(("get", url, kwargs))
        return _Resp()

    # Every login goes through the one shared session (api_calls.SESSION).
    monkeypatch.setattr(api_calls.SESSION, "post", post)
    monkeypatch.setattr(api_calls.SESSION, "get", get)
    monkeypatch.setattr("getpass.getpass", lambda prompt="": "secret")
    monkeypatch.delenv("NOMAD_CLIENT_ACCESS_TOKEN", raising=False)
    monkeypatch.setattr(access_token, "_load_token_from_secrets_file", lambda: None)
    return calls


def _assert_body_only(call):
    method, url, kwargs = call
    assert method == "post"
    assert url.endswith("/auth/token")
    assert kwargs["data"] == {"username": "u", "password": "secret"}
    assert "params" not in kwargs


def test_auth_manager_sends_credentials_in_body(seen):
    manager = auth_manager.AuthenticationManager("https://e.test", "/api/v1")
    assert manager.authenticate_with_credentials("u", "secret") == "tok"
    _assert_body_only(seen[0])


def test_access_token_get_token_sends_credentials_in_body(seen):
    assert access_token.get_token("https://e.test/api/v1", name="u") == "tok"
    _assert_body_only(seen[0])


def test_api_calls_get_token_sends_credentials_in_body(seen):
    assert api_calls.get_token("https://e.test/api/v1", name="u") == "tok"
    _assert_body_only(seen[0])


class _Refused:
    status_code = 401
    ok = False
    text = '{"detail": "Invalid credentials"}'

    def json(self):
        return {"detail": "Invalid credentials"}


def test_a_refused_login_says_why_the_same_way_everywhere(seen, monkeypatch):
    import requests

    monkeypatch.setattr(api_calls.SESSION, "post", lambda url, **kwargs: _Refused())
    manager = auth_manager.AuthenticationManager("https://e.test", "/api/v1")
    statuses = []
    manager.set_status_callback(lambda message, color=None: statuses.append(message))
    logins = (
        lambda: manager.authenticate_with_credentials("u", "secret"),
        lambda: access_token.get_token("https://e.test/api/v1", name="u"),
        lambda: api_calls.get_token("https://e.test/api/v1", name="u"),
    )
    for login in logins:
        with pytest.raises(requests.HTTPError, match="401.*Invalid credentials"):
            login()
    assert "Invalid credentials" in statuses[0]  # the auth panel still shows NOMAD's reason


def test_an_answer_without_a_token_is_a_value_error(seen, monkeypatch):
    class _NoToken(_Resp):
        def json(self):
            return {}

    monkeypatch.setattr(api_calls.SESSION, "post", lambda url, **kwargs: _NoToken())
    with pytest.raises(ValueError, match="Access token not found"):
        api_calls.password_login("https://e.test/api/v1", "u", "p")
