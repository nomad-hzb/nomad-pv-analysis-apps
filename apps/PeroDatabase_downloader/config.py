"""Central configuration for the NOMAD extractor.

The FieldSpec dataclass is the single description of one output column and
is shared by every module. The selectable field menu lives in the separate
fields_catalog.json, which you can edit freely.
"""

import logging
import os
from dataclasses import asdict, dataclass
from typing import Optional

logger = logging.getLogger(__name__)

try:
    from hysprint_utils.config import API_ENDPOINT, URL_BASE
except ImportError:
    URL_BASE = "https://nomad-hzb-se.de"
    API_ENDPOINT = "/nomad-oasis/api/v1"
    logger.warning("hysprint_utils.config not found; using hardcoded URL fallback")

# NOMAD servers. Each has a default entry type, the population to scope to
# on that server. Central defaults to the perovskite database; the HZB
# Oasis defaults to everything. The same token authenticates across Oasis
# instances (central public data needs no token). Add your own servers here.
# The HZB Oasis entry reuses the shared hysprint_utils config so the URL is
# defined in one place; the public-central server has no equivalent there.
SERVERS = {
    "NOMAD central public (nomad-lab.eu)": {
        "url": "https://nomad-lab.eu/prod/v1/api/v1",
        "default_entry_type": "PerovskiteSolarCell",
    },
    "HZB Oasis (nomad-hzb-se.de)": {
        "url": f"{URL_BASE}{API_ENDPOINT}",
        "default_entry_type": "",
    },
}
DEFAULT_SERVER_LABEL = "NOMAD central public (nomad-lab.eu)"
NOMAD_API_URL = SERVERS[DEFAULT_SERVER_LABEL]["url"]


def default_entry_type_for(url):
    for server in SERVERS.values():
        if server["url"] == url:
            return server.get("default_entry_type", "")
    return ""


# Entries pulled to test whether a hand typed path exists.
SAMPLE_SIZE = 30

# Page size for the full extraction run.
PAGE_SIZE = 1000

# Rows shown in the preview table.
PREVIEW_ROWS = 15

# Path to the editable field menu.
CATALOG_PATH = os.path.join(os.path.dirname(__file__), "fields_catalog.json")


@dataclass
class FieldSpec:
    """One requested output column.

    path        dot path into the entry
    name        column name in the CSV
    list_mode   'first' takes the first list element, 'join' concatenates
    join_sep    separator used when list_mode is 'join'
    unit_label  optional label appended to the column name, e.g. 'eV'
    scale       optional multiplier for numeric values, e.g. Joule to eV
    """

    path: str
    name: str
    list_mode: str = "first"
    join_sep: str = "; "
    unit_label: Optional[str] = None
    scale: Optional[float] = None

    def output_name(self) -> str:
        return f"{self.name} ({self.unit_label})" if self.unit_label else self.name

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "FieldSpec":
        allowed = {"path", "name", "list_mode", "join_sep", "unit_label", "scale"}
        return cls(**{k: v for k, v in d.items() if k in allowed})
