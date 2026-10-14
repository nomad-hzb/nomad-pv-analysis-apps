# utils.py
"""
Utility functions for Photoluminescence Analysis App
"""

from datetime import datetime

import config
import ipywidgets as widgets

debug_output = widgets.Output(
    layout=widgets.Layout(max_height="300px", overflow="auto", width="100%")
)


def debug_print(message, category="DEBUG"):
    """
    Print debug messages if DEBUG_MODE is enabled

    Parameters:
    -----------
    message : str
        Debug message to print
    category : str, optional
        Category/type of debug message (e.g., "DATA", "FITTING", "GUI")
    """
    if config.DEBUG_MODE:
        timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        with debug_output:
            print(f"[{timestamp}] [{category}] {message}")


def format_timestamp(timestamp_format=None):
    """
    Get formatted timestamp string

    Parameters:
    -----------
    timestamp_format : str, optional
        Format string for datetime. If None, uses config default

    Returns:
    --------
    str: Formatted timestamp
    """
    if timestamp_format is None:
        timestamp_format = config.TIMESTAMP_FORMAT
    return datetime.now().strftime(timestamp_format)
