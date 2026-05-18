"""
Pydantic v2 schema for TallyAero aircraft JSON profiles.

This is the authoritative schema. Every JSON in `aircraft_data/` must validate
against `Aircraft.model_validate(...)`.

Phase 0 deliverables (per EM_DIAGRAM_EXECUTION_PLAN.md):
- Strict-but-fair validation of all 110 existing files
- D1: provenance fields (`confidence`, `sources[]`, `estimated_fields[]`)
- A non-blocking "sanity range" pass that surfaces suspect numerical values
  (e.g., aspect_ratio outside [3, 15]) as warnings — used by the triage CSV.

The schema is canonical and identical to the one that lives in
tallyaero_overlay_tools — see Shared Asset Ledger.
"""

from __future__ import annotations

from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator


# =============================================================================
# Provenance (D1 — Phase 0 hybrid-citation decision)
# =============================================================================

ConfidenceLevel = Literal["verified", "estimated", "partial"]


class Source(BaseModel):
    """A citation for a value or group of values. Required for `verified`."""

    model_config = ConfigDict(extra="forbid")

    publication: str  # e.g., "FAA TCDS A4CE Rev 28", "Cessna 172P POH (1986)"
    page: Optional[str] = None
    year: Optional[int] = Field(default=None, ge=1900, le=2100)
    retrieved: Optional[str] = None  # ISO 8601 date string
    notes: Optional[str] = None


# =============================================================================
# Nested aircraft structures
# =============================================================================


class StallSpeedTable(BaseModel):
    """Per-flap-config stall speed vs gross weight table."""

    model_config = ConfigDict(extra="forbid")

    weights: List[float] = Field(..., min_length=1)
    speeds: List[float] = Field(..., min_length=1)

    @model_validator(mode="after")
    def _check_aligned_monotonic(self):
        if len(self.weights) != len(self.speeds):
            raise ValueError(
                f"weights/speeds length mismatch: {len(self.weights)} vs {len(self.speeds)}"
            )
        if any(self.weights[i] >= self.weights[i + 1] for i in range(len(self.weights) - 1)):
            raise ValueError(f"weights must be strictly increasing: {self.weights}")
        if any(self.speeds[i] > self.speeds[i + 1] for i in range(len(self.speeds) - 1)):
            raise ValueError(f"speeds must be non-decreasing: {self.speeds}")
        return self


class GLimitPair(BaseModel):
    model_config = ConfigDict(extra="forbid")

    positive: float = Field(..., ge=0)
    negative: float = Field(..., le=0)


class VConfig(BaseModel):
    """Holds per-configuration V-speeds (Vmca/Vyse/Vxse). Twins only."""

    model_config = ConfigDict(extra="allow")  # allow undocumented config keys

    clean_up: Optional[float] = Field(default=None, gt=0)
    takeoff_up: Optional[float] = Field(default=None, gt=0)
    landing_down: Optional[float] = Field(default=None, gt=0)


class SingleEngineLimits(BaseModel):
    """Engine-out behavior. `Vmca/Vyse/Vxse` are twin-only.

    For multi-engine aircraft, Vmca and Vyse must be present (enforced in
    Aircraft.model_validator).
    """

    model_config = ConfigDict(extra="forbid")

    best_glide: float = Field(..., gt=0, description="Best-glide IAS, kt")
    best_glide_ratio: float = Field(..., gt=0, description="Glide ratio, e.g., 9.0")

    # Twins-only
    Vmca: Optional[VConfig] = None
    Vyse: Optional[VConfig] = None
    Vxse: Optional[VConfig] = None

    # Multi-engine driftdown / powered single-engine performance.
    # All optional in schema; enforced for ME aircraft via
    # Aircraft.model_validator below. Sources: published POH/AFM,
    # cited in each aircraft's sources[] array.
    service_ceiling_ft: Optional[float] = Field(
        default=None, gt=0, lt=60000,
        description="Single-engine service ceiling (FAR 23.65: SE RoC = 50 fpm).")
    rate_of_climb_sl_fpm: Optional[float] = Field(
        default=None, ge=0, lt=3000,
        description="Single-engine rate of climb at sea level, gross weight.")
    cruise_kt: Optional[float] = Field(
        default=None, gt=0, lt=600,
        description="Single-engine cruise TAS, typically 80-90% of two-engine cruise.")
    fuel_burn_gph: Optional[float] = Field(
        default=None, gt=0, lt=200,
        description="Per-engine fuel burn at SE cruise power (one engine running).")


class PowerCurve(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sea_level_max: float = Field(..., gt=0, description="HP at sea level, full throttle")
    derate_per_1000ft: float = Field(
        ..., ge=0, le=0.10, description="Linear power loss per 1000 ft (0–0.10)"
    )


class OEIPerformanceLeaf(BaseModel):
    """Engine-out performance at a (flap_config, prop_condition) leaf."""

    model_config = ConfigDict(extra="forbid")

    max_power_fraction: float = Field(..., ge=0.0, le=1.0)
    best_glide_speed_kias: float = Field(..., gt=0)
    rate_of_climb_fpm: float


class EngineOption(BaseModel):
    model_config = ConfigDict(extra="forbid")

    horsepower: float = Field(..., gt=0)
    power_curve: PowerCurve
    # OEI tree: flap_config -> prop_condition -> leaf
    oei_performance: Optional[Dict[str, Dict[str, OEIPerformanceLeaf]]] = None


class ConfigurationOptions(BaseModel):
    model_config = ConfigDict(extra="forbid")

    flaps: List[Literal["clean", "takeoff", "landing"]] = Field(..., min_length=1)


class VFE(BaseModel):
    """Flap-extended speed limits."""

    model_config = ConfigDict(extra="allow")

    takeoff: Optional[float] = Field(default=None, gt=0)
    landing: Optional[float] = Field(default=None, gt=0)


class Arcs(BaseModel):
    """ASI arc markings (kt). Each band is [lo, hi]; entries may be null when
    the value is unknown — caught by triage as an estimated_fields entry rather
    than a hard schema failure (per D1 hybrid model).
    """

    model_config = ConfigDict(extra="forbid")

    white: List[Optional[float]] = Field(..., min_length=2, max_length=2)
    green: List[Optional[float]] = Field(..., min_length=2, max_length=2)
    yellow: List[Optional[float]] = Field(..., min_length=2, max_length=2)
    red: Optional[float] = Field(default=None, gt=0)


ThrustModel = Literal[
    "piston_fixed_pitch",       # 1-blade or fixed-pitch climb/cruise prop, low T_static
    "piston_constant_speed",    # CS prop with governor — most retractables + travelers
    "turbocharged",             # turbocharged engine with CS prop (similar static thrust)
    "turboprop",                # PT6 / TPE331 etc. — different thrust curve
]


# =============================================================================
# Performance dynamics (Phase B — 2026-05-18)
# =============================================================================
# Per-aircraft "how does it actually fly" parameters that the maneuver
# simulator needs but POHs don't always publish: roll rate, bank-response
# time-constant, longitudinal speed-response time-constant, takeoff
# acceleration ratio, inter-maneuver pause time.
#
# Three-tier provenance per the maneuver audit Theme C.4:
#   poh           — hand-curated from the airframe's POH/AFM. Most reliable.
#   class_derived — computed by scripts/classify_dynamics.py from G_limits
#                   / aspect_ratio / engine_count / gear_type etc. Plausible
#                   but unverified. Default for the 95+ non-reference fleet.
#   estimated     — last-resort fallback used by core/dynamics.py when the
#                   aircraft has no block at all. Generic light-single
#                   constants.


ProvenanceKind = Literal["poh", "class_derived", "estimated"]


class PerformanceDynamics(BaseModel):
    """Per-aircraft dynamic-response constants used by the maneuver sim.

    Field ranges are deliberately wide — a Pitts S-2C rolls at 180+°/s,
    a turbocharged twin needs 3-4s to spool, etc. Cross-validator below
    enforces poh_citation when provenance="poh"."""

    model_config = ConfigDict(extra="forbid")

    roll_rate_dps: float = Field(..., gt=0, le=200,
        description="Maximum sustained roll rate (deg/s). Aerobatic singles "
                    "up to ~180; trainers ~40-50; twins ~25-35.")
    bank_response_tau_s: float = Field(..., gt=0, le=30,
        description="First-order time constant for bank-angle command response (s).")
    speed_response_tau_s: float = Field(..., gt=0, le=30,
        description="First-order time constant for airspeed response to "
                    "power/drag changes (s).")
    takeoff_accel_factor: float = Field(..., gt=0, le=1.0,
        description="Dimensionless ratio of takeoff acceleration to g, derived "
                    "from horsepower / max_weight / Vlof.")
    inter_maneuver_pause_s: float = Field(default=1.0, ge=0, le=30,
        description="Realistic pause between sequenced maneuver phases (s). "
                    "Used by the scrubber to space adjacent maneuvers.")
    provenance: ProvenanceKind = Field(...,
        description="poh = hand-curated from POH/AFM. class_derived = "
                    "computed from class heuristics. estimated = generic "
                    "fallback when no per-aircraft data exists.")
    poh_citation: Optional[str] = Field(default=None,
        description="POH page/section reference. Required when provenance='poh'.")

    @model_validator(mode="after")
    def _check_citation(self):
        if self.provenance == "poh" and not self.poh_citation:
            raise ValueError("provenance='poh' requires a non-empty poh_citation")
        return self


class PropThrustDecay(BaseModel):
    """Quadratic thrust-vs-V model parameters.

    Phase 2f added `thrust_model`: a discriminator that downstream physics
    (compute_thrust_available) uses to pick the right thrust curve.

    Realistic per-class T_static_factor values (Phase 2f):
      piston_fixed_pitch:     1.7 – 2.0  (typical: 1.85)
      piston_constant_speed:  2.3 – 2.8  (typical: 2.5)
      turbocharged:           2.4 – 2.8  (typical: 2.5)
      turboprop:              2.5 – 3.2  (typical: 3.0)
    """

    model_config = ConfigDict(extra="forbid")

    T_static_factor: float = Field(..., gt=0)
    V_max_kts: float = Field(..., gt=0)
    thrust_model: Optional[ThrustModel] = None


# =============================================================================
# Top-level aircraft model
# =============================================================================


class Aircraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Identity
    name: str = Field(..., min_length=1)
    type: Literal["single_engine", "multi_engine"]
    gear_type: Optional[Literal["fixed", "retractable"]] = None
    engine_count: int = Field(..., ge=1, le=4)

    # Aerodynamics
    wing_area: float = Field(..., gt=0, description="ft²")
    aspect_ratio: float = Field(..., gt=0)
    CD0: float = Field(..., gt=0)
    e: float = Field(..., gt=0, le=1.0, description="Oswald efficiency")

    # Configuration / limits
    configuration_options: ConfigurationOptions
    G_limits: Dict[Literal["normal", "utility", "aerobatic"], Dict[str, GLimitPair]]
    stall_speeds: Dict[str, StallSpeedTable]
    single_engine_limits: SingleEngineLimits
    engine_options: Dict[str, EngineOption] = Field(..., min_length=1)

    # Altitude / V-speeds
    max_altitude: float = Field(..., gt=0, description="ft")
    Vne: float = Field(..., gt=0, description="kt")
    Vno: float = Field(..., gt=0, description="kt")
    Vfe: VFE
    # Vx (best-angle climb) / Vy (best-rate climb) — overlay-tool fields used by
    # scripts/add_climb_speeds.py and the engine-out climb-gradient overlay.
    # Optional here because pre-Phase-2 EM Diagram archive data lacks them.
    Vx: Optional[float] = Field(None, gt=0, description="kt — best-angle climb")
    Vy: Optional[float] = Field(None, gt=0, description="kt — best-rate climb")
    # Phase 2i extended (EM Diagram v0.2.0) — original publication unit for the
    # V-speeds. When present, indicates the airframe's POH/TCDS published V-speeds
    # in this unit (e.g., warbirds in MPH or km/h). Our stored values are still
    # KIAS — this is provenance only.
    vspeeds_published_units: Optional[Literal["KIAS", "MPH", "km/h"]] = None
    CL_max: Dict[str, float]
    arcs: Arcs

    # Mass properties
    empty_weight: float = Field(..., gt=0, description="lb")
    max_weight: float = Field(..., gt=0, description="lb")
    seats: int = Field(..., ge=1, le=20)
    cg_range: List[float] = Field(..., min_length=2, max_length=2)
    fuel_capacity_gal: float = Field(..., gt=0)
    fuel_weight_per_gal: float = Field(..., gt=0)
    prop_thrust_decay: PropThrustDecay

    # Phase 0 D1 + Phase 2a provenance fields.
    # `tcds_number` / `tcds_holder` were added by Phase 2a's lookup-table
    # migration. They cite the FAA TCDS (or EASA equivalent, or "Military"
    # / "Experimental" / "ASTM F2245" for the cases where no civil TCDS exists).
    confidence: Optional[ConfidenceLevel] = None
    sources: List[Source] = Field(default_factory=list)
    estimated_fields: List[str] = Field(default_factory=list)
    # Phase 2c — fields whose values have been compared to (and matched
    # within tolerance) the cited authoritative source. Reciprocal of
    # `estimated_fields`. Filled by data/scrapers/reconcile_tcds.py.
    verified_fields: List[str] = Field(default_factory=list)
    tcds_number: Optional[str] = None
    tcds_holder: Optional[str] = None

    # Phase B — dynamic-response constants for the maneuver simulator.
    # Optional so the existing 110 files keep parsing; populated by
    # scripts/classify_dynamics.py (tier 1) + apply_poh_dynamics.py (tier 2).
    performance_dynamics: Optional[PerformanceDynamics] = None

    # ------------------------------------------------------------------
    # Cross-field invariants
    # ------------------------------------------------------------------
    @model_validator(mode="after")
    def _check_invariants(self):
        # Mass invariants
        if self.max_weight < self.empty_weight:
            raise ValueError(
                f"max_weight ({self.max_weight}) < empty_weight ({self.empty_weight})"
            )
        # CG range
        if self.cg_range[0] >= self.cg_range[1]:
            raise ValueError(f"cg_range not strictly increasing: {self.cg_range}")
        # V-speed ordering: Vne > Vno (Vno < Vne is required by 14 CFR 23)
        if self.Vne <= self.Vno:
            raise ValueError(f"Vne ({self.Vne}) must exceed Vno ({self.Vno})")
        # Vfe must be below Vne where present
        if self.Vfe.takeoff is not None and self.Vfe.takeoff >= self.Vne:
            raise ValueError(f"Vfe.takeoff ({self.Vfe.takeoff}) >= Vne ({self.Vne})")
        if self.Vfe.landing is not None and self.Vfe.landing >= self.Vne:
            raise ValueError(f"Vfe.landing ({self.Vfe.landing}) >= Vne ({self.Vne})")
        # Engine count consistency
        if self.type == "single_engine" and self.engine_count != 1:
            raise ValueError(
                f"type=single_engine but engine_count={self.engine_count}"
            )
        if self.type == "multi_engine" and self.engine_count < 2:
            raise ValueError(
                f"type=multi_engine but engine_count={self.engine_count}"
            )
        # Multi-engine must have Vmca + Vyse defined
        if self.type == "multi_engine":
            if self.single_engine_limits.Vmca is None:
                raise ValueError("multi_engine aircraft missing single_engine_limits.Vmca")
            if self.single_engine_limits.Vyse is None:
                raise ValueError("multi_engine aircraft missing single_engine_limits.Vyse")
        # NOTE: completeness of CL_max / stall_speeds across declared flap
        # configs is a Phase 2 sourcing concern. Surfaced via triage warnings
        # rather than blocking validation here.
        # CL_max should increase with flaps: clean < takeoff < landing
        if "clean" in self.CL_max and "landing" in self.CL_max:
            if self.CL_max["clean"] >= self.CL_max["landing"]:
                raise ValueError(
                    f"CL_max.clean ({self.CL_max['clean']}) must be < CL_max.landing"
                    f" ({self.CL_max['landing']})"
                )
        # Arcs ordering: only check when both endpoints are present (None = unknown).
        for band_name, band in [
            ("white", self.arcs.white),
            ("green", self.arcs.green),
            ("yellow", self.arcs.yellow),
        ]:
            lo, hi = band
            if lo is not None and hi is not None and lo >= hi:
                raise ValueError(f"arcs.{band_name} not increasing: {band}")
        # Aerobatic G_limits: positive limit should exceed normal-category positive.
        # Convention: aerobatic.<cfg>.positive == 0 means "not aerobatic-certified"
        # — Seneca/Seminole use this sentinel. Skip the comparison in that case.
        if "normal" in self.G_limits and "aerobatic" in self.G_limits:
            for cfg in ("clean",):
                if cfg in self.G_limits["normal"] and cfg in self.G_limits["aerobatic"]:
                    n = self.G_limits["normal"][cfg].positive
                    a = self.G_limits["aerobatic"][cfg].positive
                    if a == 0:
                        continue  # not aerobatic-certified, sentinel value
                    if a < n:
                        raise ValueError(
                            f"G_limits.aerobatic.{cfg}.positive ({a}) < normal ({n})"
                        )
        return self


# =============================================================================
# Sanity ranges (non-blocking, used by triage)
# =============================================================================


SANITY_RANGES = {
    "aspect_ratio": (3.0, 15.0),  # gliders excluded
    "CD0": (0.015, 0.06),  # 0.015 = clean turbojet, 0.06 = dirty bushplane
    "e": (0.60, 0.95),
    "wing_area": (50.0, 2000.0),
    "max_altitude": (1500.0, 60000.0),
    "Vne": (50.0, 700.0),
    "Vno": (40.0, 600.0),
    "empty_weight": (300.0, 200000.0),
    "max_weight": (400.0, 300000.0),
    "fuel_capacity_gal": (1.0, 5000.0),
    "fuel_weight_per_gal": (5.5, 7.5),  # Avgas ~6.0, Jet-A ~6.7
    "seats": (1, 20),
}


def find_sanity_warnings(data: dict) -> list[str]:
    """Run non-blocking sanity-range checks on a raw aircraft dict.
    Returns a list of human-readable warning strings (may be empty).
    """
    warnings: list[str] = []
    for field, (lo, hi) in SANITY_RANGES.items():
        val = data.get(field)
        if val is None:
            continue
        try:
            if val < lo or val > hi:
                warnings.append(f"{field}={val} outside expected [{lo}, {hi}]")
        except TypeError:
            warnings.append(f"{field} not numeric: {val!r}")

    # Placeholder T_static_factor: nearly all aircraft use 2.6 currently.
    ptd = data.get("prop_thrust_decay", {})
    if isinstance(ptd, dict) and ptd.get("T_static_factor") == 2.6:
        warnings.append("prop_thrust_decay.T_static_factor=2.6 (placeholder — needs Phase 2 sourcing)")

    # Estimated confidence
    confidence = data.get("confidence")
    if confidence is None:
        warnings.append("confidence not set (defaults to 'estimated')")
    elif confidence == "estimated":
        warnings.append("confidence=estimated (needs Phase 2 citation)")

    # Sources empty
    if not data.get("sources"):
        warnings.append("sources[] is empty (needs Phase 2 citation)")

    # Null arcs (data missing — flagged for Phase 2 sourcing).
    arcs = data.get("arcs", {})
    null_arc_bands = []
    if isinstance(arcs, dict):
        for band in ("white", "green", "yellow"):
            v = arcs.get(band)
            if isinstance(v, list) and any(x is None for x in v):
                null_arc_bands.append(band)
        if arcs.get("red") is None:
            null_arc_bands.append("red")
    if null_arc_bands:
        warnings.append(f"arcs missing values in {null_arc_bands} (needs Phase 2 sourcing)")

    # Flap-config completeness: every declared flap must have CL_max + stall_speeds.
    cfg_opts = data.get("configuration_options", {})
    flaps = cfg_opts.get("flaps", []) if isinstance(cfg_opts, dict) else []
    cl_max = data.get("CL_max", {}) or {}
    stall = data.get("stall_speeds", {}) or {}
    missing_cl = [f for f in flaps if f not in cl_max]
    missing_ss = [f for f in flaps if f not in stall]
    if missing_cl:
        warnings.append(f"CL_max missing entries for declared flaps: {missing_cl}")
    if missing_ss:
        warnings.append(f"stall_speeds missing entries for declared flaps: {missing_ss}")

    # Sentinel: aerobatic G_limits all-zero (means "not aerobatic-certified").
    glim = data.get("G_limits", {})
    aero = glim.get("aerobatic", {}) if isinstance(glim, dict) else {}
    if isinstance(aero, dict) and aero:
        all_zero = all(
            isinstance(cfg, dict) and cfg.get("positive") == 0
            for cfg in aero.values()
        )
        if all_zero:
            warnings.append("G_limits.aerobatic.* all zero (not aerobatic-certified sentinel)")

    return warnings


# =============================================================================
# Airport schema (Phase 3d)
# =============================================================================
# Mirrors the shape produced by tallyaero-data/scripts/build_airports.py.
# Both nested models use extra="forbid" so upstream additions are caught
# explicitly (same pattern as the Aircraft schema).


AirportType = Literal[
    "small_airport",
    "medium_airport",
    "large_airport",
    "seaplane_base",
]


class RunwayEnd(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(..., min_length=1)
    lat: Optional[float] = Field(None, ge=-90, le=90)
    lon: Optional[float] = Field(None, ge=-180, le=180)
    elevation_ft: Optional[float] = None
    heading: Optional[float] = Field(None, ge=0, le=360)
    ils: Optional[str] = None


class Runway(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(..., min_length=1)
    # length_ft/width_ft accept 0 as a NASR placeholder for runway stubs
    # (e.g., declared-only IDs with no physical surface — KORD has one).
    length_ft: Optional[float] = Field(None, ge=0)
    width_ft: Optional[float] = Field(None, ge=0)
    surface: Optional[str] = None
    lighting: Optional[str] = None
    gradient_pct: Optional[float] = None
    ends: List[RunwayEnd] = Field(default_factory=list)


class Airport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(..., min_length=1)
    name: str = Field(..., min_length=1)
    lat: float = Field(..., ge=-90, le=90)
    lon: float = Field(..., ge=-180, le=180)
    type: AirportType
    elevation_ft: Optional[float] = None
    country: Optional[str] = None
    region: Optional[str] = None
    state: Optional[str] = None
    municipality: Optional[str] = None
    icao: Optional[str] = None
    iata: Optional[str] = None
    local: Optional[str] = None
    scheduled_service: Optional[bool] = None
    wikipedia: Optional[str] = None
    runways: List[Runway] = Field(default_factory=list)


# =============================================================================
# Route planning (Phase 5)
# =============================================================================


class RouteInput(BaseModel):
    """Inputs to compute_route_segment — what the user sets in the UI."""

    model_config = ConfigDict(extra="forbid")

    origin_airport_id: str = Field(..., min_length=1)
    dest_airport_id: str = Field(..., min_length=1)
    cruise_alt_ft: float = Field(..., ge=0, le=60000)
    tas_kt: float = Field(..., gt=0, le=600)
    wind_dir_deg: float = Field(0.0, ge=0, le=360)
    wind_speed_kt: float = Field(0.0, ge=0, le=200)
    fuel_burn_gph: Optional[float] = Field(None, ge=0)


class RouteResult(BaseModel):
    """Output of one route leg — read by the summary card + map renderer."""

    model_config = ConfigDict(extra="forbid")

    origin_airport_id: str
    dest_airport_id: str
    origin_lat: float = Field(..., ge=-90, le=90)
    origin_lon: float = Field(..., ge=-180, le=180)
    dest_lat: float = Field(..., ge=-90, le=90)
    dest_lon: float = Field(..., ge=-180, le=180)
    distance_nm: float = Field(..., ge=0)
    true_course_deg: float = Field(..., ge=0, le=360)
    magnetic_course_deg: float = Field(..., ge=0, le=360)
    true_heading_deg: float = Field(..., ge=0, le=360)
    magnetic_heading_deg: float = Field(..., ge=0, le=360)
    ground_speed_kt: float = Field(..., ge=0)
    ete_min: float = Field(..., ge=0)
    fuel_burn_gal: Optional[float] = Field(None, ge=0)
    magvar_deg: float
