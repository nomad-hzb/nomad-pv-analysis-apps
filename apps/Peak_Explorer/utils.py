# utils.py
"""
Utility functions for Photoluminescence Analysis App
"""

import logging
from datetime import datetime

import config

logger = logging.getLogger(__name__)

_debug_output = None


def debug_print(message, category="DEBUG"):
    """Log a debug message (logger.debug), tagged with its category ("DATA", "FITTING", "GUI").

    Shown in the app's debug panel when config.DEBUG_MODE is on (see get_debug_output), and
    wherever the logging configuration sends DEBUG records."""
    logger.debug("[%s] %s", category, message)


def get_debug_output():
    """The debug panel (an Output widget that shows the debug log), created on first use so
    that importing this module needs no ipywidgets. Only meaningful with config.DEBUG_MODE."""
    global _debug_output
    if _debug_output is None:
        import ipywidgets as widgets

        _debug_output = widgets.Output(
            layout=widgets.Layout(max_height="300px", overflow="auto", width="100%")
        )

        class _PanelHandler(logging.Handler):
            def emit(self, record):
                timestamp = datetime.fromtimestamp(record.created).strftime("%H:%M:%S.%f")[:-3]
                with _debug_output:
                    print(f"[{timestamp}] {record.getMessage()}")

        handler = _PanelHandler(level=logging.DEBUG)
        logger.addHandler(handler)
        logger.setLevel(logging.DEBUG)
    return _debug_output


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
