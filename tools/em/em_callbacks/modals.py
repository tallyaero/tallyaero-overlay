"""TallyAero EM Diagram — modal & help-system callbacks: disclaimer, terms, README, ghost-trigger forwarding, help-bubble routing."""

from __future__ import annotations

from dash import ctx, dcc, html
from dash.dependencies import ALL, Input, Output, State
from dash.exceptions import PreventUpdate

from em_core import dprint


def register(app):
    """Install every callback in this module."""
    @app.callback(
        Output("help-ghost", "n_clicks"),
        Input({"type": "ghost-help-trigger", "index": ALL}, "n_clicks"),
        State("help-ghost", "n_clicks"),
        prevent_initial_call=True
    )
    def forward_ghost_help_clicks(trigger_clicks, current_clicks):
        """Forward clicks from dynamic ghost help triggers to the static help-ghost element."""
        if trigger_clicks and any(c and c > 0 for c in trigger_clicks):
            return (current_clicks or 0) + 1
        raise PreventUpdate

    @app.callback(
        Output("em-disclaimer-modal", "is_open"),
        Output("em-terms-policy-modal", "is_open"),
        Output("readme-modal", "is_open"),
        Input("em-open-disclaimer", "n_clicks"),
        Input("em-close-disclaimer", "n_clicks"),
        Input("em-open-terms-policy", "n_clicks"),
        Input("em-close-terms-policy", "n_clicks"),
        Input("open-readme", "n_clicks"),
        Input("close-readme", "n_clicks"),
        State("em-disclaimer-modal", "is_open"),
        State("em-terms-policy-modal", "is_open"),
        State("readme-modal", "is_open"),
        prevent_initial_call=True
    )
    def toggle_modals(open_disc, close_disc, open_terms, close_terms, open_readme, close_readme, disc_open, terms_open, readme_open):
        if not ctx.triggered:
            raise PreventUpdate

        ctx_id = ctx.triggered_id

        if ctx_id == "open-disclaimer" and open_disc:
            return True, False, False
        elif ctx_id == "close-disclaimer" and close_disc:
            return False, terms_open, readme_open
        elif ctx_id == "open-terms-policy" and open_terms:
            return False, True, False
        elif ctx_id == "close-terms-policy" and close_terms:
            return disc_open, False, readme_open
        elif ctx_id == "open-readme" and open_readme:
            return False, False, True
        elif ctx_id == "close-readme" and close_readme:
            return disc_open, terms_open, False

        raise PreventUpdate

    HELP_CONTENT = {
        "ps": {
            "title": "Ps Contours (Specific Excess Power)",
            "body": """
    **Ps (Specific Excess Power)** represents the rate at which the aircraft can gain or lose energy per unit weight, expressed in feet per second.

    **How to interpret:**
    - **Positive Ps** (solid lines): The aircraft has excess power and can climb or accelerate
    - **Zero Ps** (dashed line): The aircraft is at its performance limit - it can maintain speed and altitude but cannot climb or accelerate
    - **Negative Ps** (inside the zero line): The aircraft is losing energy and must descend or decelerate

    **Practical use:**
    - Find the airspeed/turn rate combination where Ps = 0 to know your sustained turn capability
    - Higher Ps values indicate better climb performance at that flight condition
    - Use this to compare sustained vs instantaneous maneuvering capability
    """
        },
        "g": {
            "title": "Intermediate G Lines",
            "body": """
    **G-Lines** show constant load factor (G) contours across the maneuvering envelope.

    **What load factor means:**
    - **1G**: Level, unaccelerated flight
    - **2G**: The aircraft experiences twice its weight (common in 60° bank turns)
    - **Higher G**: More aggressive maneuvering, higher structural and physiological loads

    **How to interpret:**
    - Each line represents a specific G loading
    - Where a G-line intersects the stall boundary shows the minimum speed to achieve that G
    - The lines help visualize how turn rate relates to load factor and airspeed

    **Practical use:**
    - Identify sustainable G levels for extended maneuvering
    - Plan maneuvers that stay within structural and physiological limits
    - Understand the relationship between bank angle, G, and turn performance
    """
        },
        "radius": {
            "title": "Turn Radius Lines",
            "body": """
    **Turn Radius Lines** show constant-radius turn contours in feet.

    **How to interpret:**
    - Each curved line represents a specific turn radius
    - Smaller radius = tighter turn (more aggressive maneuvering)
    - Turn radius depends on both airspeed and turn rate

    **Key relationships:**
    - Higher speeds at the same turn rate = larger radius
    - Higher turn rates at the same speed = smaller radius
    - Minimum radius occurs at the intersection of stall boundary and structural limit

    **Practical use:**
    - Plan ground reference maneuvers with specific radius requirements
    - Evaluate maneuvering capability in confined airspace
    - Compare different speed/bank combinations that achieve the same radius
    """
        },
        "aob": {
            "title": "Angle of Bank Shading",
            "body": """
    **Angle of Bank (AOB) Shading** shows the bank angle required to achieve each turn rate at various airspeeds.

    **Color interpretation:**
    - Lighter shades = shallow bank angles (30-45°)
    - Darker shades = steep bank angles (60°+)
    - The color gradient helps visualize how bank angle varies across the envelope

    **Key relationships:**
    - At a given turn rate, higher speeds require steeper bank angles
    - At a given speed, higher turn rates require steeper bank angles
    - Bank angle directly relates to load factor: G = 1/cos(bank)

    **Practical use:**
    - Quickly identify the bank angle needed for a desired turn rate
    - Plan steep turns and chandelles at appropriate speeds
    - Understand the transition from shallow to steep maneuvering
    """
        },
        "negative_g": {
            "title": "Negative G Envelope",
            "body": """
    **Negative G Envelope** shows the aircraft's capability when flying at negative (pushed) load factors.

    **What this represents:**
    - The region where the aircraft is being "pushed" rather than "pulled"
    - Occurs during inverted flight, pushovers, or outside maneuvers
    - Limited by negative G structural limits and inverted stall characteristics

    **Key assumptions:**
    - The aircraft is being pushed to maintain level flight attitude
    - Negative G stall speeds are typically higher than positive G
    - Structural negative G limits are usually lower than positive limits

    **Practical use:**
    - Understand the full maneuvering envelope including unusual attitudes
    - Plan recovery from unusual attitudes within structural limits
    - Useful for aerobatic flight planning
    """
        },
        "dvmc": {
            "title": "Dynamic Vmc",
            "body": """
    **Dynamic Vmc** shows how the minimum control speed with one engine inoperative varies with flight conditions.

    **What affects DVmc:**
    - **Weight**: Lighter weight = higher Vmc (less rudder authority relative to asymmetric thrust)
    - **Density altitude**: Higher DA = lower Vmc (reduced engine power)
    - **Bank angle**: 5° into good engine = lowest Vmc; deviations increase it
    - **CG position**: Aft CG = higher Vmc (reduced rudder moment arm)
    - **Prop condition**: Windmilling = highest Vmc; feathered = lowest

    **How to interpret:**
    - The DVmc line shows Vmc at various bank angles
    - Points above the line are controllable; below may not be
    - The published Vmc is a certification point at specific conditions

    **Safety note:**
    - DVmc shows where directional control is lost
    - Always maintain above DVmc during OEI operations
    - Real-world Vmc depends on many factors - this is a planning tool
    """
        },
        "dvyse": {
            "title": "Dynamic Vyse",
            "body": """
    **Dynamic Vyse** shows how the best single-engine rate of climb speed varies with conditions.

    **What affects DVyse:**
    - **Weight**: Higher weight = higher Vyse
    - **Density altitude**: Higher DA = higher Vyse
    - **Configuration**: Gear/flaps extended = higher Vyse
    - **Prop condition**: Affects drag and thus optimal speed

    **How to interpret:**
    - The DVyse marker shows the calculated best single-engine climb speed
    - This is where you'll get maximum climb (or minimum sink) on one engine
    - Published Vyse is based on standard conditions and max weight

    **Practical use:**
    - Adjust Vyse for actual conditions during OEI operations
    - Lighter weight at altitude may require a different target speed
    - Use in conjunction with DVmc to understand the OEI speed envelope
    """
        },
        "fpa": {
            "title": "Flight Path Angle",
            "body": """
    **Flight Path Angle** adjusts the EM diagram for climbing or descending flight.

    **What it represents:**
    - **0°**: Level flight (default)
    - **Positive angles**: Climbing - aircraft exchanges kinetic for potential energy
    - **Negative angles**: Descending - aircraft gains kinetic energy from altitude

    **Effect on the diagram:**
    - Climbing reduces available excess power for maneuvering
    - Descending increases available energy (but altitude is being spent)
    - The diagram shifts to reflect changed energy state

    **Practical use:**
    - Analyze climb performance during maneuvering
    - Plan maneuvers during approach or departure segments
    - Understand how climb/descent affects turn performance
    """
        },
        "maneuver": {
            "title": "Maneuver Overlays & Ghost Trace",
            "body": """
    **Maneuver Overlays** trace the energy state throughout specific flight maneuvers.

    **Steep Turn:**
    - Shows the trajectory through the EM diagram during a constant-altitude steep turn
    - Traces from entry through established turn
    - Helps verify the aircraft has sufficient Ps to maintain altitude

    **Chandelle:**
    - Shows the climbing turn trajectory
    - Entry speed, bank angle, and climb combine to trace a path
    - Useful for planning energy management through the maneuver

    **Ghost Trace:**
    The Ghost Trace toggle displays a visual path showing how the maneuver progresses through the EM diagram:
    - Shows the trajectory from entry conditions through the maneuver
    - Visualizes how airspeed and turn rate change during the maneuver
    - Helps identify if you have enough Ps margin to maintain altitude/complete the maneuver

    **ACS Standards (Steep Turns):**
    - **Private**: 45° bank angle per ACS requirements
    - **Commercial**: 50° bank angle per ACS requirements

    **How to interpret:**
    - The trace shows where in the envelope the maneuver takes you
    - If the trace crosses negative Ps regions, altitude/speed will be lost
    - Staying in positive Ps regions means the maneuver is sustainable

    **Practical use:**
    - Verify maneuver feasibility before attempting
    - Optimize entry speeds and bank angles
    - Understand energy trade-offs during complex maneuvers
    """
        },
        "ghost": {
            "title": "Ghost Trace",
            "body": """
    **Ghost Trace** displays a visual path showing how a maneuver progresses through the EM diagram.

    **What it shows:**
    - The trajectory from entry conditions through the maneuver
    - How airspeed and turn rate change during the maneuver
    - Where the aircraft's energy state moves relative to the performance envelope

    **For Steep Turns:**
    - Shows the path from straight-and-level entry into the established turn
    - Visualizes the speed/energy trade-off during roll-in
    - Helps identify if you have enough Ps margin to maintain altitude

    **For Chandelles:**
    - Traces the climbing turn from entry through the 180° heading change
    - Shows energy state as speed bleeds off during the climb
    - Indicates if the maneuver will result in adequate final airspeed

    **ACS Standards (Steep Turns):**
    - **Private**: 45° bank angle requirement per ACS
    - **Commercial**: 50° bank angle requirement per ACS

    **Practical use:**
    - Preview maneuver energy requirements before flying
    - Optimize entry airspeed for maneuver completion
    - Understand why certain entry conditions may not work
    """
        }
    }

    @app.callback(
        Output("help-modal", "is_open"),
        Output("help-modal-title", "children"),
        Output("help-modal-body", "children"),
        Input("help-ps", "n_clicks"),
        Input("help-g", "n_clicks"),
        Input("help-radius", "n_clicks"),
        Input("help-aob", "n_clicks"),
        Input("help-negative-g", "n_clicks"),
        Input("help-dvmc", "n_clicks"),
        Input("help-dvyse", "n_clicks"),
        Input("help-fpa", "n_clicks"),
        Input("help-maneuver", "n_clicks"),
        Input("help-ghost", "n_clicks"),
        Input("close-help-modal", "n_clicks"),
        State("help-modal", "is_open"),
        prevent_initial_call=True
    )
    def toggle_help_modal(ps, g, radius, aob, neg_g, dvmc, dvyse, fpa, maneuver, ghost, close, is_open):
        """Handle help icon clicks and display appropriate content."""
        if not ctx.triggered:
            raise PreventUpdate

        triggered_id = ctx.triggered_id

        # Extra guard: ensure this is an actual click (n_clicks > 0)
        triggered_value = ctx.triggered[0]["value"] if ctx.triggered else None
        if triggered_value is None or triggered_value == 0:
            raise PreventUpdate

        # Close button
        if triggered_id == "close-help-modal":
            return False, "", ""

        # Map triggered ID to help topic
        topic_map = {
            "help-ps": "ps",
            "help-g": "g",
            "help-radius": "radius",
            "help-aob": "aob",
            "help-negative-g": "negative_g",
            "help-dvmc": "dvmc",
            "help-dvyse": "dvyse",
            "help-fpa": "fpa",
            "help-maneuver": "maneuver",
            "help-ghost": "ghost"
        }

        topic = topic_map.get(triggered_id)
        if topic and topic in HELP_CONTENT:
            content = HELP_CONTENT[topic]
            # Convert markdown to HTML using dcc.Markdown
            body = dcc.Markdown(content["body"], style={"lineHeight": "1.6"})
            return True, content["title"], body

        raise PreventUpdate

