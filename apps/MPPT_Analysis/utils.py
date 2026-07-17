"""
Utility functions for MPPT Analysis App
"""

import numpy as np


def validate_time_data(t_data, y_data, min_points=3):
    """
    Validate and clean time series data

    Args:
        t_data: Time array
        y_data: Data array
        min_points: Minimum number of valid points required

    Returns:
        tuple: (cleaned_t_data, cleaned_y_data, is_valid)
    """
    # Remove NaN values
    valid_mask = ~(np.isnan(t_data) | np.isnan(y_data))
    t_clean = t_data[valid_mask]
    y_clean = y_data[valid_mask]

    # Check if we have enough points
    is_valid = len(t_clean) >= min_points

    return t_clean, y_clean, is_valid


def apply_time_range_filter(t_data, y_data, time_range):
    """
    Apply time range filter to data

    Args:
        t_data: Time array
        y_data: Data array
        time_range: Tuple of (t_min, t_max) or None

    Returns:
        tuple: (filtered_t_data, filtered_y_data)
    """
    if time_range is None:
        return t_data, y_data

    t_min, t_max = time_range
    mask = (t_data >= t_min) & (t_data <= t_max)
    return t_data[mask], y_data[mask]


def extract_sample_name_parts(sample_id, name_type="sample_name"):
    """
    Extract different parts of sample name based on naming convention

    Args:
        sample_id: Full sample identifier
        name_type: Type of name to extract ('sample_name', 'batch', 'sample_description')

    Returns:
        str: Extracted name part
    """
    if name_type == "batch":
        item_split = sample_id.split("&")
        if len(item_split) >= 2:
            return item_split[0]
        else:
            return "_".join(sample_id.split("_")[:-1])

    elif name_type == "sample_name":
        item_split = sample_id.split("&")
        if len(item_split) >= 2:
            return "&".join(item_split[1:])
        else:
            return sample_id

    else:  # sample_description or other
        return sample_id


def format_parameter_value(param_value):
    """
    Format parameter value for display, handling uncertainties

    Args:
        param_value: Parameter value (may have uncertainties)

    Returns:
        dict: Dictionary with 'value' and optionally 'error' keys
    """
    if hasattr(param_value, "nominal_value"):
        return {"value": param_value.nominal_value, "error": param_value.std_dev}
    else:
        return {"value": param_value}


def pad_arrays_to_equal_length(data_dict):
    """
    Pad arrays in dictionary to equal length with NaN values

    Args:
        data_dict: Dictionary of arrays

    Returns:
        dict: Dictionary with padded arrays
    """
    if not data_dict:
        return data_dict

    max_length = max(len(values) for values in data_dict.values())

    padded_dict = {}
    for key, values in data_dict.items():
        if len(values) < max_length:
            padded = np.full(max_length, np.nan)
            padded[: len(values)] = values
            padded_dict[key] = padded
        else:
            padded_dict[key] = values

    return padded_dict


def calculate_file_size_mb(data_bytes):
    """Calculate file size in MB"""
    return len(data_bytes) / 1024 / 1024


def create_sample_info_dict(sample_id, properties_df, custom_names):
    """
    Create sample information dictionary

    Args:
        sample_id: Sample identifier
        properties_df: DataFrame with sample properties
        custom_names: Dictionary of custom names

    Returns:
        dict: Sample information
    """
    return {
        "sample_id": sample_id,
        "description": properties_df.loc[sample_id, "description"]
        if sample_id in properties_df.index
        else "",
        "custom_name": custom_names.get(sample_id, ""),
    }


def get_available_histogram_parameters(fit_results_df):
    """
    Get list of available time parameters for histograms

    Args:
        fit_results_df: DataFrame with fitting results

    Returns:
        list: List of available time parameters
    """
    if fit_results_df is None or len(fit_results_df) == 0:
        return []

    available_params = list(fit_results_df.columns)
    time_params = ["t80", "T80", "tS", "ts", "Ts80"]

    return [param for param in time_params if param in available_params]


def interpolate_curves_to_common_grid(curves_data, num_points=200):
    """
    Interpolate multiple curves to a common time grid

    Args:
        curves_data: List of dictionaries with 'time' and 'data' keys
        num_points: Number of points for interpolation grid

    Returns:
        tuple: (time_grid, interpolated_data_array)
    """
    if not curves_data:
        return None, None

    # Find time range
    all_times = np.concatenate([curve["time"] for curve in curves_data])
    time_grid = np.linspace(all_times.min(), all_times.max(), num_points)

    # Interpolate each curve
    interpolated_data = []
    for curve in curves_data:
        interp_data = np.interp(time_grid, curve["time"], curve["data"])
        interpolated_data.append(interp_data)

    return time_grid, np.array(interpolated_data)


def generate_timestamp_filename(base_name, extension="zip"):
    """
    Generate filename with timestamp

    Args:
        base_name: Base name for file
        extension: File extension (without dot)

    Returns:
        str: Filename with timestamp
    """
    from datetime import datetime

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"{base_name}_{timestamp}.{extension}"


def safe_divide(numerator, denominator, default=0):
    """
    Safely divide two numbers, returning default if denominator is zero

    Args:
        numerator: Numerator value
        denominator: Denominator value
        default: Default value if division by zero

    Returns:
        float: Result of division or default value
    """
    if denominator == 0:
        return default
    return numerator / denominator


def group_curves_by_sample(curves_data):
    """
    Group curve data by sample ID

    Args:
        curves_data: List of curve dictionaries

    Returns:
        dict: Dictionary with sample_id as keys and lists of curves as values
    """
    grouped = {}
    for curve in curves_data:
        sample_id = curve["sample_id"]
        if sample_id not in grouped:
            grouped[sample_id] = []
        grouped[sample_id].append(curve)

    return grouped


def validate_plot_data(curves_data, variable):
    """
    Validate that curve data contains the required variable

    Args:
        curves_data: List of curve dictionaries
        variable: Variable name to check for

    Returns:
        list: Filtered list of valid curves
    """
    valid_curves = []
    for curve in curves_data:
        if "data" in curve and len(curve["data"]) > 0:
            valid_curves.append(curve)

    return valid_curves
