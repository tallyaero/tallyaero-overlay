# Building TallyAero EM Diagram

Phase 6 + 6S deliverable. This document covers turning the source tree
into a downloadable, signed, browser-launching desktop bundle for
macOS and Windows.

---

## Quick build (unsigned, local development)

```bash
make install-build    # one-time: installs PyInstaller into ./venv
make build            # produces dist/TallyAero EM/ + dist/TallyAero EM.app
```

First launch picks a free localhost port, starts the Dash server in a
background thread, waits for it to respond, then opens the user's default
browser to that URL. The launcher (`launcher.py`) survives until the user
quits via the dock.

Expected bundle size on Apple Silicon: **~385 MB** unsigned. Most of the
weight is `kaleido` (bundled Chromium for server-side PNG/PDF export).

---

## Full macOS ship pipeline

Prerequisites — one-time:

1. **Apple Developer Program** membership and a **Developer ID Application**
   certificate installed in your login keychain. Verify with:
   ```bash
   security find-identity -v -p codesigning
   ```
   You should see something like
   `1) ABCD1234... "Developer ID Application: TallyAero (TEAMID)"`.

2. **App-specific password** stored as a notarytool keychain profile named
   `TALLYAERO_NOTARY`:
   ```bash
   xcrun notarytool store-credentials TALLYAERO_NOTARY \
     --apple-id you@example.com \
     --team-id ABCDE12345 \
     --password "xxxx-xxxx-xxxx-xxxx"
   ```

3. **ImageMagick** (only needed for Windows `.ico` generation):
   ```bash
   brew install imagemagick
   ```

Then one command builds, signs, notarizes, and wraps the app in a draggable
DMG:

```bash
make ship-mac
```

That runs in order:
- `make build-clean` — clear previous artefacts
- `make icons` — `scripts/build_icons.sh` → `.icns` + `.ico`
- `make build` — PyInstaller bundle
- `make sign` — `scripts/sign_macos.sh` (codesign + notarize + staple)
- `make dmg` — `scripts/build_dmg.sh` (drag-to-Applications DMG)

Final artefact: `dist/TallyAero-EM-v<version>.dmg`. Notarization is stapled,
so the DMG works offline on a fresh Mac without any Gatekeeper warning.

---

## Windows build (GitHub Actions)

There's no Windows Authenticode cert yet, so we build unsigned bundles via
the free GitHub Actions Windows runner. The workflow is
`.github/workflows/build-windows.yml`. It runs automatically on any `v*`
tag push:

```bash
echo "0.2.0" > VERSION
git commit -am "bump v0.2.0"
git tag v0.2.0
git push origin main --tags
```

GitHub Actions then:
1. Checks out the repo (submodules included).
2. Replaces the `_data` symlinks with direct copies (Windows can't follow
   them).
3. Builds `dist/TallyAero EM/` via PyInstaller.
4. Zips the bundle as `TallyAero-EM-v<version>-win-x64.zip`.
5. Attaches the ZIP to the GitHub Release for that tag.

To test the workflow without tagging, use the **Run workflow** button in
the Actions UI (it dispatches on `workflow_dispatch`).

**User experience on first run (Windows):** SmartScreen shows "Windows
protected your PC" because the .exe isn't Authenticode-signed. The user
clicks **More info → Run anyway**. Modern users know this pattern from
indie software; an Authenticode cert ($200-500/yr) can be added later.

---

## Update-check banner

The bundled app fetches `https://tallyaero.com/em-version.json` on every
launch. Expected schema:

```json
{
  "latest_version": "0.2.0",
  "release_notes":  "Improved Ps accuracy, new aircraft.",
  "download_url":   "https://tallyaero.com/em-diagram/download"
}
```

If the installed version is older than `latest_version`, a banner appears
at the top of the page with a Download link. The user can dismiss for a
specific version (localStorage flag) so they aren't nagged on every
reload of the same outdated build.

Update the JSON every time you publish a new build. Hosting requirements:
- Public URL
- `Access-Control-Allow-Origin: *` so the bundle (running at
  `http://127.0.0.1:<port>`) can fetch it cross-origin

---

## Hosting + distribution

We host the installers directly on `tallyaero.com`:

- `tallyaero.com/em-diagram/download/mac` → `TallyAero-EM-v<latest>.dmg`
- `tallyaero.com/em-diagram/download/win` → `TallyAero-EM-v<latest>-win-x64.zip`
- `tallyaero.com/em-version.json` → the update manifest

The ATLAS app links to `/em-diagram/download` and lets the user pick
their platform.

---

## Ship checklist

1. Bump `VERSION` (semver).
2. Update tallyaero-data submodule if any aircraft / airport data changed:
   ```bash
   cd _data && git pull origin main && cd ..
   git add _data && git commit -m "chore: bump shared-data submodule"
   ```
3. Run the full pipeline:
   ```bash
   make ship-mac
   ```
4. Tag and push (triggers Windows build on Actions):
   ```bash
   git tag v$(cat VERSION)
   git push origin main --tags
   ```
5. Wait for the Actions run to finish, grab the Windows ZIP from the
   release assets.
6. Upload `dist/TallyAero-EM-v*.dmg` and the Windows ZIP to
   `tallyaero.com/em-diagram/download/`.
7. Update `tallyaero.com/em-version.json` to the new version.
8. Test on a clean Mac (no Gatekeeper warning) and a clean Windows
   machine (SmartScreen click-through, then run).

---

## Sanity-test the unsigned build

After `make build`:

1. Open `dist/TallyAero EM.app` (macOS) — first time will require
   right-click → Open to bypass Gatekeeper because unsigned.
2. Browser opens to a free localhost port (random, e.g. `:59756`).
3. EM Diagram renders.
4. Pick Cessna 172P, slide altitude, see the chart respond.
5. Open the drawer (`D` key), tweak overlays.
6. Test PNG export — confirms kaleido is bundled correctly.

If any of those fail, the missing piece is usually a hidden import that
PyInstaller's static analysis missed. To debug, run the launcher directly
from terminal so output is visible:

```bash
./dist/TallyAero\ EM.app/Contents/MacOS/TallyAero\ EM
```
