"""
Shared configuration constants for HySPRINT NOMAD Oasis apps.

Place this file at:  shared/hysprint_utils/config.py

All apps import from here:
    from hysprint_utils.config import URL_BASE, API_ENDPOINT, ENTRY_TYPES
"""

# Base URL of the NOMAD Oasis instance (no trailing slash)
URL_BASE: str = "https://nomad-hzb-se.de"

# API path prefix (no trailing slash)
API_ENDPOINT: str = "/nomad-oasis/api/v1"

# ---------------------------------------------------------------------------
# NOMAD schema entry-type names
# Admins: edit the VALUES here to match your server's schema.
# These are the only place in the entire codebase where schema names appear.
# ---------------------------------------------------------------------------
ENTRY_TYPES: dict[str, str] = {
    # ELN entry types
    "batch": "HySprint_Batch",
    "jv": "HySprint_JVmeasurement",
    "eqe": "HySprint_EQEmeasurement",
    "mppt": "HySprint_SimpleMPPTracking",
    "abspl": "HySprint_AbsPLMeasurement",
    "xrd": "HySprint_XRD_XY",
    "trpl": "HySprint_TimeResolvedPhotoluminescence",
    "nmr": "HySprint_Simple_NMR",
    # NOMAD baseclass qualified names
    "base_measurement": "baseclasses.BaseMeasurement",
    "base_process": "baseclasses.BaseProcess",
}
