"""TallyAero EM Diagram — PDF / PNG export callbacks."""

from __future__ import annotations

import io
import os
import tempfile

import dash
from dash import ctx, dcc, html
from dash.dcc import send_file
from dash.dependencies import Input, Output, State
from dash.exceptions import PreventUpdate

import plotly.graph_objects as go
import plotly.io as pio

from core import (
    AIRCRAFT_DATA, aircraft_data,
    dprint, log_feature,
)


def register(app):
    """Install every callback in this module."""
    # render_maneuver_options lives in callbacks/main.py (the classifier
    # walked back too far and pulled it in here erroneously — Phase 1g fix).

    def get_summary_text(ac_name, engine_name, config, gear, occupants, fuel, total_weight, power_fraction, altitude):
        return (
            f"Aircraft: {ac_name}\n"
            f"Engine: {engine_name}\n"
            f"Flap Configuration: {config}\n"
            f"Gear: {gear if gear else 'N/A'}\n"
            f"Occupants: {occupants}\n"
            f"Fuel: {fuel} gal\n"
            f"Power: {int(power_fraction * 100)}%\n"
            f"Altitude: {altitude} ft\n"
            f"Total Weight: {int(total_weight)} lbs"
        )

    @app.callback(
        Output("pdf-download", "data"),
        Input("pdf-button", "n_clicks"),
        Input("em-graph", "figure"),
        State("aircraft-select", "value"),
        State("engine-select", "value"),
        State("config-select", "value"),
        State("gear-select", "value"),
        State("occupants-select", "value"),
        State("passenger-weight-input", "value"),
        State("fuel-slider", "value"),
        State("stored-total-weight", "data"),
        State("power-setting", "value"),
        State("altitude-slider", "value"),
        State("pitch-angle", "value"),
        State("oei-toggle", "value"),
        State("prop-condition", "data"),
        State("maneuver-select", "value"),
        State("oat-input", "value"),
        State("unit-select", "data"),
        State("cg-slider", "value"),
        State("overlay-toggle", "data"),
        prevent_initial_call=True
    )
    def generate_pdf(n_clicks, fig_data, ac_name, engine_name, config, gear, occupants, pax_weight, fuel, total_weight,
                     power_fraction, altitude, pitch, oei_toggle, prop_condition, maneuver,
                     oat_c, speed_unit, cg_position, active_overlays):
        if ctx.triggered_id != "pdf-button":
            return dash.no_update

        # Track PDF export with configuration details
        log_feature('diagram_export_pdf', {
            'aircraft': ac_name,
            'engine': engine_name,
            'config': config,
            'altitude': altitude,
            'maneuver': maneuver
        })

        fig = go.Figure(fig_data)

        # Generate timestamp
        from datetime import datetime
        export_timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    


        # Add Logo (logo2.png in top-left)
        try:
            logo_path = os.path.join("assets", "logo2.png")
            if os.path.exists(logo_path):
                from PIL import Image
                logo_img = Image.open(logo_path)
                fig.add_layout_image(
                    dict(
                        source=logo_img,
                        xref="paper", yref="paper",
                        x=-0.05, y=1.25,
                        sizex=0.25, sizey=0.25,
                        xanchor="left", yanchor="top",
                        layer="above"
                    )
                )
        except Exception as e:
            dprint(f"[LOGO WARNING] Failed to add logo2.png: {e}")

        # Summary Text
        oei_status = "YES" if oei_toggle and "enabled" in oei_toggle else "NO"

        # Convert OAT to Fahrenheit for display
        oat_f = round(oat_c * 9/5 + 32) if oat_c is not None else "N/A"
        oat_display = f"{oat_c}°C / {oat_f}°F" if oat_c is not None else "N/A"

        # Calculate CG in inches from slider position and aircraft CG range
        cg_display = "N/A"
        if cg_position is not None and ac_name and ac_name in aircraft_data:
            ac = aircraft_data[ac_name]
            cg_range = ac.get("cg_range", [0, 100])
            cg_inches = cg_range[0] + cg_position * (cg_range[1] - cg_range[0])
            cg_display = f"{cg_inches:.1f} in"

        # Format active overlays
        overlay_names = {
            "ps": "Ps Contours",
            "radius": "Turn Radius",
            "g": "G-Lines",
            "aob": "AOB Shading",
            "negative_g": "Neg-G Envelope",
            "vmca": "Dynamic Vmc",
            "vyse": "Dynamic Vyse"
        }
        active_overlay_list = [overlay_names.get(o, o) for o in (active_overlays or [])]
        overlays_display = ", ".join(active_overlay_list) if active_overlay_list else "None"

        summary_lines = [
            f"Engine: {engine_name} | {config} | Gear: {gear}",
            f"Weight: {int(total_weight) if total_weight else 'N/A'} lbs | Occupants: {occupants} x {pax_weight or 180} lbs | Fuel: {fuel} gal | CG: {cg_display}",
            f"Altitude: {altitude or 0} ft | OAT: {oat_display} | Power: {int(power_fraction * 100)}%",
            f"Speed Unit: {speed_unit or 'KIAS'} | OEI: {oei_status}" + (f" ({prop_condition})" if oei_status == "YES" else ""),
            f"Overlays: {overlays_display}" + (f" | Maneuver: {maneuver}" if maneuver else ""),
            f"<i>Generated: {export_timestamp}</i>"
        ]

        fig.add_annotation(
            text="<br>".join(summary_lines),
            xref="paper", yref="paper",
            x=0.5, y=1.01,
            xanchor="center", yanchor="bottom",
            showarrow=False,
            font=dict(size=10, color="#1b1e23"),
            align="center"
        )

        # Footer for exports
        fig.add_annotation(
            text="© 2025 Nicholas Len, TallyAero. All rights reserved. | Not FAA-approved. For educational and reference use only.",
            xref="paper", yref="paper",
            x=0.5, y=-0.12,
            xanchor="center", yanchor="top",
            showarrow=False,
            font=dict(size=9, color="gray"),
            align="center"
        )

        # Clean layout margin (increased top margin for additional info lines)
        fig.update_layout(margin=dict(t=180, b=80))

        # Save PDF to temp and return
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
            pio.write_image(fig, tmp.name, format="pdf", width=1100, height=800)
            return send_file(tmp.name, filename="EMdiagram.pdf")

    @app.callback(
        Output("png-download", "data"),
        Input("png-button", "n_clicks"),
        Input("em-graph", "figure"),
        State("aircraft-select", "value"),
        State("engine-select", "value"),
        State("config-select", "value"),
        State("gear-select", "value"),
        State("occupants-select", "value"),
        State("passenger-weight-input", "value"),
        State("fuel-slider", "value"),
        State("stored-total-weight", "data"),
        State("power-setting", "value"),
        State("altitude-slider", "value"),
        State("pitch-angle", "value"),
        State("oei-toggle", "value"),
        State("prop-condition", "data"),
        State("maneuver-select", "value"),
        State("oat-input", "value"),
        State("unit-select", "data"),
        State("cg-slider", "value"),
        State("overlay-toggle", "data"),
        prevent_initial_call=True
    )
    def generate_png(n_clicks, fig_data, ac_name, engine_name, config, gear, occupants, pax_weight, fuel, total_weight,
                     power_fraction, altitude, pitch, oei_toggle, prop_condition, maneuver,
                     oat_c, speed_unit, cg_position, active_overlays):
        if ctx.triggered_id != "png-button":
            return dash.no_update

        # Track PNG export with configuration details
        log_feature('diagram_export_png', {
            'aircraft': ac_name,
            'engine': engine_name,
            'config': config,
            'altitude': altitude,
            'maneuver': maneuver
        })

        fig = go.Figure(fig_data)

        # Generate timestamp
        from datetime import datetime
        export_timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")

        # Add Logo (logo2.png in top-left)
        try:
            logo_path = os.path.join("assets", "logo2.png")
            if os.path.exists(logo_path):
                from PIL import Image
                logo_img = Image.open(logo_path)
                fig.add_layout_image(
                    dict(
                        source=logo_img,
                        xref="paper", yref="paper",
                        x=-0.05, y=1.25,
                        sizex=0.25, sizey=0.25,
                        xanchor="left", yanchor="top",
                        layer="above"
                    )
                )
        except Exception as e:
            dprint(f"[LOGO WARNING] Failed to add logo2.png: {e}")

        # Summary Text
        oei_status = "YES" if oei_toggle and "enabled" in oei_toggle else "NO"

        # Convert OAT to Fahrenheit for display
        oat_f = round(oat_c * 9/5 + 32) if oat_c is not None else "N/A"
        oat_display = f"{oat_c}°C / {oat_f}°F" if oat_c is not None else "N/A"

        # Calculate CG in inches from slider position and aircraft CG range
        cg_display = "N/A"
        if cg_position is not None and ac_name and ac_name in aircraft_data:
            ac = aircraft_data[ac_name]
            cg_range = ac.get("cg_range", [0, 100])
            cg_inches = cg_range[0] + cg_position * (cg_range[1] - cg_range[0])
            cg_display = f"{cg_inches:.1f} in"

        # Format active overlays
        overlay_names = {
            "ps": "Ps Contours",
            "radius": "Turn Radius",
            "g": "G-Lines",
            "aob": "AOB Shading",
            "negative_g": "Neg-G Envelope",
            "vmca": "Dynamic Vmc",
            "vyse": "Dynamic Vyse"
        }
        active_overlay_list = [overlay_names.get(o, o) for o in (active_overlays or [])]
        overlays_display = ", ".join(active_overlay_list) if active_overlay_list else "None"

        summary_lines = [
            f"Engine: {engine_name} | {config} | Gear: {gear}",
            f"Weight: {int(total_weight) if total_weight else 'N/A'} lbs | Occupants: {occupants} x {pax_weight or 180} lbs | Fuel: {fuel} gal | CG: {cg_display}",
            f"Altitude: {altitude or 0} ft | OAT: {oat_display} | Power: {int(power_fraction * 100)}%",
            f"Speed Unit: {speed_unit or 'KIAS'} | OEI: {oei_status}" + (f" ({prop_condition})" if oei_status == "YES" else ""),
            f"Overlays: {overlays_display}" + (f" | Maneuver: {maneuver}" if maneuver else ""),
            f"<i>Generated: {export_timestamp}</i>"
        ]

        fig.add_annotation(
            text="<br>".join(summary_lines),
            xref="paper", yref="paper",
            x=0.5, y=1.01,
            xanchor="center", yanchor="bottom",
            showarrow=False,
            font=dict(size=10, color="#1b1e23"),
            align="center"
        )

        # Footer for exports
        fig.add_annotation(
            text="© 2025 Nicholas Len, TallyAero. All rights reserved. | Not FAA-approved. For educational and reference use only.",
            xref="paper", yref="paper",
            x=0.5, y=-0.12,
            xanchor="center", yanchor="top",
            showarrow=False,
            font=dict(size=9, color="gray"),
            align="center"
        )

        # Clean layout margin (increased top margin for additional info lines)
        fig.update_layout(margin=dict(t=180, b=80))

        # Save PNG to temp and return
        with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as tmp:
            pio.write_image(fig, tmp.name, format="png", width=1200, height=900, scale=2)
            return send_file(tmp.name, filename="EMdiagram.png")

