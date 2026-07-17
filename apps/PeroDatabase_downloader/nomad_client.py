"""Low level transport for the NOMAD Archive API.

This module has one job: send a single query request and return the
parsed JSON. No pagination, no widgets, no business logic. Keeping the
network layer this small makes it trivial to test and to swap out.
"""

import requests


class NomadClient:
    def __init__(self, api_url: str, token: str = None, timeout: int = 60):
        self.api_url = api_url.rstrip("/")
        self.token = token or None
        self.timeout = timeout

    def set_token(self, token: str) -> None:
        self.token = token or None

    def set_url(self, api_url: str) -> None:
        self.api_url = api_url.rstrip("/")

    def _headers(self) -> dict:
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    def post_query(self, payload: dict) -> dict:
        """POST to /entries/query and return the parsed JSON body.

        Raises requests.HTTPError on a non 200 status so the caller can
        surface a readable message to the user.
        """
        response = requests.post(
            f"{self.api_url}/entries/query",
            headers=self._headers(),
            json=payload,
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.json()
