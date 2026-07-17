# Finalize HySPRINT Unification - Remaining Apps

You are working inside the `nomad_voila` monorepo via Claude Code. Most apps have
already been through the unification pass described in `HYSPRINT_UNIFICATION_PROMPT.md`
at the repo root. Your job is to bring the remaining apps up to the same standard.

**Read `HYSPRINT_UNIFICATION_PROMPT.md` in full first.** It defines the target
architecture, the full per-app checklist (A1-A7, I1-I4, P1-P5, N1-N5, T1-T7, E1-E5,
L1-L8, G1-G3, C1-C5, M1-M3, R1-R5), the pre-shipping gates (G1-G12), and the
standing rules. Apply that checklist and those gates to the apps below. Do not
re-derive or restate the checklist here; treat this file as scoping the target
list only.

## Note: the `0`-prefix WIP convention is retired

Apps that previously signaled "not yet unified" with a `0` prefix
(`0App_dashboard`, `0Electrochemical_analysis`, `0Global_analyzer`,
`0Peak_Explorer`, `0SEM_crystal_counter`) have been renamed to drop the prefix:
`App_dashboard`, `Electrochemical_analysis`, `Global_analyzer`, `Peak_Explorer`,
`SEM_crystal_counter`. The prefix is gone from the filesystem -- treat the
scope list below as the source of truth for status, not the folder name. Of
these five, only `Global_analyzer` still needs the unification pass; the other
four are explicitly out of scope (see below).

`apps/JV-Analysis_v5` was an empty, abandoned folder and has been deleted.
`apps/JV-Analysis` is the canonical app going forward.

## Scope: apps needing work

### Confirmed not yet unified (apply the full checklist from scratch)
- `Global_analyzer`

### Status unknown -- audit against the checklist first, then fix what fails
- `Excel_creator`
- `Wetting_envelope`
- `XPS-Automated`
- `PeroDatabase_downloader`
- `bitmap_maker`

For this second group, do not assume they need full rework. Run Step 0 (discover
and audit) exactly as the base prompt describes, produce a pass/fail/warn table
per checklist item, and only apply fixes where something actually fails.

### Explicitly out of scope -- do not touch
`App_dashboard`, `Electrochemical_analysis`, `Peak_Explorer`, and
`SEM_crystal_counter` do not need this homogenization pass. Leave them exactly
as they are, even though their folder names no longer carry the retired `0`
prefix.

### Already done -- do not touch unless a cross-cutting fix requires it
`TRPL_Analysis`, `XRD_peak_finder`, `NMR_Analysis`, `EQE_Analysis`,
`AbsPL_Analysis`, `JV-Analysis`, `MPPT_Analysis`, `DesignOfExperiments`,
`File_Uploader`, `Hansen_green_calculator`, `smart_databaser`, `shared/`.
If auditing one of the in-scope apps reveals it depends on something broken in
one of these, flag it -- do not silently edit a "done" app.

## Ultimate goal: this repo becomes an installable NOMAD plugin

The unification checklist above is not the end state -- it's a prerequisite.
The actual goal is for this whole codebase to become a NOMAD plugin that an
administrator adds to their NOMAD instance's plugin set, after which every app
"just works" inside NOMAD. This section defines what that requires, verified
against the current NOMAD plugin docs
(https://nomad-lab.eu/prod/v1/docs/howto/plugins/plugins.html and
.../types/north_tools.html) on 2026-07-17. Do not treat any of this as
optional polish -- without it, nothing here is a plugin, no matter how clean
each app's internals are.

### Which entry-point type applies

NOMAD plugins expose several entry-point types: Apps, APIs, Dashboards,
Example uploads, Normalizers, NORTH tools, Parsers, Schema packages. Two are
easy to confuse:

- **"Apps"** configures NOMAD's own search/explore UI (filters, columns,
  dashboards for browsing entries). This is NOT what these apps are.
- **"NORTH tools"** (NOMAD Remote Tools Hub) is a containerized, interactive
  Jupyter/Voila application that connects to NOMAD's data and that a user
  opens and works in from inside NOMAD. **This is the correct entry-point
  type for every one of these Voila apps.**

### What a NORTH tool requires (per the docs, verbatim structure)

1. Repo named `nomad-<name>`, package named `nomad_<name>`.
2. Package layout:
   ```
   src/nomad_<name>/
       north_tools/
           <tool_name>/
               __init__.py   # NORTHTool + NORTHToolEntryPoint
               Dockerfile
               README.md
   ```
3. `__init__.py` defines:
   ```python
   from nomad.config.models.north import NORTHTool
   from nomad.config.models.plugins import NORTHToolEntryPoint

   tool = NORTHTool(
       image="ghcr.io/<org>/nomad-<name>-<tool>:latest",
       description="...",
       file_extensions=["ipynb"],
       default_url="/lab",
       mount_path="/home/jovyan",
       display_name="<Tool Display Name>",
   )
   my_tool_entry_point = NORTHToolEntryPoint(id="<tool-id>", north_tool=tool)
   ```
4. Registered in the root `pyproject.toml`:
   ```toml
   [project.entry-points.'nomad.plugin']
   mytool = "nomad_<name>.north_tools.<tool_name>:my_tool_entry_point"
   ```
5. A built and published Docker image per tool (Jupyter-stack base image,
   deps installed via a `[dependency-groups] north = [...]` block), pushed to
   a registry (GHCR is the natural choice given this is already on GitHub).
6. A CI workflow that builds and publishes each tool's image (the template
   ships `.github/workflows/publish-north.yaml` for this -- current
   `ci.yml` only lints and tests, it does not build or push anything).
7. `LICENSE.txt` as a standalone file (currently the license text only lives
   inline inside `README.md`).
8. A `docs/` folder (mkdocs), per plugin convention.

### Concrete gaps in this repo today (verified, not assumed)

- Root `pyproject.toml` has **no `[project]` table at all** -- no package
  name, no entry points. There is currently no single installable "plugin"
  package; there are ~21 independent per-app packages plus `shared/`. This is
  the foundational gap; nothing else here works until it's resolved.
- No `north_tools/` or any other plugin entry-point module exists anywhere in
  the repo. Nothing currently registers any app with NOMAD.
- No `NORTHTool`/`NORTHToolEntryPoint` definitions, no Dockerfiles, no
  container registry, no publish workflow.
- No `LICENSE.txt`, no `docs/`.
- The `hysprint-utils @ file:///home/jovyan/uploads/analysis_apps_restructuring-WxUahazkSNy-bSE9GaZyZQ/shared`
  dependency path already targets `/home/jovyan` (the standard Jupyter/NORTH
  container home directory), which suggests this code has run inside a
  JupyterHub-like container before -- but the specific path is a one-off
  upload-session temp directory that will not exist inside a real published
  image. Each tool's own Dockerfile will need to install `hysprint_utils`
  properly at build time instead of relying on a runtime-mounted path. Do not
  carry this exact dependency string into any Dockerfile.
- `apps/PeroDatabase_downloader` has no `pyproject.toml` at all yet (already
  flagged above); it cannot become a NORTH tool until it does.

### Open decisions -- do NOT resolve these unilaterally, ask first

- **Restructuring scope.** Does each app stay independently pip-installable
  under `apps/<AppName>/` as it is now (useful for standalone/dev use outside
  NOMAD), with a *new*, separate `src/nomad_<name>/north_tools/` tree that
  wraps and points at them for the plugin build? Or does the whole monorepo
  get physically moved into the `src/nomad_<name>/...` layout the template
  expects, with `apps/` retired? These produce very different diffs across
  every app. Get explicit sign-off on which before touching any app's layout.
- **Plugin/package name.** `nomad_<name>` needs an actual name (e.g.
  `nomad_hysprint`). This should align with whatever the earlier
  repo-naming decision (rename-old-repo-and-create-new-one) lands on.
- **One image vs. one-per-tool.** The docs show one Docker image per tool.
  With ~20 apps that's ~20 images to build, publish, and maintain. Confirm
  whether every app actually needs to be a separate NORTH tool, or whether
  some belong together in one image/tool (e.g. small single-file apps),
  before scaffolding 20 Dockerfiles.
- **Registry and credentials.** Confirm the container registry (GHCR is the
  default recommendation given this is on GitHub) and who owns the
  publishing credentials/secrets before wiring up a publish workflow.

## Step 1 - Plan and wait for approval

Same as the base prompt: before editing any file, produce a plan covering every
app in scope (both groups above), classify every file found, and stop for
approval. Do not start Step 2 until the plan is approved.

Additionally, the plan must address the "Open decisions" listed under
"Ultimate goal: this repo becomes an installable NOMAD plugin" above by asking
the user directly rather than assuming an answer. Do not scaffold any
`north_tools/`, Dockerfiles, or root `pyproject.toml` `[project]` table until
those decisions are confirmed -- the per-app checklist work in this document
can and should proceed independently of them.

## Step 2 / Step 3

Execute and gate exactly as `HYSPRINT_UNIFICATION_PROMPT.md` describes. Run the
full G1-G12 gate list at the end across the *whole* repo (not just the apps you
touched), since gates like G1 (full test suite) and G2 (repo-wide ruff) are
global by nature.

## Reminder: README follow-up

`README.md` was partially fixed on 2026-07-17 (run command corrected from
`panel serve` to `voila`, folder-naming convention corrected, app roster
reconciled with what's actually in `apps/` -- added `Smart Databaser` and
`PeroDatabase Downloader`, removed three entries that didn't correspond to any
real app: Diode Analyzer, Ink Jet Absorber Analysis, Perovskite Calculator).

Two things were deliberately left for later and still need doing once this
unification batch (and the separate repo-migration decision) are settled:

1. The `## Installation` snippet is generic (`cd apps/<AppName>`, `voila
   <notebook>.ipynb`) because `pyproject.toml` standardization (T1-T7) hadn't
   landed on every app yet. Once every in-scope app here passes the checklist,
   revisit whether a single concrete example command is accurate for all of
   them.
2. The `git clone` URL in `## Installation` still points at the old repo
   (`nomad-hzb/nomad-hysprint-jupyter-scripts`). Update it once the
   rename-old-repo-and-create-new-one plan discussed separately is executed.

## Final report

Use the same report format as the base prompt (Overview, Per-app results table,
Cross-cutting findings, Gate results, Known issues, Blocked items, Test run).
Additionally include a one-line summary at the top confirming whether every app
in the monorepo (not just this batch) now passes G1-G12, since this is intended
to be the batch that closes out the unification effort.
