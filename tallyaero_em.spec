# -*- mode: python ; coding: utf-8 -*-
"""
TallyAero EM Diagram — PyInstaller spec.

Build a one-directory bundle:
    venv/bin/python -m PyInstaller tallyaero_em.spec --noconfirm

Output:
    dist/TallyAero EM/                   (one-dir bundle, ~150 MB)
    dist/TallyAero EM.app/               (macOS app bundle, wraps the above)

The .app is **unsigned**. Signing/notarization require a Developer ID
certificate; see BUILD.md for the steps once a cert is available.
"""

from pathlib import Path
import sys

# PyInstaller injects `block_cipher`, `Analysis`, `PYZ`, `EXE`, `COLLECT`,
# `BUNDLE` into this scope at build time. The IDE will complain — fine.

block_cipher = None
PROJECT_ROOT = Path.cwd()


# ---------------------------------------------------------------------------
# Data files: aircraft data, airports, assets, VERSION, LICENSE, raw assets.
# Each entry is (source_glob_or_path, target_dir_inside_bundle).
# ---------------------------------------------------------------------------
# Phase 6S: aircraft_data and airports are symlinks into the _data submodule
# at top level (Phase 5AE migration). PyInstaller doesn't follow symlinks
# when building datas, so we point at the real submodule paths and use the
# symlink target name as the bundle destination.
datas = [
    ("_data/aircraft_data",   "aircraft_data"),
    ("_data/airports",        "airports"),
    ("assets",                "assets"),
    ("VERSION",               "."),
    ("PHYSICS_AUDIT_PLAN.md", "."),
]
if (PROJECT_ROOT / "LICENSE").exists():
    datas.append(("LICENSE", "."))


# ---------------------------------------------------------------------------
# Hidden imports — packages PyInstaller's static analysis can't find on
# its own because the app loads them dynamically (Dash callback registry,
# Plotly's adaptive renderer choice, etc.).
# ---------------------------------------------------------------------------
hiddenimports = [
    # Dash + Bootstrap stack
    "dash",
    "dash.dependencies",
    "dash.dcc",
    "dash.html",
    "dash.dash_table",
    "dash_bootstrap_components",
    # Plotly + figure stack
    "plotly",
    "plotly.graph_objects",
    "plotly.express",
    "plotly.io",
    "plotly.io._kaleido",
    "kaleido",
    # Numerics
    "numpy",
    "numpy.core",
    "pandas",
    # Schema / validation
    "pydantic",
    "pydantic_core",
    "jsonschema",
    # Web stack
    "flask",
    "werkzeug",
    "werkzeug.serving",
    # Our own packages — explicit so they survive the .pyc compilation step
    "core",
    "callbacks",
    "layouts",
    "components",
    "services",
]


# ---------------------------------------------------------------------------
# Exclusions — trim weight by dropping packages we don't import.
# ---------------------------------------------------------------------------
excludes = [
    "matplotlib",
    "scipy",
    "tkinter",
    "PySide2", "PySide6",
    "PyQt5", "PyQt6",
    "IPython",
    "notebook",
    "tornado",   # only needed by Jupyter
    "pandas",    # Phase 6: zero imports across our source tree; saves ~19 MB
    "pytz",      # Pulled in by pandas; not used directly
    "test",
    "tests",
]


a = Analysis(
    ["launcher.py"],
    pathex=[str(PROJECT_ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="TallyAero EM",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,                       # UPX is finicky on macOS arm64; skip
    console=False,                   # windowed app — no terminal popup
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,          # signed in a separate step; see BUILD.md
    entitlements_file=None,
    # Phase 6S: branded icon. PyInstaller picks .icns on macOS, .ico on Windows,
    # ignores when neither file exists.
    icon=[
        str(PROJECT_ROOT / "assets" / "branding" / "tallyaero.icns"),
        str(PROJECT_ROOT / "assets" / "branding" / "tallyaero.ico"),
    ],
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="TallyAero EM",
)

# Build a real macOS .app bundle on Darwin so the user gets a draggable icon.
if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name="TallyAero EM.app",
        icon=str(PROJECT_ROOT / "assets" / "branding" / "tallyaero.icns"),
        bundle_identifier="com.tallyaero.em-diagram",
        info_plist={
            "CFBundleName":                "TallyAero EM Diagram",
            "CFBundleDisplayName":         "TallyAero EM Diagram",
            "CFBundleShortVersionString":  (PROJECT_ROOT / "VERSION").read_text().strip(),
            "CFBundleVersion":             (PROJECT_ROOT / "VERSION").read_text().strip(),
            "NSHighResolutionCapable":     True,
            "LSMinimumSystemVersion":      "11.0",
            # We don't phone home; explicitly declare no network usage description
            # need (Dash listens locally; the only outbound call is the optional
            # NOAA AWC METAR fetch, which happens on user gesture).
            "NSAppleEventsUsageDescription": "TallyAero EM does not use Apple Events.",
        },
    )
