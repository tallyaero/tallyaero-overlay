"""Shared helpers for the horizontal-native maneuver shelf layouts.

Each per-maneuver layout returns a flex row of `_field()` mini-columns
plus action buttons + hidden helper containers that the existing
callbacks reference.
"""
from __future__ import annotations

from dash import html
import dash_bootstrap_components as dbc


def _field(label, control, slider=False, tooltip=None):
    """Compact labeled mini-column for the shelf.

    label slug appears as 9.5px uppercase letter-spaced text above
    the control. `slider=True` swaps to the wider `.shelf-field-slider`
    wrapper that clamps the rc-slider to a fixed width. `tooltip`
    surfaces as a native-OS hover tooltip on both the label and the
    control wrapper so pilots can pause-hover any field to learn what
    a non-default value will do."""
    cls = "shelf-field shelf-field-slider" if slider else "shelf-field"
    div_attrs = {"className": cls}
    if tooltip:
        div_attrs["title"] = tooltip
    return html.Div(
        [html.Div(label, className="shelf-field-label"), control],
        **div_attrs,
    )


def _spacer():
    """Pushes the elements after it to the right of the shelf row."""
    return html.Div(className="shelf-spacer")


def _grade(value, target, tol):
    delta = abs(value - target)
    if delta <= tol:
        return "pass"
    if delta <= tol * 1.5:
        return "marginal"
    return "fail"


def _acs_metric(label, value, units, target, tol, cert_level="private"):
    """Render an ACS-tolerance pass/fail/marginal badge.

    pass     when abs(value - target) <= tol
    marginal when abs(value - target) <= tol * 1.5
    fail     otherwise

    Returns an inline-flex html.Div with className="acs-metric" and a
    data-cert-level attribute carrying the supplied cert_level verbatim
    (e.g. "private", "commercial"). Used by per-maneuver info panels."""
    grade = _grade(value, target, tol)
    value_text = f"{value:.1f}" if isinstance(value, float) else str(value)
    children = [
        html.Span(label, className="acs-metric-label"),
        html.Span(value_text, className=f"acs-metric-value acs-{grade}"),
    ]
    if units:
        children.append(html.Span(units, className="acs-metric-units"))
    return html.Div(
        children,
        className="acs-metric",
        **{"data-cert-level": cert_level},
    )


def _results_modal_pair(m_id, info_div_id, title="Simulation Results"):
    """Render the (Results button, Results modal) pair for a maneuver.

    The modal's body wraps `html.Div(id=info_div_id)` so existing
    per-maneuver draw callbacks continue to write their accordion +
    chart content into that id without changes. The button + modal
    use pattern-matched ids so one shared toggle callback handles all
    twelve maneuvers.
    """
    btn = html.Button(
        "Results",
        id={"type": "sim-results-btn", "m_id": m_id},
        className="shelf-action shelf-action-results",
        title="Open the full simulation-results panel.",
        n_clicks=0,
    )
    modal = dbc.Modal(
        [
            dbc.ModalHeader(dbc.ModalTitle(title), close_button=True),
            dbc.ModalBody(
                html.Div(id=info_div_id, className="sim-results-modal-body"),
                className="sim-results-modal-scroll",
            ),
            dbc.ModalFooter(
                dbc.Button(
                    "Close",
                    id={"type": "sim-results-close-btn", "m_id": m_id},
                    className="green-button",
                    n_clicks=0,
                ),
            ),
        ],
        id={"type": "sim-results-modal", "m_id": m_id},
        size="lg",
        is_open=False,
        scrollable=True,
        centered=True,
        dialogClassName="tallyaero-modal sim-results-modal",
    )
    return [btn, modal]


def _winds_aloft_chip(wind_profile_data):
    """Render the live winds-aloft column chip for a results modal.

    `wind_profile_data` is the dcc.Store payload from wind-profile-store
    (set by the airport-pick callback in Phase H3). Returns None when
    no live data is staged so the caller can skip rendering.

    Directions displayed in MAGNETIC (pilots think magnetic, the
    sidebar inputs are magnetic). Stored values stay TRUE; the sim
    consumes them in TRUE so we don't need to round-trip.
    """
    if not wind_profile_data:
        return None
    layers = (wind_profile_data or {}).get("layers") or []
    if not layers:
        return None
    magvar_w = float((wind_profile_data or {}).get("magvar_w", 0.0))
    parts = []
    for alt_ft, dir_deg, kt in layers:
        if alt_ft <= 0:
            label = "SFC"
        elif alt_ft < 10000:
            label = f"{int(alt_ft):,}ft"
        else:
            label = f"{int(alt_ft / 1000)}k"
        mag = int(round((float(dir_deg) + magvar_w) % 360.0))
        parts.append(f"{label} {mag:03d}°/{int(round(kt))}")
    return html.Div(
        [
            html.Span("Winds (live, mag): ",
                       style={"fontWeight": "600", "color": "#475569"}),
            html.Span(" · ".join(parts)),
        ],
        className="winds-aloft-chip",
        style={
            "fontSize": "11px",
            "marginTop": "6px",
            "padding": "6px 10px",
            "background": "rgba(13, 89, 242, 0.06)",
            "borderLeft": "3px solid var(--ta-brand-blue, #0d59f2)",
            "borderRadius": "3px",
            "lineHeight": "1.5",
        },
    )


def _power_verdict(power_pct, design_power, consequence_text, failure_reason,
                   actually_failed: bool = False):
    """Render the Design Directive power verdict for a maneuver (Phase D2).

    Compares actual power (0-1) to the maneuver's design power and emits
    one of three components based on |delta| AND the sim's actual outcome:
      - abs_delta < 0.10 → green badge: "Power: X%" (within tolerance)
      - abs_delta < 0.20 → amber chip: "Off-design power: X% (design Y%) — <consequence>"
      - abs_delta >= 0.20 AND `actually_failed` → red banner: "Maneuver failed — <failure_reason>"
      - abs_delta >= 0.20 AND NOT `actually_failed` → amber chip
        (the sim completed the maneuver despite the off-design power —
        don't lie to the pilot by saying it "failed" when it didn't)

    `actually_failed` should be wired by the caller to the sim's outcome
    (e.g. the `failure_reason` field on the last hover entry, or the
    `success=False` flag in meta). Pre-fix the verdict relied purely on
    the slider delta, which painted every <80%-power chandelle red even
    though the sim cleanly completed 180° down to ~50% power.

    Returns an html.Div. consequence_text and failure_reason are short
    strings supplied by each callback per the Design Directive table.
    """
    try:
        p = float(power_pct)
    except (TypeError, ValueError):
        p = float(design_power)
    p = max(0.0, min(1.0, p))
    d = float(design_power)
    abs_delta = abs(p - d)

    if abs_delta < 0.10:
        return html.Div(
            [
                html.Span("Power", className="acs-metric-label"),
                html.Span(f"{p * 100:.0f}", className="acs-metric-value acs-pass"),
                html.Span("%", className="acs-metric-units"),
            ],
            className="acs-metric",
            **{"data-cert-level": "design-directive"},
        )

    # Off-design (delta >= 0.10). Show red ONLY if the sim itself
    # reported failure; otherwise it's just degraded performance and
    # the pilot needs the amber consequence note, not a panic banner.
    if abs_delta >= 0.20 and actually_failed:
        return html.Div(
            f"Maneuver failed — {failure_reason}",
            className="power-banner power-banner-red",
        )
    return html.Div(
        f"Off-design power: {p * 100:.0f}% (design {d * 100:.0f}%) — {consequence_text}",
        className="power-chip power-chip-amber",
    )
