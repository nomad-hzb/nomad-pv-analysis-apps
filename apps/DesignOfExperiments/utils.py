"""
Utilities for the Design of Experiments application.
Helper functions, validation utilities, and constants.
"""

import re
from typing import Any, Dict, List, Optional, Tuple, Union

import numpy as np
import pandas as pd


class Constants:
    """Application constants and configuration."""

    APPLICATION_VERSION = "1.0.0"
    APPLICATION_NAME = "Design of Experiments (DoE) Application"

    # Sampling limits
    MIN_SAMPLES = 4
    MAX_SAMPLES = 10000
    DEFAULT_SAMPLES = 25

    # Variable limits
    MAX_VARIABLES = 20
    MAX_CATEGORIES = 50

    # File size limits (in bytes)
    MAX_UPLOAD_SIZE = 10 * 1024 * 1024  # 10MB

    # Supported file formats
    SUPPORTED_IMPORT_FORMATS = [".json", ".csv", ".xlsx"]
    SUPPORTED_EXPORT_FORMATS = ["csv", "json", "excel"]

    # Algorithm requirements
    ALGORITHM_REQUIREMENTS = {
        "Latin Hypercube Sampling": [],
        "Sobol Sequences": [],
        "Halton Sequences": [],
        "Random Sampling": [],
        "Uniform Grid Sampling": [],
        "Orthogonal Arrays": [],
        "Definitive Screening Design": [],
        "Maximin Distance Design": [],
        "Augment Existing Design": [],
    }

    # Quality metric thresholds
    QUALITY_THRESHOLDS = {
        "min_distance": {"good": 0.1, "fair": 0.05},
        "overall_coverage": {"good": 0.8, "fair": 0.6},
        "distance_uniformity": {"good": 0.3, "fair": 0.5},
        "max_correlation": {"good": 0.3, "fair": 0.5},
    }


class ValidationUtils:
    """Utility class for data validation and error checking."""

    @staticmethod
    def validate_variable_name(name: str) -> Tuple[bool, str]:
        """Validate variable name format and content."""
        if not name or not name.strip():
            return False, "Variable name cannot be empty"

        name = name.strip()

        # Check length
        if len(name) > 50:
            return False, "Variable name too long (max 50 characters)"

        # Check for valid characters (alphanumeric, underscore, hyphen)
        if not re.match(r"^[a-zA-Z][a-zA-Z0-9_-]*$", name):
            return (
                False,
                "Variable name must start with letter and contain only letters, "
                "numbers, underscore, or hyphen",
            )

        # Check for reserved words
        reserved_words = ["experiment_id", "sample_id", "index", "id"]
        if name.lower() in reserved_words:
            return False, f"'{name}' is a reserved word"

        return True, ""

    @staticmethod
    def validate_numeric_range(
        min_val: float, max_val: float, step: Optional[float] = None
    ) -> Tuple[bool, str]:
        """Validate numeric range parameters."""
        if not isinstance(min_val, (int, float)) or not isinstance(max_val, (int, float)):
            return False, "Min and max values must be numeric"

        if np.isnan(min_val) or np.isnan(max_val):
            return False, "Min and max values cannot be NaN"

        if np.isinf(min_val) or np.isinf(max_val):
            return False, "Min and max values cannot be infinite"

        if min_val >= max_val:
            return False, "Max value must be greater than min value"

        if step is not None:
            if not isinstance(step, (int, float)):
                return False, "Step size must be numeric"

            if step <= 0:
                return False, "Step size must be positive"

            if step >= (max_val - min_val):
                return False, "Step size must be smaller than the range"

        return True, ""

    @staticmethod
    def validate_categories(categories: List[str]) -> Tuple[bool, str]:
        """Validate categorical variable categories."""
        if not categories:
            return False, "At least one category is required"

        if len(categories) < 2:
            return False, "At least two categories are required"

        if len(categories) > Constants.MAX_CATEGORIES:
            return False, f"Too many categories (max {Constants.MAX_CATEGORIES})"

        # Check for empty or whitespace-only categories
        valid_categories = [cat.strip() for cat in categories if cat.strip()]
        if len(valid_categories) != len(categories):
            return False, "Categories cannot be empty or whitespace-only"

        # Check for duplicates
        if len(set(valid_categories)) != len(valid_categories):
            return False, "Duplicate categories are not allowed"

        # Check category length
        for cat in valid_categories:
            if len(cat) > 100:
                return False, f"Category '{cat}' is too long (max 100 characters)"

        return True, ""

    @staticmethod
    def validate_sample_size(n_samples: int, n_variables: int) -> Tuple[bool, str]:
        """Validate sample size given number of variables."""
        if not isinstance(n_samples, int):
            return False, "Sample size must be an integer"

        if n_samples < Constants.MIN_SAMPLES:
            return False, f"Sample size must be at least {Constants.MIN_SAMPLES}"

        if n_samples > Constants.MAX_SAMPLES:
            return False, f"Sample size cannot exceed {Constants.MAX_SAMPLES}"

        # Check recommended minimum
        recommended_min = max(n_variables**2, Constants.MIN_SAMPLES)
        if n_samples < recommended_min:
            return (
                True,
                f"Warning: Recommended minimum is {recommended_min} samples "
                f"for {n_variables} variables",
            )

        return True, ""

    @staticmethod
    def validate_json_structure(json_data: Dict[str, Any]) -> Tuple[bool, str]:
        """Validate JSON configuration structure."""
        required_fields = ["variables"]

        for field in required_fields:
            if field not in json_data:
                return False, f"Missing required field: {field}"

        # Validate variables array
        variables = json_data["variables"]
        if not isinstance(variables, list):
            return False, "'variables' must be an array"

        if len(variables) == 0:
            return False, "At least one variable is required"

        if len(variables) > Constants.MAX_VARIABLES:
            return False, f"Too many variables (max {Constants.MAX_VARIABLES})"

        # Validate each variable
        required_var_fields = ["name", "type"]
        for i, var in enumerate(variables):
            if not isinstance(var, dict):
                return False, f"Variable {i + 1} must be an object"

            for field in required_var_fields:
                if field not in var:
                    return False, f"Variable {i + 1} missing required field: {field}"

            # Validate variable name
            is_valid, error_msg = ValidationUtils.validate_variable_name(var["name"])
            if not is_valid:
                return False, f"Variable {i + 1}: {error_msg}"

        return True, ""

    @staticmethod
    def sanitize_filename(filename: str) -> str:
        """Sanitize filename for safe downloads."""
        # Remove or replace unsafe characters
        safe_filename = re.sub(r"[^\w\-_.]", "_", filename)

        # Limit length
        if len(safe_filename) > 100:
            name, ext = (
                safe_filename.rsplit(".", 1) if "." in safe_filename else (safe_filename, "")
            )
            safe_filename = name[:95] + ("." + ext if ext else "")

        return safe_filename

    @staticmethod
    def format_number(value: Union[int, float], decimals: int = 3) -> str:
        """Format number for display with appropriate precision."""
        if pd.isna(value):
            return "N/A"

        if isinstance(value, int) or value == int(value):
            return str(int(value))

        return f"{value:.{decimals}f}"

    @staticmethod
    def calculate_file_size(content: str) -> str:
        """Calculate and format file size."""
        size_bytes = len(content.encode("utf-8"))

        if size_bytes < 1024:
            return f"{size_bytes} B"
        elif size_bytes < 1024**2:
            return f"{size_bytes / 1024:.1f} KB"
        elif size_bytes < 1024**3:
            return f"{size_bytes / 1024**2:.1f} MB"
        else:
            return f"{size_bytes / 1024**3:.1f} GB"
