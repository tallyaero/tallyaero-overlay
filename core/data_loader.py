"""Aircraft + airport data loaders. Pure I/O, no Dash dependency.

Module-level state lives here (not in app.py) so callback modules can
`from core.data_loader import aircraft_data, airport_data` without
triggering the `import app` circular re-entry that would otherwise
cascade through 13 callback files.

`init_data()` mutates the module-level dicts/lists IN PLACE rather than
reassigning, so any callsite that captures `aircraft_data` at import
time still sees the populated data after init runs.

Auto-init at import time can be disabled by setting
TALLYAERO_NO_AUTO_INIT in the environment (used by tests).
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from core.log import get_logger

log = get_logger(__name__)

ROOT = Path(__file__).resolve().parent.parent

# Module-level state — populated in place by init_data().
# Other modules must `from core.data_loader import aircraft_data` and
# read at callback-fire time, NOT capture-by-value at import time.
aircraft_data: dict = {}
available_aircraft: list = []
airport_data: list = []
navaid_data: list = []
fix_data: list = []


def load_aircraft_data(folder: str = "aircraft_data") -> dict:
    """Read every aircraft_data/*.json into a dict keyed by basename."""
    data = {}
    folder_path = ROOT / folder
    for filename in os.listdir(folder_path):
        if filename.endswith(".json"):
            with open(folder_path / filename) as f:
                name = filename.replace(".json", "")
                data[name] = json.load(f)
    return data


def load_airport_data() -> list:
    """Read airports/airports.json."""
    path = ROOT / "airports" / "airports.json"
    with open(path, "r") as f:
        return json.load(f)


def _load_optional_json(rel_path: str) -> list:
    """Returns [] if the bundle isn't present — keeps the app bootable
    on a fresh checkout before data ingest has been run."""
    path = ROOT / rel_path
    if not path.is_file():
        return []
    try:
        with open(path, "r") as f:
            return json.load(f)
    except Exception as e:
        log.warning("Could not parse %s: %s", rel_path, e)
        return []


def init_data() -> None:
    """Populate the module-level caches IN PLACE.

    Idempotent. Mutates `aircraft_data`, `available_aircraft`, `airport_data`,
    `navaid_data`, and `fix_data` in place so callers that captured them at
    import time still see the populated values.
    """
    if aircraft_data:
        return  # already populated
    aircraft_data.update(load_aircraft_data())
    available_aircraft.extend(sorted(aircraft_data.keys()))
    airport_data.extend(load_airport_data())
    navaid_data.extend(_load_optional_json("data/navaids/navaids.json"))
    fix_data.extend(_load_optional_json("data/navaids/fixes.json"))
    log.info("Loaded %s aircraft + %s airports + %s NAVAIDs + %s fixes",
             len(aircraft_data), len(airport_data),
             len(navaid_data), len(fix_data))


# Auto-init at import unless explicitly disabled (tests).
if not os.environ.get("TALLYAERO_NO_AUTO_INIT"):
    init_data()
