# NOMAD Oasis Data Access — Prompt for LLMs

Paste this whole file into a chatbot (Claude, ChatGPT, etc.) as system/project
instructions when you want it to write a script that reads your own
perovskite characterization data from the HZB NOMAD Oasis, without using one
of the pre-built apps in this repo. It is self-contained: it assumes only
Python + `requests`, not this repo's shared library.

If you're instead extending an app *inside* this repo, stop here and use
`shared/hysprint_utils/api_calls.py` directly — don't re-derive the queries
below, reuse the functions that already wrap them.

---

## What you're talking to

A NOMAD Oasis instance is a self-hosted deployment of the NOMAD research data
platform. Data is organized as:

- **Uploads** — a container a user created, holding one or more entries.
- **Entries** — one structured record each: a batch, a sample, a JV
  measurement, an EQE measurement, a process step, etc. Each entry has an
  `entry_type` (its schema class) and an `archive` (its actual data, split
  into `data` — the raw schema fields — and `metadata` — search-indexed
  fields, authorship, references to other entries).
- **`lab_id`** — the human-readable ID a researcher assigned (e.g. a sample
  or batch name). Not the same as `entry_id` (NOMAD's internal UUID) — you'll
  often need to resolve one from the other.
- **References** — entries link to each other (a JV measurement references
  its sample; a sample references its batch) via
  `entry_references.target_entry_id` / `results.eln.lab_ids`.

## Connection basics

```python
URL_BASE = "https://nomad-hzb-se.de"      # no trailing slash
API_ENDPOINT = "/nomad-oasis/api/v1"       # no trailing slash
API = f"{URL_BASE}{API_ENDPOINT}"
```

This is the HZB SE-ALM group's Oasis. If you're pointed at a different
Oasis, ask the user for its base URL — don't assume this one.

Interactive API docs (Swagger UI) are usually served at `{API}/docs` — check
there for anything not covered below.

### Authentication

Get a token once, then send it as a Bearer header on every call:

```python
import requests

def get_token(username, password):
    r = requests.get(f"{API}/auth/token", params={"username": username, "password": password})
    r.raise_for_status()
    return r.json()["access_token"]

token = get_token("myuser", "mypassword")   # or read from an env var / secrets file — never hardcode
headers = {"Authorization": f"Bearer {token}"}
```

A token is also available from the user's NOMAD profile page in the GUI, and
tokens are long-lived (weeks), so scripts usually just read one from an
environment variable instead of logging in each run. **Never hardcode a
token or password in code you hand back to the user** — read it from an env
var or a gitignored file instead.

## The two query endpoints

Almost everything is one of these two POST requests. Both take the same body
shape: `{"required": ..., "owner": ..., "query": ..., "pagination": ...}`.

- **`POST {API}/entries/query`** — metadata only. Fast; use it when you just
  need `entry_id`, `upload_id`, or which `lab_id`s an entry references.
- **`POST {API}/entries/archive/query`** — metadata *and* the full archive
  (`data`). Use it when you need actual field values (voltages,
  efficiencies, temperatures, etc.).

```python
query = {
    "required": {"data": "*", "metadata": "*"},   # "*" = everything; can also request specific paths
    "owner": "visible",                              # entries this token's user can see
    "query": {"entry_type": "HySprint_JVmeasurement"},
    "pagination": {"page_size": 10000},               # default page size is small — set this explicitly
}
r = requests.post(f"{API}/entries/archive/query", headers=headers, json=query)
r.raise_for_status()
results = r.json()["data"]   # list of {"archive": {"data": {...}, "metadata": {...}}, ...}
```

`owner` options: `"visible"` (default choice for an authenticated user's own
work), `"public"` (openly published entries, works without a token — mainly
useful against NOMAD's central instance, not a private Oasis), `"user"`
(only entries you authored), `"shared"`.

## Entry types on this Oasis

Entry types are schema class names, specific to this deployment. On the HZB
SE-ALM Oasis:

| Meaning | `entry_type` value |
|---|---|
| Batch | `HySprint_Batch` |
| JV measurement | `HySprint_JVmeasurement` |
| EQE measurement | `HySprint_EQEmeasurement` |
| MPPT tracking | `HySprint_SimpleMPPTracking` |
| Absolute PL | `HySprint_AbsPLMeasurement` |
| XRD | `HySprint_XRD_XY` |
| TRPL | `HySprint_TimeResolvedPhotoluminescence` |
| NMR | `HySprint_Simple_NMR` |
| Any measurement (base class) | `baseclasses.BaseMeasurement` |
| Any process step (base class) | `baseclasses.BaseProcess` |

If you're on a different Oasis, these names will differ — pull one known
entry with `"required": {"metadata": "*"}` and read its `entry_type` field to
discover the real name, rather than guessing.

## Common recipes

**List your batches:**
```python
query = {"required": {"data": "*"}, "owner": "visible",
         "query": {"entry_type": "HySprint_Batch"}, "pagination": {"page_size": 10000}}
data = requests.post(f"{API}/entries/archive/query", headers=headers, json=query).json()["data"]
batch_ids = [d["archive"]["data"]["lab_id"] for d in data if "lab_id" in d["archive"]["data"]]
```

**Get the sample `lab_id`s inside a batch:** a batch's archive has an
`entities` list of its samples.
```python
query = {"required": {"data": "*"}, "owner": "visible",
         "query": {"results.eln.lab_ids:any": batch_ids, "entry_type": "HySprint_Batch"},
         "pagination": {"page_size": 100}}
data = requests.post(f"{API}/entries/archive/query", headers=headers, json=query).json()["data"]
sample_ids = [s["lab_id"] for d in data for s in d["archive"]["data"].get("entities", [])]
```

**Get all JV measurements for a set of samples** (two-step: resolve sample
entry_ids, then find entries that reference them):
```python
q1 = {"required": {"metadata": "*"}, "owner": "visible",
      "query": {"results.eln.lab_ids:any": sample_ids}, "pagination": {"page_size": 10000}}
entry_ids = [e["entry_id"] for e in requests.post(f"{API}/entries/query", headers=headers, json=q1).json()["data"]]

q2 = {"required": {"data": "*", "metadata": "*"}, "owner": "visible",
      "query": {"entry_references.target_entry_id:any": entry_ids, "entry_type": "HySprint_JVmeasurement"},
      "pagination": {"page_size": 10000}}
jv_entries = requests.post(f"{API}/entries/archive/query", headers=headers, json=q2).json()["data"]
```
The same pattern works for any measurement type — swap the `entry_type`, or
use `baseclasses.BaseMeasurement` to get every measurement kind at once and
filter client-side.

**Pull a pre-computed property straight from the search index** (fast — no
archive read needed — only works for fields NOMAD indexes, see Gotchas):
```python
query = {
    "required": {"results": {"properties": {"optoelectronic": {"solar_cell": {"efficiency": "*"}}},
                              "eln": {"lab_ids": "*"}}},
    "owner": "visible",
    "query": {"results.eln.lab_ids:any": sample_ids,
              "results.properties.optoelectronic.solar_cell.efficiency:gt": "0"},
}
data = requests.post(f"{API}/entries/archive/query", headers=headers, json=query).json()["data"]
efficiencies = {d["archive"]["results"]["eln"]["lab_ids"][0]:
                d["archive"]["results"]["properties"]["optoelectronic"]["solar_cell"]["efficiency"]
                for d in data}
```

**Build a GUI link back to an entry** (for a report, not for the API):
```python
gui_url = f"{URL_BASE}/nomad-oasis/gui/user/uploads/upload/id/{upload_id}/entry/id/{entry_id}"
```

## Gotchas

- **Default page size is small.** Always set `pagination.page_size`
  explicitly, or you'll silently get a truncated result set.
- **Most fields are NOT search-indexed.** Only `results.*` paths are
  queryable/filterable in `query`. A field living inside a repeating or
  nested section of `data` (e.g. a layer's `band_gap`) usually is *not*
  indexed — filtering on it directly returns almost nothing. Instead, bound
  the query on `entry_type` (which *is* always indexed) to fetch every entry
  of that type, then read the field out of each entry's `data` client-side.
- **Units are SI in `results.*`.** e.g. band gap is stored in Joules, not
  eV; current density in A/m², not mA/cm². Convert client-side and verify
  the stored unit before applying a factor — applying a conversion to an
  already-correct value silently produces nonsense.
- **`entry_id` ≠ `lab_id`.** Most linking queries go through `lab_id`
  (`results.eln.lab_ids:any`) since that's what a researcher actually knows;
  `entry_id` only shows up once you need `entry_references` or a GUI link.
- **Large `:any` lists.** If querying with hundreds+ of IDs, batch the
  requests — a single oversized query body can be rejected by the server.

## If you're an LLM being handed this file

1. Confirm the base URL and how the user wants to supply a token (env var,
   prompt, existing script) before writing code — don't assume.
2. Prefer the narrowest query that answers the question over pulling
   everything and filtering in Python — this Oasis holds years of
   measurement data.
3. Never write a token or password as a literal in code you hand back.
4. If a field/entry-type name isn't confirmed, say so and suggest the
   discovery step (pull one entry, inspect `entry_type` / `data` keys)
   instead of guessing a name that looks plausible.
