# nomad_voila — HySPRINT Analysis Apps monorepo

A suite of Voila/Jupyter apps for perovskite solar cell characterization,
built around NOMAD Oasis (HZB). Each app lives in `apps/<AppName>/` and can
run standalone; shared logic lives in `shared/hysprint_utils/`. Full
per-app checklist and rationale: `HYSPRINT_UNIFICATION_PROMPT.md` (base
checklist) and `FINALIZE_UNIFICATION_PROMPT.md` (scoping for the last
unification batches) — read those in full before doing another
repo-wide unification pass. This file is the condensed, everyday version.

## Layout

```
apps/<AppName>/
    pyproject.toml
    app.py                 # entry point, imports the rest as plain names
    data_manager.py         # zero widget imports; Pydantic model + validation
    plot_manager.py         # zero widget imports; Plotly figures only
    gui_components.py       # all ipywidgets code lives here, nowhere else
    <app>.ipynb              # exactly 2 cells
shared/hysprint_utils/       # DO NOT DUPLICATE ANYTHING FROM HERE
    config.py               # URL_BASE / API_ENDPOINT — the ONLY place these are defined
    api_calls.py, access_token.py, auth_manager.py, batch_selection.py,
    error_handler.py, plotting_utils.py, process_handling.py, schemas.py
tests/<app_name>/            # ONE folder per app, at repo root — never inside apps/
    conftest.py
    test_<app_name>.py       # exactly one test file per app
pyproject.toml               # root: pytest config + the ONLY ruff config in the repo
tests/conftest.py            # strips repo root from sys.path — see gotcha below, do not remove
secrets.py                    # repo root, NOMAD_CLIENT_ACCESS_TOKEN fallback — never import directly
```

## Hard rules — apply to every edit in `apps/`

1. **Never duplicate `hysprint_utils` code.** If logic already exists there
   (auth, API calls, plotting helpers, error handling, schemas), import it —
   don't reimplement it in an app. If something is genuinely missing from
   `hysprint_utils` and should be shared, propose adding it there; don't
   silently create a new shared module.
2. **Don't touch `shared/hysprint_utils/` unless explicitly asked.** It's
   shared across every app; a "fix" there is a cross-cutting change that
   needs to be flagged and approved first, not applied inline while working
   on one app.
3. **Import convention:** `hysprint_utils.*` modules always get the
   `hysprint_utils.` prefix (`from hysprint_utils.config import URL_BASE`).
   App-local modules (`data_manager`, `plot_manager`, `gui_components`,
   `utils`, `config`) are imported as plain names, never prefixed.
4. **`URL_BASE`/`API_ENDPOINT` are never string literals** in an app or
   notebook. Import from `hysprint_utils.config`, wrapped in
   `try/except ImportError` with a hardcoded fallback:
   ```python
   try:
       from hysprint_utils.config import API_ENDPOINT, URL_BASE
   except ImportError:
       URL_BASE = "https://nomad-hzb-se.de"
       API_ENDPOINT = "/nomad-oasis/api/v1"
       logging.getLogger(__name__).warning("hysprint_utils.config not found; using hardcoded URL fallback")
   ```
   Apps that don't talk to the API at all don't need either — mark n/a, don't
   force it in.
5. **No bare `print()`** for status/debug/errors — use
   `logging.getLogger(__name__)` at module level, appropriate levels
   (DEBUG trace, INFO progress, WARNING/ERROR problems), and always
   `%s`/`%d` placeholders (never an f-string as the log message itself).
   **Exception:** `print()` used inside `with some_ipywidgets_output:` to
   render content into an `Output()` widget passed in from the caller is a
   legitimate display mechanism in this codebase (used because
   `data_manager.py`/`plot_manager.py` are forbidden from importing
   `ipywidgets`/`IPython.display`) — check for that pattern before
   "cleaning up" a print() call, don't convert it to logging blindly.
6. **Run `ruff check --fix` and `ruff format`** on every file you touch;
   leave `ruff check` clean before moving on. The ruff config lives ONLY at
   the root `pyproject.toml` — never add a per-app ruff config. Current
   ruleset is `E, F, I, G` (not `T20` yet — see Known gaps below).
7. **`pyproject.toml` per app** needs the exact dependency string:
   `"hysprint-utils @ file:///home/jovyan/uploads/analysis_apps_restructuring-WxUahazkSNy-bSE9GaZyZQ/shared"`
   — no relative paths, no alternate spellings — plus
   `[tool.hatch.metadata] allow-direct-references = true` and
   `[tool.hatch.build.targets.wheel] packages = ["."]`. `pytest`/`pytest-mock`
   belong only in the root `pyproject.toml`, never per-app.
8. **Notebooks: exactly 2 cells.** No `sys.path.append`/`insert` anywhere,
   in any app file or notebook.
9. **Tests live at `tests/<app_name>/test_<app_name>.py`**, never inside
   `apps/`. Each app's `conftest.py` must load its own `data_manager`/
   `plot_manager`/etc. under a **unique** name via
   `importlib.util.spec_from_file_location` (not just the bare module name)
   so a full `pytest tests/` run doesn't collide with another app's
   same-named module. See any of `Wetting_envelope`, `Excel_creator`,
   `bitmap_maker`, `PeroDatabase_downloader`, `Global_analyzer`'s
   `tests/<app>/conftest.py` for the current reference pattern.
10. **No em-dashes in any output you produce.**
11. **No regressions.** If making a checklist item pass would break an
    app's currently-working behavior or an already-passing test, stop and
    flag it — don't force the fix through.

## Known environment gotcha — do not "fix" by deleting `tests/conftest.py`

The repo's own root `secrets.py` shadows the *stdlib* `secrets` module
whenever the repo root ends up on `sys.path[0]` (default for any
`python -m pytest` run from repo root). Modern numpy
(`numpy.random.bit_generator`) and plotly's `narwhals` dependency both need
`secrets.randbits`/`secrets.token_hex` from the real stdlib module, so
without a fix almost every pandas/numpy/plotly-touching test fails with
`ImportError: cannot import name 'randbits'/'token_hex' from 'secrets'`.
`tests/conftest.py` strips the repo root from `sys.path` before any test
module imports, specifically to prevent this — it's load-bearing, not
boilerplate. If numpy/pandas import errors resurface, first check this file
still exists before debugging anything else.

## Known gaps (tracked, not silently fixed)

- `T20` (flake8-print) is not yet in the root ruff `select` list — enabling
  it surfaces ~650+ pre-existing `print()` violations across several
  already-unified and out-of-scope apps. Don't add it without a dedicated
  cleanup pass across the whole repo; see
  `project_hysprint_unification_batch2` memory for the exact per-app counts.
- `TRPL_Analysis`, `XRD_peak_finder`, `NMR_Analysis`, `JV-Analysis` have
  broken test setups (their `conftest.py` never puts the app dir on
  `sys.path`, so their own `test_plot_manager.py` fails even in isolation).
  Pre-existing, not this repo's newest work — don't assume a red test here
  means you broke something.
- `XPS-Automated` isn't a real app yet (one raw personal notebook, no
  `data_manager`/`plot_manager`/`gui_components`/`app.py` split, no sample
  data in-repo to validate a rewrite against). Needs a dedicated future pass.

## Ultimate goal: NOMAD plugin

This repo is meant to eventually become an installable NOMAD plugin (NORTH
tool entry points, one per app or grouped, published as Docker images).
That work has NOT started — no `north_tools/`, no Dockerfiles, no root
`[project]` table. Do not scaffold any of that without explicit sign-off on
the open questions (repo layout, package name, one-image-vs-per-tool,
registry) — see `FINALIZE_UNIFICATION_PROMPT.md`'s "Ultimate goal" section.
