"""
Utilities Module

Common utility classes and functions used throughout the Sample Data Explorer.

Classes:
    ParameterManager: Parameter filtering and blacklist management
    ProcessStepManager: Process step name mapping and parsing

Author: HySprint Team
"""

import base64
import logging
import os
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import config
import pandas as pd
from IPython.display import Javascript
from IPython.display import display as ipy_display

logger = logging.getLogger(__name__)

try:
    from hysprint_utils.config import URL_BASE
except ImportError:
    URL_BASE = "https://nomad-hzb-se.de"
    logger.warning("hysprint_utils.config not found; using hardcoded URL fallback")

DOE_VOILA_PATH_TEMPLATE = "/nomad-oasis/north/user/{user}/voila/voila/render"
DOE_APP_PATH = "DesignOfExperiments/DoE.ipynb"


def get_material_column(df: pd.DataFrame) -> Optional[str]:
    """Get the material column name from a dataframe, if one exists."""
    if "layer_material_name" in df.columns:
        return "layer_material_name"
    elif "layer_material" in df.columns:
        return "layer_material"
    # Try to find any column with 'material' and 'layer'
    material_cols = [
        col for col in df.columns if "material" in col.lower() and "layer" in col.lower()
    ]
    if material_cols:
        return material_cols[0]
    return None


class ParameterManager:
    """Manages parameter filtering and variation detection."""

    def __init__(self):
        """Initialize parameter manager."""
        self.blacklist = config.PARAMETER_BLACKLIST

    def filter_parameters(self, all_params: List[str], param_type: str) -> List[str]:
        """
        Filter parameters based on blacklist.

        Args:
            all_params: List of all available parameters
            param_type: One of 'x_parameters', 'y_parameters', 'color_parameters'

        Returns:
            Filtered list with blacklisted parameters removed
        """
        blacklist = self.blacklist.get(param_type, [])

        if not blacklist:
            return all_params

        filtered = []
        for param in all_params:
            # Check exact match
            if param in blacklist:
                logger.debug("filter_parameters: filtered (exact): %s", param)
                continue

            # Check if param contains any blacklist term
            param_lower = param.lower()
            is_blacklisted = False
            for blacklist_term in blacklist:
                if blacklist_term.lower() in param_lower:
                    is_blacklisted = True
                    logger.debug(
                        "filter_parameters: filtered (contains '%s'): %s", blacklist_term, param
                    )
                    break

            if not is_blacklisted:
                filtered.append(param)

        # Rename 'description' → 'Notes' for display
        # Handles both plain 'description' (process steps) and
        # 'description (JV)' / 'description (AbsPL)' etc. (measurement results)
        renamed = []
        for param in filtered:
            if param == "description":
                renamed.append("Notes")
            elif param.startswith("description (") and param.endswith(")"):
                suffix = param[len("description") :]  # e.g. ' (JV)'
                renamed.append(f"Notes{suffix}")
            else:
                renamed.append(param)
        return renamed

    def detect_varying_parameters(
        self, df: pd.DataFrame, exclude_columns: Optional[List[str]] = None
    ) -> List[str]:
        """
        Detect parameters with variation across the dataset.

        Args:
            df: DataFrame to analyze
            exclude_columns: Columns to exclude from analysis

        Returns:
            List of column names that have variation (unique_count > 1)
        """
        if exclude_columns is None:
            exclude_columns = [
                "sample_id",
                "variation",
                "name",
                "datetime",
                "description",
                "data_file",
            ]

        varying_params = []

        for col in df.columns:
            if col in exclude_columns:
                continue

            try:
                series = df[col].dropna()
                if len(series) > 0 and series.nunique() > 1:
                    varying_params.append(col)
            except Exception:
                continue

        return varying_params

    def filter_to_varying_only(self, params: List[str], df: pd.DataFrame) -> List[str]:
        """Filter parameter list to only varying parameters."""
        varying = self.detect_varying_parameters(df)
        return [p for p in params if p in varying]


class ProcessStepManager:
    """Manages process step display names and layer type extraction."""

    def __init__(self):
        """Initialize process step manager."""
        # These mappings are defined but not actively used in the code
        self.material_to_layer_type = {}
        self.layer_categories = []

    def extract_layer_info(self, step: Dict) -> Optional[Dict[str, str]]:
        """Extract layer information from a processing step."""
        layer_info = {}

        # Get from 'layer' field
        if "layer" in step and step["layer"]:
            layers = step["layer"] if isinstance(step["layer"], list) else [step["layer"]]
            if layers:
                layer = layers[0]
                if isinstance(layer, dict):
                    layer_info["layer_type"] = layer.get("layer_type", "")
                    layer_info["layer_material"] = layer.get("layer_material_name", "")

        # Get from organic_evaporation
        if "organic_evaporation" in step and step["organic_evaporation"]:
            org_evap = step["organic_evaporation"]
            if isinstance(org_evap, list) and org_evap:
                org_evap = org_evap[0]
            if isinstance(org_evap, dict) and "chemical_2" in org_evap:
                material_name = org_evap["chemical_2"].get("name", "")
                if material_name and "layer_material" not in layer_info:
                    layer_info["layer_material"] = material_name

        # Infer layer type from material
        if "layer_material" in layer_info and not layer_info.get("layer_type"):
            material = layer_info["layer_material"]
            for mat_key, layer_type in self.material_to_layer_type.items():
                if mat_key.lower() in material.lower():
                    layer_info["layer_type"] = layer_type
                    break

        return layer_info if layer_info else None

    def create_display_name(self, step: Dict) -> str:
        """
        Create user-friendly display name for a process step.
        Removes material name from process type and uses layer type for grouping.
        """
        # Get base process type
        process_type = ""
        if "name" in step:
            process_type = step["name"]
        elif "m_def" in step:
            process_type = step["m_def"].split(".")[-1]

        process_type = process_type.replace("HySprint_", "")

        # Extract layer info first
        layer_info = self.extract_layer_info(step)

        # Remove material name from process_type if present
        if layer_info and layer_info.get("layer_material"):
            material_name = layer_info["layer_material"]
            process_type = (
                process_type.replace(f" {material_name}", "").replace(material_name, "").strip()
            )

        # Add layer type for grouping
        if layer_info:
            if layer_info.get("layer_type"):
                layer_type = layer_info["layer_type"]
                return f"{process_type} - {layer_type}"
            elif layer_info.get("layer_material"):
                return f"{process_type} - {layer_info['layer_material']}"

        return process_type

    def extract_process_types(self, processing_steps: List[Dict]) -> List[Tuple[str, str]]:
        """
        Extract process types with display names.
        Returns list of (display_name, original_id) tuples.
        """
        logger.debug("Processing %d steps", len(processing_steps))

        # First pass: collect all display names
        all_process_info = []

        for step in processing_steps:
            original_id = None
            if "name" in step:
                original_id = step["name"]
            elif "m_def" in step:
                original_id = step["m_def"].split(".")[-1]

            if not original_id:
                continue

            layer_info = self.extract_layer_info(step)
            display_name = self.create_display_name(step)

            all_process_info.append(
                {"display_name": display_name, "original_id": original_id, "layer_info": layer_info}
            )

            logger.debug(
                "Original ID: %s, layer info: %s, display name: %s",
                original_id,
                layer_info,
                display_name,
            )

        # Second pass: deduplicate by display_name
        unique_display_names = {}
        for info in all_process_info:
            display_name = info["display_name"]
            if display_name not in unique_display_names:
                unique_display_names[display_name] = info

        # Convert to list of tuples
        process_types = [
            (info["display_name"], info["original_id"]) for info in unique_display_names.values()
        ]

        logger.debug(
            "Final dropdown options (%d unique): %s",
            len(process_types),
            sorted(name for name, _ in process_types),
        )

        return process_types

    def map_display_to_measurement_type(self, display_name: str) -> Optional[str]:
        """Map display name to internal measurement type."""
        display_lower = display_name.lower()

        mapping = {
            "inkjet": "inkjet_printing",
            "printing": "inkjet_printing",
            "cleaning": "cleaning",
            "substrate": "substrate",
            "evaporation": "evaporation",
            "slot": "slot_die_coating",
            "slotdie": "slot_die_coating",
            "spin": "spin_coating",
            "ald": "ald",
            "atomiclayerdeposition": "ald",
            "blade": "blade_coating",
            "dip": "dip_coating",
            "laser": "laser_scribing",
            "scribing": "laser_scribing",
        }

        for key, value in mapping.items():
            if key in display_lower:
                return value

        return None


def get_current_user() -> str:
    """Return the NOMAD username of the person running this notebook, or '' if unknown."""
    return os.environ.get("NOMAD_CLIENT_USER", "")


def get_uploads_path() -> str:
    """Derive 'uploads/<upload_id>/<container>' from the current working directory.

    Same derivation as App_dashboard/data_manager.py's get_uploads_path: under a NOMAD
    north tool the cwd is .../uploads/<upload_id>/<container>/<AppFolder>, where
    <container> is the folder holding all app folders.
    """
    container_dir = os.path.dirname(os.getcwd())
    upload_dir = os.path.dirname(container_dir)
    container = os.path.basename(container_dir)
    upload_id = os.path.basename(upload_dir)
    return f"uploads/{upload_id}/{container}"


def build_doe_voila_url(user: str, uploads_path: str) -> str:
    """Build the absolute Voila render path for the Design of Experiments tool."""
    base_path = DOE_VOILA_PATH_TEMPLATE.format(user=user)
    return f"{base_path}/{uploads_path}/{DOE_APP_PATH}"


def build_doe_full_url(voila_url: str) -> str:
    """Prefix a Voila render path with URL_BASE, for use as a link tooltip."""
    return f"{URL_BASE}{voila_url}"


def trigger_csv_download(df: pd.DataFrame, filename_prefix: str) -> str:
    """Base64-encode df as CSV and trigger a browser download via a Blob +
    <a download> JS snippet (client-side only - nothing is persisted server-side;
    Voila/Jupyter has no direct filesystem-download primitive). Returns the
    filename used, so the caller can print its own status line inside its own
    `with output_widget: clear_output()` block - this only triggers the download.
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{filename_prefix}_{timestamp}.csv"

    csv_string = df.to_csv(index=False)
    b64 = base64.b64encode(csv_string.encode()).decode()

    js_code = f"""
    (function() {{
        var csvContent = atob('{b64}');
        var blob = new Blob([csvContent], {{ type: 'text/csv;charset=utf-8;' }});
        var link = document.createElement('a');
        var url = URL.createObjectURL(blob);
        link.setAttribute('href', url);
        link.setAttribute('download', '{filename}');
        link.style.visibility = 'hidden';
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
    }})();
    """
    ipy_display(Javascript(js_code))
    return filename
