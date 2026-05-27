"""
TCDS lookup table builder — Phase 2a.

For each of our 110 aircraft JSONs, find the FAA TCDS (Type Certificate Data
Sheet) that covers it. For non-FAA aircraft (warbirds, foreign-cert, homebuilts)
fall back to a manual-override table that points at EASA TCDS, military
manuals, or builder docs.

Outputs:
    docs/tcds_mapping.csv       — human-reviewable mapping
    docs/tcds_mapping.json      — machine-readable, consumed by the
                                  apply_tcds_mapping migration script
"""

from __future__ import annotations

import csv
import json
import re
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parents[2]
AIRCRAFT_DIR = REPO_ROOT / "aircraft_data"
TCDS_JSON = Path(
    "/Users/nicholaslen/Desktop/tallyaero/website/.research-cache/normalized/tcds.json"
)
OUT_CSV = REPO_ROOT / "docs" / "tcds_mapping.csv"
OUT_JSON = REPO_ROOT / "docs" / "tcds_mapping.json"


# ──────────────────────────────────────────────────────────────────────
# Manual overrides — last word for aircraft the fuzzy matcher can't pin.
# Each entry is (tcds_number, holder, source_publication, notes).
#
# Sources used:
#   - FAA TCDS historical records (drs.faa.gov)
#   - EASA Type Certificates (easa.europa.eu/document-library/type-certificates)
#   - U.S. Navy / USAF Naval Aviation Pilot's Manual / NATOPS / Tech Order
#   - Van's Aircraft builder documentation (vansaircraft.com)
#   - Manufacturer official sites for current-production foreign LSA
# ──────────────────────────────────────────────────────────────────────
MANUAL_OVERRIDES: Dict[str, Dict[str, str]] = {
    # ── Vintage US singles (FAA historical TCDS, hard to match by name) ──
    "Aeronca Champ":               {"tcds": "A-759", "holder": "AERONCA AIRCRAFT CORP",
                                    "publication": "FAA TCDS A-759 (Aeronca 7-series)"},
    "Aeronca Chief":               {"tcds": "A-781", "holder": "AERONCA AIRCRAFT CORP",
                                    "publication": "FAA TCDS A-781 (Aeronca 11-series)"},
    "Ercoupe 415C":                {"tcds": "A-718", "holder": "ERCO/UNIVAIR",
                                    "publication": "FAA TCDS A-718 (Erco / Forney / Alon / Mooney M-10)"},
    "Stinson 108":                 {"tcds": "A-767", "holder": "CONSOLIDATED VULTEE AIRCRAFT (STINSON DIV)",
                                    "publication": "FAA TCDS A-767 (Stinson 108 series)"},
    "PT-17 Stearman":              {"tcds": "A-743", "holder": "BOEING/STEARMAN",
                                    "publication": "FAA TCDS A-743 (Boeing E75/A75N1/PT-17/PT-13)"},
    "Taylorcraft BC-12D":          {"tcds": "A-696", "holder": "TAYLORCRAFT AVIATION",
                                    "publication": "FAA TCDS A-696 (Taylorcraft BC/BC-12)"},

    # ── Modern Beechcraft Bonanza family ──
    # The Bonanza 36-series (A36) is under TCDS 3A21, F33-series is A-777.
    # Multiple Musketeer/Sport variants share TCDS A12CE.
    # Modern Bonanza F33/A36/V35 lineage is on 3A15.
    # (A-777 is the older 35-series V-tail, NOT the F33/A36 we ship.)
    "Beechcraft Bonanza A36":      {"tcds": "3A15", "holder": "TEXTRON AVIATION INC.",
                                    "publication": "FAA TCDS 3A15 (Beechcraft A36/B36TC Bonanza)"},
    "Beechcraft Bonanza F33":      {"tcds": "3A15", "holder": "TEXTRON AVIATION INC.",
                                    "publication": "FAA TCDS 3A15 (Beechcraft F33/F33A Bonanza)"},
    "Beechcraft Musketeer":        {"tcds": "A12CE", "holder": "TEXTRON AVIATION INC.",
                                    "publication": "FAA TCDS A12CE (Beechcraft 19/23/24 Sport/Musketeer)"},
    "Beechcraft Sierra":           {"tcds": "A12CE", "holder": "TEXTRON AVIATION INC.",
                                    "publication": "FAA TCDS A12CE Rev (Beechcraft C24R Sierra)"},
    "Beechcraft Sundowner":        {"tcds": "A12CE", "holder": "TEXTRON AVIATION INC.",
                                    "publication": "FAA TCDS A12CE Rev (Beechcraft C23 Sundowner)"},

    # ── Cessna 162 (Skycatcher LSA, certified under ASTM/SLSA) + 210 ──
    "Cessna 162":                  {"tcds": "n/a",   "holder": "CESSNA / TEXTRON AVIATION",
                                    "publication": "ASTM F2245 (LSA) + Cessna 162 POH (2010)"},
    "Cessna 210":                  {"tcds": "3A21",  "holder": "TEXTRON AVIATION INC.",
                                    "publication": "FAA TCDS 3A21 (Cessna 205/206/207/210)"},

    # ── Mooney M20 series ──
    "Mooney M20J":                 {"tcds": "2A3",   "holder": "MOONEY INTERNATIONAL CORP.",
                                    "publication": "FAA TCDS 2A3 (Mooney M20-series)"},
    "Mooney M20K":                 {"tcds": "2A3",   "holder": "MOONEY INTERNATIONAL CORP.",
                                    "publication": "FAA TCDS 2A3 (Mooney M20K Encore/Bravo)"},

    # ── Piper PA-23/PA-28/PA-30/PA-32/PA-34/PA-44 series ──
    "Piper Aztec F":               {"tcds": "1A10",  "holder": "PIPER AIRCRAFT INC.",
                                    "publication": "FAA TCDS 1A10 (Piper PA-23 Apache/Aztec)"},
    "Piper PA-30 Twin Comanche":   {"tcds": "A1EA",  "holder": "PIPER AIRCRAFT INC.",
                                    "publication": "FAA TCDS A1EA (Piper PA-30/PA-39 Twin Comanche)"},
    "Piper PA-32-260":             {"tcds": "A3SO",  "holder": "PIPER AIRCRAFT INC.",
                                    "publication": "FAA TCDS A3SO (Piper PA-32 Cherokee Six)"},
    "Piper PA-34 Seneca":          {"tcds": "A7SO",  "holder": "PIPER AIRCRAFT INC.",
                                    "publication": "FAA TCDS A7SO (Piper PA-34 Seneca)"},
    "Piper PA-44 Seminole":        {"tcds": "A19SO", "holder": "PIPER AIRCRAFT INC.",
                                    "publication": "FAA TCDS A19SO (Piper PA-44 Seminole)"},

    # ── Diamond ──
    "Diamond DA40-180":            {"tcds": "A47CE", "holder": "DIAMOND AIRCRAFT INDUSTRIES",
                                    "publication": "FAA TCDS A47CE (Diamond DA-40 series)"},
    "Diamond DA40-NG":             {"tcds": "A47CE", "holder": "DIAMOND AIRCRAFT INDUSTRIES",
                                    "publication": "FAA TCDS A47CE Rev (Diamond DA40 NG, AE300 engine)"},
    "Diamond DA42-L360":           {"tcds": "A56CE", "holder": "DIAMOND AIRCRAFT INDUSTRIES",
                                    "publication": "FAA TCDS A56CE (Diamond DA42 TwinStar)"},
    "Diamond DA42-NG":             {"tcds": "A56CE", "holder": "DIAMOND AIRCRAFT INDUSTRIES",
                                    "publication": "FAA TCDS A56CE Rev (Diamond DA42 NG)"},
    "Diamond DA62":                {"tcds": "A00010NY", "holder": "DIAMOND AIRCRAFT INDUSTRIES",
                                    "publication": "FAA TCDS A00010NY (Diamond DA62)"},

    # ── Grumman / Gulfstream AA-5 series ──
    "Grumman AA-5":                {"tcds": "A16EA", "holder": "AMERICAN AIRCRAFT CORP",
                                    "publication": "FAA TCDS A16EA (Grumman/American AA-5/AA-5A Cheetah)"},
    "Grumman AA-5B":               {"tcds": "A16EA", "holder": "AMERICAN AIRCRAFT CORP",
                                    "publication": "FAA TCDS A16EA Rev (Grumman AA-5B Tiger)"},

    # ── Maule ──
    "Maule M-7":                   {"tcds": "A6SO",  "holder": "MAULE AEROSPACE TECHNOLOGY INC.",
                                    "publication": "FAA TCDS A6SO (Maule M-4/M-5/M-6/M-7 series)"},

    # ── Pitts (aerobatic — US-certified) ──
    "Pitts S-1C":                  {"tcds": "A18SO", "holder": "AVIAT AIRCRAFT INC.",
                                    "publication": "FAA TCDS A18SO (Pitts S-1S/S-1T)"},
    "Pitts S-1C-TB":               {"tcds": "A18SO", "holder": "AVIAT AIRCRAFT INC.",
                                    "publication": "FAA TCDS A18SO (Pitts S-1 variant)"},
    "Pitts S-2C":                  {"tcds": "A21SO", "holder": "AVIAT AIRCRAFT INC.",
                                    "publication": "FAA TCDS A21SO (Pitts S-2A/S-2B/S-2C)"},

    # ── Foreign aerobatic (EASA-cert + a few historical) ──
    "CAP 232":                     {"tcds": "EASA.A.072", "holder": "MUDRY AVIATION (CAP AVIATION)",
                                    "publication": "EASA TCDS A.072 (Mudry CAP 21/231/232)"},
    "Sukhoi Su-26":                {"tcds": "n/a",  "holder": "SUKHOI DESIGN BUREAU",
                                    "publication": "Sukhoi OKB Type Specification (no FAA TCDS; sport-aerobatic)"},
    "Zivko Edge 540":              {"tcds": "n/a",  "holder": "ZIVKO AERONAUTICS INC.",
                                    "publication": "Zivko Edge 540 published spec (Experimental/Aerobatic)"},

    # ── Zlin / Robin (foreign GA — EASA TCDS) ──
    "Robin DR400":                 {"tcds": "EASA.A.075", "holder": "AVIONS PIERRE ROBIN",
                                    "publication": "EASA TCDS A.075 (Robin DR400 series)"},
    "Robin R3000":                 {"tcds": "EASA.A.057", "holder": "APEX AIRCRAFT (ROBIN)",
                                    "publication": "EASA TCDS A.057 (Robin R3000)"},
    "Zlin Savage":                 {"tcds": "n/a",  "holder": "ZLIN AVIATION s.r.o.",
                                    "publication": "Zlin Savage SLSA Spec (LAA-CZ-certified)"},
    "Zlin Z-242L":                 {"tcds": "EASA.A.030", "holder": "MORAVAN ZLIN",
                                    "publication": "EASA TCDS A.030 (Zlin Z-42/142/242 family)"},

    # ── Socata ──
    "Socata TB9":                  {"tcds": "EASA.A.157", "holder": "DAHER (SOCATA)",
                                    "publication": "EASA TCDS A.157 (Socata TB-9/TB-10/TB-20/TB-21)"},
    "Socata TB10":                 {"tcds": "EASA.A.157", "holder": "DAHER (SOCATA)",
                                    "publication": "EASA TCDS A.157 (Socata TB-10 Tobago)"},
    "Socata TB20":                 {"tcds": "EASA.A.157", "holder": "DAHER (SOCATA)",
                                    "publication": "EASA TCDS A.157 (Socata TB-20 Trinidad)"},

    # ── LSA (modern foreign light-sport, ASTM F2245-certified) ──
    "Pipistrel Alpha Trainer":     {"tcds": "ASTM F2245", "holder": "PIPISTREL d.o.o. AJDOVSCINA",
                                    "publication": "ASTM F2245 (Pipistrel Alpha Trainer SLSA)"},
    "Pipistrel Virus":             {"tcds": "ASTM F2245", "holder": "PIPISTREL d.o.o. AJDOVSCINA",
                                    "publication": "ASTM F2245 (Pipistrel Virus SW100 SLSA)"},
    "Tecnam P2002":                {"tcds": "ASTM F2245", "holder": "COSTRUZIONI AERONAUTICHE TECNAM",
                                    "publication": "ASTM F2245 (Tecnam P2002 Sierra LSA)"},
    "Tecnam P2006T":               {"tcds": "EASA.A.185", "holder": "COSTRUZIONI AERONAUTICHE TECNAM",
                                    "publication": "EASA TCDS A.185 (Tecnam P2006T light twin)"},
    "Remos GX":                    {"tcds": "ASTM F2245", "holder": "REMOS AG",
                                    "publication": "ASTM F2245 (Remos GX SLSA)"},
    "Flight Design CTLS":          {"tcds": "ASTM F2245", "holder": "FLIGHT DESIGN GmbH",
                                    "publication": "ASTM F2245 (Flight Design CTLS SLSA)"},
    "Evektor SportStar":           {"tcds": "ASTM F2245", "holder": "EVEKTOR-AEROTECHNIK A.S.",
                                    "publication": "ASTM F2245 (Evektor SportStar SLSA)"},

    # ── Homebuilt / Experimental (no TCDS — builder docs) ──
    "Van's RV-6":                  {"tcds": "Experimental", "holder": "VAN'S AIRCRAFT INC.",
                                    "publication": "Van's RV-6 Pilot's Operating Handbook"},
    "Van's RV-8":                  {"tcds": "Experimental", "holder": "VAN'S AIRCRAFT INC.",
                                    "publication": "Van's RV-8 Pilot's Operating Handbook"},
    "Van's RV-9A":                 {"tcds": "Experimental", "holder": "VAN'S AIRCRAFT INC.",
                                    "publication": "Van's RV-9A Pilot's Operating Handbook"},
    "Van's RV-10":                 {"tcds": "Experimental", "holder": "VAN'S AIRCRAFT INC.",
                                    "publication": "Van's RV-10 Pilot's Operating Handbook"},
    "Van's RV-12":                 {"tcds": "Experimental", "holder": "VAN'S AIRCRAFT INC.",
                                    "publication": "Van's RV-12 Pilot's Operating Handbook (ELSA)"},
    "Van's RV-14A":                {"tcds": "Experimental", "holder": "VAN'S AIRCRAFT INC.",
                                    "publication": "Van's RV-14/14A Pilot's Operating Handbook"},

    # ── Military trainers (US-cert with civil TCDS where applicable) ──
    "T-6A Texan II":               {"tcds": "T00012WI", "holder": "TEXTRON AVIATION (RAYTHEON AIRCRAFT)",
                                    "publication": "FAA TCDS T00012WI (Beechcraft T-6 Texan II)"},
    "T-6B Texan II":               {"tcds": "T00012WI", "holder": "TEXTRON AVIATION (RAYTHEON AIRCRAFT)",
                                    "publication": "FAA TCDS T00012WI Rev (T-6B Texan II)"},

    # ── Warbirds (no civil TCDS — military pilot manuals + Jane's) ──
    "Focke-Wulf Fw 190 A-8":       {"tcds": "Military", "holder": "FOCKE-WULF FLUGZEUGBAU GmbH",
                                    "publication": "Fw 190 A-8 Flugzeug Handbuch (Luftwaffe Pilot's Manual, 1944)"},
    "Grumman F6F-5 Hellcat":       {"tcds": "Military", "holder": "GRUMMAN AIRCRAFT ENGINEERING CORP.",
                                    "publication": "NAVAIR 01-85FB-1 F6F-5 Pilot's Handbook (US Navy, 1945)"},
    "Kawanishi N1K2-J Shiden-Kai": {"tcds": "Military", "holder": "KAWANISHI AIRCRAFT CO.",
                                    "publication": "Jane's All The World's Aircraft 1945–46 (N1K2-J Shiden-kai)"},
    "Messerschmitt Bf 109G-6":     {"tcds": "Military", "holder": "MESSERSCHMITT A.G.",
                                    "publication": "Bf 109 G-6 Flugzeug Handbuch (Luftwaffe Pilot's Manual, 1943)"},
    "Mitsubishi A6M5 Zero":        {"tcds": "Military", "holder": "MITSUBISHI HEAVY INDUSTRIES",
                                    "publication": "Jane's All The World's Aircraft 1945–46 (A6M5 Reisen)"},
    "North American P-51D Mustang": {"tcds": "Military", "holder": "NORTH AMERICAN AVIATION INC.",
                                    "publication": "AAF Manual 51-127-5 P-51D Pilot's Flight Operating Instructions (1945)"},
    "Supermarine Spitfire Mk IX":  {"tcds": "Military", "holder": "SUPERMARINE AVIATION WORKS",
                                    "publication": "Air Publication 1565 Spitfire IX Pilot's Notes (Air Ministry, 1944)"},

    # ── American Champion (Aerobat / Citabria / Decathlon / Scout) ──
    "American Champion Citabria":  {"tcds": "A-759", "holder": "AMERICAN CHAMPION AIRCRAFT CORP",
                                    "publication": "FAA TCDS A-759 (Champion/Bellanca/ACA 7-series Citabria)"},
    "American Champion Decathlon": {"tcds": "A-759", "holder": "AMERICAN CHAMPION AIRCRAFT CORP",
                                    "publication": "FAA TCDS A-759 (ACA 8KCAB Decathlon)"},
    "American Champion Scout":     {"tcds": "A-759", "holder": "AMERICAN CHAMPION AIRCRAFT CORP",
                                    "publication": "FAA TCDS A-759 (ACA 8GCBC Scout)"},

    # ── Bellanca Super Viking ──
    "Bellanca Super Viking":       {"tcds": "A00003AK", "holder": "ALEXANDRIA AIRCRAFT LLC (BELLANCA)",
                                    "publication": "FAA TCDS A00003AK (Bellanca 17-30 Super Viking)"},

    # ── Extra Aircraft (aerobatic, EASA-cert) ──
    "Extra 300":                   {"tcds": "EASA.A.034", "holder": "EXTRA FLUGZEUGPRODUKTIONS- UND VERTRIEBS-GmbH",
                                    "publication": "EASA TCDS A.034 (Extra EA-300 series)"},
    "Extra 300L":                  {"tcds": "EASA.A.034", "holder": "EXTRA FLUGZEUGPRODUKTIONS- UND VERTRIEBS-GmbH",
                                    "publication": "EASA TCDS A.034 (Extra EA-300/L)"},
    "Extra 330SC":                 {"tcds": "EASA.A.075", "holder": "EXTRA FLUGZEUGPRODUKTIONS- UND VERTRIEBS-GmbH",
                                    "publication": "EASA TCDS A.075 (Extra EA-330SC unlimited aerobatic)"},
    "Extra NG":                    {"tcds": "EASA.A.595", "holder": "EXTRA AIRCRAFT GmbH",
                                    "publication": "EASA TCDS A.595 (Extra NG)"},

    # ── GameBird GB1 (US/UK aerobatic, FAA experimental) ──
    "GameBird GB1":                {"tcds": "Experimental", "holder": "GAMECOMPOSITES LIMITED",
                                    "publication": "GameBird GB1 Pilot's Operating Handbook (UK-built, US-Experimental)"},

    # ── Luscombe 8A (vintage US trainer) ──
    "Luscombe 8A":                 {"tcds": "A-694", "holder": "LUSCOMBE AIRPLANE CORP.",
                                    "publication": "FAA TCDS A-694 (Luscombe 8 series Silvaire)"},

    # ── MX Aircraft MXS (unlimited aerobatic, Experimental) ──
    "MX Aircraft MXS":             {"tcds": "Experimental", "holder": "MX AIRCRAFT COMPANY LLC",
                                    "publication": "MXS Pilot's Operating Handbook (FAA Experimental Exhibition)"},
    "Vought F4U-4 Corsair":        {"tcds": "Military", "holder": "VOUGHT-SIKORSKY AIRCRAFT",
                                    "publication": "NAVAIR 01-45HC-1 F4U-4 Pilot's Handbook (US Navy)"},
    "Yakovlev Yak-3":              {"tcds": "Military", "holder": "YAKOVLEV DESIGN BUREAU",
                                    "publication": "Jane's All The World's Aircraft 1945–46 (Yak-3)"},
}


# ──────────────────────────────────────────────────────────────────────
# Manufacturer normalization — collapse legal-entity variants
# (Cessna Aircraft Co. ↔ Textron Aviation Inc., etc.) to a short token.
# ──────────────────────────────────────────────────────────────────────
MFR_ALIASES = {
    "CESSNA": ["CESSNA", "TEXTRON"],
    "PIPER": ["PIPER", "PIPER AIRCRAFT", "NEW PIPER"],
    "BEECHCRAFT": ["BEECHCRAFT", "BEECH", "TEXTRON"],
    "MOONEY": ["MOONEY"],
    "DIAMOND": ["DIAMOND"],
    "CIRRUS": ["CIRRUS"],
    "AMERICAN CHAMPION": ["AMERICAN CHAMPION", "ACA", "BELLANCA", "CHAMPION"],
    "AVIAT": ["AVIAT", "PITTS"],
    "GRUMMAN": ["GRUMMAN", "AMERICAN AIRCRAFT", "AAC", "GULFSTREAM AMERICAN"],
    "BELLANCA": ["BELLANCA", "VIKING"],
    "MAULE": ["MAULE"],
    "ROBIN": ["ROBIN", "APEX"],
    "SOCATA": ["SOCATA", "AEROSPATIALE", "DAHER"],
    "TECNAM": ["TECNAM"],
    "PIPISTREL": ["PIPISTREL"],
    "AERONCA": ["AERONCA"],
    "STINSON": ["STINSON", "CONSOLIDATED"],
    "TAYLORCRAFT": ["TAYLORCRAFT"],
    "VAN'S": ["VAN'S", "VANS"],
    "ERCOUPE": ["ERCO", "ERCOUPE", "FORNEY", "ALON", "UNIVAIR"],
    "ZLIN": ["ZLIN", "MORAVAN"],
    "CAP": ["MUDRY", "CAP AVIATION"],
    "SUKHOI": ["SUKHOI"],
    "ZIVKO": ["ZIVKO"],
    "REMOS": ["REMOS"],
    "EVEKTOR": ["EVEKTOR"],
    "FLIGHT DESIGN": ["FLIGHT DESIGN"],
}


_word = re.compile(r"[A-Z0-9]+")


def _tokens(name: str) -> List[str]:
    """Uppercase alphanumeric tokens from a name."""
    return _word.findall(name.upper())


def _manufacturer_token(ac_name: str) -> Optional[str]:
    """Best guess at the canonical manufacturer key for an aircraft."""
    upper = ac_name.upper()
    for canon, aliases in MFR_ALIASES.items():
        for alias in aliases:
            if alias in upper:
                return canon
    return None


def _holder_matches(holder: str, ac_name: str) -> bool:
    """Does the TCDS holder look like the manufacturer of this aircraft?"""
    canon = _manufacturer_token(ac_name)
    if not canon:
        return False
    aliases = MFR_ALIASES.get(canon, [canon])
    holder_up = holder.upper()
    return any(alias in holder_up for alias in aliases)


def find_best_tcds(
    aircraft_name: str,
    tcds_records: Iterable[dict],
) -> Optional[Tuple[dict, str]]:
    """Score every TCDS record against the aircraft name, return best.

    Returns: (tcds_record, model_matched) or None.
    Scoring: longest-prefix model match (case-insensitive) + manufacturer
    confirmation. Ties broken by most recent revisionDate.
    """
    ac_tokens = _tokens(aircraft_name)
    if not ac_tokens:
        return None

    candidates: List[Tuple[int, str, str, dict]] = []  # (score, model, rev, record)
    for rec in tcds_records:
        if rec.get("productType") != "Aircraft":
            continue
        holder_ok = _holder_matches(rec.get("tcHolder", ""), aircraft_name)
        if not holder_ok:
            continue
        for model in rec.get("models", []):
            m_tokens = _tokens(model)
            if not m_tokens:
                continue
            # Score: count of model tokens that appear as whole tokens in the
            # aircraft name. Longer model strings (more specific) win ties.
            shared = sum(1 for t in m_tokens if t in ac_tokens)
            if shared == 0:
                continue
            # Bonus when the FULL model token-string is a contiguous substring
            # of the joined aircraft tokens (e.g. "172P" matches "Cessna 172P").
            joined_model = "".join(m_tokens)
            joined_ac = "".join(ac_tokens)
            if joined_model in joined_ac:
                shared += 2
            candidates.append((shared, model, rec.get("revisionDate", ""), rec))

    if not candidates:
        return None
    # Sort by score desc, then by revision date desc.
    candidates.sort(key=lambda x: (-x[0], x[2]), reverse=False)
    candidates.sort(key=lambda x: x[0], reverse=True)
    best = candidates[0]
    return best[3], best[1]


def build_mapping() -> List[Dict[str, str]]:
    tcds_data = json.loads(TCDS_JSON.read_text())["tcds"]
    aircraft_tcds = list(tcds_data.values())

    rows: List[Dict[str, str]] = []
    for path in sorted(AIRCRAFT_DIR.glob("*.json")):
        ac = json.loads(path.read_text())
        name = ac.get("name", path.stem.replace("_", " "))

        manual = MANUAL_OVERRIDES.get(name)
        if manual:
            rows.append({
                "filename": path.name,
                "name": name,
                "type": ac.get("type", ""),
                "tcds_number": manual["tcds"],
                "tcds_holder": manual["holder"],
                "publication": manual["publication"],
                "match_source": "manual",
                "matched_model": "",
            })
            continue

        result = find_best_tcds(name, aircraft_tcds)
        if result:
            rec, model_matched = result
            rows.append({
                "filename": path.name,
                "name": name,
                "type": ac.get("type", ""),
                "tcds_number": rec.get("tcdsNumber", ""),
                "tcds_holder": rec.get("tcHolder", ""),
                "publication": f"FAA TCDS {rec.get('tcdsNumber','')} Rev {rec.get('revisionNumber','')}"
                                f" ({rec.get('revisionDate','')})",
                "match_source": "fuzzy",
                "matched_model": model_matched,
            })
        else:
            rows.append({
                "filename": path.name,
                "name": name,
                "type": ac.get("type", ""),
                "tcds_number": "",
                "tcds_holder": "",
                "publication": "",
                "match_source": "unmatched",
                "matched_model": "",
            })
    return rows


def main() -> None:
    rows = build_mapping()
    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)

    fields = ["filename", "name", "type", "tcds_number", "tcds_holder",
              "publication", "match_source", "matched_model"]
    with OUT_CSV.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)

    OUT_JSON.write_text(json.dumps(rows, indent=2))

    # Summary
    from collections import Counter
    by_src = Counter(r["match_source"] for r in rows)
    print(f"Wrote {OUT_CSV.relative_to(REPO_ROOT)} ({len(rows)} aircraft)")
    print(f"Wrote {OUT_JSON.relative_to(REPO_ROOT)}")
    print()
    print("Match source breakdown:")
    for src, n in by_src.most_common():
        print(f"  {src:<12} {n}")
    print()
    unmatched = [r for r in rows if r["match_source"] == "unmatched"]
    if unmatched:
        print("Still unmatched (need manual entry):")
        for r in unmatched:
            print(f"  {r['filename']:<40} {r['name']}")


if __name__ == "__main__":
    main()
