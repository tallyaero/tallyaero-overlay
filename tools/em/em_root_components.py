"""EM's root-level components (Stores + Modals + Download).

In standalone EM these live in app.layout's first-level children. In
the unified planning app, they need to be hoisted to the parent's
app.layout so they're always mounted regardless of which page
(/overlay or /em) is currently rendered into page-content.

`root_components(aircraft_data)` returns the list of dash components
to splat into the parent layout.
"""
from __future__ import annotations

from dash import dcc, html
import dash_bootstrap_components as dbc


def root_components(aircraft_data: dict) -> list:
    return [
        dcc.Store(id="aircraft-data-store", data=aircraft_data),
        dcc.Store(id="last-saved-aircraft"),
        dcc.Store(id="stored-total-weight"),
        dcc.Store(id="em-screen-width"),
        dcc.Store(id="em-theme-pref", storage_type="local", data=None),
        dcc.Store(id="metar-store", data=None),
        dcc.Store(id="editing-aircraft", storage_type="session", data=None),
        dcc.Store(id="compare-aircraft", data=None),
        dcc.Store(id="hv-target-point", data=None),
        dcc.Store(id="hv-target-mode", data=False),
        dcc.Store(id="ref-ias-kt", data=None),
        dcc.Store(id="hv-reach-seconds", data=None),
        dcc.Store(id="hv-margins", data=False),
        dcc.Store(id="doghouse-probe", data=None),
        dcc.Store(id="chart-tab", data="maneuver"),
        dcc.Store(id="browser-width"),
        dcc.Store(id="help-topic", data=None),
        dcc.Location(id="em-url"),
        dcc.Download(id="download-aircraft"),
        # Update banner (hidden by default; clientside JS surfaces it).
        html.Div(
            id="update-banner",
            style={"display": "none"},
            className="update-banner",
            children=[
                html.Span(id="update-banner-msg",
                          className="update-banner-msg"),
                html.A("Download", id="update-banner-link",
                       href="https://tallyaero.com/em-diagram",
                       target="_blank",
                       className="update-banner-link"),
                html.Button("×", id="update-banner-close",
                            className="update-banner-close",
                            **{"aria-label": "Dismiss update banner"}),
            ],
        ),
        # Modals — kept minimal placeholders here (full body lives in
        # tools/em/app.py for now; callbacks just need the IDs to be
        # mountable). Empty modals are fine — they don't render until
        # toggled to is_open=True by a callback.
        dbc.Modal(id="em-disclaimer-modal", is_open=False),
        dbc.Modal(id="em-terms-policy-modal", is_open=False),
        dbc.Modal(id="readme-modal", is_open=False),
        dbc.Modal(
            [
                dbc.ModalHeader(dbc.ModalTitle(id="help-modal-title")),
                dbc.ModalBody(id="help-modal-body"),
                dbc.ModalFooter(
                    dbc.Button("Close", id="close-help-modal",
                               className="ms-auto"),
                ),
            ],
            id="help-modal",
            is_open=False,
        ),
        dbc.Modal(id="readme-modal-content", is_open=False),
        html.Button(id="close-readme", style={"display": "none"}),
    ]
