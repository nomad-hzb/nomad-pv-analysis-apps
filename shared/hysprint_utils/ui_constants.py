"""UI text and widget sizes shared by the apps (STRINGS, LAYOUT).

Widget-free on purpose, so the auth and API layers can use them (LAYOUT["TIMEOUT_STANDARD"])
without importing ipywidgets. auth_manager and plotting_utils re-export both names.
"""

from hysprint_utils.config import API_ENDPOINT, URL_BASE

# --- Constants ---
STRINGS = {
    "STATUS_NOT_AUTH": "Status: Not Authenticated",
    "STATUS_AUTH_CHANGED": "Status: Not Authenticated (Method changed)",
    "STATUS_AUTHENTICATING": "Status: Authenticating...",
    "AUTH_REQUIRED": "Authentication required. Please authenticate first in Connection Settings.",
    "SE_OASIS_URL": URL_BASE,
    "API_ENDPOINT": API_ENDPOINT,
    "DATA_LOADED_SUCCESS": "Data Loaded Successfully!",
    "LOADING_DATA": "Loading Data",
    "VARIABLES_NOT_LOADED": "⚠️ Variables not loaded",
    "VARIABLES_LOADED": "Variables loaded",
    "ERROR_PREFIX": "Error: ",
    "STATUS_PREFIX": "Status: ",
}

# --- Layout Constants ---
LAYOUT = {
    "TIMEOUT_STANDARD": 10,
    "BUTTON_MIN_WIDTH": "150px",
    "DROPDOWN_WIDTH": "200px",
    "DROPDOWN_WIDE": "250px",
    "DROPDOWN_EXTRA_WIDE": "300px",
    "TEXT_INPUT_WIDTH": "100px",
    "LABEL_WIDTH": "80px",
    "TOKEN_INPUT_WIDTH": "95%",
    "CONTAINER_MAX_WIDTH": "1200px",
    "OUTPUT_MIN_HEIGHT": "100px",
    "OUTPUT_SCROLL_HEIGHT": "300px",
    "OUTPUT_SCROLL_WIDTH": "400px",
    "OUTPUT_LARGE_HEIGHT": "250px",
    "OUTPUT_MEDIUM_HEIGHT": "200px",
    "PLOT_MIN_WIDTH": "400px",
    "PLOT_MIN_HEIGHT": "300px",
    "PLOT_DEFAULT_WIDTH": "820px",
    "PLOT_DEFAULT_HEIGHT": "620px",
    "PLOT_CONTAINER_WIDTH": "800px",
    "PLOT_CONTAINER_HEIGHT": "600px",
    "RESIZE_HANDLE_SIZE": "15px",
    "MARGIN_STANDARD": "10px",
    "MARGIN_SMALL": "5px",
    "BORDER_STANDARD": "1px solid #ccc",
    "BORDER_LIGHT": "1px solid #eee",
    "BORDER_DARK": "1px solid #ddd",
    "PADDING_STANDARD": "10px",
    "PADDING_LARGE": "15px",
    "DPI_HIGH": 150,
    "RESIZE_POLL_INTERVAL": 200,
    "IFRAME_RESIZE_DELAY": 100,
}
