"""Central configuration for the NOMAD extractor.

The FieldSpec dataclass is the single description of one output column and
is shared by every module. The selectable field menu lives in the separate
fields_catalog.json, which you can edit freely.
"""

import os
from dataclasses import asdict, dataclass
from typing import Optional

# NOMAD servers. Each has a default entry type, the population to scope to
# on that server. Central defaults to the perovskite database; the HZB SE
# Oasis defaults to everything. The same token authenticates across Oasis
# instances (central public data needs no token). Add your own servers here.
#
# Both URLs are deliberately hardcoded and are NOT a deployment leak: this is
# a menu of data sources to download FROM, in the same sense as the public
# central server, not the address of the Oasis this app happens to run on. It
# stays pointed at the HZB SE Oasis on every deployment, so it must not be
# derived from hysprint_utils.config / URL_BASE. Do not "unify" it.
SERVERS = {
    "NOMAD central public (nomad-lab.eu)": {
        "url": "https://nomad-lab.eu/prod/v1/api/v1",
        "default_entry_type": "PerovskiteSolarCell",
    },
    "HZB SE Oasis (nomad-hzb-se.de)": {
        "url": "https://nomad-hzb-se.de/nomad-oasis/api/v1",
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
