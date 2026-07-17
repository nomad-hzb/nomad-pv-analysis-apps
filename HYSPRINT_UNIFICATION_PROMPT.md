# HySPRINT Monorepo Unification Task

You are working inside the `hysprint-apps` monorepo via Claude Code. Your job is to audit the current app contained in the current folder and bring the whole repo into a single, consistent standard. You have filesystem access, so discover the apps yourself rather than waiting for pasted files.

## Step 0 - Discover and scope

1. List every file on the current directory.
2. Audit the app and apply every fix that is *safely fixable*. For anything that is not safely fixable, do NOT guess. Leave it and record a precise to-do list of what remains before all checklist items can pass. Flag the app as `WIP (partial)` in your report with that to-do list.

   **Safely fixable** (apply these): renaming or reordering imports to match the convention, moving or rewriting a test into `tests/<app_name>/`, adding or correcting `pyproject.toml` fields, swapping `print()` for `logging`, wrapping the `hysprint_utils.config` import in `try/except`, removing dead `sys.path` hacks or stale `DebugTools` references, applying `ruff` autofixes and formatting, and any change that is purely structural and does not depend on knowing the real data.

   **Not safely fixable** (leave and record as a to-do): the app's real data shape is ambiguous or unknown, a referenced file or module does not exist, the Pydantic model does not match real NOMAD/source output, a function's intended behavior is unclear, or a fix would require inventing fixture values you cannot derive from the code. When in doubt, treat it as not safely fixable and flag it.

3. Read `shared/hysprint_utils/` in full first so you know what already exists. Never duplicate anything that lives there.
4. There is a `secrets.py` file on the root directory, two levels above the current one. It is used for logging in as an alternative to `os.environ['NOMAD_CLIENT_ACCESS_TOKEN']` via `get_token()` in `hysprint_utils.access_token`. Do not import `secrets.py` directly in app code; `get_token()` already handles the walk-up discovery.

## General repo layout

```
hysprint-apps/
├── apps/<app-name>/
│   ├── pyproject.toml
│   ├── app.py
│   ├── data_manager.py
│   ├── plot_manager.py
│   ├── gui_components.py
│   └── <app>.ipynb
├── shared/hysprint_utils/
│   ├── config.py        <- URL_BASE and API_ENDPOINT live here ONLY
│   ├── api_calls.py
│   ├── access_token.py
│   ├── auth_manager.py
│   ├── batch_selection.py
│   ├── error_handler.py
│   ├── plotting_utils.py
│   ├── process_handling.py
│   └── schemas.py
├── tests/                       <- ONE folder for the whole monorepo
│   ├── conftest.py
│   └── <app_name>/              <- one subfolder per app, named after the app
│       ├── conftest.py
│       └── test_<app_name>.py   <- exactly ONE test file per app
└── pyproject.toml               <- pytest / pytest-mock live here, not per-app
```

## Step 1 - Plan and wait for approval

Before editing ANY file, produce a plan and stop for my approval. The plan must list:

- Every file found under the app folder, each classified as: **fix fully**, **WIP (partial)** (`0`-prefixed), or **skip** (with reason).
- Check whether it uses the API (and therefore whether `URL_BASE`/`API_ENDPOINT` apply).
- The set of checklist items you expect to change per app, at a summary level.
- The planned `ruff` ruleset and root config location.

Do not edit, move, or create any files until I reply with approval. If I ask for changes to the plan, revise and wait again.

## Core unification goals

1. **No duplicated code.** Anything reusable (auth, API calls, plotting helpers, error handling, schemas) must come from `shared/hysprint_utils/`, not be re-implemented inside an app. If you find duplicated logic across apps, either point it at the existing shared util or, if genuinely shared and missing, propose adding it to `hysprint_utils` (do not silently create new shared modules without flagging it).
2. **Single source of config.** `URL_BASE` and `API_ENDPOINT` are defined ONLY in `shared/hysprint_utils/config.py`. They must never appear as string literals in any notebook or app module.
3. **Not every app uses the API.** Apps that read local files or non-NOMAD sources do NOT need `URL_BASE`/`API_ENDPOINT` and must not import them just to satisfy a rule. For these, config checks are `n/a`, not `fail`. Detect API usage by whether the app actually calls `hysprint_utils.api_calls` / fetches from NOMAD.
4. **One test per app, all in `tests/<app_name>/`.** No `tests/` folder inside any app directory. The test must verify the app still reads its expected data correctly and operates on it (load -> validate -> produce a figure/result), not just that imports resolve.
5. **Consistent toml.** Every app has a `pyproject.toml` following the standard below.

## Import convention

Shared modules in `shared/hysprint_utils/` are imported WITH the `hysprint_utils.` prefix. App-local modules are imported as plain names.

| Module | Lives in | Correct import |
|---|---|---|
| `api_calls`, `access_token`, `auth_manager`, `batch_selection`, `error_handler`, `plotting_utils`, `process_handling`, `schemas` | `shared/hysprint_utils/` | `from hysprint_utils.<mod> import ...` |
| shared `config` | `shared/hysprint_utils/` | `from hysprint_utils.config import URL_BASE, API_ENDPOINT` |
| `data_manager`, `plot_manager`, `gui_components`, `utils`, app-local `config` | app-local | plain name, e.g. `from data_manager import DataManager` |

## Per-app checklist

### Architecture
- A1 - `data_manager.py` has zero widget imports (`ipywidgets`, `IPython.display`)
- A2 - `plot_manager.py` has zero widget imports
- A3 - All `ipywidgets` code lives only in `gui_components.py`
- A4 - `app.py` imports `data_manager`/`plot_manager`/`gui_components` as plain local names
- A5 - `gui_components.py` imports `data_manager`/`plot_manager` as plain local names
- A6 - No global mutable state; all data state lives on `data_manager` instance attributes
- A7 - (API-connected apps only) `data_manager.py` has both `load_offline(fixture_path)` and `_build_from_raw(raw, descriptions)` for offline/demo use. For apps that do not use the API, mark `n/a`.

### Imports
- I1 - All `shared/hysprint_utils/` modules imported with the `hysprint_utils.` prefix, never bare
- I2 - No inline/deferred shared imports inside function bodies; all at module level
- I3 - App-local modules imported as plain names without the `hysprint_utils.` prefix
- I4 - No `DebugTools` or other removed utility classes still imported or instantiated anywhere

### Pydantic / Data
- P1 - App-specific Pydantic model defined in `data_manager.py`
- P2 - Validation inside `load()` uses per-row `try/except` catching `ValidationError`
- P3 - `model_dump()` used to convert validated rows to dicts before building the DataFrame
- P4 - Optional numeric fields default to `None`, not `0` or `NaN`
- P5 - `field_validator` with `mode="before"` used to coerce array-like values where needed

### Notebook
- N1 - Notebook has exactly 2 cells
- N2 - `log_notebook_usage()` called in cell 1 only, with all app logic in cell 2
- N3 - No `sys.path.append` or `sys.path.insert` anywhere in any app file or notebook
- N4 - `URL_BASE`/`API_ENDPOINT` not defined as plain string constants in the notebook
- N5 - If needed in the notebook, they are imported via `from hysprint_utils.config import URL_BASE, API_ENDPOINT`, never assigned as literals

### pyproject.toml
- T1 - `pyproject.toml` exists in the app directory
- T2 - `hysprint-utils` dependency declared identically in every app, using the exact working form:
  `"hysprint-utils @ file:///home/jovyan/uploads/analysis_apps_restructuring-WxUahazkSNy-bSE9GaZyZQ/shared"`
  Any other variant (relative `../../shared` paths, different absolute paths, alternate PEP 508 spellings) must be replaced with this exact string.
- T3 - `pydantic>=2.0` listed in dependencies
- T4 - `[tool.hatch.build.targets.wheel] packages = ["."]` present (flat layout)
- T5 - `[tool.hatch.metadata] allow-direct-references = true` present
- T6 - `pytest`/`pytest-mock` NOT listed per-app (they live at monorepo root)
- T7 - All runtime deps listed as actually used: `pandas`, `numpy`, `plotly`, `ipywidgets`, `ipython`, `notebook`, `voila`, `natsort`, `requests`, `openpyxl` (only those the app uses; do not pad with unused deps)

### Tests (monorepo layout)
- E1 - No `tests/` folder inside the app directory; tests live in `tests/<app_name>/` at the root
- E2 - `conftest.py` uses in-memory fixtures only, never hits real files or APIs
- E3 - `FIXTURE_ROWS` covers the app's actual Pydantic model fields
- E4 - Exactly one test file per app, `test_<app_name>.py`. The fixture must use the app's *real* column/field names (the ones this app actually consumes from its data source), not generic placeholders. The test must cover: valid load producing the expected populated structure, empty/invalid input handled gracefully, and at least one plot/result function returning the expected type (e.g. `go.Figure`) with key traces present. Assertions must check actual values and field presence (e.g. a known fixture value survives load and reaches the figure), not merely `isinstance` type checks. The test must demonstrate the app still reads its real data shape correctly and works with it.
- E5 - Each app's `conftest.py` loads `data_manager` under a unique module name (e.g. `dm_<app_name>`) via `importlib.util.spec_from_file_location` so that running `pytest tests/` (full suite) does not cause `sys.modules` collisions between apps that share the `data_manager` module name.

### Logging
- L1 - No bare `print()` for status/debug in `data_manager.py`; use `logging.getLogger(__name__)`
- L2 - No bare `print()` in `plot_manager.py`
- L3 - No bare `print()` in `gui_components.py`; use `ErrorHandler` or `logging`
- L4 - No bare `print()` in `app.py`
- L5 - No `print_debug()` or ad-hoc debug helpers defined anywhere
- L6 - Logger created at module level with `logging.getLogger(__name__)`
- L7 - Appropriate log levels (`DEBUG` trace, `INFO` progress, `WARNING`/`ERROR` problems)
- L8 - `logger.*()` calls use `%s`/`%d` placeholder style, never f-strings inside the format string

### Widgets / GUI
- G1 - Each panel is a class with a `.widget` property returning a `VBox`
- G2 - Download/save widgets are `self._download_area` per-panel instance, not module-level globals
- G3 - Shared widget factory uses `kw.setdefault("layout", ...)`, not a hardcoded `layout=` kwarg

### Config
- C1 - `shared/hysprint_utils/config.py` exists with `URL_BASE` and `API_ENDPOINT`
- C2 - No notebook or app file defines `URL_BASE`/`API_ENDPOINT` as a string constant
- C3 - Any module needing them imports directly from `hysprint_utils.config`; never passed as constructor/function args from the notebook
- C4 - The `hysprint_utils.config` import in app modules is wrapped in `try/except ImportError` with hardcoded fallback values
- C5 - For apps that do not use the API at all, none of C2-C4 apply; mark them `n/a`

### Misc
- M1 - No stale `sys.path.append` workarounds anywhere
- M2 - Optional external models (UNIFAC, etc.) wrapped in `try/except ImportError`
- M3 - No leftover debug scaffolding (`# TEST:` blocks, throwaway API probes) in production code

### Linting (ruff)
- R1 - A single `ruff` config lives at the monorepo root (in the root `pyproject.toml` under `[tool.ruff]`), not per-app. No per-app ruff config.
- R2 - `ruff check` passes for the app with no errors after fixing
- R3 - `ruff format` has been applied so the app is consistently formatted
- R4 - The ruff ruleset includes `G` (flake8-logging-format) so `G004` mechanically catches f-strings inside logger calls, `I` (isort) so import ordering and the `hysprint_utils.`-prefix vs plain-local split are enforced by the linter, and `T20` (flake8-print) so bare `print()` in app modules is a lint error rather than a manual grep hunt.
- R5 - No blanket `# noqa` or broad per-file ignores added just to silence real findings; only narrowly scoped, justified ignores if truly unavoidable

## Step 2 - Execute (only after approval)

Before processing any app, set up the root `ruff` config in the monorepo root `pyproject.toml` (under `[tool.ruff]` / `[tool.ruff.lint]`) so every app is linted identically. The ruleset must at minimum enable `E`, `F`, `I` (isort), `G` (flake8-logging-format, which includes `G004` for f-strings in logger calls), and `T20` (flake8-print, which catches bare `print()` statements in app modules). Configure isort so `hysprint_utils` is recognized as a first-party package and app-local modules (`data_manager`, `plot_manager`, `gui_components`, `utils`, `config`) sort correctly. Do not create per-app ruff configs.

Then process apps one at a time. For each app:

1. Read all its files plus its current test (if any).
2. Audit against the checklist. Note which checks are `pass` / `fail` / `warn` / `n/a`.
3. Apply fixes directly. For `0`-prefixed apps, apply everything safely fixable and record a to-do list for the rest.
4. Move/rewrite the test into `tests/<app_name>/test_<app_name>.py` with a matching `conftest.py`, deleting any in-app `tests/` folder.
5. Run `ruff check --fix` then `ruff format` on the app, and confirm `ruff check` is clean. Do not silence real findings with blanket ignores.
6. Run that app's test (`pytest tests/<app_name>/`) and confirm it passes before moving on.
7. Record the result.

After all apps are done:
- Ensure the root `pyproject.toml` carries `pytest`/`pytest-mock` and the shared `[tool.ruff]` config.
- Report any code you found duplicated across apps that should be consolidated into `hysprint_utils` (flag, do not silently create new shared modules).
- Proceed to Step 3 before writing the final report.

## Step 3 - Pre-shipping gate

Run every item below **in order**, after all per-app work in Step 2 is done, before writing the final report. If an item fails, fix it immediately if safely fixable; otherwise record it under a "Blocked items" heading in the final report. Do not deliver the final report until every item either passes or is explicitly documented as a blocker.

**G1 - Full test suite (non-live).**
```
pytest tests/ -m "not live"
```
All tests must pass. Zero failures, zero errors. Live-marker tests are excluded; they require a running NOMAD server.

**G2 - Repo-wide lint.**
```
ruff check .
```
Zero errors. The per-file ignores already in the root `pyproject.toml` are pre-approved. Do not add new broad ignores to pass this gate.

**G3 - No URL string literals in app code.**
Grep across all files under `apps/` for:
```
URL_BASE\s*=\s*["']
API_ENDPOINT\s*=\s*["']
```
Zero matches.

**G4 - No `tests/` folders inside app directories.**
Grep for any directory named `tests` directly under any `apps/<app-name>/`. Zero matches.

**G5 - No bare `print()` in production app modules.**
```
ruff check --select T20 apps/
```
Zero errors.

**G6 - Consistent `hysprint-utils` dependency string.**
Grep for `hysprint-utils @` across every `pyproject.toml` under `apps/`. Every occurrence must be exactly:
```
"hysprint-utils @ file:///home/jovyan/uploads/analysis_apps_restructuring-WxUahazkSNy-bSE9GaZyZQ/shared"
```
No relative paths, no alternate spellings.

**G7 - No `sys.path` hacks.**
Grep for `sys.path.append` and `sys.path.insert` across all files. Zero matches.

**G8 - No `DebugTools` references.**
Grep for `DebugTools` across all files. Zero matches.

**G9 - Notebook cell count.**
For every `.ipynb` in `apps/` that is not `0`-prefixed and not flagged WIP: parse the notebook JSON and confirm it has exactly 2 cells. If any notebook is malformed JSON, flag it.

**G10 - Fixture isolation.**
For every `tests/<app_name>/conftest.py`, confirm no file contains a live network call: grep for `requests.get`, `requests.post`, or the literal NOMAD URL string. Zero matches.

**G11 - Full-suite sys.modules collision check.**
Re-run:
```
pytest tests/ -m "not live" -p no:randomly --tb=no -q
```
If results differ from G1 (some tests pass in isolation but fail in the full suite), document every affected app under "Known issues - full suite" in the final report with the exact error. This is a `warn`, not a `fail`, if the per-app run is clean and the collision was pre-existing. If E5 was applied to all conftest files, this gate should be clean.

**G12 - Offline/demo mode completeness (API-connected apps only).**
For every app that calls `hysprint_utils.api_calls` or fetches from NOMAD: confirm `data_manager.py` has both `load_offline(fixture_path)` and `_build_from_raw(raw, descriptions)`. Apps that do not use the API: mark `n/a`.

After all gates are evaluated, include a "Gate results" table in the final report:

| Gate | Status | Notes |
|------|--------|-------|
| G1 Full tests | PASS/FAIL | N passed, M failed |
| G2 Ruff | PASS/FAIL | |
| G3 URL literals | PASS/FAIL | |
| G4 No in-app tests/ | PASS/FAIL | |
| G5 No print() | PASS/FAIL | |
| G6 Dep string | PASS/FAIL | |
| G7 sys.path | PASS/FAIL | |
| G8 DebugTools | PASS/FAIL | |
| G9 Notebook cells | PASS/FAIL/WARN | |
| G10 Fixture isolation | PASS/FAIL | |
| G11 sys.modules collision | PASS/WARN | |
| G12 Offline mode | PASS/FAIL/n/a | |

## Standing rules (apply to every edit)

- Only change what the checklist requires; do not refactor unrelated code.
- No regressions: if making a check pass would break an app's currently-working behavior or an already-passing test, stop and flag it instead of proceeding. A green app must stay green.
- For app folders whose name starts with `0`: fix everything safely fixable, but never guess at work that depends on me. Leave those items and record a to-do list instead.
- The `hysprint-utils` dependency in every app's `pyproject.toml` must be exactly:
  `"hysprint-utils @ file:///home/jovyan/uploads/analysis_apps_restructuring-WxUahazkSNy-bSE9GaZyZQ/shared"`
- Replace bare `print()` status/debug calls with `logging.getLogger(__name__)` at module level, using appropriate levels.
- All `logger.*()` calls use `%s`/`%d` placeholder style, never f-strings inside the format string.
- All shared `hysprint_utils` imports use the `hysprint_utils.` prefix; app-local modules use plain names.
- `URL_BASE`/`API_ENDPOINT` are never string literals in notebooks or app modules; import from `hysprint_utils.config` with a `try/except ImportError` fallback in app modules. Apps that do not use the API need neither.
- Never duplicate code that already exists in `hysprint_utils`.
- Run `ruff check --fix` and `ruff format` on every app you touch; leave `ruff check` clean. The ruff config is at the monorepo root only, never per-app, and must keep `G004`, `T20`, and isort (`I`) enabled.
- `_TESTS_ROOT` and `DEMO_FIXTURE_PATH` constants must appear AFTER all imports in their module (not interleaved), to avoid E402 ruff errors.
- Preserve all existing logic and variable names unless a fix requires renaming.
- No em-dashes in any output you produce.

## Final report format

Produce one Markdown summary at the end:

### Overview
2-3 sentences on the overall state of the repo and what changed.

### Per-app results

For each app, a table:

| ID | Status | Rule | Detail | File |
|----|--------|------|--------|------|

Status legend: `pass`, `fail`, `warn`, `n/a`. For `0`-prefixed apps, add a top line `WIP (partial)` and a to-do list of what remains before all items can pass.

### Cross-cutting findings
- Duplicated code to consolidate into `hysprint_utils`
- Any app that could not be made to pass its test, and why

### Gate results

| Gate | Status | Notes |
|------|--------|-------|
| G1 Full tests | | |
| G2 Ruff | | |
| G3 URL literals | | |
| G4 No in-app tests/ | | |
| G5 No print() | | |
| G6 Dep string | | |
| G7 sys.path | | |
| G8 DebugTools | | |
| G9 Notebook cells | | |
| G10 Fixture isolation | | |
| G11 sys.modules collision | | |
| G12 Offline mode | | |

### Known issues - full suite
List any apps where `pytest tests/<app>/` passes but `pytest tests/` (full suite) fails, with the exact error. If G11 is clean, omit this section.

### Blocked items
List any gate items or checklist failures that could not be safely fixed, with a precise to-do for each.

### Test run
Final `pytest tests/ -m "not live"` summary and repo-wide `ruff check .` summary.
