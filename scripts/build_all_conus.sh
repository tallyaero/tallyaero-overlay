#!/usr/bin/env bash
# Build the full CONUS sectional set. Skips charts already tiled
# (won't re-download/process Charlotte etc.). Serial — gdal2tiles
# already uses 4 worker processes inside.
#
# Output: tiles/sectional/{z}/{x}/{y}.png — all sectionals merged
# into one XYZ pyramid that auto-stitches at chart-edge seams.
#
# Run time: ~2-3 hours, ~15-20 GB tile output.
# Usage:    scripts/build_all_conus.sh [cycle_date]

set -euo pipefail

CYCLE="${1:-05-14-2026}"
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

# All 34 CONUS sectionals + Hawaiian Islands as of cycle 05-14-2026.
# Skipping Alaska / Canadian / Caribbean charts.
SECTIONALS=(
  Albuquerque Atlanta Billings Brownsville Charlotte Cheyenne
  Chicago Cincinnati Dallas-Ft_Worth Denver Detroit El_Paso
  Great_Falls Green_Bay Hawaiian_Islands Houston Jacksonville
  Kansas_City Klamath_Falls Las_Vegas Los_Angeles Memphis Miami
  New_Orleans New_York Omaha Phoenix Salt_Lake_City San_Antonio
  San_Francisco Seattle St_Louis Twin_Cities Washington Wichita
)

LOG="$REPO_ROOT/scripts/build_all_conus.log"
echo "Logging to $LOG"
date >> "$LOG"
echo "Cycle: $CYCLE" >> "$LOG"

TOTAL=${#SECTIONALS[@]}
i=0
DONE=0
SKIPPED=0
FAILED=0

for sec in "${SECTIONALS[@]}"; do
  i=$((i+1))
  printf "[%2d/%d] %s ..." "$i" "$TOTAL" "$sec" | tee -a "$LOG"

  # Skip if a marker file says we already built this chart.
  # build_chart_tiles.sh writes the marker on success.
  if [ -f "$REPO_ROOT/tiles/sectional/.built_${sec}" ]; then
    echo " skip (already built)" | tee -a "$LOG"
    SKIPPED=$((SKIPPED+1))
    continue
  fi

  if "$REPO_ROOT/scripts/build_chart_tiles.sh" "$sec" "$CYCLE" sectional \
       >> "$LOG" 2>&1; then
    echo " done" | tee -a "$LOG"
    DONE=$((DONE+1))
  else
    echo " FAILED (see log)" | tee -a "$LOG"
    FAILED=$((FAILED+1))
  fi
done

echo ""
echo "================================================" | tee -a "$LOG"
echo "Built $DONE   Skipped $SKIPPED   Failed $FAILED" | tee -a "$LOG"
du -sh "$REPO_ROOT/tiles/sectional/" | tee -a "$LOG"
echo "================================================" | tee -a "$LOG"
