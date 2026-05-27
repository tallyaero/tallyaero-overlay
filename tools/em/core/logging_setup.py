"""
TallyAero structured logging.

Single place to wire up logging for the EM diagram (and, by way of the Shared
Asset Ledger, the overlay tool). Controlled by the `TALLYAERO_LOG` environment
variable:

    TALLYAERO_LOG=DEBUG    everything (formerly the dprint() debug spam)
    TALLYAERO_LOG=INFO     boot messages and feature usage (default in dev)
    TALLYAERO_LOG=WARNING  only warnings and errors (default in distribution)
    TALLYAERO_LOG=ERROR    errors only

Call `setup_logging()` once at app startup. Then anywhere in the codebase:

    from core.logging_setup import get_logger
    log = get_logger(__name__)
    log.debug("Ps min %.2f", ps_min)
    log.info("loaded %d aircraft", n)

Format includes timestamp, level, logger name, and message — appropriate for
both terminal and file capture without further configuration.
"""

from __future__ import annotations

import logging
import os
import sys
from typing import Optional

ROOT_LOGGER_NAME = "tallyaero"

# Cached state so repeated calls are idempotent.
_SETUP_DONE = False


def _resolve_level(env_value: Optional[str]) -> int:
    """Map the TALLYAERO_LOG env value to a logging level. Default WARNING."""
    if not env_value:
        return logging.WARNING
    candidate = env_value.strip().upper()
    return getattr(logging, candidate, logging.WARNING)


def setup_logging(level: Optional[int] = None) -> logging.Logger:
    """Configure the `tallyaero` logger tree. Idempotent.

    Args:
        level: Optional explicit level override. If None, reads TALLYAERO_LOG
               from the environment (default WARNING).

    Returns:
        The root tallyaero logger.
    """
    global _SETUP_DONE
    if level is None:
        level = _resolve_level(os.environ.get("TALLYAERO_LOG"))

    logger = logging.getLogger(ROOT_LOGGER_NAME)
    logger.setLevel(level)

    if not _SETUP_DONE:
        handler = logging.StreamHandler(stream=sys.stderr)
        handler.setFormatter(
            logging.Formatter(
                fmt="%(asctime)s %(levelname)-7s %(name)s — %(message)s",
                datefmt="%H:%M:%S",
            )
        )
        logger.addHandler(handler)
        logger.propagate = False  # Don't bubble to root (avoid duplicate prints)
        _SETUP_DONE = True

    return logger


def log_feature(event: str, payload: dict | None = None) -> None:
    """Telemetry hook — intentionally a no-op in the desktop build (D3).

    Call sites in app.py and callbacks/edit_aircraft.py use this for
    feature-level events ("aircraft_select", "diagram_export_pdf", etc.).
    The desktop binary ships with zero phone-home, so this is a no-op.
    Future internal builds can wire it to whatever sink — keep the signature
    stable so call sites never need to change.
    """
    _ = event, payload  # silence unused-arg linters


def get_logger(name: str = ROOT_LOGGER_NAME) -> logging.Logger:
    """Return a child logger under the `tallyaero` tree.

    Call with `__name__` from within a module:

        log = get_logger(__name__)

    The returned logger inherits the level and handler from `setup_logging()`.
    Safe to call before `setup_logging()` — the logger just won't emit until
    setup is done.
    """
    if name == ROOT_LOGGER_NAME or name.startswith(ROOT_LOGGER_NAME + "."):
        return logging.getLogger(name)
    return logging.getLogger(f"{ROOT_LOGGER_NAME}.{name}")
