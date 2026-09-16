import logging
import os
from dataclasses import dataclass

logger = logging.getLogger(__name__)

try:
    from hysprint_utils.config import URL_BASE
except ImportError:
    URL_BASE = "https://nomad-hzb-se.de"
    logging.getLogger(__name__).warning(
        "hysprint_utils.config not found; using hardcoded URL fallback"
    )

try:
    from hysprint_utils.access_token import log_button_usage
except ImportError:
    logger.warning("hysprint_utils.access_token not found; button usage will not be logged")

    def log_button_usage(action: str, user: str | None = None) -> None:
        return None


VOILA_PATH_TEMPLATE = "/nomad-oasis/north/user/{user}/voila/voila/render"
JUPYTER_PATH_TEMPLATE = "/nomad-oasis/north/user/{user}/voila/lab/tree"
"""Deliberately the "voila" NORTH tool, not a separate "jupyter2" tool -- the
latter isn't provisioned on this Oasis (confirmed via a Jupyter-Server-level
404 on a real upload where the target file genuinely existed); the voila
tool's container also serves a full JupyterLab tree view at /voila/lab/tree,
in addition to /voila/voila/render for rendered Voila apps."""


@dataclass(frozen=True)
class AppEntry:
    folder: str
    notebook: str
    name: str
    description: str
    icon: str
    experimental: bool = False
    external_url: str | None = None
    """When set, the card links straight here instead of rendering folder/notebook via Voila."""
    upload_id: str | None = None
    """When set, build the Voila link against this NOMAD upload instead of the dashboard's
    own upload (for apps that live in a separate upload, e.g. Projects apps). Must be the
    full '<slug>-<id>' upload folder name (e.g. 'ml-img-cropper-11-DuFOohIVQ5aauygNxEOXyg'),
    same as what get_uploads_path() derives for the dashboard's own upload -- the raw
    alphanumeric ID shown in NOMAD GUI file-browser URLs is NOT enough on its own."""


@dataclass(frozen=True)
class Project:
    name: str
    description: str
    icon: str
    apps: list[AppEntry]


@dataclass(frozen=True)
class LearningEntry:
    name: str
    description: str
    icon: str
    path: str
    """Path to the notebook within this dashboard's own upload, e.g.
    'Learning/01_Python_logic_intro.ipynb'. Always resolved against get_upload_id() --
    unlike AppEntry, there's no override for a separate upload."""
    experimental: bool = False


CATEGORIES: dict[str, list[AppEntry]] = {
    "Data Management": [
        AppEntry(
            "File_Uploader",
            "file_uploader.ipynb",
            "File Uploader",
            "Upload measurement files to NOMAD and link them to samples.",
            "fa-upload",
        ),
        AppEntry(
            "Excel_creator",
            "excel_creator.ipynb",
            "Excel Creator",
            "Generate formatted Excel reports from measurement data.",
            "fa-file-excel",
        ),
        AppEntry(
            "smart_databaser",
            "smart_databaser.ipynb",
            "Smart Databaser",
            "The evolution of Excel Creator: build and curate sample/batch entries "
            "straight into the NOMAD database, no spreadsheet required.",
            "fa-database",
        ),
        AppEntry(
            "Entry_Auditor",
            "entry_auditor.ipynb",
            "Entry Auditor",
            "Hunt down inconsistencies across your NOMAD database and fix the "
            "values right where they live.",
            "fa-clipboard-check",
        ),
        AppEntry(
            "PeroDatabase_downloader",
            "nomad_extractor.ipynb",
            "Database Downloader",
            "Extract and export data from NOMAD into files.",
            "fa-download",
        ),
    ],
    "Device Characterization": [
        AppEntry(
            "JV-Analysis",
            "jv-analysis.ipynb",
            "JV Analysis",
            "Examine current-voltage characteristics of solar cell devices.",
            "fa-chart-bar",
        ),
        AppEntry(
            "EQE_Analysis",
            "EQE_Analysis.ipynb",
            "EQE Analyzer",
            "Visualize and analyze external quantum efficiency measurements.",
            "fa-chart-area",
        ),
        AppEntry(
            "MPPT_Analysis",
            "MPPT_analyzer.ipynb",
            "MPPT Analyzer",
            "Analyze maximum power point tracking data for solar cells.",
            "fa-chart-line",
        ),
        AppEntry(
            "AbsPL_Analysis",
            "abspl_plotter.ipynb",
            "AbsPL Analysis",
            "Plot and analyze absolute photoluminescence measurements.",
            "fa-lightbulb",
        ),
        AppEntry(
            "TRPL_Analysis",
            "trpl_dashboard.ipynb",
            "TRPL Analysis",
            "Analyze time-resolved photoluminescence decay data.",
            "fa-clock",
        ),
        AppEntry(
            "XRD_peak_finder",
            "xy_visualizer.ipynb",
            "XRD Peak Finder",
            "Visualize XRD patterns and identify diffraction peaks.",
            "fa-mountain",
        ),
        AppEntry(
            "NMR_Analysis",
            "nmr_plotter.ipynb",
            "NMR Analysis",
            "Plot and analyze nuclear magnetic resonance spectra.",
            "fa-wave-square",
        ),
        AppEntry(
            "Peak_Explorer",
            "peak_analyzer.ipynb",
            "Peak Explorer",
            "General-purpose peak detection and analysis tool.",
            "fa-search",
        ),
    ],
    # In-situ apps read the HDF5 files insitu_analyser writes to NOMAD. The previewer is the
    # usual way in and hands its selection to the others, but each of them also works on its
    # own: opened from here they start on their own upload/sample/run selectors, and each one
    # links back to the previewer's heatmaps.
    "In-situ and GIWAXS Data Analysis": [
        AppEntry(
            "ISA_Previewer",
            "isa_previewer.ipynb",
            "ISA Previewer",
            "Pick a NOMAD upload, sample and measurement, then step through its heatmaps, "
            "diffractograms and logging.",
            "fa-map",
        ),
        AppEntry(
            "ISA_Previewer",
            "giwaxs_analysis.ipynb",
            "GIWAXS Analysis",
            "Cuts and run-to-run comparison for the GIWAXS detector images.",
            "fa-sun",
        ),
        AppEntry(
            "ISA_Previewer",
            "optical_analysis.ipynb",
            "Optical Analysis",
            "Reflectance, transmission and PL spectra of an in-situ run.",
            "fa-rainbow",
        ),
        AppEntry(
            "ISA_Previewer",
            "timely_teller.ipynb",
            "Timely Teller",
            "Plot any logged signal of a whole upload's in-situ runs against time, and "
            "correlate them.",
            "fa-chart-line",
        ),
        AppEntry(
            "Thickness_tracer",
            "thickness_tracer.ipynb",
            "Thickness Tracer",
            "Film thickness from reflectance modelling. Not implemented yet!",
            "fa-ruler-vertical",
            experimental=True,
        ),
    ],
    "Utilities & Calculators": [
        AppEntry(
            "DesignOfExperiments",
            "DoE.ipynb",
            "Design of Experiments",
            "Plan and generate experimental design matrices.",
            "fa-flask",
        ),
        AppEntry(
            "Global_analyzer",
            "global_analyzer.ipynb",
            "Global Analyzer",
            "Explore and compare measurements across samples.",
            "fa-globe",
        ),
        AppEntry(
            "Hansen_green_calculator",
            "hansen_app.ipynb",
            "Hansen Calculator",
            "Calculate Hansen solubility parameters for solvent blends.",
            "fa-tint",
        ),
        AppEntry(
            "Wetting_envelope",
            "wetting_envelope.ipynb",
            "Wetting Envelope",
            "Compute wetting envelopes for solvent selection.",
            "fa-water",
        ),
        AppEntry(
            "bitmap_maker",
            "bitmap_generator.ipynb",
            "Bitmap Maker",
            "Generate bitmap patterns for combinatorial inkjet printing.",
            "fa-th",
        ),
    ],
    "Build Your Own": [
        AppEntry(
            "",
            "",
            "Make Your Own App With This Prompt",
            "Paste this into an LLM chatbot (Claude, ChatGPT, ...) so it can query your NOMAD "
            "data directly and write a custom analysis script, no new app required.",
            "fa-robot",
            external_url=(
                "https://raw.githubusercontent.com/nomad-hzb/nomad-pv-analysis-apps/main/"
                "NOMAD_DATA_ACCESS_PROMPT.md"
            ),
        ),
    ],
    "Experimental / In Progress": [
        AppEntry(
            "Electrochemical_analysis",
            "Echem_analysis_voila_v1.ipynb",
            "Electrochemical Analysis",
            "Analyze EIS and other electrochemical measurements.",
            "fa-bolt",
            experimental=True,
        ),
        AppEntry(
            "SEM_crystal_counter",
            "SEM_Analyzer.ipynb",
            "SEM Crystal Counter",
            "Count and analyze crystal grains in SEM images.",
            "fa-microscope",
            experimental=True,
        ),
        AppEntry(
            "XPS-Automated",
            "Max_Huebner_try_11(1).ipynb",
            "XPS Automated",
            "Automated XPS peak fitting.",
            "fa-atom",
            experimental=True,
        ),
        AppEntry(
            "LCC_Calculator",
            "lcc_calculator.ipynb",
            "LCC Calculator",
            "Estimate life cycle cost (processes, materials, labor, overhead) "
            "for selected batches, exported to an editable Excel workbook.",
            "fa-money-bill-alt",
            experimental=True,
        ),
    ],
}


def _project_upload_id(env_var: str, hzb_default: str) -> str | None:
    """Resolve one Projects-section upload_id from env, HZB's value as default.

    A fork with no matching upload sets the env var to an empty string to drop
    that card entirely, rather than keeping a link that can only ever 404.
    """
    return os.environ.get(env_var, hzb_default) or None


def _build_projects() -> list[Project]:
    slot_die_apps = [
        entry
        for entry in (
            AppEntry(
                "",
                "image_cropper.ipynb",
                "1. Image Cropper",
                "Crop raw PL images down to the region used by the rest of the pipeline.",
                "fa-crop",
                upload_id=_project_upload_id(
                    "HYSPRINT_PROJECT_IMAGE_CROPPER_UPLOAD_ID",
                    "ml-img-cropper-11-DuFOohIVQ5aauygNxEOXyg",
                ),
            ),
            AppEntry(
                "",
                "feature_extraction_app.ipynb",
                "2. Feature Extraction",
                "Extract quantitative features from the cropped PL images.",
                "fa-vector-square",
                # FIXME: needs real '<slug>-<id>' upload folder (see AppEntry.upload_id)
                upload_id=_project_upload_id(
                    "HYSPRINT_PROJECT_FEATURE_EXTRACTION_UPLOAD_ID", "XnIHIdrkTT6VFyxFD8a6Hg"
                ),
            ),
            AppEntry(
                "",
                "pl_defect_voila_app.ipynb",
                "3. PL Defect Analysis",
                "Detect and visualize defects in photoluminescence images.",
                "fa-eye",
                # FIXME: needs real '<slug>-<id>' upload folder (see AppEntry.upload_id)
                upload_id=_project_upload_id(
                    "HYSPRINT_PROJECT_PL_DEFECT_UPLOAD_ID", "XnIHIdrkTT6VFyxFD8a6Hg"
                ),
            ),
            AppEntry(
                "",
                "nomad_ml_app.ipynb",
                "4. ML Model",
                "Train/apply the ML model on the extracted PL features.",
                "fa-brain",
                # FIXME: needs real '<slug>-<id>' upload folder (see AppEntry.upload_id)
                upload_id=_project_upload_id(
                    "HYSPRINT_PROJECT_ML_MODEL_UPLOAD_ID", "sSP9nxKDRhax0cuBzsrvEA"
                ),
            ),
            AppEntry(
                "",
                "correlation_analysis_app.ipynb",
                "5. Correlation Analysis",
                "Correlate PL/ML features with device performance.",
                "fa-project-diagram",
                # FIXME: needs real '<slug>-<id>' upload folder (see AppEntry.upload_id)
                upload_id=_project_upload_id(
                    "HYSPRINT_PROJECT_CORRELATION_UPLOAD_ID", "Jeb8HXjnSNy9T0-Z5VVbhA"
                ),
            ),
            AppEntry(
                "",
                "ROI_JV_NOMAD_app.ipynb",
                "6. PL ROI → JV Assignment",
                "Map PL-imaged ROIs to per-device JV curves and export the joined "
                "dataset back to NOMAD.",
                "fa-object-group",
                # FIXME: needs real '<slug>-<id>' upload folder (see AppEntry.upload_id)
                upload_id=_project_upload_id(
                    "HYSPRINT_PROJECT_ROI_JV_UPLOAD_ID", "YRS7abDQS26o2NplzjBwKg"
                ),
            ),
        )
        if entry.upload_id
    ]
    if not slot_die_apps:
        return []
    return [
        Project(
            "Slot-die coater ML",
            "PL-imaging to JV-performance pipeline for slot-die coated devices.",
            "fa-industry",
            slot_die_apps,
        )
    ]


PROJECTS: list[Project] = _build_projects()


LEARNING_FOLDER = LearningEntry(
    "Learning",
    "Learn to build your own NOMAD solutions: guided Python & NOMAD tutorial notebooks. "
    "Opens the first lesson in JupyterLab, with the whole Learning folder in the sidebar "
    "so you can browse and pick whichever one you want.",
    "fa-graduation-cap",
    path="Learning/01_Python_logic_intro.ipynb",
)


def get_current_user() -> str:
    """Return the NOMAD username of the person running this notebook, or '' if unknown."""
    return os.environ.get("NOMAD_CLIENT_USER", "")


def log_navigation(action: str) -> None:
    """Log an in-dashboard navigation click (project drill-in, back button, ...).

    Only covers events that actually run in this app's Python kernel -- the
    outbound app-launch cards are plain <a target="_blank"> links and never
    reach the kernel, so they can't be logged this way.
    """
    log_button_usage(action, user=get_current_user())


UPLOADS_DIR_NAME = "uploads"


def _cwd_parts() -> list[str]:
    """The current working directory as path segments, separator-agnostic."""
    return [part for part in os.getcwd().replace("\\", "/").split("/") if part]


def _uploads_index(parts: list[str]) -> int | None:
    """Index of the NOMAD 'uploads' mount in parts, or None if cwd is not under one.

    The leftmost match wins: the mount lives at a fixed prefix (/home/jovyan/uploads),
    so a later segment of the same name is an upload or folder that happens to be
    called "uploads", not the mount point.
    """
    for index, part in enumerate(parts):
        # Needs at least <upload_id>/<AppFolder> after it to be usable.
        if part == UPLOADS_DIR_NAME and index + 2 < len(parts):
            return index
    return None


def get_upload_id() -> str:
    """Derive this dashboard's own NOMAD upload ID from the current working directory.

    Under a NOMAD north tool the cwd is .../uploads/<upload_id>/.../<AppFolder>, so the
    upload ID is the segment right after 'uploads'. Read from cwd rather than hardcoded
    so this keeps working if the upload is ever re-uploaded under a different ID.

    Anchored on the 'uploads' segment rather than counting directories up from the cwd,
    because how deep the repo sits inside the upload varies with how it was deployed:
    unpacking the repo at the top of an upload gives <upload_id>/apps/<AppFolder>, while
    `git clone` inside the upload adds the repo directory, giving
    <upload_id>/nomad-pv-analysis-apps/apps/<AppFolder>. Fixed-depth walking silently
    returned the repo folder as the upload ID in the latter case, producing links with
    the upload name missing entirely.
    """
    parts = _cwd_parts()
    index = _uploads_index(parts)
    if index is None:
        # Not under an uploads mount (local dev, tests): best-effort, previous behaviour.
        return os.path.basename(os.path.dirname(os.path.dirname(os.getcwd())))
    return parts[index + 1]


def get_uploads_path() -> str:
    """Derive 'uploads/<upload_id>/.../<container>' from the current working directory.

    <container> is the folder holding all app folders ("apps" for this repo). Everything
    between the upload ID and the app folder is preserved, so a repo cloned into a
    subdirectory of the upload keeps that subdirectory in the path. See get_upload_id
    for why this is not a fixed number of levels.
    """
    parts = _cwd_parts()
    index = _uploads_index(parts)
    if index is None:
        container = os.path.basename(os.path.dirname(os.getcwd()))
        return f"{UPLOADS_DIR_NAME}/{get_upload_id()}/{container}"
    # From 'uploads' up to, but not including, this app's own folder.
    return "/".join(parts[index:-1])


def build_voila_url(entry: AppEntry, user: str, uploads_path: str) -> str:
    """Build the absolute Voila render path for an app entry.

    Uses entry.upload_id instead of uploads_path when set, for apps that live in a
    separate NOMAD upload from this dashboard (e.g. Projects apps).
    """
    base_path = VOILA_PATH_TEMPLATE.format(user=user)
    path = f"uploads/{entry.upload_id}" if entry.upload_id else uploads_path
    folder = f"{entry.folder}/" if entry.folder else ""
    return f"{base_path}/{path}/{folder}{entry.notebook}"


def build_jupyter_url(entry: LearningEntry, user: str, upload_id: str) -> str:
    """Build the absolute JupyterLab 'tree' path that opens a learning notebook directly.

    Unlike build_voila_url, this points at the jupyter2 NORTH tool so the notebook opens
    already-loaded in a JupyterLab tab instead of being rendered as a Voila app. Takes
    upload_id explicitly (from get_upload_id()) rather than reading it off entry, since
    LearningEntry always lives in this dashboard's own upload -- there's no per-entry
    override the way AppEntry.upload_id provides for apps living in a separate upload.
    """
    base_path = JUPYTER_PATH_TEMPLATE.format(user=user)
    return f"{base_path}/uploads/{upload_id}/{entry.path}"


def notebook_exists(entry: AppEntry) -> bool:
    """Best-effort local existence check for the entry notebook, relative to this app's folder."""
    local_path = os.path.join("..", entry.folder, entry.notebook)
    try:
        return os.path.exists(local_path)
    except OSError:
        logger.warning("Could not check existence of %s", local_path)
        return True
