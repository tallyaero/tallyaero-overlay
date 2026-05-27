#!/usr/bin/env bash
# Build FAA chart tile pyramid from the AeroNav GeoTIFF bundles.
#
# Usage:
#   scripts/build_chart_tiles.sh <chart_name> [cycle_date] [layer]
#
# Examples:
#   scripts/build_chart_tiles.sh Charlotte               # current cycle, sectional
#   scripts/build_chart_tiles.sh Atlanta 07-09-2026      # specific cycle
#   scripts/build_chart_tiles.sh Atlanta 07-09-2026 tac  # TAC instead of sectional
#
# Output:
#   tiles/<layer>/   — gdal2tiles XYZ pyramid (zoom 6-12 for sectional,
#                       7-13 for TAC, 6-11 for IFR Lo)
#
# Prereqs: gdal (brew install gdal). Generates ~500 MB-1 GB per chart.
# Re-run every 28-day FAA cycle.

set -euo pipefail

CHART="${1:?Chart name required (e.g. Charlotte, Atlanta, San_Francisco)}"
CYCLE="${2:-05-14-2026}"   # default = current cycle; update each pull
LAYER="${3:-sectional}"

case "$LAYER" in
  sectional) URL_PATH="sectional-files"; ZOOMS="6-12" ;;
  tac)       URL_PATH="tac-files";       ZOOMS="7-13" ;;
  *) echo "Unknown layer: $LAYER (sectional|tac)" >&2; exit 2 ;;
esac

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
RAW_DIR="$REPO_ROOT/raw_charts"
TILES_DIR="$REPO_ROOT/tiles/$LAYER"
URL="https://aeronav.faa.gov/visual/${CYCLE}/${URL_PATH}/${CHART}.zip"

mkdir -p "$RAW_DIR" "$TILES_DIR"

# Skip download + unzip if the source TIF already exists (script
# may be re-run after a TIF-pattern bug etc.).
CHART_NOUS="${CHART//_/ }"
EXISTING_TIF="$(find "$RAW_DIR" -maxdepth 1 \
    \( -iname "${CHART}*SEC.tif" -o -iname "${CHART_NOUS}*SEC.tif" \) \
    -not -iname "*_3857*" -not -iname "*_rgb*" 2>/dev/null | head -1)"
if [ -n "$EXISTING_TIF" ]; then
  echo ">>> Reusing existing TIF: $EXISTING_TIF"
else
  echo ">>> Downloading $CHART from $URL"
  curl -A "Mozilla/5.0" -L --fail -o "$RAW_DIR/${CHART}.zip" "$URL"
  echo ">>> Unzipping"
  unzip -o "$RAW_DIR/${CHART}.zip" -d "$RAW_DIR/"
fi

# AeroNav names files as e.g. "Charlotte SEC.tif" or "Las Vegas SEC.tif"
# — spaces in the filename even though the URL slug uses underscores.
# Try both forms.
CHART_NOUS="${CHART//_/ }"
TIF_SRC="$(find "$RAW_DIR" -maxdepth 1 \
    \( -iname "${CHART}*.tif" -o -iname "${CHART_NOUS}*.tif" \) \
    -not -iname "*_3857*" -not -iname "*_rgb*" | head -1)"
if [ -z "$TIF_SRC" ]; then
  echo "ERROR: no GeoTIFF found in $RAW_DIR for $CHART (tried '${CHART}*' and '${CHART_NOUS}*')" >&2
  exit 3
fi

TIF_3857="$RAW_DIR/${CHART}_3857.tif"
TIF_RGB="$RAW_DIR/${CHART}_3857_rgb.tif"

echo ">>> Reprojecting to Web Mercator: $TIF_SRC -> $TIF_3857"
gdalwarp -overwrite -t_srs EPSG:3857 -r bilinear -dstalpha \
  -co COMPRESS=DEFLATE -co TILED=YES \
  "$TIF_SRC" "$TIF_3857"

echo ">>> Expanding color table to RGBA: $TIF_3857 -> $TIF_RGB"
gdal_translate -expand rgba "$TIF_3857" "$TIF_RGB" \
  -co COMPRESS=DEFLATE -co TILED=YES

echo ">>> Generating XYZ tile pyramid (zooms $ZOOMS): $TIF_RGB -> $TILES_DIR"
gdal2tiles.py --xyz -z "$ZOOMS" --processes=4 "$TIF_RGB" "$TILES_DIR"

echo ">>> Cleaning intermediate files (keep the source TIF for reference)"
rm -f "$TIF_3857" "$TIF_RGB"

# Marker so build_all_conus.sh skips this chart on re-runs.
touch "$TILES_DIR/.built_${CHART}"

N_TILES="$(find "$TILES_DIR" -name "*.png" | wc -l | tr -d ' ')"
SIZE="$(du -sh "$TILES_DIR" | awk '{print $1}')"
echo ""
echo "================================================"
echo "Done. $CHART -> tiles/$LAYER/"
echo "  $N_TILES tiles, $SIZE total"
echo ""
echo "Restart the server to pick up new layers:"
echo "  lsof -ti tcp:8050 | xargs kill -9; python app.py"
echo "================================================"
