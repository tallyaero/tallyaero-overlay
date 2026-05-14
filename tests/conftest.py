"""Pytest config + shared fixtures for the Maneuver Overlay Tool."""

import os
import sys
from pathlib import Path

# Tests load a curated aircraft subset, not the full 115-file fleet.
os.environ.setdefault("TALLYAERO_NO_AUTO_INIT", "1")

# Make the repo root importable.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
