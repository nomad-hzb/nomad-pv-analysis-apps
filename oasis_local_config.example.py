# Example deployment overrides. Copy this file to `oasis_local_config.py` (same folder, gitignored,
# it must travel with the upload) and un-comment what your Oasis needs. Every line is optional.
#
# Every UPPERCASE string defined here becomes an environment variable of the same name before any
# app starts (see bootstrap.py and DEPLOYMENT.md). A variable already set at the container level
# always wins. Plain strings only.

# --- Which Oasis -----------------------------------------------------------------------------
# Required on any Oasis other than the HZB SE one. No trailing slash.
# HYSPRINT_URL_BASE = "https://nomad-ce-ame.helmholtz-berlin.de"
# Only if the API is not at /nomad-oasis/api/v1:
# HYSPRINT_API_ENDPOINT = "/nomad-oasis/api/v1"

# --- Outbound proxy (only if the container has no direct route out) --------------------------
# The HZB SE Oasis gets the HZB proxy by default; any other deployment gets none unless set here.
# To switch the proxy off on HZB SE, set both to the empty string.
# HTTP_PROXY = "http://proxy.example.org:3128"
# HTTPS_PROXY = "http://proxy.example.org:3128"
# NO_PROXY = "localhost,127.0.0.1"

# --- App Dashboard: which apps are listed ----------------------------------------------------
# Hide apps (comma-separated app folder names or card names; case and spaces are ignored; unknown
# names only log a warning). "Learning" and "Projects" name those two sections.
# HYSPRINT_DASHBOARD_HIDE_APPS = "XPS-Automated,SEM_crystal_counter"
# Or show only these (an allow-list; the hide list is applied on top):
# HYSPRINT_DASHBOARD_SHOW_APPS = "JV-Analysis,File_Uploader,Learning"
# Order of the groups: the groups named here come first, in this order (case and spaces are
# ignored, unknown names only log a warning); every other group follows in its default order.
# Unset: the default order. Names: Data Management, Device Characterization,
# Optical & Structural Analysis, Utilities & Calculators, Build Your Own,
# Experimental / In Progress.
# HYSPRINT_DASHBOARD_GROUP_ORDER = "Data Management,Device Characterization"

# --- App Dashboard: the "Projects" cards (slot-die ML pipeline) ------------------------------
# Each card links into a specific HZB upload. Set the upload id of your own copy, or set the
# variable to the empty string to drop that card (all six empty: the section disappears).
# HYSPRINT_PROJECT_IMAGE_CROPPER_UPLOAD_ID = ""
# HYSPRINT_PROJECT_FEATURE_EXTRACTION_UPLOAD_ID = ""
# HYSPRINT_PROJECT_PL_DEFECT_UPLOAD_ID = ""
# HYSPRINT_PROJECT_ML_MODEL_UPLOAD_ID = ""
# HYSPRINT_PROJECT_CORRELATION_UPLOAD_ID = ""
# HYSPRINT_PROJECT_ROI_JV_UPLOAD_ID = ""

# --- Logs and debugging ----------------------------------------------------------------------
# Where notebook_usage.log and button_usage.log are written (default: shared/log/ of the upload).
# HYSPRINT_USAGE_LOG_DIR = "/home/jovyan/hysprint_logs"
# Show the banner some packages print on import (silenced by default):
# HYSPRINT_KEEP_IMPORT_OUTPUT = "1"
