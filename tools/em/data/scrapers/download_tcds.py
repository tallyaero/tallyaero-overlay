"""
Download missing FAA TCDS PDFs from drs.faa.gov.

Reads `docs/missing_tcds.json` (produced by the gap analysis), looks up each
TCDS in `tcds.json`'s index for the `pdfUrl`, fetches the PDF with a polite
delay, and saves to `data/sources/tcds_pdfs/<TCDS>.pdf`.

EASA TCDS aren't in the FAA index — they get logged and skipped here, to be
sourced separately in Phase 2e.

Idempotent: skips TCDS that already have a local PDF.
"""

from __future__ import annotations

import json
import time
import urllib.request
import urllib.error
from pathlib import Path
from typing import List, Tuple

REPO_ROOT = Path(__file__).resolve().parents[2]
MISSING_JSON = REPO_ROOT / "docs" / "missing_tcds.json"
TCDS_INDEX = Path(
    "/Users/nicholaslen/Desktop/tallyaero/website/.research-cache/normalized/tcds.json"
)
# Direct-PDF URLs harvested from the legacy `download_tcds.py` in the
# tallyaero monorepo. These are CloudFront / S3 mirrors maintained by
# third parties (Univair, ATP, pegasusaviation, etc.) — much friendlier
# than the FAA's drs.faa.gov SPA which requires browser automation.
LEGACY_URLS = REPO_ROOT / "docs" / "legacy_tcds_urls.json"
OUT_DIR = REPO_ROOT / "data" / "sources" / "tcds_pdfs"

USER_AGENT = (
    "TallyAero-EM-Diagram/0.1 (+https://tallyaero.app) "
    "downloads FAA TCDS PDFs for educational aircraft-performance modeling"
)
POLITE_DELAY_SEC = 1.5    # don't hammer drs.faa.gov


def fetch_pdf(url: str, dest: Path, timeout: int = 30) -> Tuple[bool, str]:
    """Download `url` to `dest`. Returns (success, message)."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            content_type = resp.headers.get("Content-Type", "")
            data = resp.read()
        if "pdf" not in content_type.lower() and not data.startswith(b"%PDF"):
            return (False, f"non-PDF content (got {content_type[:50]})")
        dest.write_bytes(data)
        return (True, f"{len(data):,} bytes")
    except urllib.error.HTTPError as e:
        return (False, f"HTTP {e.code} {e.reason}")
    except urllib.error.URLError as e:
        return (False, f"URL error: {e.reason}")
    except Exception as e:
        return (False, f"{type(e).__name__}: {e}")


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    missing = json.loads(MISSING_JSON.read_text())
    legacy_urls = json.loads(LEGACY_URLS.read_text()) if LEGACY_URLS.exists() else {}

    print(f"Missing TCDS to attempt: {len(missing)}")
    print(f"Legacy direct URLs available: {len(legacy_urls)}")
    print(f"Destination: {OUT_DIR.relative_to(REPO_ROOT)}/")
    print()

    fetched: List[str] = []
    skipped_existing: List[str] = []
    skipped_easa:     List[str] = []
    skipped_no_url:   List[str] = []
    failed:           List[Tuple[str, str]] = []

    for i, (tcds_n, aircraft_names) in enumerate(sorted(missing.items()), 1):
        dest = OUT_DIR / f"{tcds_n}.pdf"
        if dest.exists():
            skipped_existing.append(tcds_n)
            continue
        if tcds_n.startswith("EASA"):
            skipped_easa.append(tcds_n)
            continue
        # Prefer the legacy direct-PDF URL — drs.faa.gov is a JS SPA and
        # serves HTML instead of PDF when scraped headlessly.
        url = legacy_urls.get(tcds_n)
        if not url:
            skipped_no_url.append(tcds_n)
            continue

        ok, msg = fetch_pdf(url, dest)
        if ok:
            print(f"  [{i:>2}/{len(missing)}]  ok  {tcds_n:<12}  {msg}")
            fetched.append(tcds_n)
        else:
            print(f"  [{i:>2}/{len(missing)}]  XX  {tcds_n:<12}  {msg}")
            failed.append((tcds_n, msg))

        time.sleep(POLITE_DELAY_SEC)

    print()
    print(f"Summary:")
    print(f"  fetched:           {len(fetched)}")
    print(f"  already had local: {len(skipped_existing)}")
    print(f"  EASA (skip - Phase 2e): {len(skipped_easa)}")
    print(f"  no direct URL known: {len(skipped_no_url)}")
    print(f"  failed:            {len(failed)}")
    if failed:
        print("\nFailures:")
        for t, m in failed:
            print(f"  {t:<14}  {m}")
    if skipped_easa or skipped_no_url:
        print("\nDeferred to Phase 2e (need a direct PDF URL or manual fetch):")
        for t in skipped_easa + skipped_no_url:
            print(f"  {t}")


if __name__ == "__main__":
    main()
