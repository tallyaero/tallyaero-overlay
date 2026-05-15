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

# Phase 4 — Theme system + early-paint mirror the EM Diagram. The inline
# <script> reads localStorage and sets data-theme on <html> before first
# paint to prevent flash-of-unstyled-content. The toggle UI and the
# syncThemeFromStorage clientside callback read the same key.
app.index_string = """
<!DOCTYPE html>
<html>
    <head>
        {%metas%}
        <title>{%title%}</title>
        {%favicon%}
        {%css%}
        <script>
        (function() {
          var pref = localStorage.getItem('tallyaero_theme') || 'light';
          var resolved = pref;
          if (pref === 'system') {
            resolved = window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
          }
          document.documentElement.setAttribute('data-theme', resolved);
          document.documentElement.setAttribute('data-theme-pref', pref);
        })();
        </script>
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
    # Phase 4: theme preference. Seeded by the early-paint <script> from
    # localStorage; the syncThemeFromStorage clientside callback mirrors
    # the same value into this Store after layout mounts. Light is default.
    dcc.Store(id="theme-pref", storage_type="local", data="light"),
    html.Div(id="page-content"),
])


# === Theme clientside callbacks ===
# These wire to button IDs that the layouts will introduce in Batch 2.
# Registered conditionally so a stray missing button doesn't crash the
# callback graph during the transition.
from dash import ClientsideFunction, Input, Output

app.clientside_callback(
    ClientsideFunction(namespace="tallyaero", function_name="cycleTheme"),
    [
        Output("theme-pref", "data", allow_duplicate=True),
        Output("theme-btn-auto", "className"),
        Output("theme-btn-light", "className"),
        Output("theme-btn-dark", "className"),
    ],
    [
        Input("theme-btn-auto", "n_clicks"),
        Input("theme-btn-light", "n_clicks"),
        Input("theme-btn-dark", "n_clicks"),
    ],
    prevent_initial_call=True,
)

app.clientside_callback(
    ClientsideFunction(namespace="tallyaero", function_name="syncThemeFromStorage"),
    Output("theme-pref", "data", allow_duplicate=True),
    Input("url", "pathname"),
    prevent_initial_call="initial_duplicate",
)

# Note: screen-width is registered in callbacks/navigation.py — keep one
# canonical source so we don't double-register the same Output.


if __name__ == "__main__":
    # host="0.0.0.0" allows access from other devices on the network.
    # Port is overridable via CLI arg (used by `make run PORT=8052`).
    import sys
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8050
    app.run(debug=True, host="0.0.0.0", port=port)
