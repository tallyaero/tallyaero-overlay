#!/usr/bin/env bash
#
# Phase 6S — Generate platform icon files from the master 1024×1024 PNG.
#
# Inputs:
#   assets/branding/tallyaero-icon-1024.png
#
# Outputs:
#   assets/branding/tallyaero.icns   (macOS)
#   assets/branding/tallyaero.ico    (Windows)
#
# Uses macOS native `sips` + `iconutil` (no extra deps) for .icns,
# and ImageMagick `magick` (or `convert`) for .ico. If you don't have
# ImageMagick, the .ico step is skipped and a warning is printed.
#
# Run from repo root:
#   bash scripts/build_icons.sh

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BRAND="$ROOT/assets/branding"
SRC="$BRAND/tallyaero-icon-1024.png"

if [[ ! -f "$SRC" ]]; then
  echo "Missing source: $SRC" >&2
  exit 1
fi

echo "==> Building macOS .icns from $SRC"
ICONSET="$BRAND/tallyaero.iconset"
rm -rf "$ICONSET" && mkdir -p "$ICONSET"

# Apple wants 10 sizes inside the .iconset directory; iconutil packs them.
sips -z   16   16 "$SRC" --out "$ICONSET/icon_16x16.png"        >/dev/null
sips -z   32   32 "$SRC" --out "$ICONSET/icon_16x16@2x.png"     >/dev/null
sips -z   32   32 "$SRC" --out "$ICONSET/icon_32x32.png"        >/dev/null
sips -z   64   64 "$SRC" --out "$ICONSET/icon_32x32@2x.png"     >/dev/null
sips -z  128  128 "$SRC" --out "$ICONSET/icon_128x128.png"      >/dev/null
sips -z  256  256 "$SRC" --out "$ICONSET/icon_128x128@2x.png"   >/dev/null
sips -z  256  256 "$SRC" --out "$ICONSET/icon_256x256.png"      >/dev/null
sips -z  512  512 "$SRC" --out "$ICONSET/icon_256x256@2x.png"   >/dev/null
sips -z  512  512 "$SRC" --out "$ICONSET/icon_512x512.png"      >/dev/null
cp "$SRC"                  "$ICONSET/icon_512x512@2x.png"

iconutil -c icns "$ICONSET" -o "$BRAND/tallyaero.icns"
rm -rf "$ICONSET"
echo "    wrote $BRAND/tallyaero.icns"

echo "==> Building Windows .ico"
if command -v magick >/dev/null 2>&1; then
  magick "$SRC" -define icon:auto-resize=256,128,64,48,32,16 "$BRAND/tallyaero.ico"
  echo "    wrote $BRAND/tallyaero.ico"
elif command -v convert >/dev/null 2>&1; then
  convert "$SRC" -define icon:auto-resize=256,128,64,48,32,16 "$BRAND/tallyaero.ico"
  echo "    wrote $BRAND/tallyaero.ico"
else
  echo "    SKIP: ImageMagick not installed (\`brew install imagemagick\`)." >&2
  echo "    Windows .ico not generated. macOS build will still work." >&2
fi

echo "Done."
