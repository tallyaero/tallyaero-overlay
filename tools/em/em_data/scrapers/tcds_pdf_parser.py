"""
TCDS PDF parser — Phase 2b.

For each FAA TCDS PDF in the local cache, extract:
  - TCDS number, revision, holder
  - Per-variant blocks (Section I., II., III., ... each covering one model)
  - Within each variant: engine + HP, V-speeds (Vne / Vno / Vfe / Va),
    max gross weight (per category), fuel capacity, CG range, seats

Outputs a JSON per TCDS at `data/sources/tcds_parsed/<TCDS>.json`.

We use `pdftotext -layout` because the FAA PDFs are column-aligned data
sheets — that flag preserves the column structure better than the default
flow mode. Field extraction is then anchor-based: every line that starts
with a known label opens a field, every subsequent line is content for
that field until the next labeled line.

Phase 2c will consume these JSONs to reconcile against our aircraft_data/*.json
values and upgrade `confidence: partial → verified` field by field.
"""

from __future__ import annotations

import json
import re
import subprocess
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# ──────────────────────────────────────────────────────────────────────
# Configuration
# ──────────────────────────────────────────────────────────────────────
REPO_ROOT = Path(__file__).resolve().parents[2]
PDF_DIR = Path(
    "/Users/nicholaslen/Desktop/tallyaero/website/.research-cache/raw/tcds-pdfs"
)
OUT_DIR = REPO_ROOT / "data" / "sources" / "tcds_parsed"

# Filenames that aren't real TCDS dumps (NTSB-derived excerpts, etc.)
SKIP_SUFFIXES = ("-ntsb", "-ntsb-excerpt", "-vintage")


# ──────────────────────────────────────────────────────────────────────
# Per-variant labeled-field regex patterns.
# The pattern is matched at line start (allowing whitespace + optional
# leading '*' that FAA uses to flag certified critical parameters).
# ──────────────────────────────────────────────────────────────────────
LABELS: Dict[str, str] = {
    "engine":              r"Engine(?!\s+Limits)",
    "engine_limits":       r"Engine Limits",
    "fuel_grade":          r"Fuel(?!\s+Capacity)",
    "propeller":           r"Propeller(?!\s+(?:and|Limits))",
    "propeller_block":     r"Propeller and",
    "airspeed_limits":     r"Airspeed [Ll]imits",
    "cg_range":            r"C\.G\.\s*Range",
    "empty_weight_cg":     r"Empty Weight C\.G\.\s*Range",
    "max_weight":          r"Maximum Weight",
    "seats":               r"Number of Seats",
    "max_baggage":         r"Maximum Baggage",
    "fuel_capacity":       r"Fuel Capacity",
    "oil_capacity":        r"Oil Capacity",
    "control_surfaces":    r"Control Surface Movements",
    "serial_numbers":      r"Serial Numbers Eligible",
    "datum":               r"Datum\b",
    "leveling_means":      r"Leveling Means",
}


ROMAN_RE = re.compile(
    # Roman numeral, then either "." or "-" or "—" as separator, then "Model(s)"
    r"^\s*([IVXLCDM]+)\s*[\.\-–—]\s+Models?\s+(.+?)(?:\s*\((?:cont|cont'd)[^\)]*\))?$",
    re.IGNORECASE,
)
# The page-footer "3A12 — Page N — Rev M" pattern.
PAGE_FOOTER_RE = re.compile(r"^\s*(?:Rev\s*\.?\s*\d+|Page\s+No\.?|\d{1,3})\s*$")


# ──────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────


def pdftotext(pdf_path: Path) -> str:
    """Run `pdftotext -layout` and return text. Raises on failure."""
    return subprocess.run(
        ["pdftotext", "-layout", str(pdf_path), "-"],
        capture_output=True, text=True, check=True,
    ).stdout


def parse_tcds_header(text: str) -> Dict[str, str]:
    """Extract top-of-document TCDS number + revision + holder."""
    header = {}
    # TCDS number — try several formats:
    #   3A12         — modern numeric-prefix format
    #   A-759        — historical CAA-era "A-NNN" format
    #   T00012WI     — type-cert with letter prefix
    #   EASA.A.022   — EASA designation
    for pat in (
        r"\b((?:[0-9]{1,2}[A-Z]+[0-9]*(?:[A-Z]+[0-9]*)*))\b\s*(?:Revision|Rev)",
        r"\b(A[-‐]\d{2,4})\b",
        r"\b(EASA\.[A-Z]+\.\d{2,4})\b",
        r"\b(T\d{5,7}[A-Z]{0,3})\b",
    ):
        m = re.search(pat, text[:2000])
        if m:
            header["tcds_number"] = m.group(1).strip()
            break
    # Revision number
    m = re.search(r"Revision\s+(\d+)", text[:1500])
    if m:
        header["revision"] = m.group(1).strip()
    # TC holder
    m = re.search(r"Type Certificate Holder\s+(.+?)(?:\n|$)", text)
    if m:
        header["tc_holder"] = m.group(1).strip()
    # Issue / revision date — try a few common date formats
    m = re.search(
        r"\b(January|February|March|April|May|June|July|August|September|October|November|December)"
        r"\s+\d{1,2},?\s+\d{4}\b",
        text[:2000],
    )
    if m:
        header["revision_date"] = m.group(0).strip()
    return header


def split_variants(text: str) -> List[Tuple[str, str, str]]:
    """Return [(roman, models, body_text), ...].

    Each section is everything from one `I. Model X` anchor up to the next
    such anchor. Continuation pages (` … (cont'd)`) are folded into the
    current section.
    """
    lines = text.splitlines()

    # Find all section anchors (skipping the "(cont'd)" continuation lines)
    anchors: List[Tuple[int, str, str]] = []
    for i, line in enumerate(lines):
        m = ROMAN_RE.match(line)
        if not m:
            continue
        roman, models = m.group(1).upper(), m.group(2).strip()
        # Skip continuation headers — they repeat the roman + model.
        if "(cont" in line.lower() or "cont'd" in line.lower():
            continue
        anchors.append((i, roman, models))

    if not anchors:
        return []

    # Build sections: from each anchor to the next (or end of doc)
    sections: List[Tuple[str, str, str]] = []
    for j, (line_idx, roman, models) in enumerate(anchors):
        end = anchors[j + 1][0] if j + 1 < len(anchors) else len(lines)
        body = "\n".join(lines[line_idx:end])
        sections.append((roman, models, body))
    return sections


def extract_fields(section_text: str) -> Dict[str, str]:
    """Walk lines and group them under the most recent labeled field."""
    lines = section_text.splitlines()

    # Compile a single combined label regex anchored at line start
    label_alt = "|".join(f"(?P<{key}>{pattern})" for key, pattern in LABELS.items())
    label_re = re.compile(rf"^\s*\*?\s*({label_alt})\b", re.IGNORECASE)

    fields: Dict[str, List[str]] = {}
    current_key: Optional[str] = None

    for raw in lines:
        m = label_re.match(raw)
        if m:
            # New field starts here. Save residue from current field.
            current_key = next(k for k, v in m.groupdict().items() if v)
            # The label might be followed by the value on the SAME line.
            value_part = raw[m.end():].strip()
            fields.setdefault(current_key, []).append(value_part)
        else:
            if current_key:
                stripped = raw.rstrip()
                if not stripped:
                    # Blank line → don't break the field, but compress to a
                    # single newline so we keep multi-line layout for CG range
                    # tables (they have blank gaps).
                    if fields[current_key] and fields[current_key][-1] != "":
                        fields[current_key].append("")
                else:
                    fields[current_key].append(stripped.strip())
    # Collapse list of strings into a single value per field
    return {k: "\n".join(v).strip() for k, v in fields.items()}


# ── Post-processors: extract concrete numbers from the labeled raw text ─


def post_engine_limits(value: str) -> Dict[str, Optional[float]]:
    """`"For all operations, 2700 rpm (160 hp)"` → {rpm: 2700, hp: 160}."""
    out: Dict[str, Optional[float]] = {"rpm": None, "hp": None}
    m = re.search(r"(\d{3,5})\s*rpm", value)
    if m:
        out["rpm"] = int(m.group(1))
    m = re.search(r"\((\d{2,4})\s*hp\)", value)
    if m:
        out["hp"] = int(m.group(1))
    return out


def post_airspeed_limits(value: str) -> Dict[str, Optional[Dict[str, float]]]:
    """Pull Vne / Vno / Vfe / Va out of an Airspeed Limits block.

    Returns a dict like {Vne: {value: 158, unit: "knots"}, ...}. Older TCDS
    use mph; newer use knots. We capture the unit verbatim so the consumer
    can normalize.
    """
    out: Dict[str, Optional[Dict[str, float]]] = {
        "Vne": None, "Vno": None, "Vfe": None, "Va": None
    }
    # Generic pattern: <label phrase> ... <integer> ... <optional unit word>.
    # We capture the number greedily and look for a knots/mph hint after.
    patterns = [
        ("Vne", r"Never exceed[^A-Za-z\d]*\s*(\d{2,4})\s*(knots|kts|mph|KCAS|KIAS)?"),
        ("Vno", r"(?:Maximum structural cruising|Normal operating)[^A-Za-z\d]*\s*(\d{2,4})\s*(knots|kts|mph|KCAS|KIAS)?"),
        ("Vfe", r"Flaps?\s+extended[^A-Za-z\d]*\s*(\d{2,4})\s*(knots|kts|mph|KCAS|KIAS)?"),
        ("Va",  r"Maneuvering[^A-Za-z\d]*\s*(\d{2,4})\s*(knots|kts|mph|KCAS|KIAS)?"),
    ]
    # Default unit per-block, inferred if any line declares one.
    block_unit = "knots"
    if re.search(r"\bmph\b", value, re.IGNORECASE) and not re.search(r"\bknots\b|\bkts\b", value, re.IGNORECASE):
        block_unit = "mph"
    for key, pat in patterns:
        m = re.search(pat, value, re.IGNORECASE)
        if m:
            unit = (m.group(2) or block_unit).lower()
            unit = "knots" if unit in ("kts", "kcas", "kias") else unit
            out[key] = {"value": int(m.group(1)), "unit": unit}
    return out


def post_max_weight(value: str) -> Dict[str, Optional[int]]:
    """Parse weight values. Two passes:
       1) Find each '(modifier)' parenthetical (e.g. '2400 lb. (landplane)')
          and pair it with the nearest preceding category word.
       2) For lines with no parenthetical (just 'Normal category: 1850 lb'),
          fall back to category-only classification.
    """
    out: Dict[str, Optional[int]] = {}
    # Track which (start, end) ranges we've consumed
    consumed: List[Tuple[int, int]] = []

    # Pass 1: "(NNNN lb. (landplane))" — multi-modifier lines
    for m in re.finditer(r"(\d[\d,]{1,5})\s*lb\.?\s*\(([^\)]+)\)", value):
        weight = int(m.group(1).replace(",", ""))
        modifier = m.group(2).lower()
        # Find category that PRECEDES this match (most recent)
        upto = value[: m.start()].lower()
        cats = re.findall(r"(normal|utility|aerobatic)", upto)
        cat = cats[-1] if cats else "normal"
        craft = "landplane"
        for ct in ("seaplane", "floatplane", "skiplane", "landplane"):
            if ct in modifier:
                craft = ct
                break
        out[f"{cat}_{craft}"] = weight
        consumed.append((m.start(), m.end()))

    # Pass 2: bare "NNNN lb" without a (modifier) — process each line
    for line in value.splitlines():
        line_lower = line.lower()
        for m in re.finditer(r"(\d[\d,]{1,5})\s*lb", line):
            # Skip if this match was already consumed by Pass 1
            global_start = value.find(line) + m.start() if value.find(line) >= 0 else -1
            if any(s <= global_start < e for s, e in consumed):
                continue
            weight = int(m.group(1).replace(",", ""))
            cat = "normal"
            for c in ("aerobatic", "utility", "normal"):
                if c in line_lower:
                    cat = c
                    break
            key = f"{cat}_landplane"
            # Don't overwrite a higher-confidence Pass-1 result
            out.setdefault(key, weight)
    return out


def post_fuel_capacity(value: str) -> Dict[str, Optional[float]]:
    """Parse '42 gal. total, 40 gal. usable' style."""
    out: Dict[str, Optional[float]] = {"total_gal": None, "usable_gal": None}
    m = re.search(r"(\d{1,4}(?:\.\d+)?)\s*gal\.?\s*total", value, re.IGNORECASE)
    if m:
        out["total_gal"] = float(m.group(1))
    m = re.search(r"(\d{1,4}(?:\.\d+)?)\s*gal\.?\s*usable", value, re.IGNORECASE)
    if m:
        out["usable_gal"] = float(m.group(1))
    # Fallback: single number followed by 'gal'
    if out["total_gal"] is None:
        m = re.search(r"(\d{1,4}(?:\.\d+)?)\s*gal", value, re.IGNORECASE)
        if m:
            out["total_gal"] = float(m.group(1))
    return out


def post_seats(value: str) -> Optional[int]:
    m = re.search(r"(\d{1,2})", value)
    return int(m.group(1)) if m else None


# ──────────────────────────────────────────────────────────────────────
# Driver
# ──────────────────────────────────────────────────────────────────────


def parse_one_pdf(pdf_path: Path) -> Optional[dict]:
    """Parse one TCDS PDF and return the structured output dict."""
    try:
        text = pdftotext(pdf_path)
    except subprocess.CalledProcessError as e:
        return {
            "tcds_file": pdf_path.name,
            "error": f"pdftotext failed: {e.stderr.strip()[:200]}",
        }

    header = parse_tcds_header(text)
    # Fallback: derive from filename. Use the FULL stem (without splitting
    # on '-') so historical `A-759.pdf` → `A-759` and EASA-prefixed files
    # keep their full identifier as a fallback.
    if "tcds_number" not in header:
        header["tcds_number"] = pdf_path.stem

    sections = split_variants(text)
    variants: List[dict] = []
    for roman, models, body in sections:
        raw_fields = extract_fields(body)

        engine_limits = post_engine_limits(raw_fields.get("engine_limits", ""))
        airspeed_limits = post_airspeed_limits(raw_fields.get("airspeed_limits", ""))
        max_weight = post_max_weight(raw_fields.get("max_weight", ""))
        fuel_capacity = post_fuel_capacity(raw_fields.get("fuel_capacity", ""))
        seats = post_seats(raw_fields.get("seats", ""))

        # Clean the models list: section headers look like
        # "Model F33, Bonanza, 4 PCLM (Normal Category), approved March 25, 1947"
        # We want just ['F33'] (or ['172D', '172E', '172F'] if multiple).
        # Heuristics: keep tokens that are short alphanumeric designators
        # (≤8 chars, no spaces, possibly with hyphen / slash). Drop common
        # non-model words like "Bonanza", "PCLM", "Normal", "approved", year.
        STOPWORDS = {
            "BONANZA", "BARON", "TRAVEL", "AIR", "SKYHAWK", "CARDINAL", "CUTLASS",
            "PCLM", "PCL-SM", "PCL", "NORMAL", "UTILITY", "ACROBATIC", "AEROBATIC",
            "CATEGORY", "APPROVED", "MODELS", "MODEL", "OR",
        }
        raw_model_tokens = [m.strip() for m in re.split(r",\s*", models)]
        cleaned_models: List[str] = []
        for tok in raw_model_tokens:
            # Drop everything from "approved" onward in a token
            tok = re.sub(r"\bapproved\b.*$", "", tok, flags=re.IGNORECASE).strip()
            if not tok or len(tok) > 20:
                continue
            if "(" in tok or ")" in tok:
                continue
            # The token may have multiple space-separated pieces — keep only
            # the ones that look like model designators (alphanumeric, possibly
            # with hyphen/slash). A pure digit string of 4+ digits is a year.
            for piece in tok.split():
                piece = piece.strip(",.-/")
                if not piece or len(piece) > 12:
                    continue
                if piece.upper() in STOPWORDS:
                    continue
                if re.fullmatch(r"\d{4,}", piece):    # year
                    continue
                if not re.match(r"^[A-Z0-9][A-Z0-9/\-]*$", piece, re.IGNORECASE):
                    continue                          # must look like a model designator
                cleaned_models.append(piece)
        variants.append({
            "section_roman": roman,
            "models": cleaned_models or [raw_model_tokens[0]],
            "engine":           raw_fields.get("engine", "").splitlines()[0] if raw_fields.get("engine") else None,
            "engine_limits":    engine_limits,
            "fuel_grade":       raw_fields.get("fuel_grade", "").splitlines()[0] if raw_fields.get("fuel_grade") else None,
            "v_speeds_kcas":    airspeed_limits,
            "max_weight_lb":    max_weight,
            "fuel_capacity":    fuel_capacity,
            "seats":            seats,
            # Keep the multiline strings around for things we don't fully
            # parse yet (CG range, control-surface movements, serial-number
            # eligibility). Phase 2c can mine them further.
            "cg_range_raw":     raw_fields.get("cg_range"),
            "control_surfaces": raw_fields.get("control_surfaces"),
            "serial_numbers":   raw_fields.get("serial_numbers"),
        })

    return {
        "tcds_number":   header.get("tcds_number"),
        "revision":      header.get("revision"),
        "revision_date": header.get("revision_date"),
        "tc_holder":     header.get("tc_holder"),
        "source_pdf":    pdf_path.name,
        "parsed_at":     str(date.today()),
        "variant_count": len(variants),
        "variants":      variants,
    }


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    pdfs = sorted(PDF_DIR.glob("*.pdf"))
    pdfs = [p for p in pdfs if not any(p.stem.endswith(suf) for suf in SKIP_SUFFIXES)]
    print(f"Parsing {len(pdfs)} TCDS PDFs from {PDF_DIR}")
    print(f"Writing to {OUT_DIR.relative_to(REPO_ROOT)}/")
    print()

    summary = {
        "parsed": 0, "failed": 0, "variants_total": 0,
        "with_vne": 0, "with_max_weight": 0, "with_fuel": 0,
    }
    for pdf in pdfs:
        result = parse_one_pdf(pdf)
        if not result or "error" in result:
            summary["failed"] += 1
            print(f"  FAIL {pdf.name}: {(result or {}).get('error', '?')}")
            continue

        out_path = OUT_DIR / f"{result['tcds_number']}.json"
        out_path.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")

        summary["parsed"] += 1
        summary["variants_total"] += result["variant_count"]
        for v in result["variants"]:
            if v["v_speeds_kcas"].get("Vne"):  summary["with_vne"] += 1
            if v["max_weight_lb"]:            summary["with_max_weight"] += 1
            if v["fuel_capacity"]["total_gal"]: summary["with_fuel"] += 1

    print()
    print(f"  parsed:        {summary['parsed']} PDFs")
    print(f"  failed:        {summary['failed']}")
    print(f"  variants:      {summary['variants_total']} total")
    print(f"  with Vne:      {summary['with_vne']}")
    print(f"  with max_wt:   {summary['with_max_weight']}")
    print(f"  with fuel:     {summary['with_fuel']}")


if __name__ == "__main__":
    main()
