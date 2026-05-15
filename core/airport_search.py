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
