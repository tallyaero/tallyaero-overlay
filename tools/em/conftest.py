"""
Top-level pytest config. Ensures the project root is on sys.path so
`from core.calculations import ...` works without installing the package.

This file deliberately lives at the repo root (not in tests/) so it is
applied to any pytest invocation in this project.
"""

import os
import sys

# Add project root to sys.path so `core`, `callbacks`, etc. resolve.
ROOT = os.path.dirname(os.path.abspath(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
