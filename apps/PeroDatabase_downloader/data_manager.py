"""Orchestration and state.

The GUI, or a future Dash app, talks only to DataManager. It loads the
field catalog, derives the query from the selected fields, runs the full
paginated extraction with a progress callback, and holds the resulting
DataFrame. It knows nothing about widgets.

Progress is reported through an optional callback with the signature
progress(current: int, total: int, message: str).

Owner handling: unauthenticated requests must use owner 'public'. If a
token is present (from the environment) we can ask for 'visible', which
also includes the user's own non public entries.
"""

import json
import logging

import config
import pandas as pd
from config import FieldSpec
from nomad_client import NomadClient
from schema import get_nested_field

logger = logging.getLogger(__name__)


class DataManager:
    def __init__(self, api_url=config.NOMAD_API_URL, token=None):
        self.client = NomadClient(api_url, token=token)
        self.fields = []  # starts empty, user builds it up
        self.entry_type = ""  # population anchor, "" means all
        self.results_df = None
        self.debug_log = []
        self.catalog = self._load_catalog()
        self.catalog_by_path = {c["path"]: c for c in self.catalog}

    def _load_catalog(self):
        try:
            with open(config.CATALOG_PATH, encoding="utf-8") as fh:
                return json.load(fh)
        except (OSError, ValueError):
            return []

    def _owner(self):
        return "visible" if self.client.token else "public"

    def set_server(self, api_url):
        """Point at a different NOMAD server. Clears the old results, since
        they belong to the previous server. Fields are kept, the schema is
        the same across servers.
        """
        self.client.set_url(api_url)
        self.results_df = None

    def _log(self, message):
        self.debug_log.append(str(message))
        logger.info("%s", message)

    # -- turning a picked path into a full column spec -------------------
    def make_field(self, path, name):
        extra = self.catalog_by_path.get(path, {})
        return FieldSpec(
            path=path,
            name=name or extra.get("column") or path.split(".")[-1],
            list_mode=extra.get("list_mode", "first"),
            unit_label=extra.get("unit_label"),
            scale=extra.get("scale"),
        )

    def add_field(self, spec):
        existing = {f.output_name() for f in self.fields}
        if spec.output_name() in existing:
            return f"A column named '{spec.output_name()}' already exists. Rename it before adding."
        self.fields.append(spec)
        return None

    def add_to_catalog(self, spec):
        """If this path is new to the catalog, append it and save to disk so
        it persists across sessions. Returns True if the catalog changed.
        """
        if spec.path in self.catalog_by_path:
            return False
        entry = {"label": spec.name, "column": spec.name, "path": spec.path}
        if spec.list_mode and spec.list_mode != "first":
            entry["list_mode"] = spec.list_mode
        if spec.unit_label:
            entry["unit_label"] = spec.unit_label
        if spec.scale is not None:
            entry["scale"] = spec.scale
        self.catalog.append(entry)
        self.catalog_by_path[spec.path] = entry
        self._save_catalog()
        return True

    def _save_catalog(self):
        try:
            with open(config.CATALOG_PATH, "w", encoding="utf-8") as fh:
                json.dump(self.catalog, fh, indent=2)
            self._log(f"Catalog saved with {len(self.catalog)} entries.")
        except OSError as exc:
            self._log(f"Could not save catalog: {exc}")

    def remove_field(self, output_name):
        self.fields = [f for f in self.fields if f.output_name() != output_name]

    def set_entry_type(self, entry_type):
        self.entry_type = entry_type or ""
        self.results_df = None

    # -- queries ---------------------------------------------------------
    def build_query(self):
        """Population = entries of the chosen entry type. This is the
        reliable anchor: NOMAD's search index does not list every field
        (repeating sections such as band_gap are often not searchable), so
        bounding on a field would miss most entries that actually hold it.
        Bounding on entry type finds all of them, and the field is then
        read from the archive of each. Empty entry type means all entries.
        """
        return {"entry_type": self.entry_type} if self.entry_type else {}

    def list_entry_types(self, limit=100):
        """Ask the server which entry types exist, with counts, so the UI
        can offer a real list. Returns [(type, count)] sorted by count.
        Defensive: any failure returns an empty list.
        """
        payload = {
            "owner": self._owner(),
            "query": {},
            "aggregations": {"types": {"terms": {"quantity": "entry_type", "size": limit}}},
            "pagination": {"page_size": 0},
        }
        self._log(f"Aggregation on entry_type, owner={payload['owner']}")
        try:
            data = self.client.post_query(payload)
        except Exception as exc:
            self._log(f"Entry type aggregation failed: {exc}")
            return []
        buckets = data.get("aggregations", {}).get("types", {}).get("terms", {}).get("data", [])
        out = []
        for b in buckets:
            value = b.get("value")
            count = b.get("count", b.get("size", 0))
            if value:
                out.append((value, count))
        out.sort(key=lambda x: -x[1])
        self._log(f"Found {len(out)} entry types.")
        return out

    def _required(self):
        includes = ["entry_id"] + [f.path for f in self.fields]
        seen = set()
        unique = [p for p in includes if not (p in seen or seen.add(p))]
        return {"include": unique}

    # -- test whether a path exists --------------------------------------
    def validate(self, path):
        """Sample entries from the current population and report whether the
        path resolves in them. With an entry type chosen, this tests against
        the same entries you would extract.
        """
        self.debug_log = []
        entries, total = self._sample(self.build_query())
        if entries is None:
            return False, 0.0
        hits = sum(1 for e in entries if get_nested_field(e, path) is not None)
        coverage = hits / len(entries) if entries else 0.0
        self._log(f"Sample size {len(entries)}, hits {hits}, population total {total}.")
        return hits > 0, coverage

    def _sample(self, query, size=config.SAMPLE_SIZE):
        payload = {"owner": self._owner(), "query": query, "pagination": {"page_size": size}}
        self._log(f"POST /entries/query  owner={payload['owner']}  query={json.dumps(query)}")
        try:
            data = self.client.post_query(payload)
        except Exception as exc:
            self._log(f"Request error: {exc}")
            return None, 0
        entries = data.get("data", [])
        total = data.get("pagination", {}).get("total", len(entries))
        self._log(f"Returned {len(entries)} entries, total match {total}.")
        return entries, total

    # -- full extraction -------------------------------------------------
    def run(self, progress=None):
        self.debug_log = []
        query = self.build_query()
        required = self._required()
        owner = self._owner()
        self._log(f"Extract owner={owner}")
        self._log(f"query={json.dumps(query)}")
        self._log(f"include={json.dumps(required['include'])}")
        page_after = None
        entries = []
        total = None
        while True:
            payload = {
                "owner": owner,
                "query": query,
                "required": required,
                "pagination": {"page_size": config.PAGE_SIZE},
            }
            if page_after:
                payload["pagination"]["page_after_value"] = page_after
            try:
                data = self.client.post_query(payload)
            except Exception as exc:
                self._log(f"Request error: {exc}")
                raise
            page = data.get("data", [])
            if not page:
                break
            entries.extend(page)
            pg = data.get("pagination", {})
            if total is None:
                total = pg.get("total", len(page))
                self._log(f"Total matching entries: {total}")
            if progress:
                progress(
                    min(len(entries), total),
                    max(total, 1),
                    f"Retrieved {len(entries)} of {total} entries ...",
                )
            page_after = pg.get("next_page_after_value")
            if not page_after:
                break
        self.results_df = self._to_frame(entries)
        rows = 0 if self.results_df is None else len(self.results_df)
        self._log(f"Built DataFrame with {rows} rows.")
        if progress:
            progress(max(total or rows, 1), max(total or rows, 1), f"Done. {rows} rows extracted.")
        return self.results_df

    def _to_frame(self, entries):
        rows = []
        for entry in entries:
            row = {"entry_id": entry.get("entry_id")}
            for spec in self.fields:
                raw = get_nested_field(entry, spec.path)
                row[spec.output_name()] = self._coerce(spec, raw)
            rows.append(row)
        return pd.DataFrame(rows) if rows else pd.DataFrame()

    def _coerce(self, spec, value):
        if value is None:
            return None
        if isinstance(value, list):
            if spec.list_mode == "join":
                return spec.join_sep.join(str(v) for v in value)
            value = value[0] if value else None
        if value is None:
            return None
        is_numeric = isinstance(value, (int, float)) and not isinstance(value, bool)
        if spec.scale is not None and is_numeric:
            value = value * spec.scale
        return value

    # -- results helpers -------------------------------------------------
    def field_columns(self):
        return [f.output_name() for f in self.fields]

    def coverage(self):
        if self.results_df is None or self.results_df.empty:
            return {}
        n = len(self.results_df)
        return {
            col: self.results_df[col].notna().sum() / n
            for col in self.field_columns()
            if col in self.results_df
        }

    def get_dataframe(self, complete_only=False):
        if self.results_df is None:
            return pd.DataFrame()
        if complete_only:
            cols = [c for c in self.field_columns() if c in self.results_df]
            return self.results_df.dropna(subset=cols)
        return self.results_df

    def to_csv_bytes(self, complete_only=False):
        return self.get_dataframe(complete_only).to_csv(index=False).encode("utf-8")
