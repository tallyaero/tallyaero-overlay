"""TallyAero Maneuver Overlay — structured logging.

Reads TALLYAERO_OVERLAY_LOG from the environment to set the root level.
Defaults to INFO. Use:

    from core.log import get_logger
    log = get_logger(__name__)
    log.info("starting simulation")
    log.warning("falling back to default")

The format is intentionally short for terminal readability: HH:MM:SS LEVEL
module — message.
"""

from __future__ import annotations

import logging
import os
import sys

_INITIALIZED = False


def _initialize() -> None:
    global _INITIALIZED
    if _INITIALIZED:
        return

    level_name = os.environ.get("TALLYAERO_OVERLAY_LOG", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)

    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter(
        fmt="%(asctime)s %(levelname)-7s %(name)s — %(message)s",
        datefmt="%H:%M:%S",
    ))

    root = logging.getLogger("tallyaero.overlay")
    root.setLevel(level)
    root.addHandler(handler)
    root.propagate = False

    _INITIALIZED = True


def get_logger(name: str) -> logging.Logger:
    """Return a child logger under the tallyaero.overlay namespace."""
    _initialize()
    return logging.getLogger(f"tallyaero.overlay.{name}")
