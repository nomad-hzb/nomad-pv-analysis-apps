# nomad_voila: HySPRINT Analysis Apps

Voila/Jupyter apps for perovskite solar-cell characterization on NOMAD Oasis (HZB SE by
default, other Oasis via `oasis_local_config.py`, see DEPLOYMENT.md). Each app runs on its own
from `apps/<App>/`; shared code is `shared/hysprint_utils/`. Process for humans: CONTRIBUTING.md.

## Layout

```
apps/<App>/
    pyproject.toml        # the app's real runtime deps (bootstrap installs them on the Oasis)
    app.py                # entry point; imports app-local modules by plain name
    data_manager.py       # no ipywidgets/IPython.display; Pydantic models, loading, validation
    plot_manager.py       # no ipywidgets/IPython.display; Plotly figures
    gui_components.py     # ipywidgets panels
    <app>.ipynb           # cell 0 is the bootstrap cell, see rule 8
shared/hysprint_utils/    # config, api_calls, access_token, auth_manager, batch_selection,
                          # consistency, error_handler, plotting_utils, process_specs, schemas
tests/<App>/              # conftest.py + test_<app>*.py, never inside apps/
tests/conftest.py         # load-bearing, see gotchas
scripts/check_repo_rules.py  # the rules below that ruff cannot check; runs in CI
bootstrap.py              # run by every notebook's cell 0
pyproject.toml            # root: the only ruff and pytest config
```

API-connected apps also provide `load_offline(fixture_path)` for demo mode and tests. Not
converted to the layout (parked, excluded from ruff and the rule checks; leave alone unless
asked): `Electrochemical_analysis`, `SEM_crystal_counter`, `XPS-Automated`. `Peak_Explorer`
and `ISA_Previewer` use their own module sets.

## Hard rules for edits in apps/

1. Never reimplement what `hysprint_utils` already has (auth, API calls, batch selection,
   error handling, schemas). If something should be shared, propose it; don't create it silently.
2. Don't edit `shared/hysprint_utils/` unless asked: it is a cross-app change needing sign-off.
3. Shared modules always as `from hysprint_utils.<mod> import ...`; app-local modules
   (`data_manager`, `plot_manager`, `gui_components`, `utils`, `config`) by plain name.
4. `URL_BASE`/`API_ENDPOINT` come from `hysprint_utils.config` inside `try/except ImportError`
   with the HZB fallback (copy `apps/Entry_Auditor/data_manager.py`). Never elsewhere as
   literals. Apps that don't call the API need neither.
5. No `print()` for status or errors: `logger = logging.getLogger(__name__)`, `%s` placeholders.
   Exception: `print()` inside `with <Output widget>:` is how widget-free modules render text
   into the UI. Check for that before converting any `print()`.
6. `ruff check --fix` and `ruff format` on every touched file; CI runs `ruff check .`,
   `ruff format --check .` and `scripts/check_repo_rules.py`. Never add per-app ruff config or
   blanket ignores.
7. App `pyproject.toml`: bare `"hysprint-utils"` (never a `file:` path), hatchling with
   `[tool.hatch.build.targets.wheel] packages = ["."]` and `allow-direct-references = true`,
   no pytest deps, no other app as a dependency (smart_databaser reaches Excel_creator through
   `excel_creator_modules.py`). Keep lower bounds at what the NORTH image already has:
   bootstrap installs them into the shared kernel environment.
8. Notebooks: cell 0 is exactly the bootstrap cell (below); the following cells import the
   app, call `log_notebook_usage()` and display it. No `sys.path` edits, no package installs,
   no saved outputs. `bootstrap.py` and `tests/` are the only sanctioned `sys.path` changes.
9. Tests: `tests/<App>/`, basenames unique across the repo. A conftest loads its app's modules
   with `importlib.util.spec_from_file_location` (under a unique name and, if the tests import
   them that way, the bare name). Fixtures only, never the network; live tests carry
   `@pytest.mark.live`.
10. No em-dashes in anything you write (code, docs, commits, PRs).
11. No regressions: if satisfying a rule would break working behavior or a passing test,
    stop and flag it.

## Process types (Excel_creator, smart_databaser)

`shared/hysprint_utils/process_specs.py` is the single source of truth for every process
type's Excel columns, archive paths, repeated groups, optional blocks and GUI config. Add or
change a process type there first (schema in its docstring); touch `sheet_experiment.py` only
for genuinely new assembly logic. Confirm archive paths against the real `map_<type>` in
nomad-baseclasses; never guess, and leave `unit_verified: False` until checked.

## Change management

- Every user-visible change has an issue on `nomad-hzb/nomad-pv-analysis-apps` and a PR with
  `Fixes #N`. Ask whether to file one if the user hasn't mentioned it. Issue numbers from
  nomad-hysprint or nomad-baseclasses are never used as `Fixes #N` here.
- Bump only the touched app's `version` (SemVer) in the same PR. No bump for refactors,
  test-only changes or `shared/` edits.
- PR titles become release notes (`gh release create <tag> --generate-notes`); make them
  descriptive. No CHANGELOG file. Push to the `hzb` remote; branches are `<issue>-<slug>`.
- After any merge or rebase where both sides touched a file, diff each touched file against
  the pre-merge tip and read it: git has auto-merged cleanly here while duplicating an `elif`
  branch and dropping a test assertion.

## Gotchas

**Repo-root `secrets.py` shadows the stdlib `secrets`.** numpy and plotly then fail with
`cannot import name 'randbits'/'token_hex'`. `tests/conftest.py` strips the repo root from
`sys.path`; never delete it. Run `voila` and `python -c` from the app directory, not the root.

**One test process, many apps.** Every app reuses the same module names, so
`tests/conftest.py` records which module objects belong to which app and binds that app's bare
names for its test modules and tests. `pytest tests/ -m "not live"` runs the whole suite, in
any folder order; if a cross-app failure appears, look there first.

**Bootstrap cell 0** is exactly:
```python
import runpy
_ = runpy.run_path("../../bootstrap.py")
```
The `_ =` stops the notebook from rendering bootstrap's globals. bootstrap.py applies
`oasis_local_config.py` (every uppercase string becomes an env var; container variables win),
applies the HZB outbound proxy by default for the HZB SE Oasis (opt out with
`HTTP_PROXY = ""`/`HTTPS_PROXY = ""`), installs `shared/` and inserts it into `sys.path` (that
insert fixes "the app needs two runs"; keep it), installs the app's own pyproject deps once per
container, and mutes import-time stdout (`HYSPRINT_KEEP_IMPORT_OUTPUT=1` to debug). Details:
bootstrap.py docstrings and DEPLOYMENT.md. Never add per-app install cells or banner suppression.

**Voila widget callbacks.** A bare `display(...)` inside `on_click`/`observe` is silently
dropped. Route it through an `Output()` that stays in the displayed tree
(`apps/App_dashboard/app.py`, `js_output`). `ipywidgets.HTML` never runs `<script>`; use
`IPython.display.HTML`.

**Verify GUI changes in a real Voila + browser**, not the VS Code notebook view. Kill every
`voila`, kernel and Playwright process you start (track PID/port); on Windows prefer Git Bash
`ps`/`kill -9` when PowerShell hangs.

## Known limits (don't fix in passing)

- `T20` (print) is not enabled on purpose: ~650 legacy prints plus the Output() pattern.
- Usage logs are written per installed copy of `hysprint_utils`, with no aggregation (issue #7).
- The parked `Electrochemical_analysis` notebooks have no bootstrap cell, so they get no
  deployment environment (Oasis URL, proxy) on a non-HZB Oasis.
- Oasis-specific content has three ad-hoc mechanisms (per-item env override in App_dashboard,
  the deliberate SE pin in PeroDatabase_downloader, derivation from `hysprint_utils.config`),
  and the Excel_creator guide link (`sheet_data_entry_guide.py`) awaits a decision. Don't add
  a fourth mechanism.
- NOMAD-plugin packaging (NORTH tools, Dockerfiles, root `[project]`): open decisions in issue
  #62; scaffold nothing without sign-off.
