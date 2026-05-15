#!/usr/bin/env bash
#
# Phase 6S — Sign + notarize + staple the TallyAero EM macOS bundle.
#
# Prerequisites (one-time setup):
#   1. Apple Developer ID Application certificate in your login keychain.
#      Verify with: security find-identity -v -p codesigning
#   2. App-specific password stored in keychain via:
#        xcrun notarytool store-credentials TALLYAERO_NOTARY \
#          --apple-id you@example.com \
#          --team-id ABCDE12345 \
#          --password "xxxx-xxxx-xxxx-xxxx"
#
# Run:
#   make build                     # creates dist/TallyAero EM.app
#   bash scripts/sign_macos.sh    # signs + notarizes + staples
#
# After this completes you can hand `dist/TallyAero EM.app` to anyone
# on macOS and Gatekeeper will accept it without warning.

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
APP="$ROOT/dist/TallyAero EM.app"
ENTITLEMENTS="$ROOT/scripts/entitlements.plist"

# --- env / cert resolution -----------------------------------------------
: "${TALLYAERO_SIGN_ID:=}"
if [[ -z "$TALLYAERO_SIGN_ID" ]]; then
  # Auto-pick the first Developer ID Application cert in the keychain.
  TALLYAERO_SIGN_ID="$(security find-identity -v -p codesigning \
    | grep -m1 "Developer ID Application" \
    | sed -E 's/.*"(Developer ID Application: [^"]+)".*/\1/')"
fi
if [[ -z "$TALLYAERO_SIGN_ID" ]]; then
  echo "ERROR: no 'Developer ID Application' certificate found in keychain." >&2
  echo "       Run: security find-identity -v -p codesigning" >&2
  exit 1
fi
echo "==> Signing identity: $TALLYAERO_SIGN_ID"

: "${TALLYAERO_NOTARY_PROFILE:=TALLYAERO_NOTARY}"

if [[ ! -d "$APP" ]]; then
  echo "ERROR: $APP not found. Run 'make build' first." >&2
  exit 1
fi

# --- entitlements (hardened runtime) -------------------------------------
mkdir -p "$(dirname "$ENTITLEMENTS")"
cat > "$ENTITLEMENTS" <<'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <!-- Required for Python embedded apps to allow Just-In-Time compilation -->
    <key>com.apple.security.cs.allow-unsigned-executable-memory</key><true/>
    <key>com.apple.security.cs.allow-jit</key><true/>
    <!-- The launcher fetches METAR from NOAA AWC and the version JSON -->
    <key>com.apple.security.network.client</key><true/>
    <!-- Server socket for the local Dash app -->
    <key>com.apple.security.network.server</key><true/>
</dict>
</plist>
EOF

# --- sign every Mach-O inside the bundle (deepest first) -----------------
echo "==> Codesigning bundle contents"
find "$APP" -type f \( -name "*.dylib" -o -name "*.so" -o -name "Python*" \
                  -o -name "*.framework" -o -perm -u+x \) 2>/dev/null \
  | while read -r f; do
    codesign --force --options runtime --timestamp \
      --sign "$TALLYAERO_SIGN_ID" \
      --entitlements "$ENTITLEMENTS" \
      "$f" 2>&1 | grep -v "is already signed" || true
  done

# Sign the bundle itself last
codesign --force --options runtime --timestamp \
  --sign "$TALLYAERO_SIGN_ID" \
  --entitlements "$ENTITLEMENTS" \
  "$APP"

echo "==> Verifying signature"
codesign --verify --deep --strict --verbose=2 "$APP"
echo "    OK"

# --- notarize -------------------------------------------------------------
echo "==> Zipping for notarization upload"
ZIP="$ROOT/dist/TallyAero EM.zip"
ditto -c -k --keepParent "$APP" "$ZIP"

echo "==> Submitting to Apple notary service (this can take a few minutes)"
xcrun notarytool submit "$ZIP" \
  --keychain-profile "$TALLYAERO_NOTARY_PROFILE" \
  --wait

echo "==> Stapling notarization ticket"
xcrun stapler staple "$APP"
xcrun stapler validate "$APP"

echo "==> Done. Signed + notarized: $APP"
