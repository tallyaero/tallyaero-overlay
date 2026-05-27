# Callback Audit — `prevent_initial_call`

Audit completed 2026-05-12 as part of Phase 0 step 6.

## Summary

| Status | Count |
|---|---:|
| `prevent_initial_call=True` (deliberate) | 54 |
| Fires on load (deliberate — see "legitimate" below) | 7 |
| Fires on load (audit gap, fixed in this pass) | 8 → 0 |
| **Total `@app.callback` in app.py** | **61** |

## Callbacks that legitimately fire on initial page load

These intentionally do NOT have `prevent_initial_call=True` because the EM-diagram needs to render *something* the moment the page loads.

| Line | Function | Why it fires on load |
|---:|---|---|
| 806 | `display_page` | Router — sets initial page layout from the URL pathname. |
| 853 | `update_aircraft_options` | Populates the aircraft dropdown from `dcc.Store(aircraft-data-store)`. |
| 1078 | `update_pa_da_display` | Shows initial Pressure Altitude / Density Altitude using default altitude+OAT+altimeter. |
| 1130 | `update_oat_fahrenheit` | Mirrors the default OAT (°C) into the °F display. |
| 1243 | `update_total_weight` | Shows initial weight calc (empty + default fuel + default occupants). |
| 1506 | `update_graph` | **The sacred chart function.** Must render once with defaults so the user lands on a working diagram. |
| 3750 | `get_browser_width` | Detects viewport width on page load to choose mobile vs desktop layout. |

## Callbacks fixed in this audit pass

Added `prevent_initial_call=True` — outputs cleanly depend on user-driven state (aircraft selection, maneuver selection) that is `None` before the user acts:

| Line | Function | Reason |
|---:|---|---|
| 866 | `update_category_dropdown` | `aircraft-select` value is `None` on load. |
| 882 | `expand_ui_on_aircraft_select` | Triggers UI accordion expansion only after a pick. |
| 968 | `update_aircraft_dependent_inputs` | Engine/occupants/fuel/altitude derived from aircraft. |
| 1143 | `render_cg_slider` | CG slider geometry comes from aircraft JSON. |
| 1205 | `update_config_dropdown` | Config options come from aircraft JSON. |
| 1219 | `update_gear_dropdown` | Gear options come from aircraft JSON. |
| 1234 | `toggle_gear_selector_visibility` | Shows the selector only if the aircraft has retractable gear. |
| 3273 | `render_maneuver_options` | Maneuver-specific controls render only when a maneuver is chosen. |

Also normalized two callbacks that had a missing trailing comma on their last `Input(...)` arg (cosmetic — Python tolerates it, but the audit script flagged it).

## Phase 1 follow-up

When `app.py` decomposes into `callbacks/*` modules (Phase 1), audit every callback in its new home and re-run the enumeration. The enumeration script lives in this folder if regenerated:

```python
# Quick re-audit:
venv/bin/python -c "
import re
from pathlib import Path
src = Path('app.py').read_text()
n = src.count('@app.callback')
pic = sum(1 for m in re.finditer(r'@app\.callback\([^)]+\)', src, re.S) if 'prevent_initial_call' in m.group())
print(f'{pic}/{n} have prevent_initial_call set')
"
```
