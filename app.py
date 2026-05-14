"""TallyAero Maneuver Overlay Tool — entry point.

After Phase 1 decomposition (Apr-May 2026), this module is just the
plumbing: Dash instantiation, the global layout shell, the callback
wiring hook, and the __main__ runner. Every callback now lives under
`callbacks/` and every page layout under `layouts/`.

Import side-effect note: `callbacks` (via `register_all`) imports the
domain modules, which in turn import `core.data_loader`. The loader
auto-runs `init_data()` at module load time, so aircraft + airport
caches are populated before any callback fires.
"""

import dash
from dash import dcc, html
import dash_bootstrap_components as dbc

from core.log import get_logger

# Re-export data caches so external smoke tests can introspect them on
# `app` directly (tests/test_smoke.py asserts `app.aircraft_data == {}`
# when TALLYAERO_NO_AUTO_INIT is set). The loader module is the source
# of truth; this import is also what triggers the auto-init side-effect
# under normal startup.
from core.data_loader import aircraft_data, airport_data  # noqa: F401

log = get_logger(__name__)

# === Dash App ===
app = dash.Dash(
    __name__,
    external_stylesheets=[dbc.themes.BOOTSTRAP],
    suppress_callback_exceptions=True,
    prevent_initial_callbacks="initial_duplicate",
)
server = app.server

# Wire every callback decomposed out of this file during Phase 1.
# Order is for readability only — Dash fires callbacks by input graph.
from callbacks import register_all
register_all(app)

app.title = "Maneuver Overlay Tool | TallyAero"

app.index_string = """
<!DOCTYPE html>
<html>
    <head>
        {%metas%}
        <title>{%title%}</title>
        {%favicon%}
        {%css%}
    </head>
    <body>
        {%app_entry%}
        <footer>
            {%config%}
            {%scripts%}
            {%renderer%}
        </footer>
    </body>
</html>
"""


# === Root Layout with Routing ===
# The router callback in callbacks/navigation.py swaps `page-content` based
# on URL pathname + screen width. Everything else lives below that node.
app.layout = html.Div([
    dcc.Location(id="url", refresh=False),
    dcc.Store(id="screen-width"),
    html.Div(id="page-content"),
])


if __name__ == "__main__":
    # host="0.0.0.0" allows access from other devices on the network.
    # Port is overridable via CLI arg (used by `make run PORT=8052`).
    import sys
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8050
    app.run(debug=True, host="0.0.0.0", port=port)
