"""
Configuration Module

Central configuration for the Sample Data Explorer application.
All user-configurable settings are defined here.

Configuration Sections:
    - PARAMETER_BLACKLIST: Parameters to exclude from dropdowns

Author: HySprint Team
"""

# ============================================================================
# PARAMETER FILTERING (BLACKLIST)
# ============================================================================
# Parameters in these lists will be EXCLUDED from dropdowns
# New parameters not in the blacklist will automatically appear

PARAMETER_BLACKLIST = {
    "x_parameters": [
        #'sample_id',
        #'variation',
        "name",
        #'datetime',
        #'description',
        "data_file",
        #'lab_id',
        "position_in_plan",
        "timestamp",
        #'measured_at',
        "raw_data",
        "data_path",
        #'measurement_id',
    ],
    "y_parameters": [
        # Keep mostly empty to show result parameters
        #'sample_id',
        #'variation',
        "name",
        "datetime",
        "description",
        "data_file",
        #'lab_id',
        "position_in_plan",
        "timestamp",
        "measured_at",
        "raw_data",
        "data_path",
        #'measurement_id',
    ],
    "color_parameters": [
        #'sample_id',
        #'datetime',
        #'description',
        "data_file",
        #'lab_id',
        "position_in_plan",
        "timestamp",
        #'measured_at',
        "raw_data",
        "data_path",
        #'measurement_id',
    ],
}

AI_JSON_BLACKLIST = [
    # Raw array data — too large and not useful as text
    "voltage",
    "current_density",
    "jv_curve",
    "eqe_data",
    "wavelength",
    "flux",
    "intensity_array",
    "raw_data",
    "data_path",
    "data_file",
    # NOMAD internal fields — not meaningful to the LLM
    "m_def",
    "lab_id",
    "mainfile",  #'samples','name',
    # Redundant — already captured as top-level keys
    "sample_id",
    "variation",
]
