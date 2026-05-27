#!/usr/bin/env bash
#
# Phase 6S — Wrap the signed .app into a draggable .dmg installer.
#
# Run after `bash scripts/sign_macos.sh` so the .app is signed + notarized;
# the resulting DMG inherits that trust.
#
# Output: dist/TallyAero-EM-vX.Y.Z.dmg

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
APP="$ROOT/dist/TallyAero EM.app"
VERSION="$(cat "$ROOT/VERSION" | tr -d '[:space:]')"
DMG="$ROOT/dist/TallyAero-EM-v${VERSION}.dmg"
STAGING="$ROOT/dist/dmg_stage"

if [[ ! -d "$APP" ]]; then
  echo "ERROR: $APP not found. Run 'make build' first." >&2
  exit 1
fi

echo "==> Staging DMG contents at $STAGING"
rm -rf "$STAGING"
mkdir -p "$STAGING"
cp -R "$APP" "$STAGING/"
ln -s /Applications "$STAGING/Applications"

echo "==> Building DMG → $DMG"
rm -f "$DMG"
hdiutil create \
  -volname "TallyAero EM v${VERSION}" \
  -srcfolder "$STAGING" \
  -ov \
  -format UDZO \
  "$DMG"

rm -rf "$STAGING"

# Sign the DMG itself so Gatekeeper accepts the download too.
: "${TALLYAERO_SIGN_ID:=}"
if [[ -z "$TALLYAERO_SIGN_ID" ]]; then
  TALLYAERO_SIGN_ID="$(security find-identity -v -p codesigning \
    | grep -m1 "Developer ID Application" \
    | sed -E 's/.*"(Developer ID Application: [^"]+)".*/\1/')"
fi
if [[ -n "$TALLYAERO_SIGN_ID" ]]; then
  echo "==> Signing the DMG with $TALLYAERO_SIGN_ID"
  codesign --force --sign "$TALLYAERO_SIGN_ID" --timestamp "$DMG"
fi

echo "==> Done. Installer: $DMG"
ls -lh "$DMG"
