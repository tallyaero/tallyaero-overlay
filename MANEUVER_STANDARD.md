# AeroEdge Maneuver Overlay Tool - Standardization Guide

This document defines the standard implementation pattern for all flight maneuvers in the AeroEdge Overlay Tool. Every maneuver should follow these guidelines to ensure consistency, accuracy, and maximum training value.

---

## Core Philosophy

This tool creates **true Energy-Maneuverability (E-M) diagram-based visualizations** by integrating:
- Real aircraft performance data
- Actual environmental conditions
- Weight and balance effects
- Power management considerations

The goal is to provide pilots with accurate, physics-based maneuver visualizations that reflect real-world flight dynamics.

---

## Design Philosophy: Perfect Execution

**This tool shows PERFECTION - the standard to aim for.**

Unlike flight simulators that model realistic flight with accumulated errors, this tool displays **what perfect execution looks like**. This is critical for briefing and debriefing:

### Geometric Approach (Not Time-Step Simulation)

For ground reference maneuvers, the path IS the ideal geometry:
- **Turns Around a Point**: Path is a perfect circle; we calculate what bank/heading/drift is REQUIRED at each point
- **S-Turns**: Path crosses the reference line at exact perpendicular; semicircles are geometrically perfect
- **Rectangular Course**: Path follows exact ground track over the road/field boundaries

### Why This Matters

| Approach | Shows | Use Case |
|----------|-------|----------|
| Time-step simulation | What might happen with errors | Flight simulators |
| **Geometric/perfect** | **What should happen** | **Briefing, training, standards** |

### Implementation Pattern

```python
# WRONG: Time-step integration (accumulates errors)
for t in range(steps):
    pos += velocity * dt  # Numerical drift causes path not to close

# RIGHT: Geometric/parametric approach
for angle in range(0, 360, step):
    pos = center + radius * [cos(angle), sin(angle)]  # Perfect circle
    bank = calculate_required_bank(groundspeed_at_this_point)
    heading = calculate_required_heading(wind, track)
```

### What Pilots See

At each point on the PERFECT path, the hover data shows:
- **What bank angle is required** to maintain that radius at current groundspeed
- **What heading is required** to track the desired ground path given the wind
- **What crab/drift angle** results from the wind correction
- **What groundspeed** results from the wind component

This answers the pilot's question: *"If I want to fly this maneuver perfectly, what do I need to do at each point?"*

### Altitude in Perfect Execution

For level maneuvers (turns around a point, S-turns, steep turns):
- Perfect execution = constant altitude
- The info panel shows `Altitude Loss: 0 ft` for perfect execution
- Power setting integration shows what power is needed to maintain altitude

For descending maneuvers (steep spirals, engine-out):
- Path shows ideal descent profile
- Altitude varies as expected for the maneuver

---

## Required Components for Every Maneuver

### 1. Time Scrubber (Slider)

Every maneuver must include a time scrubber that allows users to:
- Scrub through the maneuver timeline
- View flight parameters at any point
- See a marker on the map showing aircraft position

**Implementation Pattern:**
```python
# In the layout function:
html.Div(id="[maneuver]-slider-container", style={"display": "none"}, children=[
    html.Label("Time Scrubber", className="input-label"),
    dcc.Slider(
        id="[maneuver]-time-slider",
        min=0,
        max=100,
        step=1,
        value=0,
        marks={},
        tooltip={"placement": "bottom", "always_visible": False}
    ),
]),
dcc.Store(id="[maneuver]-hover-store", data=[]),
dcc.Store(id="[maneuver]-path-store", data=[]),
```

**Scrubber Callback Pattern:**
```python
@app.callback(
    Output("scrubber-layer", "children", allow_duplicate=True),
    Input("[maneuver]-time-slider", "value"),
    State("[maneuver]-hover-store", "data"),
    State("[maneuver]-path-store", "data"),
    prevent_initial_call=True
)
def update_[maneuver]_scrubber(slider_value, hover_data, path_data):
    # Return airplane marker at current position with tooltip showing flight data
    # Use the create_airplane_marker() helper function
```

**Airplane Marker:**

The time scrubber displays a rotating F-18 Super Hornet style SVG icon that points in the direction of flight. Use the `create_airplane_marker()` helper function defined in app.py:

```python
def create_airplane_marker(pos, heading, tooltip_content, bank_angle=0):
    """
    Create an airplane marker that points in the direction of flight.
    Uses an F-18 Super Hornet style fighter jet icon.
    """
    import base64

    # F-18 Super Hornet style SVG pointing UP (north/0°)
    svg_airplane = f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100" width="36" height="36">
        <g transform="rotate({heading}, 50, 50)">
            <!-- Main fuselage -->
            <path d="M50,8 L54,25 L54,75 L50,88 L46,75 L46,25 Z" fill="#2d3436" stroke="#dfe6e9" stroke-width="1.5"/>
            <!-- Nose cone -->
            <path d="M50,8 L53,20 L47,20 Z" fill="#636e72" stroke="#dfe6e9" stroke-width="1"/>
            <!-- Cockpit canopy -->
            <ellipse cx="50" cy="26" rx="3.5" ry="7" fill="#74b9ff" stroke="#0984e3" stroke-width="1"/>
            <!-- Leading Edge Extensions (LEX) -->
            <path d="M46,30 L35,48 L46,45 Z" fill="#2d3436" stroke="#dfe6e9" stroke-width="1"/>
            <path d="M54,30 L65,48 L54,45 Z" fill="#2d3436" stroke="#dfe6e9" stroke-width="1"/>
            <!-- Main wings -->
            <path d="M46,42 L12,62 L14,66 L46,55 Z" fill="#2d3436" stroke="#dfe6e9" stroke-width="1.2"/>
            <path d="M54,42 L88,62 L86,66 L54,55 Z" fill="#2d3436" stroke="#dfe6e9" stroke-width="1.2"/>
            <!-- Horizontal stabilizers -->
            <path d="M46,72 L28,82 L30,85 L46,78 Z" fill="#2d3436" stroke="#dfe6e9" stroke-width="1"/>
            <path d="M54,72 L72,82 L70,85 L54,78 Z" fill="#2d3436" stroke="#dfe6e9" stroke-width="1"/>
            <!-- Twin vertical tails (canted like F-18) -->
            <path d="M44,65 L38,62 L40,78 L46,78 Z" fill="#2d3436" stroke="#dfe6e9" stroke-width="1"/>
            <path d="M56,65 L62,62 L60,78 L54,78 Z" fill="#2d3436" stroke="#dfe6e9" stroke-width="1"/>
            <!-- Engine exhausts with afterburner glow -->
            <ellipse cx="47" cy="86" rx="2.5" ry="3" fill="#fd79a8" stroke="#e84393" stroke-width="0.8"/>
            <ellipse cx="53" cy="86" rx="2.5" ry="3" fill="#fd79a8" stroke="#e84393" stroke-width="0.8"/>
            <ellipse cx="47" cy="89" rx="1.5" ry="2" fill="#ffeaa7" opacity="0.8"/>
            <ellipse cx="53" cy="89" rx="1.5" ry="2" fill="#ffeaa7" opacity="0.8"/>
        </g>
    </svg>'''

    svg_base64 = base64.b64encode(svg_airplane.encode('utf-8')).decode('utf-8')
    icon_url = f"data:image/svg+xml;base64,{svg_base64}"

    return dl.Marker(
        position=pos,
        icon={"iconUrl": icon_url, "iconSize": [36, 36], "iconAnchor": [18, 18]},
        children=dl.Tooltip(tooltip_content, permanent=True, direction="right", offset=[22, 0])
    )
```

**Usage in scrubber callback:**
```python
heading = pt.get('heading', 0)
bank = pt.get('aob', 0)
marker = create_airplane_marker(pos, heading, tooltip_content, bank)
return [marker]
```

---

### 2. Environmental Integration

Every maneuver must account for atmospheric conditions:

| Parameter | UI Element | Effect |
|-----------|------------|--------|
| OAT (°F) | `env-oat` | TAS calculation, density altitude |
| Altimeter (inHg) | `env-altimeter` | Pressure altitude calculation |
| Wind Direction (°) | `env-wind-dir` | Ground track, drift angle |
| Wind Speed (kt) | `env-wind-speed` | Groundspeed variation |
| Field Elevation (ft) | From airport selection | MSL to AGL conversion |

**Physics Calculations:**
```python
# Pressure altitude
pressure_alt_ft = compute_pressure_altitude(alt_msl_ft, altimeter_inhg)

# True airspeed from indicated
tas_knots = compute_true_airspeed(ias_knots, pressure_alt_ft, oat_c)

# Wind components (NE frame)
wind_to_rad = math.radians((wind_dir_deg + 180.0) % 360.0)
wind_fps = wind_speed_kt * 1.68781
wn_fps = wind_fps * math.cos(wind_to_rad)
we_fps = wind_fps * math.sin(wind_to_rad)

# Ground velocity
hdg_rad = math.radians(hdg_deg)
va_n = tas_fps * math.cos(hdg_rad)
va_e = tas_fps * math.sin(hdg_rad)
vg_n = va_n + wn_fps
vg_e = va_e + we_fps
gs_fps = math.hypot(vg_n, vg_e)
track_deg = math.degrees(math.atan2(vg_e, vg_n)) % 360
```

---

### 3. Weight Integration

Aircraft weight affects multiple performance parameters:

| Affected Parameter | Relationship |
|-------------------|--------------|
| Stall Speed | Vs = Vs_ref × √(W / W_ref) |
| Maneuvering Speed | Va = Va_ref × √(W / W_max) |
| Best Glide Speed | Vbg = Vbg_ref × √(W / W_ref) |
| Glide Ratio | Slightly degraded at higher weights |
| Turn Radius | Larger at higher weights (higher TAS needed) |

**Implementation:**
```python
# Get weight from runtime store
State("runtime-total-weight-lb", "data")

# In callback:
weight_lb = float(runtime_weight) if runtime_weight not in [None, "", "null"] else None
if weight_lb:
    ac["total_weight_lb"] = weight_lb

# In simulation:
stall_speed = _get_stall_speed_for_weight(ac, weight_lb, flap_config)
```

**Stall Speed Interpolation:**
If aircraft has `stall_speeds` data with weight/speed tables, interpolate. Otherwise, use weight scaling formula.

---

### 4. CG Position Integration

Center of gravity position affects:

| Effect | Forward CG (0.0) | Mid CG (0.5) | Aft CG (1.0) |
|--------|------------------|--------------|--------------|
| Stall Speed | +2% | Baseline | -2% |
| Stability | More stable | Normal | Less stable |
| Control Authority | More required | Normal | Less required |
| Fuel Efficiency | Slightly worse | Normal | Slightly better |

**Implementation:**
```python
# Get CG from slider (0.0 = forward limit, 1.0 = aft limit)
State("cg-slider", "value")

# In simulation:
cg_position = float(cg_position) if cg_position is not None else 0.5
cg_position = max(0.0, min(1.0, cg_position))

# CG effect on stall speed
# Forward CG requires more tail-down force, increasing effective wing loading
cg_stall_factor = 1.0 + (0.5 - cg_position) * 0.04
stall_speed_adjusted = stall_speed_base * cg_stall_factor
```

---

### 5. Power Setting Integration

Power setting affects altitude maintenance and energy state:

| Power Level | Effect |
|-------------|--------|
| IDLE (5%) | Maximum descent rate, energy bleeding |
| 20-40% | Gradual descent in level flight |
| 50-65% | Near-level flight in moderate turns |
| 65-80% | Level flight, can maintain altitude in turns |
| 80-100% | Climbing capability |

**Implementation:**
```python
# Get power from slider (0.05 = idle, 1.0 = full power)
State("power-setting", "value")

# In simulation:
power_setting = float(power_setting) if power_setting is not None else 0.5
power_setting = max(0.05, min(1.0, power_setting))

# Power effect on vertical speed in turns
power_balance_point = 0.65  # Power for level flight in turns
if bank_deg > 5.0:
    drag_factor = load_factor - 1.0
    power_deficit = power_balance_point - power_setting
    vs_fpm = power_deficit * drag_factor * 1200.0
    vs_fpm = max(-300.0, min(vs_fpm, 200.0))
```

---

### 6. Load Factor and G-Limit Checking

Every maneuvering simulation must:

1. **Calculate load factor** from bank angle:
   ```python
   load_factor = 1.0 / math.cos(math.radians(bank_deg))
   ```

2. **Check against aircraft G-limits**:
   ```python
   g_limit = _get_g_limit(ac, flap_config)  # Typically 3.8G normal category
   if load_factor > g_limit:
       warnings["g_limit_warning"] = True
       # Reduce bank angle to stay within limits
   ```

3. **Calculate stall speed in the turn**:
   ```python
   stall_speed_in_turn = stall_speed_clean * math.sqrt(load_factor)
   ```

4. **Verify stall margin** (minimum 1.2, prefer 1.3):
   ```python
   stall_margin = ias_knots / stall_speed_in_turn
   if stall_margin < 1.2:
       warnings["stall_margin_warning"] = True
   ```

---

### 7. Information Panel

Every maneuver must display a comprehensive info panel with:

#### Warning Section (Yellow box when applicable)
- Airspeed warnings (below 1.3×Vs or above Va)
- Stall margin warnings
- G-limit warnings
- Bank angle limitations applied
- Altitude loss warnings

#### Maneuver Summary Section
- Maneuver-specific parameters (turns, headings, etc.)
- Weight (lb)
- Power setting (%)
- CG position (%)
- IAS and TAS (kt)
- Density altitude (ft)

#### Performance Section
- Turn radius (ft and nm)
- Bank angle range (min-max)
- Groundspeed range (min-max)
- Load factor (G)

#### Altitude Section (for non-level maneuvers)
- Entry altitude
- Final altitude
- Minimum altitude
- Total altitude loss/gain

#### Stall Margins Section
- Vs clean
- Vs in turn (at max bank)
- Total maneuver time

#### Footer
- Instructions for time scrubber

---

### 8. Path Drawing Colors

All maneuvers use a consistent color scheme:

| Element | Color | Hex Code |
|---------|-------|----------|
| **Flight Path** | Red | `#ff0000` or `"red"` |
| **Entry Point Marker** | Green | `#00aa00` or `"green"` |
| **Exit Point Marker** | Red | `#cc0000` or `"red"` |
| **Reference Points** | Blue | `#3498db` or `"blue"` |

```python
# Standard path drawing
path_line = dl.Polyline(positions=path, color="red", weight=3)

# Entry marker
entry_marker = dl.CircleMarker(center=entry_pos, radius=6, color="green", fill=True)

# Exit marker
exit_marker = dl.CircleMarker(center=exit_pos, radius=6, color="red", fill=True)
```

---

### 9. Hover Data Structure

Every simulation must return hover data with these fields:

```python
hover.append({
    "time": round(t, 2),           # Elapsed time (seconds)
    "alt": round(altitude, 1),      # Altitude AGL (feet)
    "tas": round(tas_knots, 1),     # True airspeed (knots)
    "ias": round(ias_knots, 1),     # Indicated airspeed (knots)
    "gs": round(gs_kt, 1),          # Groundspeed (knots)
    "aob": round(bank_deg, 1),      # Angle of bank (degrees)
    "vs": round(vs_fpm, 0),         # Vertical speed (fpm, positive=climb)
    "track": round(track_deg, 1),   # Ground track (degrees)
    "heading": round(hdg_deg, 1),   # Magnetic heading (degrees)
    "drift": round(drift_deg, 1),   # Wind drift angle (degrees)
    "load_factor": round(n, 2),     # Load factor (G)
    "segment": segment_name,        # Current phase/segment name
    # Maneuver-specific fields as needed
})
```

---

### 9. Warnings Dictionary

Every simulation must return a warnings dict with:

```python
warnings = {
    # Safety warnings (boolean flags)
    "stall_margin_warning": False,
    "g_limit_warning": False,
    "bank_limited": False,

    # Text warnings (strings when applicable)
    "airspeed_warning": None,
    "altitude_warning": None,

    # Configuration data
    "power_setting_pct": round(power_setting * 100, 0),
    "cg_position_pct": round(cg_position * 100, 0),
    "original_bank": base_bank_deg,
    "effective_bank": actual_bank_deg,

    # Performance data
    "weight_lb": round(weight_lb, 0),
    "tas_knots": round(tas_knots, 1),
    "density_altitude_ft": round(density_alt, 0),
    "turn_radius_ft": round(radius_ft, 0),
    "turn_radius_nm": round(radius_nm, 2),
    "stall_speed_clean": round(vs_clean, 1),
    "stall_speed_in_turn": round(vs_turn, 1),
    "load_factor": round(max_load_factor, 2),

    # Statistics
    "max_bank_achieved": round(max_bank, 1),
    "min_bank_achieved": round(min_bank, 1),
    "max_groundspeed": round(max_gs, 1),
    "min_groundspeed": round(min_gs, 1),
    "total_time_sec": round(total_time, 1),

    # Altitude tracking (for non-level maneuvers)
    "entry_altitude_ft": round(entry_alt, 0),
    "final_altitude_ft": round(final_alt, 0),
    "min_altitude_ft": round(min_alt, 0),
    "max_altitude_ft": round(max_alt, 0),
    "altitude_loss_ft": round(alt_loss, 0),
}
```

---

## Maneuver-Specific Considerations

### Ground Reference Maneuvers (S-Turns, Turns Around a Point, Rectangular Course)
- **Perfect ground track** - Path IS the ideal geometry (circle/rectangle)
- Constant altitude (perfect execution = 0 ft loss)
- Bank varies with groundspeed (steeper downwind, shallower upwind)
- Crab angle varies to maintain ground track in crosswind
- Wings level when crossing reference features

#### S-Turns
- Entry perpendicular to reference line, wings level
- Equal-radius semicircles on each side
- Wings level at each crossing

#### Turns Around a Point
- Perfect circular ground track around reference
- Entry typically downwind at orbit radius
- Bank: max downwind (~45° limit), min upwind
- Continuous turn, no wings-level segments

#### Rectangular Course
- Four straight legs following field/road boundaries
- Four 90° turns at corners
- **Legs**: Downwind (tailwind), Base (crosswind), Upwind (headwind), Entry (crosswind)
- **Turns**: Vary bank based on groundspeed entering turn
- **Crab**: Required on crosswind legs to maintain ground track
- Steeper bank turns when entering from downwind (high GS)
- Shallower bank turns when entering from upwind (low GS)

### Steep Turns
- Constant altitude, constant bank (±5°)
- Entry and rollout on same heading
- 360° or 720° turns
- Load factor approximately 1.4G at 45° bank

### Steep Spirals
- Descending turns around a point
- Constant radius ground track
- Bank varies with wind
- Track altitude loss per turn

### Chandelles
- Climbing turn, 180° heading change
- Maximum pitch at 90° point
- Rollout to wings level at 180° point
- Entry speed at Va or below

### Lazy Eights
- Symmetrical climbing/descending turns
- 180° heading change per half
- Maximum bank at 90° and 270° points
- Altitude same at 180° as entry

### Engine-Out Glide
- Best glide speed (weight-adjusted)
- Maximum glide ratio
- Wind significantly affects glide range
- Track altitude vs distance

### Impossible Turn
- Engine failure after takeoff scenario
- Reaction time delay
- Turn back to runway analysis
- Minimum altitude for successful return

---

## Callback State Requirements

Every draw callback should include these States:

```python
# Aircraft and weight
State("aircraft-select", "value"),
State("runtime-total-weight-lb", "data"),

# Configuration
State("power-setting", "value"),
State("cg-slider", "value"),

# Environmental
State("env-oat", "value"),
State("env-altimeter", "value"),
State("env-wind-dir", "value"),
State("env-wind-speed", "value"),

# Airport (for field elevation)
State("selected-airport-id", "data"),
```

---

## Testing Checklist

Before considering a maneuver complete, verify:

- [ ] Time scrubber works and shows all data fields
- [ ] Wind causes appropriate drift/track changes
- [ ] Weight changes affect stall speeds and turn radius
- [ ] CG changes affect stall speed (forward = higher)
- [ ] Power setting affects altitude (low power = descent in turns)
- [ ] G-limit warnings appear when exceeded
- [ ] Stall margin warnings appear when inadequate
- [ ] Bank is automatically reduced for safety when needed
- [ ] Info panel shows all relevant data
- [ ] Path colors distinguish different segments
- [ ] Hover tooltips show flight data at each point
- [ ] Zero wind case produces expected geometry
- [ ] Strong wind case shows appropriate drift

---

## File Structure

```
simulation/
├── __init__.py              # Exports all simulation functions
├── base.py                  # Shared utilities (_get_best_glide_and_ratio, etc.)
├── s_turn.py                # S-Turn simulation
├── turns_around_point.py    # Turns Around a Point simulation
├── rectangular_course.py    # Rectangular Course simulation
├── steep_turn.py            # Steep Turn simulation
├── steep_spiral.py          # Steep Spiral simulation
├── chandelle.py             # Chandelle simulation
├── lazy_eight.py            # Lazy Eight simulation
├── glide_path.py            # Glide path to target
├── engine_out.py            # Engine-out glide simulation
└── impossible_turn.py       # Impossible turn analysis
```

---

## Summary

By following this standard, every maneuver in the AeroEdge Overlay Tool will:

1. **Be physics-accurate** - Using real aerodynamic relationships
2. **Be environmentally aware** - Accounting for wind, temperature, pressure
3. **Be weight-conscious** - Adjusting performance for actual loading
4. **Be CG-aware** - Reflecting stability and stall characteristic changes
5. **Be power-integrated** - Showing altitude management effects
6. **Be safe** - Warning about G-limits and stall margins
7. **Be informative** - Providing comprehensive flight data
8. **Be interactive** - Allowing time-based exploration of the maneuver

This makes the tool invaluable for:
- Flight training visualization
- Maneuver planning and practice
- Understanding energy management
- Learning wind correction techniques
- Appreciating weight and balance effects
