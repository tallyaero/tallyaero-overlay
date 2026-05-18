"""Airport radio frequencies loaded from OurAirports' airport-
frequencies CSV (which itself rolls up FAA NASR + ICAO data).

Source: https://ourairports.com/data/airport-frequencies.csv
Vendored at _data/airports/airport-frequencies.csv. ~30K rows, 1.2 MB.

The CSV's `type` column uses a small set of codes; we normalize them
into the categories pilots actually look for on a nav log:

    ATIS     → ATIS / AWOS / ASOS broadcast
    GND      → Ground control
    TWR      → Tower
    DEP      → Departure control          (split out of A/D)
    APP      → Approach control            (split out of A/D)
    CLD      → Clearance Delivery
    CTAF     → Common Traffic Advisory     (non-towered fields)
    UNICOM   → UNICOM
    FSS      → Flight Service Station
    RDO      → Radio
    MULTICOM → Multicom

When the same airport has multiple entries of the same type
(e.g. two ATIS frequencies), they're joined with " / " in the
returned string so the pilot sees both on the printable nav log.
"""
from __future__ import annotations

import csv
import logging
import os
from functools import lru_cache
from pathlib import Path
from typing import Dict, List

_LOG = logging.getLogger("tallyaero.overlay.core.airport_freq")

_DATA_PATH = (
    Path(__file__).parent.parent
    / "_data" / "airports" / "airport-frequencies.csv"
)

# Map OurAirports type codes → canonical bucket keys we display.
# A/D is split into APP/DEP at runtime by inspecting the description
# (e.g. "DENVER APP/DEP" → both keys); plain A/D gets duplicated to
# both fields.
_TYPE_MAP: Dict[str, str] = {
    "ATIS":   "ATIS",
    "AWOS":   "ATIS",   # treat AWOS/ASOS as ATIS for nav-log purposes
    "ASOS":   "ATIS",
    "GND":    "GND",
    "TWR":    "TWR",
    "CLD":    "CLD",
    "CTAF":   "CTAF",
    "UNIC":   "UNICOM",
    "UNICOM": "UNICOM",
    "FSS":    "FSS",
    "RDO":    "RDO",
    "RCO":    "FSS",    # Remote Communication Outlet — pilot tunes
                        # FSS via the local RCO frequency
    "MULTICOM": "MULTICOM",
    "MUL":    "MULTICOM",
}


@lru_cache(maxsize=1)
def _load_index() -> Dict[str, Dict[str, str]]:
    """Parse the CSV once and return {airport_id: {bucket: "freq[ / freq]"}}.

    Empty dict if the CSV is missing (so callers degrade gracefully —
    blank rows in the nav log rather than a crash).
    """
    if not _DATA_PATH.exists():
        _LOG.warning("airport-frequencies.csv not found at %s", _DATA_PATH)
        return {}

    # Two-pass: first collect per-airport lists of (bucket, freq) so we
    # can dedupe + join multiples, then flatten.
    raw: Dict[str, Dict[str, List[str]]] = {}
    try:
        with open(_DATA_PATH, "r", encoding="utf-8", newline="") as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                ident = (row.get("airport_ident") or "").strip()
                if not ident:
                    continue
                raw_type = (row.get("type") or "").strip().upper()
                freq = (row.get("frequency_mhz") or "").strip()
                desc = (row.get("description") or "").upper()
                if not freq:
                    continue
                buckets: List[str] = []
                if raw_type == "A/D":
                    # Combined Approach/Departure — duplicate into both.
                    if "APP" in desc:
                        buckets.append("APP")
                    if "DEP" in desc:
                        buckets.append("DEP")
                    if not buckets:
                        buckets.extend(("APP", "DEP"))
                elif raw_type in _TYPE_MAP:
                    buckets.append(_TYPE_MAP[raw_type])
                else:
                    # Unknown type — keep raw code so it surfaces
                    # somewhere rather than getting silently dropped.
                    buckets.append(raw_type or "OTHER")
                ap = raw.setdefault(ident, {})
                for b in buckets:
                    ap.setdefault(b, []).append(freq)
    except (OSError, csv.Error) as exc:
        _LOG.warning("airport-frequencies.csv parse failed: %s", exc)
        return {}

    # Flatten: dedupe per-bucket freq list while preserving order, join.
    out: Dict[str, Dict[str, str]] = {}
    for ident, buckets in raw.items():
        flat = {}
        for k, freqs in buckets.items():
            seen: set = set()
            uniq = []
            for f in freqs:
                if f not in seen:
                    seen.add(f)
                    uniq.append(f)
            flat[k] = " / ".join(uniq)
        out[ident] = flat

    _LOG.info(
        "Loaded frequencies for %d airports from %s",
        len(out), _DATA_PATH.name,
    )
    return out


def frequencies_for(airport_id: str | None) -> Dict[str, str]:
    """Return the frequency dict for one airport or {} if not found.

    Keys are normalized bucket names (ATIS, GND, TWR, APP, DEP, CTAF,
    UNICOM, FSS, CLD, ...). Values are pre-formatted "freq" strings
    or "freq1 / freq2" when multiples exist.
    """
    if not airport_id:
        return {}
    return _load_index().get(airport_id, {})
