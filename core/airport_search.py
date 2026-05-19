"""Airport search + waypoint resolution — single source of truth.

Used by:
  - Top-bar APT search input (`callbacks/environment.py`)
  - Route Planner waypoint dropdown (`callbacks/route.py`)

The query is matched case-insensitively across ID, ICAO, IATA, FAA LID,
name, municipality, and US state. Results are ranked so exact-code hits
come first (a pilot typing "DYB" wants KDYB on top of "Dyess AFB"),
then prefix matches on codes, then prefix on city, then substring
elsewhere.

Future: this is also where VOR/intersection/lat-lon resolvers will plug
in — same query → multi-source candidate list. For now: airports only.
"""
from __future__ import annotations

from typing import Iterable

# Fields we'll match against, in priority order (higher = stronger weight).
SEARCH_FIELDS = ("id", "icao", "iata", "local",
                 "name", "municipality", "state")


def _norm(s: object) -> str:
    return (s or "").strip().lower() if isinstance(s, str) else ""


def _score(ap: dict, q: str) -> int:
    """Higher = better match. 0 = no match. Caller filters out 0s."""
    qid = q.upper()
    code_fields = (ap.get("id"), ap.get("icao"), ap.get("iata"), ap.get("local"))
    # Exact code hit — top tier
    for c in code_fields:
        if c and c.upper() == qid:
            return 1000
    # Prefix on a code
    for c in code_fields:
        if c and c.upper().startswith(qid):
            return 500
    # Substring on a code
    for c in code_fields:
        if c and qid in c.upper():
            return 300

    name = _norm(ap.get("name"))
    muni = _norm(ap.get("municipality"))
    state = _norm(ap.get("state"))

    # Prefix on city/name → strong
    if muni.startswith(q):
        return 250
    if name.startswith(q):
        return 200
    # Substring on city
    if q in muni:
        return 150
    # Substring on name
    if q in name:
        return 100
    # State match (weakest — "FL" matches every Florida airport)
    if state and (state.lower() == q or state.lower().startswith(q)):
        return 50
    return 0


def search_airports(airport_data: list[dict],
                    query: str,
                    limit: int = 20) -> list[dict]:
    """Return a ranked list of airports matching `query`. Empty list
    if query is too short or no matches."""
    if not query or len(query.strip()) < 2:
        return []
    q = query.strip().lower()

    scored: list[tuple[int, dict]] = []
    for ap in airport_data:
        s = _score(ap, q)
        if s > 0:
            scored.append((s, ap))
    # Sort by score desc, then prefer larger airports (rough proxy: has
    # iata code, has runways → put first within the same score band).
    scored.sort(key=lambda t: (
        -t[0],
        not bool(t[1].get("iata")),    # iata-coded first
        t[1].get("name", "").lower(),
    ))
    return [ap for _, ap in scored[:limit]]


def airport_label(ap: dict) -> str:
    """User-facing label for a single airport result.
    Format: "KDYB · Summerville Apt — Summerville, SC".
    """
    short = ap.get("icao") or ap.get("id") or ap.get("iata") or ""
    name = ap.get("name", "")
    muni = ap.get("municipality") or ""
    state = ap.get("state") or ""
    country = ap.get("country") or ""
    if muni and state:
        locality = f"{muni}, {state}"
    elif muni and country:
        locality = f"{muni}, {country}"
    elif country:
        locality = country
    else:
        locality = ""
    if short and short != ap.get("id"):
        head = f"{short} · {name}"
    elif short:
        head = f"{short} · {name}" if name else short
    else:
        head = name
    return f"{head} — {locality}" if locality else head


def resolve_waypoint(airport_data: list[dict], token: str) -> dict | None:
    """Resolve a single textual waypoint token to a concrete airport dict.

    Tries (in order):
      - exact case-insensitive match on id / icao / iata / local
      - the top result of search_airports() — fallback for partial typing

    Returns None if nothing matches. Future: extend with VOR/FIX/lat-lon
    resolvers without changing callers.
    """
    if not token:
        return None
    t = token.strip().upper()
    if not t:
        return None
    for ap in airport_data:
        for f in ("id", "icao", "iata", "local"):
            v = ap.get(f)
            if v and v.upper() == t:
                return ap
    # Fallback: best fuzzy hit
    hits = search_airports(airport_data, token, limit=1)
    return hits[0] if hits else None


# === Phase 7N-bc: NAVAID + fix search ======================================
#
# These mirror the airport pipeline (exact ident, then ranked fuzzy hits)
# but are kept separate so the search ranking stays predictable: airports
# always rank above same-named NAVAIDs (SAV the IATA before SAV the VOR),
# but NAVAID ident matches beat airport partial matches.

# Map TYPE_CODE → short type label for display badges. Empty / unknown
# codes fall through to a plain "NAVAID" label.
NAVAID_TYPE_LABELS = {
    "VOR": "VOR",
    "VOR/DME": "VOR-DME",
    "VORTAC": "VORTAC",
    "TACAN": "TACAN",
    "NDB": "NDB",
    "NDB/DME": "NDB-DME",
    "DME": "DME",
}


def _score_navaid(nv: dict, q: str) -> int:
    """Same scoring shape as _score(airport) but with only ident + name
    to match on. NAVAIDs are mostly known by their 3-letter ident."""
    ident = (nv.get("ident") or "").lower()
    name = (nv.get("name") or "").lower()
    if ident == q:
        return 950   # below airport icao (1000) so KSAV beats SAV
    if ident.startswith(q):
        return 700
    if q in ident:
        return 200
    if name.startswith(q):
        return 110
    if q in name:
        return 60
    return 0


def search_navaids(navaid_data: list[dict],
                   query: str,
                   limit: int = 10) -> list[dict]:
    if not query or len(query.strip()) < 2 or not navaid_data:
        return []
    q = query.strip().lower()
    scored: list[tuple[int, dict]] = []
    for nv in navaid_data:
        s = _score_navaid(nv, q)
        if s > 0:
            scored.append((s, nv))
    scored.sort(key=lambda t: (
        -t[0],
        (t[1].get("ident") or "").upper(),
    ))
    return [nv for _, nv in scored[:limit]]


def search_fixes(fix_data: list[dict],
                 query: str,
                 limit: int = 10) -> list[dict]:
    """Fixes only support exact / prefix ident match — they're named
    5-letter strings with no semantic content to fuzzy-search."""
    if not query or len(query.strip()) < 2 or not fix_data:
        return []
    q = query.strip().upper()
    out: list[dict] = []
    for fx in fix_data:
        ident = (fx.get("ident") or "").upper()
        if ident == q or ident.startswith(q):
            out.append(fx)
            if len(out) >= limit * 4:  # keep some buffer for ranking
                break
    out.sort(key=lambda f: (
        (f.get("ident") or "").upper() != q,  # exact first
        f.get("ident") or "",
    ))
    return out[:limit]


def navaid_label(nv: dict) -> str:
    tlabel = NAVAID_TYPE_LABELS.get(nv.get("type_code", ""), "NAVAID")
    name = nv.get("name") or ""
    freq = nv.get("freq_mhz")
    freq_str = f" ({freq:.2f})" if isinstance(freq, (int, float)) else ""
    return f"{nv.get('ident', '')} · {tlabel} {name}{freq_str}"


def fix_label(fx: dict) -> str:
    state = fx.get("state") or ""
    return f"{fx.get('ident', '')} · FIX{(' — ' + state) if state else ''}"
