# PROJECT ANALYSIS: Overlay Tools (TallyAero)

## Executive Summary

**Overlay Tools** is a web-based flight training and maneuver visualization application designed for aviation education. Built with Python (Dash/Flask) and interactive mapping (Leaflet), it allows pilots and students to simulate and visualize various aircraft maneuvers and emergency procedures on real-world maps with accurate terrain data.

| Metric | Value |
|--------|-------|
| **Total Python Code** | ~4,876 lines |
| **CSS Styling** | ~357 lines |
| **Aircraft Database** | 115+ aircraft |
| **Airport Database** | 16,128 airports |
| **Supported Maneuvers** | 11 types |

---

## Table of Contents

1. [Project Structure](#1-project-structure)
2. [Technology Stack](#2-technology-stack)
3. [Architecture Overview](#3-architecture-overview)
4. [Core Components](#4-core-components)
5. [Data Models](#5-data-models)
6. [Feature Breakdown](#6-feature-breakdown)
7. [Key Algorithms](#7-key-algorithms)
8. [External Integrations](#8-external-integrations)
9. [User Workflows](#9-user-workflows)
10. [Code Quality Assessment](#10-code-quality-assessment)
11. [Recommendations](#11-recommendations)
12. [Security Considerations](#12-security-considerations)

---

## 1. Project Structure

```
Overlay_Tools/
├── app.py                    # Main Dash application (2,335 lines)
├── utility.py                # Aviation calculations engine (2,256 lines)
├── edit_aircraft_page.py     # Aircraft data editor (285 lines)
├── requirements.txt          # Python dependencies
├── assets/
│   ├── styles.css            # Global styling (357 lines)
│   ├── logo.png              # Primary brand logo
│   └── logo2.png             # Secondary logo
├── aircraft_data/            # Aircraft performance database
│   └── [115 JSON files]      # Individual aircraft specifications
├── airports/
│   └── airports.json         # 16,128 airport records
└── __pycache__/              # Python bytecode cache
```

---

## 2. Technology Stack

### Backend
| Technology | Version | Purpose |
|------------|---------|---------|
| Python | 3.x | Core language |
| Dash | 3.0.3 | Web framework for interactive UI |
| Flask | 3.0.3 | Underlying web server |
| Gunicorn | 22.0.0 | WSGI production server |

### Frontend
| Technology | Version | Purpose |
|------------|---------|---------|
| Dash Bootstrap Components | 2.0.2 | Bootstrap styling |
| Dash Leaflet | 1.0.15 | Interactive mapping |
| Plotly | 6.0.1 | Data visualization |

### Scientific Computing
| Technology | Version | Purpose |
|------------|---------|---------|
| NumPy | 2.2.4 | Numerical computations |
| Pandas | 2.2.3 | Data manipulation |
| Geopy | 2.4.1 | Geographic calculations |

### Utilities
| Technology | Version | Purpose |
|------------|---------|---------|
| Requests | 2.32.3 | HTTP API calls |
| Kaleido | 0.2.1 | Image export |

---

## 3. Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                        PRESENTATION LAYER                        │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │                      app.py                              │    │
│  │  - Dash Layout (Sidebar + Map)                          │    │
│  │  - Callbacks (User Interaction)                         │    │
│  │  - State Management (dcc.Store)                         │    │
│  └─────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│                        BUSINESS LOGIC LAYER                      │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │                     utility.py                           │    │
│  │  - Aerodynamic Calculations                             │    │
│  │  - Flight Path Simulations                              │    │
│  │  - Wind/Weather Computations                            │    │
│  │  - Performance Envelope Analysis                        │    │
│  └─────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│                          DATA LAYER                              │
│  ┌──────────────────┐  ┌──────────────────┐  ┌──────────────┐   │
│  │  aircraft_data/  │  │    airports/     │  │ Open-Meteo   │   │
│  │  (115 JSON)      │  │  airports.json   │  │ Elevation API│   │
│  └──────────────────┘  └──────────────────┘  └──────────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

### Design Pattern: Callback-Driven Architecture

The application uses Dash's reactive callback system where:
- User interactions trigger callbacks
- Callbacks update state stores
- State changes propagate to dependent components
- Map visualization updates automatically

---

## 4. Core Components

### 4.1 app.py - Main Application

**Responsibilities:**
- Application initialization and configuration
- Complete UI layout definition
- All user interaction callbacks
- Map interaction and drawing logic

**Key Sections:**

| Function/Section | Lines | Purpose |
|------------------|-------|---------|
| Data Loading | ~50 | Load aircraft and airport databases |
| Layout Definition | ~800 | UI structure and components |
| Maneuver Layouts | ~400 | Parameter forms for each maneuver |
| Callbacks | ~1,000 | Event handlers and state updates |

**Maneuver Layout Functions:**
- `impossible_turn_layout()` - Engine failure on takeoff
- `poweroff180_layout()` - Power-off approach
- `engineout_layout()` - Engine-out glide
- `steep_turn_layout()` - Steep turn demonstration
- `chandelle_layout()` - Chandelle maneuver
- `lazy8_layout()` - Lazy eight
- `steep_spiral_layout()` - Spiral descent
- `sturns_layout()` - S-turns across a line
- `turns_point_layout()` - Turns around a point
- `rect_course_layout()` - Rectangular course
- `pylons_layout()` - Eights on pylons

### 4.2 utility.py - Calculation Engine

**Responsibilities:**
- All aerodynamic computations
- Flight path simulation algorithms
- Geographic and wind calculations
- Performance data extraction

**Function Categories:**

#### Atmospheric Calculations
| Function | Purpose |
|----------|---------|
| `compute_density_altitude()` | DA from OAT and pressure altitude |
| `compute_pressure_altitude()` | Pressure alt from indicated alt |
| `compute_air_density()` | Air density at altitude |
| `adjust_glide_ratio_for_density()` | Non-standard atmosphere adjustment |

#### Speed Conversions
| Function | Purpose |
|----------|---------|
| `compute_true_airspeed()` | IAS to TAS conversion |
| `knots_to_fps()` / `fps_to_knots()` | Speed unit conversions |
| `fpm_to_fps()` | Vertical speed conversion |

#### Aerodynamic Calculations
| Function | Purpose |
|----------|---------|
| `compute_glide_ratio()` | Adjusted for configuration |
| `compute_descent_angle_deg()` | From glide ratio |
| `compute_turn_radius()` | From speed and bank |
| `compute_required_bank()` | Bank for given radius |
| `compute_load_factor()` | G-load from bank angle |
| `compute_stall_speed()` | At given load factor |

#### Simulation Functions
| Function | Purpose |
|----------|---------|
| `simulate_impossible_turn()` | Engine failure recovery path |
| `simulate_glide_path_to_target()` | Power-off 180 simulation |
| `simulate_engineout_glide()` | Engine-out descent |
| `simulate_steep_turn()` | Steep turn visualization |

#### Helper Functions (prefixed with `_`)
- `_wrap_360()` - Normalize angles
- `_angle_diff_deg()` - Shortest angle difference
- `_local_xy_ft()` - Lat/lon to local coordinates
- `_canon_flap_config()` - Normalize flap settings
- `_weight_adjust_speed_kias()` - Weight-adjusted speeds

### 4.3 edit_aircraft_page.py - Data Editor

**Purpose:** Administrative interface for aircraft database management

**Features:**
- Aircraft search and selection
- Property editing form
- Default templates by aircraft type
- Configuration management (flaps, G-limits, stall speeds)
- JSON export/save functionality

### 4.4 styles.css - Frontend Styling

**Design System:**

```css
/* Color Palette */
--primary-blue: #00A6FB
--primary-orange: #FF4B00
--dark-text: #1b1e23
--light-bg: #f7f9fc
```

**Layout:**
- Resizable sidebar (260-600px, default 360px)
- Flexible map column
- Mobile breakpoint at 768px

---

## 5. Data Models

### 5.1 Aircraft Data Schema

```json
{
  "name": "Aircraft Name",
  "type": "single_engine | multi_engine | aerobatic",
  "engine_count": 1,

  "aerodynamics": {
    "wing_area": 174.0,
    "aspect_ratio": 7.3,
    "CD0": 0.027,
    "e": 0.81,
    "CL_max": { "clean": 1.4, "takeoff": 1.6, "landing": 1.8 }
  },

  "configuration_options": {
    "flaps": ["clean", "takeoff", "landing"]
  },

  "G_limits": {
    "normal": { "clean": { "positive": 3.8, "negative": -1.5 } }
  },

  "stall_speeds": {
    "clean": { "weights": [1800, 2100, 2300], "speeds": [45, 48, 51] }
  },

  "single_engine_limits": {
    "best_glide": 65,
    "best_glide_ratio": 9.0
  },

  "engine_options": {
    "Engine Name": {
      "horsepower": 150,
      "power_curve": { "sea_level_max": 150, "derate_per_1000ft": 0.03 }
    }
  },

  "speeds": {
    "Vne": 160,
    "Vno": 128,
    "Vfe": { "takeoff": 110, "landing": 85 }
  },

  "weight_balance": {
    "empty_weight": 1400,
    "max_weight": 2300,
    "cg_range": [35.01, 47.3],
    "fuel_capacity_gal": 43,
    "fuel_weight_per_gal": 6.0
  }
}
```

### 5.2 Airport Data Schema

```json
{
  "id": "KORD",
  "name": "Chicago O'Hare International Airport",
  "lat": 41.9742,
  "lon": -87.9073,
  "elevation_ft": 682
}
```

### 5.3 UI State Management

| Store ID | Purpose |
|----------|---------|
| `runtime-total-weight-lb` | Current calculated weight |
| `point-store` (pattern-matched) | Click point coordinates by maneuver |
| `active-click-target` | Current click handler registration |
| `selected-airport-id` | Selected airport for reference |

---

## 6. Feature Breakdown

### 6.1 Supported Maneuvers

| Maneuver | Description | Key Parameters |
|----------|-------------|----------------|
| **Impossible Turn** | Engine failure on upwind | Reaction delay, turn direction |
| **Power-Off 180** | Approach without power | Pattern direction, touchdown point |
| **Engine-Out Glide** | Multi-engine failure | Glide configuration, target |
| **Steep Turns** | Up to 60° bank | Bank angle, turn sequence |
| **Chandelle** | Steep climbing turn | Entry heading, bank angle |
| **Lazy Eight** | Climbing/descending turns | Entry heading, altitude |
| **Steep Spiral** | Vertical spiral descent | Turn count, bank angle |
| **S-Turns** | Cross a reference line | Arc pairs, entry heading |
| **Turns Around a Point** | Pivotal altitude | Ground speed, turn direction |
| **Rectangular Course** | Box pattern | Entry altitude |
| **Eights on Pylons** | Figure-8 around markers | Pylon positions |

### 6.2 Aircraft Configuration

- **Weight & Balance:** Empty weight + occupants + fuel + baggage
- **Environmental:** Temperature (OAT), wind direction/speed, altimeter setting
- **Aircraft Config:** Flap setting, propeller condition, gear position

### 6.3 Visualization Features

- Interactive Leaflet map with OpenStreetMap tiles
- Path polylines showing flight trajectory
- Color-coded markers (start, touchdown, impact)
- Hover tooltips with telemetry data
- Automatic bounds fitting

---

## 7. Key Algorithms

### 7.1 Glide Path Simulation

```
1. Initialize at start position/altitude/heading
2. Apply energy bleed distance (speed transition)
3. Time-step simulation loop:
   a. Calculate wind components
   b. Compute descent rate from glide ratio
   c. Update position using TAS + wind
   d. Check for terrain impact
   e. Adjust heading toward target
4. Continue until landing or impact
5. Return path and hover data
```

### 7.2 Impossible Turn Algorithm

```
1. Apply reaction delay (straight flight)
2. Initiate turn toward opposite runway
3. Gradually increase bank to commanded angle
4. Monitor for runway alignment
5. Roll out when aligned
6. Continue descent to landing
7. Binary search option for minimum safe altitude
```

### 7.3 Wind Integration

```
Wind_N = wind_speed * cos(wind_direction)
Wind_E = wind_speed * sin(wind_direction)
Ground_Speed = sqrt((TAS_N + Wind_N)² + (TAS_E + Wind_E)²)
Ground_Track = atan2(TAS_E + Wind_E, TAS_N + Wind_N)
```

---

## 8. External Integrations

### 8.1 Open-Meteo Elevation API

- **Endpoint:** `https://api.open-meteo.com/v1/elevation`
- **Purpose:** Real-time terrain elevation lookup
- **Usage:** Called when user clicks on map
- **Fallback:** Uses airport elevation if API fails

### 8.2 OpenStreetMap (via Leaflet)

- **Usage:** Base map tiles
- **Features:** Pan, zoom, click detection

---

## 9. User Workflows

### Primary Workflow

```
1. Select Aircraft → Engine auto-populated
        ↓
2. Configure Weight → Fuel, occupants, baggage
        ↓
3. Set Environment → Wind, temperature, altimeter
        ↓
4. Choose Maneuver → Parameters form appears
        ↓
5. Set Points on Map → Click to place markers
        ↓
6. Draw Maneuver → Simulation runs, path displayed
        ↓
7. Analyze Results → Hover for telemetry data
```

### Callback Flow

```
Aircraft Selection
    ├── → Update Engine Options
    ├── → Update Fuel Capacity
    ├── → Update CG Range
    └── → Recalculate Weight

Map Click
    ├── → Fetch Elevation (API)
    ├── → Store Point Coordinates
    └── → Draw Marker

Draw Button
    ├── → Run Simulation
    ├── → Generate Path Points
    ├── → Create Hover Data
    └── → Update Map Layer
```

---

## 10. Code Quality Assessment

### Strengths

| Aspect | Assessment |
|--------|------------|
| **Separation of Concerns** | Clean split between UI (app.py) and logic (utility.py) |
| **Comprehensive Data** | 115+ real aircraft with detailed specs |
| **Documentation** | Functions have clear naming conventions |
| **Error Handling** | Graceful fallbacks for missing data |
| **Responsive Design** | Mobile-friendly CSS |

### Areas for Improvement

| Issue | Impact | Recommendation |
|-------|--------|----------------|
| **Large Files** | app.py is 2,335 lines | Split into modules by feature |
| **No Type Hints** | Reduced IDE support | Add Python type annotations |
| **Limited Tests** | No test files found | Add unit tests for calculations |
| **Hardcoded Values** | Some magic numbers | Extract to configuration |
| **No Logging** | Debugging difficulty | Add structured logging |

### Code Metrics

| File | Lines | Functions | Complexity |
|------|-------|-----------|------------|
| app.py | 2,335 | ~50 | High |
| utility.py | 2,256 | ~45 | Medium |
| edit_aircraft_page.py | 285 | ~10 | Low |
| styles.css | 357 | N/A | Low |

---

## 11. Recommendations

### High Priority

#### 1. Code Organization
**Current:** Monolithic files (app.py ~2,300 lines)
**Recommendation:** Split into feature modules

```
app/
├── __init__.py
├── main.py              # App initialization
├── layouts/
│   ├── __init__.py
│   ├── sidebar.py       # Sidebar components
│   ├── maneuvers/       # One file per maneuver
│   │   ├── impossible_turn.py
│   │   ├── poweroff180.py
│   │   └── ...
│   └── map.py           # Map components
├── callbacks/
│   ├── __init__.py
│   ├── aircraft.py      # Aircraft selection
│   ├── weight.py        # Weight calculations
│   ├── drawing.py       # Map drawing
│   └── ...
└── utils/
    └── state.py         # State management helpers
```

#### 2. Add Type Hints
```python
# Before
def compute_turn_radius(speed_knots, bank_deg):
    ...

# After
def compute_turn_radius(speed_knots: float, bank_deg: float) -> float:
    ...
```

#### 3. Implement Unit Tests
```python
# tests/test_utility.py
def test_compute_turn_radius():
    radius = compute_turn_radius(100, 45)
    assert abs(radius - expected) < 0.01
```

### Medium Priority

#### 4. Add Logging
```python
import logging
logger = logging.getLogger(__name__)

def simulate_glide_path(...):
    logger.info(f"Starting simulation: {start_point}")
    ...
```

#### 5. Configuration Management
```python
# config.py
class Config:
    API_TIMEOUT = 5.0
    DEFAULT_TIMESTEP = 0.5
    MAX_SIMULATION_TIME = 600
```

#### 6. Error Handling Enhancement
```python
class SimulationError(Exception):
    """Base exception for simulation errors"""
    pass

class TerrainImpactError(SimulationError):
    """Raised when aircraft impacts terrain"""
    pass
```

### Low Priority

#### 7. Performance Optimization
- Cache elevation lookups
- Lazy-load aircraft data
- Optimize large airport searches

#### 8. Documentation
- Add docstrings to all public functions
- Create API documentation
- Add inline comments for complex algorithms

#### 9. UI Enhancements
- Add loading indicators
- Implement undo/redo
- Save/load maneuver configurations

---

## 12. Security Considerations

### Current Implementation

| Aspect | Status | Notes |
|--------|--------|-------|
| **Input Validation** | Partial | Some numeric inputs validated |
| **API Security** | Basic | External API calls without rate limiting |
| **Data Storage** | Good | No PII collected |
| **Legal Compliance** | Good | Disclaimers and terms present |

### Recommendations

1. **Rate Limit API Calls** - Prevent abuse of elevation API
2. **Input Sanitization** - Validate all user inputs server-side
3. **Error Messages** - Avoid exposing internal details

---

## Appendix A: Aircraft Database Summary

| Category | Count | Examples |
|----------|-------|----------|
| Single-Engine Piston | 80+ | Cessna 172, Piper Cherokee |
| Multi-Engine Piston | 15+ | Piper Seneca, Beech Baron |
| Aerobatic | 10+ | Extra 300, Pitts S-2 |
| Military/Warbird | 5+ | T-6 Texan, P-51 Mustang |
| Experimental | 5+ | Various homebuilts |

## Appendix B: Callback Reference

| Callback | Trigger | Output |
|----------|---------|--------|
| `update_total_weight_display` | Weight inputs change | Weight display |
| `search_airport_database` | Search input | Airport results |
| `render_maneuver_layout` | Maneuver dropdown | Parameter form |
| `draw_impossible_turn` | Draw button click | Map layer |
| `handle_resets` | Reset button click | Cleared state |

## Appendix C: File Size Breakdown

| File | Size | Type |
|------|------|------|
| airports.json | ~2.5 MB | Data |
| logo.png | ~1.7 MB | Image |
| logo2.png | ~1.5 MB | Image |
| Aircraft JSONs | ~50 KB each | Data |

---

*Generated: January 2026*
*Project Version: Initial Release*
