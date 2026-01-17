"""
Shared utility functions.
Consolidated safe_float (deduplicated from app.py callbacks).
"""


def safe_float(value, default=None):
    """
    Safely convert a value to float.

    Args:
        value: Value to convert
        default: Default value if conversion fails (default None)

    Returns:
        Float value or default if conversion fails
    """
    if value is None:
        return default
    try:
        return float(value)
    except (ValueError, TypeError):
        return default


def safe_int(value, default=None):
    """
    Safely convert a value to int.

    Args:
        value: Value to convert
        default: Default value if conversion fails (default None)

    Returns:
        Int value or default if conversion fails
    """
    if value is None:
        return default
    try:
        return int(value)
    except (ValueError, TypeError):
        return default


def clamp(value, min_val, max_val):
    """
    Clamp a value between min and max.

    Args:
        value: Value to clamp
        min_val: Minimum allowed value
        max_val: Maximum allowed value

    Returns:
        Clamped value
    """
    return max(min_val, min(max_val, value))
