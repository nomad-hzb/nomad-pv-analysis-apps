# Deploying the app suite to a second NOMAD Oasis

This repo defaults to the HZB SE Oasis (`nomad-hzb-se.de`) but contains no
hardcoded dependency on it. Everything a second deployment needs to change
lives in one gitignored file, `oasis_local_config.py`, read by `bootstrap.py`
at the top of every notebook.

The worked example throughout is the CE-AME Oasis
(`https://nomad-ce-ame.helmholtz-berlin.de/`), which needs two things HZB does
not: a different host, and an outbound HTTP proxy.

---

## 1. Check the target Oasis is compatible

The apps assume a NOMAD Oasis running the `nomad_hysprint` schema package and
offering the `voila` NORTH tool. Confirm both before uploading anything:

```bash
curl -s https://<your-oasis>/nomad-oasis/api/v1/info | python -m json.tool
```

Look for:

| Field | Expected | Why it matters |
|---|---|---|
| `version` | 1.4.x, `oasis: true` | API shape the apps are written against |
| `plugin_packages` / schema | `nomad_hysprint.schema_packages:hysprint_package` | `ENTRY_TYPES` in `shared/hysprint_utils/config.py` names `HySprint_*` entry types; a different schema means those queries return nothing |
| `north_tools` | includes `voila` | how the apps are launched |

CE-AME was probed and returns NOMAD 1.4.2, the `hysprint_package` schema, and
both `voila` and `jupyter2`, so no schema work is needed. If your Oasis runs a
different schema package, `ENTRY_TYPES` is the single place to remap the names.

Also note the API base path. CE-AME serves at `/nomad-oasis` like HZB; if yours
differs, see the known gap on path literals at the end of this document.

## 2. Upload the repo

Upload the repo to the target Oasis as a NOMAD upload, preserving the directory
structure. The layout matters more than the name: every notebook's cell 0 is

```python
import runpy
runpy.run_path("../../bootstrap.py")
```

which resolves from `apps/<AppName>/` to the repo root. As long as `apps/`,
`shared/` and `bootstrap.py` keep their relative positions, the upload's own
`<slug>-<hash>` folder name is irrelevant - that is the whole point of the
bootstrap, and why no path in this repo names a specific upload any more.

## 3. Create `oasis_local_config.py`

Create it at the repo root of the upload, next to `bootstrap.py`. It is
gitignored (same pattern as `secrets.py`) because it describes one deployment,
not the repo - it travels with the upload, and is not committed upstream.

Every uppercase string assignment in it is exported as an environment variable
of the same name before `hysprint_utils` is imported or installed. Anything
already set at the container level wins; this file never overwrites it.

### The CE-AME file

```python
# --- Which Oasis the apps talk to ---
HYSPRINT_URL_BASE = "https://nomad-ce-ame.helmholtz-berlin.de"
HYSPRINT_API_ENDPOINT = "/nomad-oasis/api/v1"

# --- Outbound network ---
HTTP_PROXY = "http://proxy.csn29.bessy.de:3128"
HTTPS_PROXY = "http://proxy.csn29.bessy.de:3128"
NO_PROXY = "localhost,127.0.0.1,.helmholtz-berlin.de"
```

### What each variable does

| Variable | Needed when | Notes |
|---|---|---|
| `HYSPRINT_URL_BASE` | always, on any non-HZB Oasis | Read by `shared/hysprint_utils/config.py`. No trailing slash. This is the one variable you cannot skip. |
| `HYSPRINT_API_ENDPOINT` | only if the API is not at `/nomad-oasis/api/v1` | Identical to the HZB default on CE-AME. Set anyway so the deployment is fully described by one file. |
| `HTTP_PROXY`, `HTTPS_PROXY` | the container has no direct outbound route | Applied *before* `pip install shared/` runs, because pip fetches `hatchling` from PyPI to build it. Also picked up by `git` for the `insitu_analyser` dependency. |
| `NO_PROXY` | whenever a proxy is set | Without it, `requests` sends *every* call through the proxy, including in-house API traffic to the Oasis itself. If omitted, `bootstrap.py` derives a sensible default from `HYSPRINT_URL_BASE` (`localhost,127.0.0.1,<oasis host>`); the explicit form above additionally covers other `helmholtz-berlin.de` hosts. |

### Ordering, and why it is not cosmetic

`bootstrap.py` applies the environment, then applies the proxy, then installs
`shared/`. Both halves of that order are load-bearing:

- `hysprint_utils.config` reads `HYSPRINT_URL_BASE` **at import time**, so
  setting it after any app import has no effect.
- `pip install <local dir>` is not an offline operation - it builds in an
  isolated environment and fetches `hatchling` from PyPI. On a proxied Oasis,
  a bootstrap that installs before setting the proxy fails outright.

## 4. Launch and verify

Launch the `voila` NORTH tool against `apps/App_dashboard/app_dashboard.ipynb`
first - it exercises auth, the API, and the NORTH URL construction all at once.

Run this in a fresh kernel on the target Oasis to confirm the environment
before debugging anything else:

```python
import runpy
runpy.run_path("../../bootstrap.py")

import os
from hysprint_utils.config import API_ENDPOINT, URL_BASE

print("URL_BASE    :", URL_BASE)
print("API_ENDPOINT:", API_ENDPOINT)
print("proxy       :", os.environ.get("HTTPS_PROXY"))
print("no_proxy    :", os.environ.get("NO_PROXY"))

import requests
print("info        :", requests.get(f"{URL_BASE}{API_ENDPOINT}/info", timeout=30).status_code)
```

Expected on CE-AME: the URL and proxy values from the config file, and `200`
from the `/info` call. A `200` here proves `NO_PROXY` is working, since the
call has to reach an in-house host.

Checklist for the dashboard itself:

- [ ] Dashboard renders with your username in the header
- [ ] App cards point at `https://<your-oasis>/nomad-oasis/north/...`
- [ ] Clicking a card opens that app's Voila instance
- [ ] That app can authenticate and list batches from your Oasis

## 5. Known gaps on a non-HZB Oasis

These are tracked, not silently broken. None of them block the core apps.

**The "Projects" section of the App Dashboard will 404.** Its six cards
deep-link into specific HZB uploads (the slot-die-coater ML pipeline) that do
not exist elsewhere. Each card's upload ID is overridable via a
`HYSPRINT_PROJECT_*_UPLOAD_ID` variable, and setting one to an empty string
drops that card - setting all six drops the section entirely. Deliberately not
configured for CE-AME yet; see `apps/App_dashboard/data_manager.py`.

**The six `Electrochemical_analysis` notebooks have no bootstrap cell.** They
fall back to the hardcoded HZB URL and get no proxy, so they will not work on a
second Oasis. They are pre-existing raw notebooks (`!pip install impedance` in
cell 0, star imports) that have not been through the unification pass.

**`ISA_Previewer` needs outbound git access.** It pins `insitu_analyser` from
`codebase.helmholtz.cloud`. `git` reads `HTTPS_PROXY` from the environment and
pip's subprocess inherits it, so the bootstrap proxy should cover it - but
whether that host is reachable *through* `proxy.csn29.bessy.de`, or needs to be
added to `NO_PROXY` instead, is unverified.

**Some `/nomad-oasis/...` path literals bypass `API_ENDPOINT`.** GUI-link and
NORTH-path templates in `auth_manager.py`, `App_dashboard/data_manager.py`,
`Global_analyzer/utils.py`, `ISA_Previewer/config.py` and `JV-Analysis/app.py`
build their own prefixes. Harmless wherever the base path is `/nomad-oasis`
(HZB and CE-AME both), broken on an Oasis served under a different prefix.

**A few user-visible strings still name the HZB Oasis** - the server dropdown
label in `PeroDatabase_downloader/config.py`, help text in
`JV-Analysis/gui_components.py`, and hyperlinks written into the files
`Excel_creator` generates. Cosmetic.

## 6. Local development

Unrelated to Oasis deployment, but the same variables apply. Export them in
your shell instead of using `oasis_local_config.py`:

```bash
export HYSPRINT_URL_BASE=https://your-oasis.example.org
export HYSPRINT_API_ENDPOINT=/nomad-oasis/api/v1
```

See `README.md` for the local install and how to supply an access token.