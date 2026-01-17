"""
Data module for loading aircraft and airport data.
"""

from .loaders import (
    load_aircraft_data,
    load_airport_data,
    get_aircraft_data,
    get_available_aircraft,
    get_airport_data
)

__all__ = [
    'load_aircraft_data',
    'load_airport_data',
    'get_aircraft_data',
    'get_available_aircraft',
    'get_airport_data',
]
