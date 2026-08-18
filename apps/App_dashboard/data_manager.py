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

VOILA_PATH_TEMPLATE = "/nomad-oasis/north/user/{user}/voila/voila/render"
JUPYTER_PATH_TEMPLATE = "/nomad-oasis/north/user/{user}/jupyter2/lab/tree"


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
    upload_id: str
    """Raw NOMAD upload ID, as shown in the GUI file-browser URL (.../upload/id/<this>/files/...).
    Unlike AppEntry.upload_id, this is NOT the '<slug>-<id>' folder name -- the jupyter2 tool
    mounts uploads under their raw ID, while Voila's own container path uses the slug form."""
    path: str
    """Path to the notebook within the upload, e.g. 'Learning/01_Python_logic_intro.ipynb'."""
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


PROJECTS: list[Project] = [
    Project(
        "Slot-die coater ML",
        "PL-imaging to JV-performance pipeline for slot-die coated devices.",
        "fa-industry",
        [
            AppEntry(
                "",
                "image_cropper.ipynb",
                "1. Image Cropper",
                "Crop raw PL images down to the region used by the rest of the pipeline.",
                "fa-crop",
                upload_id="ml-img-cropper-11-DuFOohIVQ5aauygNxEOXyg",
            ),
            AppEntry(
                "",
                "feature_extraction_app.ipynb",
                "2. Feature Extraction",
                "Extract quantitative features from the cropped PL images.",
                "fa-vector-square",
                # FIXME: needs real '<slug>-<id>' upload folder (see AppEntry.upload_id)
                upload_id="XnIHIdrkTT6VFyxFD8a6Hg",
            ),
            AppEntry(
                "",
                "pl_defect_voila_app.ipynb",
                "3. PL Defect Analysis",
                "Detect and visualize defects in photoluminescence images.",
                "fa-eye",
                # FIXME: needs real '<slug>-<id>' upload folder (see AppEntry.upload_id)
                upload_id="XnIHIdrkTT6VFyxFD8a6Hg",
            ),
            AppEntry(
                "",
                "nomad_ml_app.ipynb",
                "4. ML Model",
                "Train/apply the ML model on the extracted PL features.",
                "fa-brain",
                # FIXME: needs real '<slug>-<id>' upload folder (see AppEntry.upload_id)
                upload_id="sSP9nxKDRhax0cuBzsrvEA",
            ),
            AppEntry(
                "",
                "correlation_analysis_app.ipynb",
                "5. Correlation Analysis",
                "Correlate PL/ML features with device performance.",
                "fa-project-diagram",
                # FIXME: needs real '<slug>-<id>' upload folder (see AppEntry.upload_id)
                upload_id="Jeb8HXjnSNy9T0-Z5VVbhA",
            ),
            AppEntry(
                "",
                "ROI_JV_NOMAD_app.ipynb",
                "6. PL ROI → JV Assignment",
                "Map PL-imaged ROIs to per-device JV curves and export the joined "
                "dataset back to NOMAD.",
                "fa-object-group",
                # FIXME: needs real '<slug>-<id>' upload folder (see AppEntry.upload_id)
                upload_id="YRS7abDQS26o2NplzjBwKg",
            ),
        ],
    ),
]


LEARNING_FOLDER = LearningEntry(
    "Learning",
    "Learn to build your own NOMAD solutions: guided Python & NOMAD tutorial notebooks, "
    "opens the folder in JupyterLab so you can browse and pick whichever lesson you want.",
    "fa-graduation-cap",
    upload_id="mr60amaQRZ-Ta21fXdf64Q",
    path="Learning",
)


def get_current_user() -> str:
    """Return the NOMAD username of the person running this notebook, or '' if unknown."""
    return os.environ.get("NOMAD_CLIENT_USER", "")


def get_uploads_path() -> str:
    """Derive 'uploads/<upload_id>/<container>' from the current working directory.

    Under a NOMAD north tool the cwd is .../uploads/<upload_id>/<container>/<AppFolder>,
    where <container> is the folder holding all app folders (this repo's own upload
    mirrors the repo layout, so <container> is "apps"). Both names are read from cwd
    rather than hardcoded so this keeps working if the upload layout changes.
    """
    container_dir = os.path.dirname(os.getcwd())
    upload_dir = os.path.dirname(container_dir)
    container = os.path.basename(container_dir)
    upload_id = os.path.basename(upload_dir)
    return f"uploads/{upload_id}/{container}"


def build_voila_url(entry: AppEntry, user: str, uploads_path: str) -> str:
    """Build the absolute Voila render path for an app entry.

    Uses entry.upload_id instead of uploads_path when set, for apps that live in a
    separate NOMAD upload from this dashboard (e.g. Projects apps).
    """
    base_path = VOILA_PATH_TEMPLATE.format(user=user)
    path = f"uploads/{entry.upload_id}" if entry.upload_id else uploads_path
    folder = f"{entry.folder}/" if entry.folder else ""
    return f"{base_path}/{path}/{folder}{entry.notebook}"


def build_jupyter_url(entry: LearningEntry, user: str) -> str:
    """Build the absolute JupyterLab 'tree' path that opens a learning notebook directly.

    Unlike build_voila_url, this points at the jupyter2 NORTH tool so the notebook opens
    already-loaded in a JupyterLab tab instead of being rendered as a Voila app.
    """
    base_path = JUPYTER_PATH_TEMPLATE.format(user=user)
    return f"{base_path}/uploads/{entry.upload_id}/{entry.path}"


def notebook_exists(entry: AppEntry) -> bool:
    """Best-effort local existence check for the entry notebook, relative to this app's folder."""
    local_path = os.path.join("..", entry.folder, entry.notebook)
    try:
        return os.path.exists(local_path)
    except OSError:
        logger.warning("Could not check existence of %s", local_path)
        return True
