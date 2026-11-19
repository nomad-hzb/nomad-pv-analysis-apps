"""An expired NOMAD token says what to do about it (#280).

NORTH tool tokens expire 24 h after the container starts; every request then answers
401 "Expired token." The shared sessions and the login panel add a hint to that error."""

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
import requests

from hysprint_utils import api_calls, auth_manager, config, north

HUB = "https://oasis.test/nomad-oasis/north/hub/home"


@pytest.fixture
def in_north(monkeypatch):
    monkeypatch.setenv("NOMAD_CLIENT_ACCESS_TOKEN", "tool-token")
    monkeypatch.setenv("JUPYTERHUB_BASE_URL", "/nomad-oasis/north/")
    monkeypatch.setattr(config, "URL_BASE", "https://oasis.test")


def _response(status, body):
    response = requests.Response()
    response.status_code = status
    response._content = json.dumps(body).encode()
    response.reason = "Unauthorized" if status == 401 else "Error"
    response.url = "https://oasis.test/nomad-oasis/api/v1/entries/archive/query"
    return response


# --- recognising the expired token ------------------------------------------------------


def test_expired_token_is_a_401_that_says_expired():
    assert north.is_expired_token(_response(401, {"detail": "Expired token."}))
    assert not north.is_expired_token(_response(401, {"detail": "Not authenticated"}))
    assert not north.is_expired_token(_response(403, {"detail": "Expired token."}))
    assert not north.is_expired_token(None)


# --- the hub link -----------------------------------------------------------------------


def test_hub_link_from_jupyterhub_base_url(in_north):
    assert north.hub_control_panel_url() == HUB


def test_hub_link_falls_back_to_the_oasis_path(in_north, monkeypatch):
    monkeypatch.delenv("JUPYTERHUB_BASE_URL")
    monkeypatch.setattr(config, "API_ENDPOINT", "/nomad-oasis/api/v1")
    assert north.hub_control_panel_url() == HUB


def test_hub_link_with_a_hub_at_the_root(in_north, monkeypatch):
    monkeypatch.setenv("JUPYTERHUB_BASE_URL", "/")
    assert north.hub_control_panel_url() == "https://oasis.test/hub/home"


def test_no_hub_link_outside_north(monkeypatch):
    monkeypatch.delenv("NOMAD_CLIENT_ACCESS_TOKEN", raising=False)
    assert north.hub_control_panel_url() == ""


def test_hint_in_north_names_the_reset_and_the_link(in_north):
    hint = north.expired_token_hint()
    assert hint.startswith("This is an error and we are working on it.")
    assert HUB in hint and "Stop My Server" in hint


def test_hint_outside_north_asks_for_a_new_token_file(monkeypatch):
    monkeypatch.delenv("NOMAD_CLIENT_ACCESS_TOKEN", raising=False)
    assert "nomad_secrets.py" in north.expired_token_hint()


# --- the shared sessions ----------------------------------------------------------------


def test_both_sessions_carry_the_hook():
    for session in (api_calls.SESSION, api_calls.WRITE_SESSION):
        assert api_calls._explain_expired_token in session.hooks["response"]


def test_expired_token_error_keeps_the_401_and_adds_the_hint(in_north):
    response = api_calls._explain_expired_token(_response(401, {"detail": "Expired token."}))
    with pytest.raises(requests.HTTPError) as caught:
        response.raise_for_status()
    first_line, hint = str(caught.value).split("\n")
    assert first_line.startswith("401 Client Error: Unauthorized for url: ")
    assert hint == north.expired_token_hint()
    assert caught.value.response is response


def test_other_errors_are_unchanged(in_north):
    for status, body in [(401, {"detail": "Not authenticated"}), (500, {"detail": "boom"})]:
        response = api_calls._explain_expired_token(_response(status, body))
        with pytest.raises(requests.HTTPError) as caught:
            response.raise_for_status()
        assert "\n" not in str(caught.value)


def test_a_success_still_passes(in_north):
    response = api_calls._explain_expired_token(_response(200, {"data": []}))
    response.raise_for_status()


class _ExpiredOasis(BaseHTTPRequestHandler):
    def do_POST(self):  # noqa: N802 - http.server's name
        self.rfile.read(int(self.headers.get("Content-Length", 0)))
        body = json.dumps({"detail": "Expired token."}).encode()
        self.send_response(401)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


def test_a_real_query_against_an_expired_token_reports_the_hint(in_north, monkeypatch):
    """Through the real SESSION and query_all, against a local server, as an app calls it."""
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")
    server = HTTPServer(("127.0.0.1", 0), _ExpiredOasis)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        url = f"http://127.0.0.1:{server.server_port}/api/v1"
        with pytest.raises(requests.HTTPError) as caught:
            api_calls.query_all(url, "old-token", "entries/archive/query", {})
    finally:
        server.shutdown()
    assert "401 Client Error" in str(caught.value)
    assert HUB in str(caught.value)


# --- the login panel --------------------------------------------------------------------


def test_login_panel_status_adds_the_hint(in_north, monkeypatch):
    messages = []
    manager = auth_manager.AuthenticationManager("https://oasis.test", "/nomad-oasis/api/v1")
    manager.status_callback = lambda message, color=None: messages.append(message)
    manager.current_token = "old-token"

    expired = api_calls._explain_expired_token(_response(401, {"detail": "Expired token."}))
    monkeypatch.setattr(api_calls.SESSION, "get", lambda *a, **k: expired)
    with pytest.raises(requests.HTTPError):
        manager.verify_token()
    assert messages[-1].startswith("Status: API Error (401): Expired token. This is an error")
    assert HUB in messages[-1]
