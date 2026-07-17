# alias_config.py
# Zero widget imports. Loads config/alias_groups.json and resolves per-process-instance
# "progress units" for the material-gated progress bar - see that file's "_readme" key for
# the schema and the primary real scenario (config-dependent field renaming, e.g. single-
# vs multi-step Spin Coating rotation fields).

import json
from pathlib import Path

ALIAS_GROUPS_CONFIG_PATH = Path(__file__).parent / "config" / "alias_groups.json"


def load_alias_groups(config_path: Path | None = None) -> list[dict]:
    path = config_path or ALIAS_GROUPS_CONFIG_PATH
    with open(path, encoding="utf-8") as config_file:
        raw = json.load(config_file)
    return raw.get("alias_groups", [])


def _field_matches_member(field_key: str, process_type: str, member: dict) -> bool:
    if member["process_type"] != process_type:
        return False
    pattern = member["field_pattern"]
    if "{n}" not in pattern:
        return field_key == pattern
    prefix, suffix = pattern.split("{n}", 1)
    if not (field_key.startswith(prefix) and field_key.endswith(suffix)):
        return False
    middle = field_key[len(prefix) : len(field_key) - len(suffix)]
    return middle.isdigit()


def resolve_progress_units(
    process_type: str, field_keys: list[str], alias_groups: list[dict] | None = None
) -> list[list[str]]:
    """Groups field_keys into progress units, scoped to ONE process instance: fields
    matching the same alias group's members become one unit (satisfied if any member is
    filled); everything else is its own unit. Order of field_keys is preserved for
    ungrouped fields; grouped units are appended after them."""
    groups = alias_groups if alias_groups is not None else load_alias_groups()

    key_to_group_id: dict[str, str] = {}
    for group in groups:
        for member in group["members"]:
            for field_key in field_keys:
                if field_key in key_to_group_id:
                    continue
                if _field_matches_member(field_key, process_type, member):
                    key_to_group_id[field_key] = group["id"]

    units_by_group: dict[str, list[str]] = {}
    units: list[list[str]] = []
    for field_key in field_keys:
        group_id = key_to_group_id.get(field_key)
        if group_id is None:
            units.append([field_key])
        else:
            units_by_group.setdefault(group_id, []).append(field_key)
    units.extend(units_by_group.values())
    return units
