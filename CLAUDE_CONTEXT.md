# Claude Context: tallyaero_overlay_tools

## App Purpose

The Overlay Tools app generates visual maneuver overlays for flight training. It creates standardized maneuver diagrams that can be overlaid on sectional charts or used as standalone training aids.

## Key Features
- Maneuver trajectory visualization
- Standard maneuver patterns (turns, stalls, chandelles, lazy 8s, etc.)
- Physics-based flight path simulation
- Export to various formats
- Customizable aircraft parameters

## Tech Stack
- **Framework**: Python Dash
- **Physics**: Custom flight dynamics simulation
- **Visualization**: Plotly/custom rendering
- **Entry Point**: `app.py`

## Ecosystem Position

This is a **standalone app** for generating training materials. Could integrate with:
- `tallyaero_logbook` - Attach overlays to flight records
- `tallyaero_website` - Embed interactive tool
- Syllabus node - Visual aids for lesson plans

## Key Files

```
tallyaero_overlay_tools/
├── _ecosystem/              # Synced from master
│   └── docs/
├── CLAUDE_CONTEXT.md        # This file
├── app.py                   # Main Dash application
├── tallyaero_tracker.py      # Analytics/tracking
├── aircraft_data/           # Aircraft profiles
├── airports/                # Airport data
├── assets/                  # Static assets
├── callbacks/               # Dash callbacks
├── core/                    # Core calculations
├── data/                    # Maneuver data
├── layouts/                 # UI layouts
├── physics/                 # Flight physics engine
├── rendering/               # Visual rendering
├── simulation/              # Flight simulation
├── scripts/                 # Utility scripts
├── utils/                   # Helper utilities
├── requirements.txt         # Python dependencies
└── wsgi.py                  # WSGI entry point
```

## Maneuver Standards

See `MANEUVER_STANDARD.md` for:
- ACS/PTS standards for each maneuver
- Entry/exit parameters
- Tolerances
- Visual representation specs

## Current Sprint

- [ ] Per `NEXT_TASK.md` priorities
- [ ] Additional maneuver types
- [ ] Improved rendering
- [ ] Export formats

## Local Development

| Service | Port | URL |
|---------|------|-----|
| Dash App | 8050 | http://localhost:8050 |

```bash
# Start app
python app.py
```

## Development Notes

- Run with: `python app.py`
- See `_ecosystem/docs/PORT_ALLOCATION.md` for full port assignments
- See `Master prompt and context.md` for detailed context
- See `Lessons_learned.md` for development history
- Physics engine in `physics/` and `simulation/`

## Locked decisions

- **D3 — No telemetry.** This tool makes no analytics or tracking HTTP calls.
  Functional network calls (NOAA AWC, Open-Meteo) are explicit user-initiated
  features. `tallyaero_tracker.py` and its heartbeat script were removed in
  Phase 0g.
