# Engine Out Glide: Bucket-Based Navigation v2

## Concept

Each transition point is a **bucket** - a 3D capture volume with defined dimensions.
Aircraft progresses through buckets sequentially: Current → Next → ... → Touchdown.

**Key insight**: Based on starting position (distance + altitude from touchdown), dynamically
create the optimal bucket chain. Use SPIRAL buckets when too high/far, then transition to
pattern buckets (DOWNWIND → ABEAM → BASE → FINAL → TOUCHDOWN).

## Bucket Definition

```python
@dataclass
class Bucket:
    name: str              # Unique identifier
    lat: float             # Center latitude
    lon: float             # Center longitude
    altitude_ft: float     # Target altitude AGL at bucket center

    # Capture dimensions
    height_ft: float       # Vertical tolerance (total, e.g., 500 = ±250)
    width_ft: float        # Lateral/crosstrack tolerance
    depth_ft: float        # Along-track tolerance

    # Heading
    heading_deg: float     # Expected heading when entering
    heading_tol_deg: float # Heading tolerance for capture

    # Navigation
    next_bucket: str       # Name of next bucket (None = touchdown)
```

## Standard Buckets

### 1. TOUCHDOWN_BUCKET
- **Location**: Runway threshold/touchdown point
- **Height**: 50 ft (must be close to ground)
- **Width**: 150 ft (runway width + tolerance)
- **Depth**: 200 ft (touchdown zone)
- **Heading**: Runway heading ±10°
- **Next**: None (end state)

### 2. FINAL_BUCKET
- **Location**: 0.5 nm before touchdown on extended centerline
- **Height**: 300 ft (at ~3° glidepath from touchdown)
- **Width**: 200 ft (centerline tolerance)
- **Depth**: 500 ft
- **Heading**: Runway heading ±15°
- **Next**: TOUCHDOWN_BUCKET

### 3. BASE_BUCKET
- **Location**: Pattern width offset, perpendicular to runway
- **Height**: 600 ft (pattern altitude minus some descent)
- **Width**: 500 ft
- **Depth**: 500 ft
- **Heading**: Perpendicular to runway ±30°
- **Next**: FINAL_BUCKET

### 4. ABEAM_BUCKET
- **Location**: Abeam touchdown point, pattern width offset
- **Height**: 800-1000 ft (pattern altitude)
- **Width**: 500 ft
- **Depth**: 500 ft
- **Heading**: Opposite runway heading ±20°
- **Next**: BASE_BUCKET

### 5. DOWNWIND_BUCKET
- **Location**: Start of downwind, pattern width offset
- **Height**: 800-1000 ft
- **Width**: 500 ft
- **Depth**: 1000 ft (longer to allow entry)
- **Heading**: Opposite runway heading ±30°
- **Next**: ABEAM_BUCKET

### 6. PATTERN_ENTRY_BUCKET
- **Location**: 45° entry to downwind
- **Height**: 800-1200 ft
- **Width**: 1000 ft (generous for entry)
- **Depth**: 1000 ft
- **Heading**: 45° to downwind ±45°
- **Next**: DOWNWIND_BUCKET

### 7. FINAL_INTERCEPT_BUCKET (for direct approaches)
- **Location**: Extended centerline, 1-2 nm out
- **Height**: Varies (glidepath dependent)
- **Width**: 500 ft
- **Depth**: 1000 ft
- **Heading**: Runway heading ±30°
- **Next**: FINAL_BUCKET

## Bucket Chain Selection

Based on starting position, select appropriate chain:

| Start Position | Bucket Chain |
|----------------|--------------|
| On final | FINAL → TOUCHDOWN |
| On base | BASE → FINAL → TOUCHDOWN |
| Abeam | ABEAM → BASE → FINAL → TOUCHDOWN |
| On downwind | DOWNWIND → ABEAM → BASE → FINAL → TOUCHDOWN |
| Overhead/far | PATTERN_ENTRY → DOWNWIND → ABEAM → BASE → FINAL → TOUCHDOWN |
| Extended final | FINAL_INTERCEPT → FINAL → TOUCHDOWN |

## Simulation Logic

```python
def simulate():
    # 1. Build bucket chain based on starting position
    buckets = build_bucket_chain(start_pos, touchdown_point, runway_heading)

    current_bucket_idx = 0

    while True:
        current_bucket = buckets[current_bucket_idx]

        # 2. Check if we've captured current bucket
        if is_in_bucket(state, current_bucket):
            # Advance to next bucket
            current_bucket_idx += 1
            if current_bucket_idx >= len(buckets):
                # Reached touchdown
                return SUCCESS
            continue

        # 3. Navigate toward current bucket
        desired_track = bearing_to(state.position, current_bucket.center)

        # 4. Apply flight dynamics (bank, descent, etc.)
        step_simulation(state, desired_track, ...)

        # 5. Check for ground contact
        if state.alt_agl <= 0:
            if is_in_bucket(state, touchdown_bucket):
                return SUCCESS
            else:
                return IMPACT
```

## Bucket Capture Check

```python
def is_in_bucket(state, bucket) -> bool:
    # Lateral (crosstrack) check
    xtrack_ft = cross_track_distance(state.pos, bucket.center, bucket.heading)
    if abs(xtrack_ft) > bucket.width_ft / 2:
        return False

    # Along-track check
    along_ft = along_track_distance(state.pos, bucket.center, bucket.heading)
    if abs(along_ft) > bucket.depth_ft / 2:
        return False

    # Altitude check
    alt_diff = abs(state.alt_agl - bucket.altitude_ft)
    if alt_diff > bucket.height_ft / 2:
        return False

    # Heading check
    hdg_diff = angle_diff(state.track, bucket.heading)
    if abs(hdg_diff) > bucket.heading_tol_deg:
        return False

    return True
```

## Dynamic Spiral Bucket System

### The Problem
Aircraft can start anywhere - different distances and altitudes from touchdown.
Need to "catch" the aircraft and guide it to the pattern regardless of starting position.

### Solution: Dynamic Spiral Entry Bucket

```
                    Aircraft Start
                         ★
                          \
                           \  (flies toward spiral bucket)
                            \
                             ▼
            ┌─────────────────────────────────┐
            │     SPIRAL_ENTRY_BUCKET         │  ← Positioned on spiral circumference
            │   (between aircraft & touchdown) │     between aircraft and touchdown
            └─────────────────────────────────┘
                             │
                             │ (spiral down)
                             ▼
                      ┌─────────────┐
                      │  DOWNWIND   │  ← Exit spiral when altitude allows
                      │   BUCKET    │     reaching downwind bucket
                      └─────────────┘
                             │
                             ▼
                      (normal pattern)
```

### Spiral Bucket Positioning

```python
def create_spiral_entry_bucket(aircraft_pos, aircraft_alt, touchdown_point, pattern_offset_ft):
    """
    Create a spiral entry bucket positioned to intercept the aircraft.

    The spiral is centered on the touchdown point with radius = pattern_offset_ft.
    The bucket is placed on the spiral circumference on the side facing the aircraft.
    """
    # 1. Calculate bearing from touchdown to aircraft
    bearing_to_aircraft = bearing(touchdown_point, aircraft_pos)

    # 2. Place spiral entry bucket on circumference toward aircraft
    spiral_entry_point = point_from(touchdown_point, bearing_to_aircraft, pattern_offset_ft)

    # 3. Bucket heading is tangent to spiral (perpendicular to radius)
    # For right-hand spiral: heading = bearing_to_aircraft + 90
    # For left-hand spiral: heading = bearing_to_aircraft - 90
    tangent_heading = (bearing_to_aircraft + 90) % 360  # Right-hand default

    return Bucket(
        name="SPIRAL_ENTRY",
        lat=spiral_entry_point.lat,
        lon=spiral_entry_point.lon,
        altitude_ft=aircraft_alt - 200,  # Slightly below current (descending)
        height_ft=1000,      # Large vertical capture
        width_ft=1000,       # Large lateral capture
        depth_ft=1500,       # Large along-track capture
        heading_deg=tangent_heading,
        heading_tol_deg=60,  # Very generous heading tolerance for entry
        next_bucket="SPIRAL_DESCENT"
    )
```

### Spiral Descent Logic

Once captured in SPIRAL_ENTRY, aircraft spirals down:

```python
def spiral_to_pattern(state, touchdown_point, pattern_offset_ft, pattern_alt_ft, downwind_bucket):
    """
    Spiral down until altitude allows reaching downwind bucket.
    """
    spiral_radius_ft = pattern_offset_ft
    spiral_center = touchdown_point

    while True:
        # Check: Can we reach downwind bucket from here?
        dist_to_downwind = distance(state.pos, downwind_bucket.center)
        required_gr = dist_to_downwind / (state.alt_agl - downwind_bucket.altitude_ft)

        if required_gr <= aircraft_glide_ratio:
            # YES! Exit spiral, fly to downwind bucket
            return "DOWNWIND"

        # NO - continue spiraling
        # Fly tangent to spiral circle (perpendicular to radius from center)
        bearing_from_center = bearing(spiral_center, state.pos)
        tangent_track = (bearing_from_center + 90) % 360  # Right-hand spiral

        # Apply bank for turn
        state.bank_target = calculate_bank_for_radius(spiral_radius_ft, state.tas)

        # Descend at glide ratio
        step_simulation(state, tangent_track, ...)
```

### Spiral Exit Conditions

Exit spiral to downwind when ANY of these are true:
1. **Altitude allows**: Can glide to downwind bucket with current GR
2. **Below pattern altitude**: Alt < pattern_alt + 200 ft (must exit)
3. **Completed max spirals**: Safety limit (e.g., 3 turns)

## Energy Management: Slip-First Approach

### Priority Order
1. **SLIP** (primary) - Steepen descent up to 40% GR reduction
2. **S-TURNS** (secondary) - Only if slip at 100% is insufficient

### When to Apply

```python
def manage_energy_for_bucket(state, target_bucket, glide_ratio):
    """
    Determine if energy management needed to reach target bucket.
    Apply slip first, S-turns only if necessary.
    """
    dist_to_bucket = distance(state.pos, target_bucket.center)
    alt_to_lose = state.alt_agl - target_bucket.altitude_ft

    if alt_to_lose <= 0:
        # Already at or below target altitude - no energy mgmt needed
        return slip_intensity=0, s_turns=False

    required_gr = dist_to_bucket / alt_to_lose
    min_gr_with_slip = glide_ratio * 0.6  # 40% reduction

    if required_gr >= glide_ratio:
        # On or below glidepath - no slip needed
        return slip_intensity=0, s_turns=False

    if required_gr >= min_gr_with_slip:
        # Slip can handle it
        slip_intensity = calculate_slip_intensity(glide_ratio, required_gr)
        return slip_intensity, s_turns=False

    # Need maximum slip PLUS S-turns
    return slip_intensity=1.0, s_turns=True
```

### Slip Applied at Bucket Transitions

When approaching a bucket but too high:
```python
if close_to_bucket(state, target_bucket) and too_high(state, target_bucket):
    # Apply slip to descend into bucket
    slip_intensity = calculate_slip_to_reach_bucket(state, target_bucket)
    effective_gr = glide_ratio * (1.0 - slip_intensity * 0.4)
```

## Complete Bucket Chain Selection

```python
def build_bucket_chain(start_pos, start_alt, touchdown_point, runway_heading, pattern_offset_ft, pattern_alt_ft):
    """
    Build the optimal bucket chain based on starting position.
    """
    dist_to_touchdown = distance(start_pos, touchdown_point)
    bearing_to_touchdown = bearing(start_pos, touchdown_point)

    # Calculate what's reachable with current altitude
    max_glide_dist = start_alt * glide_ratio

    # Check: Can we reach FINAL directly?
    final_bucket = create_final_bucket(touchdown_point, runway_heading)
    if can_reach_bucket(start_pos, start_alt, final_bucket):
        if is_aligned_for_final(start_pos, bearing_to_touchdown, runway_heading):
            return [final_bucket, touchdown_bucket]

    # Check: Can we reach ABEAM directly?
    abeam_bucket = create_abeam_bucket(touchdown_point, runway_heading, pattern_offset_ft, pattern_alt_ft)
    if can_reach_bucket(start_pos, start_alt, abeam_bucket):
        return [abeam_bucket, base_bucket, final_bucket, touchdown_bucket]

    # Check: Can we reach DOWNWIND directly?
    downwind_bucket = create_downwind_bucket(touchdown_point, runway_heading, pattern_offset_ft, pattern_alt_ft)
    if can_reach_bucket(start_pos, start_alt, downwind_bucket):
        return [downwind_bucket, abeam_bucket, base_bucket, final_bucket, touchdown_bucket]

    # Need SPIRAL first
    spiral_entry = create_spiral_entry_bucket(start_pos, start_alt, touchdown_point, pattern_offset_ft)
    return [spiral_entry, "SPIRAL_DESCENT", downwind_bucket, abeam_bucket, base_bucket, final_bucket, touchdown_bucket]
```

## Bucket Dimensions Summary

| Bucket | Height (ft) | Width (ft) | Depth (ft) | Heading Tol |
|--------|-------------|------------|------------|-------------|
| SPIRAL_ENTRY | 1000 | 1000 | 1500 | ±60° |
| DOWNWIND | 500 | 500 | 1000 | ±30° |
| ABEAM | 400 | 500 | 500 | ±20° |
| BASE | 400 | 500 | 500 | ±30° |
| FINAL | 300 | 200 | 500 | ±15° |
| TOUCHDOWN | 100 | 150 | 200 | ±10° |

## Benefits

1. **Clear transitions**: Each phase has explicit spatial criteria
2. **Predictable behavior**: Aircraft always navigating to well-defined target
3. **Easy debugging**: Can visualize buckets on map
4. **Flexible routing**: Different bucket chains for different scenarios
5. **"Have it made"**: Simply check if altitude/distance ratio allows reaching next bucket
6. **Dynamic spiral**: Catches aircraft from any position/altitude
7. **Slip-first energy**: Reliable altitude loss without path deviation
