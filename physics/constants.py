"""
Physical constants used in aviation calculations.
"""

# Gravitational acceleration
g = 32.174  # ft/s^2
G_FPS2 = 32.174  # ft/s^2 (alias)

# Gas constant for air
R = 1716.0  # ft*lbf/(slug*R)

# Standard sea level conditions
T_sl = 518.67  # Rankine (standard temp at sea level)
P_sl = 2116.22  # lbf/ft^2 (standard pressure at sea level)
rho_sl = 0.0023769  # slugs/ft^3 (standard density at sea level)

# Distance conversions
FT_PER_NM = 6076.12
FT_PER_M = 3.28084

# Glide path geometry constants
OVERHEAD_THRESH_FT = 4000
FINAL_MIN_DIST_NM = 0.05  # shortest acceptable final leg
FINAL_MAX_DIST_NM = 0.8  # longest acceptable final leg
FINAL_CROSSING_HEIGHT_FT = 50.0  # height to cross the threshold
FINAL_ALIGN_TOL_DEG = 30.0  # alignment tolerance for breakout heading
DEFAULT_ALIGN_WINDOW_DEG = 10.0
