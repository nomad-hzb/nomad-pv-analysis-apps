"""
Utility functions for MPPT Analysis App
"""


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
