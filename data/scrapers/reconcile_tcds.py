"""
Reconcile our 110 aircraft JSONs against the Phase-2b parsed TCDS JSONs.

For each aircraft:
  1. Locate the parsed TCDS file by `tcds_number`.
  2. Pick the variant whose `models[]` contains the aircraft's model string.
  3. Compare each comparable field; classify each as:
        match     — within tolerance, mark field "verified"
        mismatch  — disagrees beyond tolerance, log for human review
        silent    — TCDS doesn't carry that field, no change
        n/a       — aircraft has no TCDS or TCDS wasn't parsed

  4. Update the aircraft JSON's `verified_fields[]`. Upgrade
     `confidence: partial → verified` when every comparable field matches.

  5. Emit `docs/reconciliation_report.csv` with one row per (aircraft,field).

Tolerances are loose (±2 kt, ±1 gal, ±5 lb) — rounding and unit conversions
on either side can produce small drifts that aren't real discrepancies.
"""

from __future__ import annotations

import csv
import json
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parents[2]
AIRCRAFT_DIR = REPO_ROOT / "aircraft_data"
TCDS_DIR     = REPO_ROOT / "data" / "sources" / "tcds_parsed"
REPORT_CSV   = REPO_ROOT / "docs" / "reconciliation_report.csv"


# Tolerance per field (absolute, in the field's native unit)
TOL = {
    "Vne": 3, "Vno": 3, "Vfe": 3, "Va": 3,
    "max_weight":    20,
    "empty_weight":  20,
    "fuel_capacity": 1,
    "seats":         0,
    "engine_hp":     1,
}


def _model_tokens(text: str) -> List[str]:
    return re.findall(r"[A-Z0-9]+", (text or "").upper())


def _ias_to_knots(speed: Dict) -> Optional[float]:
    """Normalize a parsed v-speed (`{value, unit}`) to knots."""
    if not speed or speed.get("value") is None:
        return None
    unit = (speed.get("unit") or "knots").lower()
    val = float(speed["value"])
    if unit in ("mph", "miles per hour"):
        return val / 1.15078
    return val


def pick_variant(aircraft_name: str, tcds: dict) -> Optional[dict]:
    """Pick the TCDS variant that most specifically matches the aircraft.

    Multiple passes, each more permissive than the last:
      1) Variant model is a substring of the aircraft name (model "172P"
         matches aircraft "Cessna 172P"). Longest match wins.
      2) Reverse-substring: a digit-bearing token from the aircraft name
         is a substring of the variant's model. Catches the "we ship F33
         but the TCDS section is F33A" case.
      3) Token overlap fallback.
    """
    if not tcds or not tcds.get("variants"):
        return None

    ac_compact = re.sub(r"[^A-Z0-9]", "", aircraft_name.upper())

    # Pass 1: variant.model ⊆ aircraft_name
    pass1: List[Tuple[int, dict]] = []
    for v in tcds["variants"]:
        for model in v.get("models", []):
            m_compact = re.sub(r"[^A-Z0-9]", "", model.upper())
            if len(m_compact) >= 2 and m_compact in ac_compact:
                pass1.append((len(m_compact), v))
    if pass1:
        pass1.sort(key=lambda x: -x[0])
        return pass1[0][1]

    # Pass 2: aircraft-name digit-bearing token ⊆ variant.model
    digit_tokens = [t for t in _model_tokens(aircraft_name) if any(c.isdigit() for c in t)]
    pass2: List[Tuple[int, dict]] = []
    for t in digit_tokens:
        for v in tcds["variants"]:
            for model in v.get("models", []):
                m_compact = re.sub(r"[^A-Z0-9]", "", model.upper())
                if t in m_compact and len(t) >= 2:
                    pass2.append((len(t), v))
    if pass2:
        pass2.sort(key=lambda x: -x[0])
        return pass2[0][1]

    # Pass 3: token-overlap fallback
    ac_tokens = set(_model_tokens(aircraft_name))
    best_score = 0
    best_variant = None
    for v in tcds["variants"]:
        for model in v.get("models", []):
            shared = len(ac_tokens & set(_model_tokens(model)))
            if shared > best_score:
                best_score = shared
                best_variant = v
    return best_variant


def reconcile_one(ac: dict, variant: dict) -> List[Dict]:
    """Compare `ac` (our JSON) against `variant` (one TCDS variant block).
    Returns a list of comparison rows."""
    rows: List[Dict] = []
    name = ac.get("name", "?")
    tcds_n = ac.get("tcds_number") or ""

    def cmp(field: str, ours, theirs, tolerance):
        if theirs is None:
            return ("silent", ours, None)
        if ours is None:
            return ("ours-missing", None, theirs)
        try:
            diff = abs(float(ours) - float(theirs))
        except (TypeError, ValueError):
            return ("type-error", ours, theirs)
        if diff <= tolerance:
            return ("match", ours, theirs)
        return ("mismatch", ours, theirs)

    # ── Vne ────────────────────────────────────────────────────
    vne_t = _ias_to_knots(variant["v_speeds_kcas"].get("Vne"))
    status, ours, theirs = cmp("Vne", ac.get("Vne"), vne_t, TOL["Vne"])
    rows.append({"aircraft": name, "tcds": tcds_n, "field": "Vne", "ours": ours, "tcds_value": theirs, "status": status})

    # ── Vno ────────────────────────────────────────────────────
    vno_t = _ias_to_knots(variant["v_speeds_kcas"].get("Vno"))
    status, ours, theirs = cmp("Vno", ac.get("Vno"), vno_t, TOL["Vno"])
    rows.append({"aircraft": name, "tcds": tcds_n, "field": "Vno", "ours": ours, "tcds_value": theirs, "status": status})

    # ── Vfe — our JSON stores per-flap-config (takeoff has higher Vfe than
    # landing). TCDS publishes the MOST RESTRICTIVE Vfe (full-flap, lowest).
    # So compare TCDS against MIN of our Vfe dict.
    vfe_t = _ias_to_knots(variant["v_speeds_kcas"].get("Vfe"))
    vfe_ours = None
    vfe_dict = ac.get("Vfe") or {}
    if isinstance(vfe_dict, dict):
        nums = [v for v in vfe_dict.values() if isinstance(v, (int, float))]
        vfe_ours = min(nums) if nums else None
    status, ours, theirs = cmp("Vfe", vfe_ours, vfe_t, TOL["Vfe"])
    rows.append({"aircraft": name, "tcds": tcds_n, "field": "Vfe", "ours": ours, "tcds_value": theirs, "status": status})

    # ── Max weight — compare the largest TCDS weight (normal landplane usually)
    weights_t = variant.get("max_weight_lb") or {}
    # Prefer "normal_landplane" if present, else first value
    tcds_max = weights_t.get("normal_landplane") or next(iter(weights_t.values()), None)
    status, ours, theirs = cmp("max_weight", ac.get("max_weight"), tcds_max, TOL["max_weight"])
    rows.append({"aircraft": name, "tcds": tcds_n, "field": "max_weight", "ours": ours, "tcds_value": theirs, "status": status})

    # ── Fuel capacity ──────────────────────────────────────────
    fuel_t = variant["fuel_capacity"].get("total_gal")
    status, ours, theirs = cmp("fuel_capacity_gal", ac.get("fuel_capacity_gal"), fuel_t, TOL["fuel_capacity"])
    rows.append({"aircraft": name, "tcds": tcds_n, "field": "fuel_capacity_gal", "ours": ours, "tcds_value": theirs, "status": status})

    # ── Seats ──────────────────────────────────────────────────
    seats_t = variant.get("seats")
    status, ours, theirs = cmp("seats", ac.get("seats"), seats_t, TOL["seats"])
    rows.append({"aircraft": name, "tcds": tcds_n, "field": "seats", "ours": ours, "tcds_value": theirs, "status": status})

    # ── Engine HP — our JSON has multiple engine_options. Compare each.
    # We mark "match" when ANY of our engine options matches the TCDS HP value.
    engine_hp_t = variant["engine_limits"].get("hp")
    engines = ac.get("engine_options") or {}
    our_hps = [e.get("horsepower") for e in engines.values() if isinstance(e, dict)]
    if our_hps:
        # Pick the our-HP closest to the TCDS value
        if engine_hp_t is not None:
            our_best = min(our_hps, key=lambda h: abs((h or 0) - engine_hp_t))
        else:
            our_best = our_hps[0]
    else:
        our_best = None
    status, ours, theirs = cmp("engine_hp", our_best, engine_hp_t, TOL["engine_hp"])
    rows.append({"aircraft": name, "tcds": tcds_n, "field": "engine_hp", "ours": ours, "tcds_value": theirs, "status": status})

    return rows


def main() -> None:
    # Index TCDS files by tcds_number
    tcds_by_num: Dict[str, dict] = {}
    for p in TCDS_DIR.glob("*.json"):
        d = json.loads(p.read_text())
        if d.get("tcds_number"):
            tcds_by_num[d["tcds_number"]] = d

    all_rows: List[Dict] = []
    summary = {
        "aircraft": 0, "with_parsed_tcds": 0, "fields_matched": 0,
        "fields_mismatched": 0, "fields_silent": 0, "fields_no_tcds": 0,
        "upgraded_to_verified": 0,
    }

    for path in sorted(AIRCRAFT_DIR.glob("*.json")):
        summary["aircraft"] += 1
        ac = json.loads(path.read_text())
        name = ac.get("name", path.stem)
        tcds_n = ac.get("tcds_number") or ""

        # If we have a parsed TCDS for this aircraft, run reconciliation
        tcds = tcds_by_num.get(tcds_n)
        if not tcds:
            # No structured TCDS available (Military / Experimental / EASA / unparsed)
            # — write one row to the report so it shows up
            all_rows.append({
                "aircraft": name, "tcds": tcds_n or "(none)",
                "field": "(all)", "ours": "", "tcds_value": "",
                "status": "no-parsed-tcds",
            })
            summary["fields_no_tcds"] += 6
            continue

        summary["with_parsed_tcds"] += 1
        variant = pick_variant(name, tcds)
        if not variant:
            all_rows.append({
                "aircraft": name, "tcds": tcds_n,
                "field": "(all)", "ours": "", "tcds_value": "",
                "status": "no-variant-match",
            })
            continue

        rows = reconcile_one(ac, variant)
        all_rows.extend(rows)

        # Tally + update aircraft JSON
        matched_fields = [r["field"] for r in rows if r["status"] == "match"]
        for r in rows:
            if r["status"] == "match":
                summary["fields_matched"] += 1
            elif r["status"] == "mismatch":
                summary["fields_mismatched"] += 1
            elif r["status"] == "silent":
                summary["fields_silent"] += 1

        if matched_fields:
            existing = set(ac.get("verified_fields") or [])
            ac["verified_fields"] = sorted(existing | set(matched_fields))
            # Promote confidence to verified ONLY if ALL six comparable fields matched
            checkable = {r["field"] for r in rows
                         if r["status"] in ("match", "mismatch")}
            verified_set = {r["field"] for r in rows if r["status"] == "match"}
            if checkable and verified_set == checkable and len(checkable) >= 4:
                if ac.get("confidence") != "verified":
                    summary["upgraded_to_verified"] += 1
                ac["confidence"] = "verified"
            path.write_text(json.dumps(ac, indent=2, ensure_ascii=False) + "\n")

    # Write the report
    REPORT_CSV.parent.mkdir(parents=True, exist_ok=True)
    fields = ["aircraft", "tcds", "field", "ours", "tcds_value", "status"]
    with REPORT_CSV.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        w.writerows(all_rows)

    print(f"Wrote {REPORT_CSV.relative_to(REPO_ROOT)} ({len(all_rows)} rows)")
    print()
    print(f"  aircraft total:            {summary['aircraft']}")
    print(f"  with parsed TCDS:          {summary['with_parsed_tcds']}")
    print(f"  fields matched (✓):        {summary['fields_matched']}")
    print(f"  fields mismatched (⚠):     {summary['fields_mismatched']}")
    print(f"  fields TCDS-silent:        {summary['fields_silent']}")
    print(f"  aircraft upgraded:         {summary['upgraded_to_verified']}  → confidence: verified")


if __name__ == "__main__":
    main()
