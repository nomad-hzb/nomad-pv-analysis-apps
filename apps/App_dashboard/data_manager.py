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


@dataclass(frozen=True)
class AppEntry:
    folder: str
    notebook: str
    name: str
    description: str
    icon: str
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
            "smart_databaser",
            "smart_databaser.ipynb",
            "Smart Databaser",
            "Build and curate sample/batch entries in the NOMAD database.",
            "fa-database",
        ),
        AppEntry(
            "PeroDatabase_downloader",
            "nomad_extractor.ipynb",
            "Database Downloader",
            "Extract and export data from NOMAD into local files.",
            "fa-download",
        ),
        AppEntry(
            "DesignOfExperiments",
            "DoE.ipynb",
            "Design of Experiments",
            "Plan and generate experimental design matrices.",
            "fa-flask",
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
            "Global_analyzer",
            "global_analyzer.ipynb",
            "Global Analyzer",
            "Explore and compare measurements across samples.",
            "fa-globe",
        ),
    ],
    "Optical & Structural Analysis": [
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
            "Excel_creator",
            "excel_creator.ipynb",
            "Excel Creator",
            "Generate formatted Excel reports from measurement data.",
            "fa-file-excel",
        ),
        AppEntry(
            "bitmap_maker",
            "bitmap_generator.ipynb",
            "Bitmap Maker",
            "Generate bitmap patterns for combinatorial inkjet printing.",
            "fa-th",
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
    ],
}


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
    """Build the absolute Voila render path for an app entry."""
    base_path = VOILA_PATH_TEMPLATE.format(user=user)
    return f"{base_path}/{uploads_path}/{entry.folder}/{entry.notebook}"


def notebook_exists(entry: AppEntry) -> bool:
    """Best-effort local existence check for the entry notebook, relative to this app's folder."""
    local_path = os.path.join("..", entry.folder, entry.notebook)
    try:
        return os.path.exists(local_path)
    except OSError:
        logger.warning("Could not check existence of %s", local_path)
        return True
