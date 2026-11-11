import json
import os

import requests

from hysprint_utils.api_calls import SESSION

# Re-exported: code written against auth_manager.LAYOUT / STRINGS keeps working.
from hysprint_utils.ui_constants import LAYOUT, STRINGS  # noqa: F401


# --- API Client for URL Construction ---
class APIClient:
    def __init__(self, base_url, api_endpoint):
        self.base_url = base_url
        self.api_endpoint = api_endpoint
        self.full_api_url = f"{base_url}{api_endpoint}"
        # The GUI sits next to the API: "/nomad-oasis/api/v1" -> "/nomad-oasis/gui", and
        # "/api/v1" (an Oasis served at the root) -> "/gui".
        self.gui_url = f"{base_url}{api_endpoint.split('/api/')[0]}/gui"

    # Authentication endpoints
    def get_auth_token_url(self):
        """Get URL for token authentication"""
        return f"{self.full_api_url}/auth/token"

    def get_user_verification_url(self):
        """Get URL for user verification"""
        return f"{self.full_api_url}/users/me"

    # Data entry URLs
    def get_entry_data_url(self, entry_id):
        """Get URL for entry data view"""
        return f"{self.gui_url}/entry/id/{entry_id}/data/data"

    def get_entry_image_preview_url(self, entry_id, image_index=0):
        """Get URL for entry image preview (for SEM images)"""
        return (
            f"{self.gui_url}/entry/id/{entry_id}/data/data/"
            f"images:{image_index}/image_preview/preview"
        )

    # Generic entry URL
    def get_entry_url(self, entry_id, entry_type=None):
        """Get appropriate URL based on entry type"""
        if entry_type and "SEM" in entry_type:
            return self.get_entry_image_preview_url(entry_id)
        else:
            return self.get_entry_data_url(entry_id)

    # API endpoint getters
    def get_api_url(self):
        """Get the full API URL"""
        return self.full_api_url

    def get_base_url(self):
        """Get the base URL"""
        return self.base_url


# --- Authentication Manager ---
class AuthenticationManager:
    def __init__(self, url_base, api_endpoint):
        self.url_base = url_base
        self.url = f"{url_base}{api_endpoint}"
        self.status_callback = None
        self.current_token = None
        self.current_user_info = None
        # Create API client instance for this auth manager
        self.api_client = APIClient(url_base, api_endpoint)

    def set_status_callback(self, callback):
        """Set callback function to update UI status"""
        self.status_callback = callback

    def _update_status(self, message, color=None):
        """Update status through callback if available"""
        if self.status_callback:
            self.status_callback(message, color)

    def authenticate_with_credentials(self, username, password):
        """Authenticate using username and password"""
        if not username or not password:
            raise ValueError("Username and Password are required.")

        auth_dict = dict(username=username, password=password)
        token_url = self.api_client.get_auth_token_url()

        try:
            # NOMAD takes the login as form data; query params would leak the password into URLs.
            response = SESSION.post(token_url, data=auth_dict, timeout=LAYOUT["TIMEOUT_STANDARD"])
            response.raise_for_status()

            token_data = response.json()
            if "access_token" not in token_data:
                raise ValueError("Access token not found in response.")

            self.current_token = token_data["access_token"]
            return self.current_token

        except requests.exceptions.RequestException as e:
            self._handle_request_error(e)
            raise

    def authenticate_with_token(self, token=None):
        """Authenticate using provided token or environment variable"""
        if token is None:
            token = os.environ.get("NOMAD_CLIENT_ACCESS_TOKEN")
            if not token:
                raise ValueError(
                    "Token not found in environment variable 'NOMAD_CLIENT_ACCESS_TOKEN'."
                )

        self.current_token = token
        return self.current_token

    def verify_token(self):
        """Verify the current token and get user info"""
        if not self.current_token:
            raise ValueError("No token available for verification.")

        verify_url = self.api_client.get_user_verification_url()
        headers = {"Authorization": f"Bearer {self.current_token}"}

        try:
            verify_response = SESSION.get(
                verify_url, headers=headers, timeout=LAYOUT["TIMEOUT_STANDARD"]
            )
            verify_response.raise_for_status()

            self.current_user_info = verify_response.json()
            return self.current_user_info

        except requests.exceptions.RequestException as e:
            self._handle_request_error(e)
            raise

    def _handle_request_error(self, e):
        """Handle and format request errors consistently"""
        if e.response is not None:
            try:
                error_detail = e.response.json().get("detail", e.response.text)
                if isinstance(error_detail, list):
                    error_message = (
                        f"API Error ({e.response.status_code}): {json.dumps(error_detail)}"
                    )
                else:
                    error_message = (
                        f"API Error ({e.response.status_code}): {error_detail or e.response.text}"
                    )
            except json.JSONDecodeError:
                error_message = f"API Error ({e.response.status_code}): {e.response.text}"
        else:
            error_message = f"Network/API Error: {e}"

        self._update_status(f"Status: {error_message}", "red")

    def get_auth_headers(self):
        """Get authorization headers for API calls"""
        if not self.current_token:
            raise ValueError("Not authenticated. Please authenticate first.")
        return {"Authorization": f"Bearer {self.current_token}"}

    def is_authenticated(self):
        """Check if currently authenticated"""
        return self.current_token is not None and self.current_user_info is not None

    def clear_authentication(self):
        """Clear current authentication state"""
        self.current_token = None
        self.current_user_info = None

    def get_user_display_name(self):
        """Get display name for current user"""
        if not self.current_user_info:
            return "Unknown User"
        return self.current_user_info.get(
            "name", self.current_user_info.get("username", "Unknown User")
        )
