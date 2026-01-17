# Next Task: Fix Steep Turn Maneuver

## Overview

The steep turn maneuver needs to be updated to:
1. Match the visual style of other maneuvers (hover points, polyline rendering)
2. Fix wind integration issues causing snap movements between turn directions
3. Simulate realistic flight dynamics with all available input parameters

---

## Current Issues

### 1. Visual Inconsistency
The steep turn doesn't match the look of other maneuvers:
- **Impossible Turn, Engine Out, PO180** use `render_hover_polyline()` with detailed hover data including:
  - Altitude (ft AGL)
  - TAS (kt)
  - Ground Speed (kt)
  - Time (sec)
  - AOB (degrees)
  - Vertical Speed (fpm)
  - Track/Heading/Drift

- **Steep Turn** currently returns simpler hover data and may not use the same rendering approach

### 2. Wind Integration Bug
When transitioning from one turn direction to the next (e.g., left-right sequence):
- There's a **snap movement** instead of smooth transition
- The wind effect calculation doesn't properly handle the rollout/roll-in between turns
- The pause between turns (5 seconds) doesn't account for wind drift during wings-level flight

### 3. Unrealistic Simulation
Current steep turn simulation:
- Uses simplified wind model (just offsets position by wind*time)
- Doesn't properly compute ground track vs heading
- Doesn't account for changing groundspeed around the turn
- Bank angle transitions (roll-in/roll-out) are simplistic

---

## Files to Modify

**Primary:** `/Users/nicholaslen/Desktop/Overlay_Tools/simulation/steep_turn.py`

**Reference implementations (for consistent style):**
- `simulation/impossible_turn.py` - Best example of wind integration
- `simulation/glide_path.py` - Good example of drift_corrected() pattern
- `simulation/engine_out.py` - Good example of continuous path with wind

---

## Required Changes

### 1. Update Hover Data Structure
Match the format used by other simulations:
```python
hover.append({
    "alt": altitude_ft,
    "tas": tas_knots,
    "gs": ground_speed_knots,  # ADD
    "time": time_sec,
    "aob": bank_angle,
    "vs": vertical_speed_fpm,  # Should be 0 for level steep turn
    "track": ground_track_deg,  # ADD
    "heading": heading_deg,     # ADD
    "drift": drift_deg,         # ADD
    "segment": "steep_turn",    # ADD
})
```

### 2. Implement Proper Wind Model
Use the same `drift_corrected()` pattern from other simulations:
```python
def drift_corrected(wind_from_deg, track_hdg_deg, tas_knots, wind_speed_knots):
    """
    Calculate groundspeed, heading, and drift to maintain desired ground track.
    """
    if wind_speed_knots <= 0.1:
        return tas_knots, track_hdg_deg, 0.0

    wind_to_deg = (wind_from_deg + 180.0) % 360.0
    alpha_deg = (wind_to_deg - track_hdg_deg + 360.0) % 360.0
    alpha = math.radians(alpha_deg)

    cross = wind_speed_knots * math.sin(alpha)
    head = wind_speed_knots * math.cos(alpha)

    cross_clamped = max(min(cross, tas_knots * 0.99), -tas_knots * 0.99)
    drift_rad = math.asin(cross_clamped / tas_knots)
    drift_deg = math.degrees(drift_rad)

    heading_deg = (track_hdg_deg + drift_deg + 360.0) % 360.0

    along_air = tas_knots * math.cos(drift_rad)
    gs_knots = along_air + head
    gs_knots = max(5.0, gs_knots)

    return gs_knots, heading_deg, drift_deg
```

### 3. Fix Turn Transitions
For left-right or right-left sequences:
1. **Roll-out phase**: Gradually reduce bank from full to 0 over ~3 seconds
2. **Wings-level segment**: Maintain heading with wind correction during pause
3. **Roll-in phase**: Gradually increase bank from 0 to full over ~3 seconds
4. **Continuous path**: No snap/teleport - each step moves based on actual groundspeed

### 4. Use Time-Step Integration
Instead of computing arc points geometrically, use time-step simulation like other maneuvers:
```python
dt = timestep_sec  # e.g., 0.5 seconds
while not complete:
    # Calculate current bank angle (with roll-in/roll-out)
    # Calculate turn rate from bank and TAS
    # Update heading
    # Calculate ground track with wind
    # Move position based on groundspeed and track
    # Record path and hover data
    time += dt
```

---

## Input Parameters Available

From the UI (see `steep_turn_layout()` in app.py):
- `steepturn-bank` - Bank angle (degrees)
- `steepturn-sequence` - Turn sequence (left, right, left-right, right-left)
- `steepturn-entry-hdg` - Entry heading (degrees)
- `steepturn-altitude` - Altitude (ft AGL)
- `steepturn-ias` - Indicated airspeed (KIAS)

From environment inputs:
- `oat-input` - Outside air temperature (°C)
- `altimeter-input` - Altimeter setting (inHg)
- `wind-dir-input` - Wind direction (degrees FROM)
- `wind-speed-input` - Wind speed (knots)

**Note:** Currently steep turn may not use all these - should use TAS calculated from IAS/altitude/OAT like other maneuvers.

---

## Testing Checklist

After modifications:
- [ ] Single left turn renders smoothly with wind
- [ ] Single right turn renders smoothly with wind
- [ ] Left-right sequence has smooth transition (no snap)
- [ ] Right-left sequence has smooth transition (no snap)
- [ ] Hover tooltips show all data (alt, TAS, GS, time, AOB, track, heading, drift)
- [ ] Wind causes visible drift of the turn circle
- [ ] Entry/exit points align correctly
- [ ] Groundspeed varies around turn (faster downwind, slower upwind)

---

## Reference: Current Steep Turn Code Location

`/Users/nicholaslen/Desktop/Overlay_Tools/simulation/steep_turn.py`

The current implementation is ~120 lines. It will likely need significant rewrite to match the ~300-400 line implementations of other maneuvers.

---

## Command to Resume

When returning with fresh context, tell Claude:
```
Read NEXT_TASK.md and implement the steep turn fixes described there
```
