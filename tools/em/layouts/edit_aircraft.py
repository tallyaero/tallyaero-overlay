import dash
from dash import dcc, html
import dash_bootstrap_components as dbc
import json
import os
from dash.exceptions import PreventUpdate

# Import shared aircraft data from core module
from core import AIRCRAFT_DATA, aircraft_data


def create_field_row(label, component, width="100%"):
    """Helper to create a consistent field row"""
    return html.Div([
        html.Label(label, className="edit-field-label"),
        component
    ], className="edit-field-row", style={"width": width})


def create_inline_fields(fields):
    """Helper to create inline fields - list of (label, component, width) tuples"""
    return html.Div([
        html.Div([
            html.Label(label, className="edit-field-label-inline"),
            component
        ], style={"width": width, "marginRight": "12px"})
        for label, component, width in fields
    ], className="edit-inline-row")


# --- Full Edit Aircraft Page Layout ---
def edit_aircraft_layout():
    return html.Div([
        # Stores
        dcc.Store(id="stored-flap-configs", data=[]),
        dcc.Store(id="stored-g-limits", data=[]),
        dcc.Store(id="stored-stall-speeds", data=[]),
        dcc.Store(id="stored-single-engine-limits", data=[]),
        dcc.Store(id="stored-engine-options", data=[]),
        dcc.Store(id="stored-other-limits", data={}),
        dcc.Store(id="stored-oei-performance", data=[]),

        # Phase 5T: top strip — chip-style actions consistent with the main
        # page shell. Banner-header + disclaimer-banner-small removed (the
        # legal-disclaimer modal carries the educational-use disclaimer).
        html.Div([
            # Left cluster: brand + Back + currently editing
            html.Div([
                html.Span("TallyAero EM", className="top-strip-brand"),
                html.Button(
                    [html.Span("BACK", className="chip-prefix"),
                     html.Span("EM Diagram", className="chip-label")],
                    id="back-button", n_clicks=0,
                    className="env-chip", type="button",
                    title="Return to the EM Diagram (shortcut: Esc)",
                    **{"aria-label": "Return to main EM Diagram page"},
                ),
                html.Div(id="edit-page-title", className="edit-page-title"),
            ], className="top-strip-left"),

            # Right cluster: Save / Duplicate / Clear
            html.Div([
                html.Button(
                    [html.Span("SAVE", className="chip-prefix"),
                     html.Span("Aircraft", className="chip-label")],
                    id="save-aircraft-button", n_clicks=0,
                    className="env-chip rail-drawer-trigger", type="button",
                    title="Validate + download the aircraft JSON",
                    **{"aria-label": "Save the aircraft profile to a JSON file"},
                ),
                html.Button(
                    [html.Span("COPY", className="chip-prefix"),
                     html.Span("Duplicate", className="chip-label")],
                    id="duplicate-aircraft-button", n_clicks=0,
                    className="env-chip", type="button",
                    title="Duplicate the currently-loaded aircraft as a new profile",
                    **{"aria-label": "Duplicate the current aircraft as a new profile"},
                ),
                html.Button(
                    [html.Span("CLEAR", className="chip-prefix"),
                     html.Span("Reset Form", className="chip-label")],
                    id="new-aircraft-button", n_clicks=0,
                    className="env-chip", type="button",
                    title="Clear all fields and start a blank profile",
                    **{"aria-label": "Clear all form fields"},
                ),
            ], className="top-strip-right"),
        ], className="top-strip edit-page-top-strip"),

        # Main content
        html.Div([
            # Aircraft picker — primary CTA, no longer hidden
            html.Div([
                html.Div([
                    html.Label("Edit existing aircraft", className="edit-section-label"),
                    html.Div(id="edit-aircraft-helper",
                             className="edit-section-helper",
                             children="Pick any of the 110 aircraft to load its profile into the form."),
                ], className="edit-section-header"),
                dcc.Dropdown(
                    id="aircraft-search",
                    options=[],  # populated by callback below
                    placeholder="Search aircraft to edit…",
                    searchable=True,
                    clearable=True,
                    className="edit-aircraft-search",
                ),
            ], className="edit-aircraft-search-section"),

            # Status messages (search result + save status)
            html.Div([
                html.Div(id="search-result", className="edit-status-msg"),
                html.Div(id="save-status", className="edit-status-msg"),
            ], className="edit-action-bar"),

            # Quick Start with help buttons
            html.Div([
                html.Div("Quick Start", className="edit-quick-title"),
                html.Div("Select a category to pre-fill typical values. Click ? for details.", className="edit-quick-subtitle"),
                html.Div([
                    # Basic Trainer
                    html.Div([
                        html.Button("Basic Trainer", id="default-trainer", n_clicks=0, className="btn-quickstart"),
                        html.Button("?", id="help-trainer", n_clicks=0, className="btn-help-sm"),
                        dbc.Popover([
                            dbc.PopoverHeader("Basic Trainer"),
                            dbc.PopoverBody([
                                html.P([html.Strong("Similar Aircraft: "), "C150, C152, PA-28-140, DA20, Tomahawk"]),
                                html.Hr(className="popover-divider"),
                                html.P([html.Strong("Typical Specs:")]),
                                html.Ul([
                                    html.Li("100-120 HP, Fixed Gear"),
                                    html.Li("Empty: ~1,100 lbs / Max: ~1,670 lbs"),
                                    html.Li("Wing Area: ~160 ft², Vne: ~140 kts"),
                                    html.Li("G Limits: +3.8/-1.5 (Normal)"),
                                ], className="popover-list"),
                            ])
                        ], target="help-trainer", trigger="click", placement="bottom"),
                    ], className="quickstart-item"),

                    # Standard Single
                    html.Div([
                        html.Button("Standard Single", id="default-single", n_clicks=0, className="btn-quickstart"),
                        html.Button("?", id="help-single", n_clicks=0, className="btn-help-sm"),
                        dbc.Popover([
                            dbc.PopoverHeader("Standard Single Engine"),
                            dbc.PopoverBody([
                                html.P([html.Strong("Similar Aircraft: "), "C172, C177, PA-28-161/181, DA40, SR20"]),
                                html.Hr(className="popover-divider"),
                                html.P([html.Strong("Typical Specs:")]),
                                html.Ul([
                                    html.Li("150-180 HP, Fixed Gear"),
                                    html.Li("Empty: ~1,600 lbs / Max: ~2,550 lbs"),
                                    html.Li("Wing Area: ~174 ft², Vne: ~163 kts"),
                                    html.Li("G Limits: +3.8/-1.5 (Normal)"),
                                ], className="popover-list"),
                            ])
                        ], target="help-single", trigger="click", placement="bottom"),
                    ], className="quickstart-item"),

                    # High Performance
                    html.Div([
                        html.Button("High Performance", id="default-highperf", n_clicks=0, className="btn-quickstart"),
                        html.Button("?", id="help-highperf", n_clicks=0, className="btn-help-sm"),
                        dbc.Popover([
                            dbc.PopoverHeader("High Performance Single"),
                            dbc.PopoverBody([
                                html.P([html.Strong("Similar Aircraft: "), "C182, C210, Bonanza, Mooney, SR22"]),
                                html.Hr(className="popover-divider"),
                                html.P([html.Strong("Typical Specs:")]),
                                html.Ul([
                                    html.Li("200-310 HP, Often Retractable"),
                                    html.Li("Empty: ~2,000 lbs / Max: ~3,400 lbs"),
                                    html.Li("Wing Area: ~175 ft², Vne: ~200 kts"),
                                    html.Li("G Limits: +3.8/-1.5 (Normal)"),
                                ], className="popover-list"),
                            ])
                        ], target="help-highperf", trigger="click", placement="bottom"),
                    ], className="quickstart-item"),

                    # Light Twin
                    html.Div([
                        html.Button("Light Twin", id="default-multi", n_clicks=0, className="btn-quickstart"),
                        html.Button("?", id="help-multi", n_clicks=0, className="btn-help-sm"),
                        dbc.Popover([
                            dbc.PopoverHeader("Light Twin Engine"),
                            dbc.PopoverBody([
                                html.P([html.Strong("Similar Aircraft: "), "PA-44 Seminole, DA42, Baron 58, PA-34 Seneca"]),
                                html.Hr(className="popover-divider"),
                                html.P([html.Strong("Typical Specs:")]),
                                html.Ul([
                                    html.Li("2x 180-220 HP, Retractable"),
                                    html.Li("Empty: ~2,400 lbs / Max: ~3,800 lbs"),
                                    html.Li("Wing Area: ~183 ft², Vne: ~202 kts"),
                                    html.Li("Includes Vmca, Vyse, Vxse, OEI data"),
                                ], className="popover-list"),
                            ])
                        ], target="help-multi", trigger="click", placement="bottom"),
                    ], className="quickstart-item"),

                    # Aerobatic
                    html.Div([
                        html.Button("Aerobatic", id="default-aerobatic", n_clicks=0, className="btn-quickstart"),
                        html.Button("?", id="help-aerobatic", n_clicks=0, className="btn-help-sm"),
                        dbc.Popover([
                            dbc.PopoverHeader("Aerobatic"),
                            dbc.PopoverBody([
                                html.P([html.Strong("Similar Aircraft: "), "Extra 300, Pitts S-2, CAP 232, Decathlon"]),
                                html.Hr(className="popover-divider"),
                                html.P([html.Strong("Typical Specs:")]),
                                html.Ul([
                                    html.Li("180-330 HP, Fixed or Retract"),
                                    html.Li("Empty: ~1,100 lbs / Max: ~1,650 lbs"),
                                    html.Li("Wing Area: ~100 ft², Vne: ~220 kts"),
                                    html.Li("G Limits: +6/-3 to +10/-10 (Aerobatic)"),
                                ], className="popover-list"),
                            ])
                        ], target="help-aerobatic", trigger="click", placement="bottom"),
                    ], className="quickstart-item"),

                    # LSA/Experimental
                    html.Div([
                        html.Button("LSA / Experimental", id="default-experimental", n_clicks=0, className="btn-quickstart"),
                        html.Button("?", id="help-experimental", n_clicks=0, className="btn-help-sm"),
                        dbc.Popover([
                            dbc.PopoverHeader("Light Sport / Experimental"),
                            dbc.PopoverBody([
                                html.P([html.Strong("Similar Aircraft: "), "RV-12, CTLS, SportStar, Zenith, Sonex"]),
                                html.Hr(className="popover-divider"),
                                html.P([html.Strong("Typical Specs:")]),
                                html.Ul([
                                    html.Li("80-120 HP (often Rotax), Fixed Gear"),
                                    html.Li("Empty: ~750 lbs / Max: ~1,320 lbs"),
                                    html.Li("Wing Area: ~120 ft², Vne: ~140 kts"),
                                    html.Li("G Limits: +4/-2 (LSA limits)"),
                                ], className="popover-list"),
                            ])
                        ], target="help-experimental", trigger="click", placement="bottom"),
                    ], className="quickstart-item"),
                ], className="quickstart-grid"),
            ], className="edit-quick-section"),

            # Units & Expand All bar (styled like accordion header)
            html.Div([
                html.Div([
                    html.Span("Units:", className="units-bar-label"),
                    html.Span("KIAS", className="edit-toggle-label-left"),
                    dbc.Switch(id="units-toggle-switch", value=False, className="edit-units-switch"),
                    html.Span("MPH", className="edit-toggle-label-right"),
                    # Hidden input to maintain compatibility with existing callbacks
                    dcc.Input(id="units-toggle", type="hidden", value="KIAS"),
                ], className="units-bar-left"),
                html.Div([
                    html.Button("Expand All", id="expand-all-btn", n_clicks=0, className="btn-expand-all"),
                    html.Button("Collapse All", id="collapse-all-btn", n_clicks=0, className="btn-expand-all"),
                ], className="units-bar-right"),
            ], className="units-expand-bar"),

            # Accordions
            dbc.Accordion([
                # 1. Basic Information
                dbc.AccordionItem([
                    html.Div([
                        create_field_row("Aircraft Name",
                            dcc.Input(id="aircraft-name", type="text", placeholder="e.g. Cessna 172S", className="edit-input-text"),
                            width="100%"),

                        html.Div([
                            html.Div([
                                html.Label("Aircraft Type", className="edit-field-label"),
                                dcc.Dropdown(
                                    id="aircraft-type",
                                    options=[
                                        {"label": "Single Engine", "value": "single_engine"},
                                        {"label": "Multi Engine", "value": "multi_engine"}
                                    ],
                                    placeholder="Select...",
                                    className="edit-dropdown"
                                )
                            ], style={"flex": "1", "marginRight": "12px"}),
                            html.Div([
                                html.Label("Landing Gear", className="edit-field-label"),
                                dcc.Dropdown(
                                    id="gear-type",
                                    options=[
                                        {"label": "Fixed", "value": "fixed"},
                                        {"label": "Retractable", "value": "retractable"}
                                    ],
                                    value="fixed",
                                    className="edit-dropdown",
                                    clearable=False
                                )
                            ], style={"flex": "1", "marginRight": "12px"}),
                            html.Div([
                                html.Label("Engine Count", className="edit-field-label"),
                                dcc.Input(id="engine-count", type="number", min=1, step=1, value=1, className="edit-input-num")
                            ], style={"width": "100px"}),
                        ], className="edit-row-flex"),
                    ], className="edit-section-content"),
                ], title="Basic Information", item_id="basic"),

                # 2. Physical Properties
                dbc.AccordionItem([
                    html.Div([
                        html.Div([
                            html.Div([
                                html.Label("Wing Area (ft²)", className="edit-field-label"),
                                dcc.Input(id="wing-area", type="number", placeholder="174", className="edit-input-num")
                            ], style={"flex": "1", "marginRight": "12px"}),
                            html.Div([
                                html.Label("Aspect Ratio", className="edit-field-label"),
                                dcc.Input(id="aspect-ratio", type="number", placeholder="7.32", step=0.01, className="edit-input-num")
                            ], style={"flex": "1", "marginRight": "12px"}),
                            html.Div([
                                html.Label("CD₀", className="edit-field-label"),
                                dcc.Input(id="cd0", type="number", placeholder="0.027", step=0.001, className="edit-input-num")
                            ], style={"flex": "1", "marginRight": "12px"}),
                            html.Div([
                                html.Label("Oswald (e)", className="edit-field-label"),
                                dcc.Input(id="oswald-efficiency", type="number", placeholder="0.8", step=0.01, className="edit-input-num")
                            ], style={"flex": "1"}),
                        ], className="edit-row-flex"),

                        html.Div([
                            html.Div([
                                html.Label("T_static Factor", className="edit-field-label"),
                                dcc.Input(id="prop-static-factor", type="number", placeholder="2.6", step=0.1, className="edit-input-num")
                            ], style={"flex": "1", "marginRight": "12px"}),
                            html.Div([
                                html.Label("V_max (kts)", className="edit-field-label"),
                                dcc.Input(id="prop-vmax-kts", type="number", placeholder="160", className="edit-input-num")
                            ], style={"flex": "1"}),
                        ], className="edit-row-flex", style={"marginTop": "12px"}),
                    ], className="edit-section-content"),
                ], title="Aerodynamics & Propulsion", item_id="aero"),

                # 3. Weight & Balance
                dbc.AccordionItem([
                    html.Div([
                        html.Div([
                            html.Div([
                                html.Label("Empty Weight (lbs)", className="edit-field-label"),
                                dcc.Input(id="empty-weight", type="number", placeholder="1660", className="edit-input-num")
                            ], style={"flex": "1", "marginRight": "12px"}),
                            html.Div([
                                html.Label("Max Gross (lbs)", className="edit-field-label"),
                                dcc.Input(id="max-weight", type="number", placeholder="2550", className="edit-input-num")
                            ], style={"flex": "1", "marginRight": "12px"}),
                            html.Div([
                                html.Label("Seats", className="edit-field-label"),
                                dcc.Input(id="seats", type="number", placeholder="4", className="edit-input-num")
                            ], style={"width": "80px"}),
                        ], className="edit-row-flex"),

                        html.Div([
                            html.Div([
                                html.Label("CG FWD (in)", className="edit-field-label"),
                                dcc.Input(id="cg-fwd", type="number", placeholder="35.0", className="edit-input-num")
                            ], style={"flex": "1", "marginRight": "12px"}),
                            html.Div([
                                html.Label("CG AFT (in)", className="edit-field-label"),
                                dcc.Input(id="cg-aft", type="number", placeholder="47.3", className="edit-input-num")
                            ], style={"flex": "1", "marginRight": "12px"}),
                            html.Div([
                                html.Label("Fuel Cap (gal)", className="edit-field-label"),
                                dcc.Input(id="fuel-capacity-gal", type="number", placeholder="56", className="edit-input-num")
                            ], style={"flex": "1", "marginRight": "12px"}),
                            html.Div([
                                html.Label("Fuel lbs/gal", className="edit-field-label"),
                                dcc.Input(id="fuel-weight-per-gal", type="number", placeholder="6.0", step=0.1, className="edit-input-num")
                            ], style={"flex": "1"}),
                        ], className="edit-row-flex", style={"marginTop": "12px"}),
                    ], className="edit-section-content"),
                ], title="Weight & Balance", item_id="weight"),

                # 4. Speed Limits
                dbc.AccordionItem([
                    html.Div([
                        html.Div([
                            html.Div([
                                html.Label("Vne", className="edit-field-label"),
                                dcc.Input(id="vne", type="number", placeholder="163", className="edit-input-num")
                            ], style={"flex": "1", "marginRight": "12px"}),
                            html.Div([
                                html.Label("Vno", className="edit-field-label"),
                                dcc.Input(id="vno", type="number", placeholder="129", className="edit-input-num")
                            ], style={"flex": "1", "marginRight": "12px"}),
                            html.Div([
                                html.Label("Best Glide", className="edit-field-label"),
                                dcc.Input(id="best-glide", type="number", placeholder="68", className="edit-input-num")
                            ], style={"flex": "1", "marginRight": "12px"}),
                            html.Div([
                                html.Label("Glide Ratio", className="edit-field-label"),
                                dcc.Input(id="best-glide-ratio", type="number", placeholder="9.0", step=0.1, className="edit-input-num")
                            ], style={"flex": "1", "marginRight": "12px"}),
                            html.Div([
                                html.Label("Ceiling (ft)", className="edit-field-label"),
                                dcc.Input(id="max-altitude", type="number", placeholder="14000", className="edit-input-num")
                            ], style={"flex": "1"}),
                        ], className="edit-row-flex"),

                        html.Hr(className="edit-divider"),
                        html.Label("Airspeed Indicator Arcs", className="edit-subsection-label"),

                        html.Div([
                            html.Div([
                                html.Label("White (Vs0-Vfe)", className="edit-field-label"),
                                html.Div([
                                    dcc.Input(id="arc-white-bottom", type="number", placeholder="41", className="edit-input-num-sm"),
                                    html.Span("-", className="edit-arc-dash"),
                                    dcc.Input(id="arc-white-top", type="number", placeholder="85", className="edit-input-num-sm"),
                                ], className="edit-arc-inputs")
                            ], style={"flex": "1", "marginRight": "12px"}),
                            html.Div([
                                html.Label("Green (Vs1-Vno)", className="edit-field-label"),
                                html.Div([
                                    dcc.Input(id="arc-green-bottom", type="number", placeholder="47", className="edit-input-num-sm"),
                                    html.Span("-", className="edit-arc-dash"),
                                    dcc.Input(id="arc-green-top", type="number", placeholder="129", className="edit-input-num-sm"),
                                ], className="edit-arc-inputs")
                            ], style={"flex": "1", "marginRight": "12px"}),
                            html.Div([
                                html.Label("Yellow (Vno-Vne)", className="edit-field-label"),
                                html.Div([
                                    dcc.Input(id="arc-yellow-bottom", type="number", placeholder="129", className="edit-input-num-sm"),
                                    html.Span("-", className="edit-arc-dash"),
                                    dcc.Input(id="arc-yellow-top", type="number", placeholder="163", className="edit-input-num-sm"),
                                ], className="edit-arc-inputs")
                            ], style={"flex": "1", "marginRight": "12px"}),
                            html.Div([
                                html.Label("Red Line", className="edit-field-label"),
                                dcc.Input(id="arc-red", type="number", placeholder="163", className="edit-input-num-sm"),
                            ], style={"width": "90px"}),
                        ], className="edit-row-flex"),
                    ], className="edit-section-content"),
                ], title="Speed Limits & Arcs", item_id="speeds"),

                # 5. Flap Configurations
                dbc.AccordionItem([
                    html.Div([
                        html.Div(id="flap-configs-container", children=[
                            html.Div([
                                html.Div([
                                    html.Label("Clean / Up", className="edit-field-label"),
                                    dcc.Input(id={"type": "clmax-input", "config": "clean"}, type="number", placeholder="CLmax", step=0.01, className="edit-input-num")
                                ], style={"flex": "1", "marginRight": "12px"}),
                                html.Div([
                                    html.Label("Takeoff Vfe", className="edit-field-label"),
                                    dcc.Input(id={"type": "vfe-input", "config": "takeoff"}, type="number", placeholder="Vfe", className="edit-input-num")
                                ], style={"flex": "1", "marginRight": "12px"}),
                                html.Div([
                                    html.Label("Takeoff CLmax", className="edit-field-label"),
                                    dcc.Input(id={"type": "clmax-input", "config": "takeoff"}, type="number", placeholder="CLmax", step=0.01, className="edit-input-num")
                                ], style={"flex": "1", "marginRight": "12px"}),
                                html.Div([
                                    html.Label("Landing Vfe", className="edit-field-label"),
                                    dcc.Input(id={"type": "vfe-input", "config": "landing"}, type="number", placeholder="Vfe", className="edit-input-num")
                                ], style={"flex": "1", "marginRight": "12px"}),
                                html.Div([
                                    html.Label("Landing CLmax", className="edit-field-label"),
                                    dcc.Input(id={"type": "clmax-input", "config": "landing"}, type="number", placeholder="CLmax", step=0.01, className="edit-input-num")
                                ], style={"flex": "1"}),
                            ], className="edit-row-flex"),
                        ])
                    ], className="edit-section-content"),
                ], title="Flap Configurations", item_id="flaps"),

                # 6. G Limits
                dbc.AccordionItem([
                    html.Div([
                        html.Div(id="g-limits-container"),
                        html.Button("+ Add G Limit", id="add-g-limit", n_clicks=0, className="btn-add-sm"),
                    ], className="edit-section-content"),
                ], title="G Limits", item_id="glimits"),

                # 7. Stall Speeds
                dbc.AccordionItem([
                    html.Div([
                        html.Div(id="stall-speeds-container"),
                        html.Button("+ Add Stall Speed", id="add-stall-speed", n_clicks=0, className="btn-add-sm"),
                    ], className="edit-section-content"),
                ], title="Stall Speeds", item_id="stall"),

                # 8. Engine Options
                dbc.AccordionItem([
                    html.Div([
                        html.Div(id="engine-options-container"),
                        html.Button("+ Add Engine", id="add-engine-option", n_clicks=0, className="btn-add-sm"),
                    ], className="edit-section-content"),
                ], title="Engine Options", item_id="engines"),

            ], id="edit-accordion", always_open=True, active_item=["basic"]),

            # Multi-engine only sections
            html.Div(id="multi-engine-sections", children=[
                dbc.Accordion([
                    dbc.AccordionItem([
                        html.Div([
                            html.Div(id="single-engine-limits-container"),
                            html.Button("+ Add Limit", id="add-single-engine-limit", n_clicks=0, className="btn-add-sm"),
                        ], className="edit-section-content"),
                    ], title="Multi-Engine Limits (Vmca/Vyse/Vxse)", item_id="melimits"),

                    dbc.AccordionItem([
                        html.Div([
                            html.Div(id="oei-performance-container"),
                            html.Button("+ Add OEI Entry", id="add-oei-performance", n_clicks=0, className="btn-add-sm"),
                        ], className="edit-section-content"),
                    ], title="OEI Performance", item_id="oei"),
                ], always_open=True, active_item=[]),
            ], style={"display": "none"}),  # Hidden by default, shown for multi-engine

        ], className="edit-page-content"),

        # Footer spacing
        html.Div(style={"height": "40px"}),
    ], className="edit-page-container desktop-shell")
