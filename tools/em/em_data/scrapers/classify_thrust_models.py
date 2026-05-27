"""
Phase 2f — Classify thrust model per aircraft, set realistic T_static_factor.

For each of our 110 aircraft, infer one of:
    piston_fixed_pitch       — most small trainers (152, Cherokee 140, etc.)
    piston_constant_speed    — most retractables, twins, and ≥200 HP singles
    turbocharged             — name says "turbo" / "T210" / "421" / etc.
    turboprop                — T-6 Texan II (only one in our v1 fleet)

The default T_static_factor for each class replaces the placeholder 2.6 that
102 of 110 aircraft currently carry. Manual overrides handle ambiguous cases.

Idempotent: re-running with the same heuristics produces the same output.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

REPO_ROOT = Path(__file__).resolve().parents[2]
AIRCRAFT_DIR = REPO_ROOT / "aircraft_data"

# Per-class realistic T_static_factor defaults (lb static thrust per HP)
T_STATIC_BY_CLASS = {
    "piston_fixed_pitch":     1.85,
    "piston_constant_speed":  2.50,
    "turbocharged":           2.50,
    "turboprop":              3.00,
}

# Manual overrides — name → thrust_model. Use sparingly; the inference rules
# should handle most cases. Entries here are for aircraft where the heuristic
# would mis-classify (e.g., fixed-gear high-HP CS singles).
MANUAL_OVERRIDES = {
    # ── Turboprops ──
    "T-6A Texan II":              "turboprop",
    "T-6B Texan II":              "turboprop",

    # ── Turbocharged singles ──
    "Cessna 210":                 "turbocharged",        # T210 variants
    "Piper PA-28R-201T":          "turbocharged",        # Turbo Arrow IV

    # ── Twins with turbo'd engines ──
    "Piper PA-30 Twin Comanche":  "piston_constant_speed",
    "Piper PA-34 Seneca":         "turbocharged",        # Seneca II/III turbo
    "Piper Aztec F":              "piston_constant_speed",
    "Piper PA-44 Seminole":       "piston_constant_speed",
    "Beechcraft Baron 58":        "piston_constant_speed",
    "Cessna 310R":                "piston_constant_speed",
    "Tecnam P2006T":              "piston_constant_speed",
    "Diamond DA42-L360":          "piston_constant_speed",
    "Diamond DA42-NG":            "piston_constant_speed",
    "Diamond DA62":               "piston_constant_speed",

    # ── High-HP CS singles (fixed-gear ≥200 HP) ──
    "Cessna 182P":                "piston_constant_speed",
    "Cessna 182Q":                "piston_constant_speed",
    "Cessna 182T":                "piston_constant_speed",
    "Cessna 206":                 "piston_constant_speed",
    "Beechcraft Bonanza A36":     "piston_constant_speed",
    "Beechcraft Bonanza F33":     "piston_constant_speed",
    "Mooney M20J":                "piston_constant_speed",
    "Mooney M20K":                "turbocharged",        # M20K is the turbo Mooney
    "Pitts S-2C":                 "piston_constant_speed",
    "Cirrus SR22":                "piston_constant_speed",
    "Cirrus SR22T":               "turbocharged",
    "Cirrus SR20":                "piston_constant_speed",

    # ── Retractables that need CS ──
    "Cessna 177RG":               "piston_constant_speed",
    "Beechcraft Sierra":          "piston_constant_speed",  # C24R retractable

    # ── LSAs and small fixed-pitch trainers ──
    "Cessna 162":                 "piston_fixed_pitch",
    "Pipistrel Alpha Trainer":    "piston_fixed_pitch",
    "Pipistrel Virus":            "piston_fixed_pitch",
    "Tecnam P2002":               "piston_fixed_pitch",
    "Remos GX":                   "piston_fixed_pitch",
    "Flight Design CTLS":         "piston_fixed_pitch",
    "Evektor SportStar":          "piston_fixed_pitch",
    "Aeronca Champ":              "piston_fixed_pitch",
    "Aeronca Chief":              "piston_fixed_pitch",
    "Taylorcraft BC-12D":         "piston_fixed_pitch",
    "Ercoupe 415C":               "piston_fixed_pitch",
    "Luscombe 8A":                "piston_fixed_pitch",
    "PT-17 Stearman":             "piston_fixed_pitch",
    "Stinson 108":                "piston_fixed_pitch",
    "Pitts S-1C":                 "piston_constant_speed",  # most S-1s have CS
    "Pitts S-1C-TB":              "piston_constant_speed",

    # ── Warbirds — all CS (they had big radial engines with governors) ──
    "North American P-51D Mustang": "piston_constant_speed",
    "Supermarine Spitfire Mk IX":   "piston_constant_speed",
    "Focke-Wulf Fw 190 A-8":        "piston_constant_speed",
    "Messerschmitt Bf 109G-6":      "piston_constant_speed",
    "Vought F4U-4 Corsair":         "piston_constant_speed",
    "Grumman F6F-5 Hellcat":        "piston_constant_speed",
    "Mitsubishi A6M5 Zero":         "piston_constant_speed",
    "Kawanishi N1K2-J Shiden-Kai":  "piston_constant_speed",
    "Yakovlev Yak-3":               "piston_constant_speed",

    # ── Aerobatic CS ──
    "CAP 232":                    "piston_constant_speed",
    "Sukhoi Su-26":               "piston_constant_speed",
    "Zivko Edge 540":             "piston_constant_speed",
    "Extra 300":                  "piston_constant_speed",
    "Extra 300L":                 "piston_constant_speed",
    "Extra 330SC":                "piston_constant_speed",
    "Extra NG":                   "piston_constant_speed",
    "GameBird GB1":               "piston_constant_speed",
    "MX Aircraft MXS":            "piston_constant_speed",
}


def infer_thrust_model(ac: dict) -> str:
    """Default heuristic for aircraft not in MANUAL_OVERRIDES."""
    name = ac.get("name", "").lower()

    # Explicit name hints
    if any(k in name for k in ("texan", "tbm", "pc-12", "king air")):
        return "turboprop"
    if "turbo" in name or "t210" in name or "210t" in name:
        return "turbocharged"

    is_twin = ac.get("engine_count", 1) >= 2
    gear = ac.get("gear_type") or ""
    engines = (ac.get("engine_options") or {}).values()
    max_hp = max((e.get("horsepower", 0) for e in engines), default=0)

    if is_twin:
        return "piston_constant_speed"
    if gear == "retractable":
        return "piston_constant_speed"
    if max_hp >= 200:
        return "piston_constant_speed"
    return "piston_fixed_pitch"


def main() -> None:
    summary = {k: 0 for k in T_STATIC_BY_CLASS}
    summary["unchanged_factor"] = 0
    updated = 0
    classified_via_manual = 0

    for path in sorted(AIRCRAFT_DIR.glob("*.json")):
        ac = json.loads(path.read_text())
        name = ac.get("name", path.stem)

        # Resolve thrust model
        if name in MANUAL_OVERRIDES:
            tm = MANUAL_OVERRIDES[name]
            classified_via_manual += 1
        else:
            tm = infer_thrust_model(ac)
        summary[tm] = summary.get(tm, 0) + 1

        # Update PropThrustDecay
        ptd = ac.get("prop_thrust_decay") or {}
        new_factor = T_STATIC_BY_CLASS[tm]
        if ptd.get("T_static_factor") != new_factor or ptd.get("thrust_model") != tm:
            ptd["T_static_factor"] = new_factor
            ptd["thrust_model"] = tm
            ac["prop_thrust_decay"] = ptd
            path.write_text(json.dumps(ac, indent=2, ensure_ascii=False) + "\n")
            updated += 1
        else:
            summary["unchanged_factor"] += 1

    print(f"Phase 2f classification complete")
    print(f"  via MANUAL_OVERRIDES: {classified_via_manual}")
    print(f"  via heuristic:        {110 - classified_via_manual}")
    print(f"  files updated:        {updated}")
    print()
    print(f"Thrust-model breakdown:")
    for tm, n in sorted(summary.items(), key=lambda x: -x[1] if x[0] != 'unchanged_factor' else 999):
        if tm == "unchanged_factor":
            continue
        print(f"  {tm:<26} {n}")
    print()
    print(f"T_static_factor distribution:")
    for tm, factor in T_STATIC_BY_CLASS.items():
        print(f"  {tm:<26} → {factor}")


if __name__ == "__main__":
    main()
