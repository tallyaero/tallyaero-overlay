"""
Unit conversion functions for aviation calculations.
"""


def knots_to_fps(knots: float) -> float:
    """Convert knots to feet per second."""
    return knots * 1.68781


def fps_to_knots(fps: float) -> float:
    """Convert feet per second to knots."""
    return fps / 1.68781


def fpm_to_fps(fpm: float) -> float:
    """Convert feet per minute to feet per second."""
    return fpm / 60.0


def fps_to_fpm(fps: float) -> float:
    """Convert feet per second to feet per minute."""
    return fps * 60.0


def celsius_to_fahrenheit(c: float) -> float:
    """Convert Celsius to Fahrenheit."""
    return (c * 9.0 / 5.0) + 32.0


def fahrenheit_to_celsius(f: float) -> float:
    """Convert Fahrenheit to Celsius."""
    return (f - 32.0) * 5.0 / 9.0
