"""Schema helpers.

These functions turn raw NOMAD entries into something the UI can offer as
choices. There is no network and no GUI here, only pure data logic, so it
can be reused unchanged behind a Dash front end later.

The important idea: rather than reconstruct the full NOMAD metainfo tree
(huge, mostly irrelevant to any one dataset), we learn the available
paths from a small sample of real entries. The picker then shows only
paths that actually occur in your data, annotated with how often.
"""


def get_nested_field(entry, path):
    """Return the value at a dot path, or None if any step is missing.

    Lists are traversed by taking their first element, matching the
    convention used across the HySPRINT extraction scripts. Paths may carry
    a trailing '#<qualified_name>' disambiguation suffix (needed when
    querying custom schema quantities via the API's required.include list,
    see data_manager._required); that suffix never appears in the actual
    response structure, so it is dropped before walking the path.
    """
    value = entry
    for key in path.split("#", 1)[0].split("."):
        if isinstance(value, list):
            value = value[0] if value else None
        if isinstance(value, dict) and key in value:
            value = value[key]
        else:
            return None
    return value


def flatten_paths(obj, prefix="", out=None):
    """Collect every leaf dot path present in a nested object.

    Dicts are descended by key. A list of dicts is descended through its
    first element so nested structure is still discovered, and the list
    path itself is recorded. Any other value (scalar or list of scalars)
    is treated as a leaf.
    """
    if out is None:
        out = set()
    if isinstance(obj, dict):
        for key, value in obj.items():
            child = f"{prefix}.{key}" if prefix else key
            if isinstance(value, dict):
                flatten_paths(value, child, out)
            elif isinstance(value, list) and value and isinstance(value[0], dict):
                flatten_paths(value[0], child, out)
                out.add(child)
            else:
                out.add(child)
    return out


def discover_paths(entries):
    """Return {path: count} across a sample.

    The count is how many sampled entries hold a non null value at that
    path. This drives the coverage hint shown next to each suggestion.
    """
    counts = {}
    for entry in entries:
        for path in flatten_paths(entry):
            if get_nested_field(entry, path) is not None:
                counts[path] = counts.get(path, 0) + 1
    return counts


def validate_path(entries, path):
    """Return (exists, coverage_fraction) for a path over the sample."""
    if not entries:
        return False, 0.0
    hits = sum(1 for e in entries if get_nested_field(e, path) is not None)
    return hits > 0, hits / len(entries)
