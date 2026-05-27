# core/constants.py

"""
Application-wide constants for the EM Diagram Generator.
Physics constants are in calculations.py - this file is for app config constants.
"""

# =============================================================================
# DEBUG SETTINGS
# =============================================================================
DEBUG_LOG = False  # Set to False before deploying to Render

# =============================================================================
# DEFAULT VALUES
# =============================================================================
DEFAULT_PASSENGER_WEIGHT = 180  # lbs
DEFAULT_FUEL_WEIGHT_PER_GAL = 6.0  # lbs
DEFAULT_POWER_SETTING = 0.50
DEFAULT_ALTITUDE = 0  # ft
DEFAULT_PITCH_ANGLE = 0  # degrees

# =============================================================================
# RESOLUTION SETTINGS (for graph rendering)
# =============================================================================
HIGH_RES_SCREEN_WIDTH = 1200  # pixels
HIGH_RES_AOB_IAS_STEP = 0.5   # kts
HIGH_RES_TR_STEP = 0.5        # deg/s
LOW_RES_AOB_IAS_STEP = 1.0    # kts
LOW_RES_TR_STEP = 1.0         # deg/s

# =============================================================================
# GRAPH SETTINGS
# =============================================================================
DEFAULT_SCREEN_WIDTH = 1400  # fallback for server-side calls

# PS contour settings
PS_CONTOUR_LEVELS = [-20, -15, -10, -5, 0, 5, 10, 15, 20]
PS_GRID_POINTS = 100  # Number of grid points for Ps calculations

# =============================================================================
# STYLING CONSTANTS
# =============================================================================
COLORS = {
    "ps_positive": "green",
    "ps_negative": "red",
    "ps_zero": "black",
    "stall_boundary": "red",
    "g_limit": "black",
    "aob_bands": ["#f7f7f7", "#e0e0e0", "#c0c0c0", "#a0a0a0"],
    "turn_radius": "rgba(128, 128, 128, 0.5)",
    "vmca_line": "purple",
    "vyse_line": "blue",
}

# =============================================================================
# MANEUVER SETTINGS
# =============================================================================
STEEP_TURN_DEFAULT_AOB = 45  # degrees
STEEP_TURN_DEFAULT_IAS = 100  # kts
CHANDELLE_DEFAULT_BANK = 30  # degrees
CHANDELLE_DEFAULT_IAS = 120  # kts

# =============================================================================
# PROPELLER DRAG FACTORS
# =============================================================================
PROP_DRAG_FACTORS = {
    "feathered": 1.0,
    "stationary": 1.15,
    "windmilling": 1.30,
}
