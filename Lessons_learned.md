 Prompt for Claude Code - Maneuver Overlay Tool:

  I'm building an TallyAero Maneuver Overlay Tool that needs to follow the same patterns established in our EM Diagram app. This is a reference guide for architecture, UI/UX patterns, and lessons learned.

  ## DESIGN SYSTEM
  Reference our shared style guide in AEROEDGE_STYLE_GUIDE.md (or read from the EM Diagram's assets/styles.css). Key brand elements:
  - Primary Orange: #E65C00 (buttons, accents, active states)
  - Primary Blue: #2980B9 (links, secondary actions)
  - Navy Background: #0A1628 (header banner)
  - Font: 'Inter', 'Helvetica Neue', sans-serif

  ## LAYOUT ARCHITECTURE

  ### Desktop Layout (reference EM Diagram pattern)
  ┌─────────────────────────────────────────────────────────┐
  │ Header Banner (navy bg, centered logo, 110px height)    │
  ├─────────────────────────────────────────────────────────┤
  │ Warning/Disclaimer Banner (yellow #fff3cd, brown text)  │
  ├─────────────────────────────────────────────────────────┤
  │ Quick Links Bar (centered, 13px, underlined links)      │
  ├──────────────────┬──────────────────────────────────────┤
  │ Resizable        │                                      │
  │ Sidebar          │  Main Content / Graph Area           │
  │ (360px default)  │  (flex: 1, fills remaining)          │
  │ - Accordions     │                                      │
  │ - Config inputs  │  Export toolbar overlay (top-left)   │
  │ - Collapse btn   │                                      │
  ├──────────────────┴──────────────────────────────────────┤
  │ Legal Links Footer (centered, 12px)                     │
  └─────────────────────────────────────────────────────────┘

  ### Mobile Layout (separate component, not responsive CSS)
  - Detect viewport width and render entirely different layout
  - Collapsible settings panel (orange border, slides down)
  - Horizontal scroll for square graph in portrait mode
  - Compact logo bar, minimal padding
  - Touch-friendly controls (larger tap targets)

  ### Key CSS Patterns:
  - `.full-height-container` with flex column, 100vh
  - `.main-row` with flex: 1 1 0, min-height: 0 (critical for nested flex)
  - `.resizable-sidebar` with resize: horizontal, overflow-y: auto
  - `.graph-column` with flex: 1 1 0, min-width: 0

  ## SIDEBAR ARCHITECTURE

  ### Accordion Pattern (Bootstrap dbc.Accordion)
  ```python
  dbc.Accordion([
      dbc.AccordionItem([...content...], title="Section Name", item_id="section-id"),
  ], id="main-accordion", active_item=["section-id"], always_open=True)

  Styling for dark theme accordions:
  - Header bg: #5a6a7a
  - Body bg: #4a5568
  - Border: #718096
  - Active header: #667788 with orange text
  - Arrow icon filter for light/orange colors

  Collapsible Sidebar

  - Toggle button (« / ») in sidebar header
  - .collapsed class reduces to 36px strip
  - Store collapse state in dcc.Store for persistence
  - Hide all children except header when collapsed

  Input Field Patterns

  - Light backgrounds (#f7fafc) with dark text (#1a202c) on dark accordion bodies
  - Consistent border radius (4px)
  - Orange focus border color
  - Dropdown menus with z-index: 9999 and overflow: visible on parent containers

  AIRCRAFT EDIT PAGE PATTERN

  Route Setup

  # In app.py
  app.layout = html.Div([
      dcc.Location(id='url', refresh=False),
      html.Div(id='page-content')
  ])

  @app.callback(Output('page-content', 'children'), Input('url', 'pathname'))
  def display_page(pathname):
      if pathname == '/edit-aircraft':
          return edit_aircraft_layout
      return main_layout

  Quick Start / Preset System

  - Grid of preset buttons (Basic Trainer, High Performance, Light Twin, etc.)
  - Each preset fills ALL form fields with sensible defaults
  - "?" help buttons next to each with dbc.Popover explaining assumptions
  - Example aircraft listed in popover content

  Dynamic Form Sections

  - Use dcc.Store to hold list data (e.g., stored-stall-speeds, stored-engine-options)
  - Render callbacks that rebuild UI from store data
  - Pattern-matching callbacks for dynamic add/remove:
  Input({"type": "field-name", "index": ALL}, "value")

  Units Toggle

  - Two-position toggle switch (dbc.Switch)
  - Hidden dcc.Input to store actual unit value
  - Conversion callback that transforms all speed values

  Expand All / Collapse All

  @app.callback(
      Output("accordion-id", "active_item"),
      Input("expand-all-btn", "n_clicks"),
      Input("collapse-all-btn", "n_clicks"),
  )
  def expand_collapse_all(expand, collapse):
      all_items = ["item1", "item2", "item3", ...]
      if ctx.triggered_id == "expand-all-btn":
          return all_items
      return []

  EXPORT FUNCTIONALITY

  Current Implementation (PNG/PDF)

  - Export toolbar positioned absolute, top-left of graph area
  - Server-side generation using kaleido for Plotly figures
  - dcc.Download component for file delivery
  Output("download-component", "data"),
  # Return: dcc.send_bytes(image_bytes, filename)

  For Maneuver Overlay Exports

  Consider exporting:
  - Maneuver diagram as PNG/PDF
  - Maneuver data as JSON (parameters, aircraft config, results)
  - Combined report: image + calculated values + notes
  - Print-friendly layout option

  HELP SYSTEM

  README Modal

  dbc.Modal([
      dbc.ModalHeader(dbc.ModalTitle("How to Use This Tool")),
      dbc.ModalBody([
          # Markdown or structured HTML content
          dcc.Markdown(readme_content)
      ]),
      dbc.ModalFooter(
          dbc.Button("Close", id="close-readme", className="btn-primary-sm")
      ),
  ], id="readme-modal", size="lg", scrollable=True)

  "?" Help Icons Pattern

  html.Div([
      html.Span("Field Label", className="input-label-sm"),
      html.Span("?", id="help-fieldname", className="help-icon"),
      dbc.Popover(
          [
              dbc.PopoverHeader("Field Name"),
              dbc.PopoverBody([
                  html.P("Explanation of what this field does..."),
                  html.P("Why it matters for the calculation..."),
              ])
          ],
          target="help-fieldname",
          trigger="click",  # or "hover"
          placement="right"
      )
  ], style={"display": "flex", "alignItems": "center", "gap": "6px"})

  CSS for help icons:
  .help-icon {
      width: 16px; height: 16px;
      border-radius: 50%;
      background-color: var(--blue-primary);
      color: white;
      font-size: 10px;
      cursor: pointer;
  }

  MANEUVER-SPECIFIC FEATURES TO IMPLEMENT

  1. Slip Physics (for Power-Off 180)

  - Calculate slip angle effects on glide performance
  - Cross-controlled configuration drag increase
  - Forward slip vs side slip aerodynamics
  - Show energy bleed rate with slip applied

  2. Engine-Out Glide

  - Best glide speed at current weight
  - Glide ratio degradation factors (prop windmilling vs feathered)
  - Distance achievable from current altitude
  - Wind correction for glide distance

  3. Impossible Turn Analysis

  - Minimum altitude required for turnback
  - Turn radius at various bank angles
  - Energy loss during turn (altitude + speed)
  - Runway alignment geometry
  - GO/NO-GO visualization with safety margins

  4. Dead Engine Approach

  - Single-engine approach path planning
  - Avoiding runway overrun scenarios
  - Energy management on final
  - Slip-to-land option analysis

  PHYSICS AUDIT CHECKLIST TEMPLATE

  For each maneuver, create an audit covering:

  Physics Accuracy

  - Equations sourced from authoritative references (FAA, POH, aerodynamics texts)
  - Units handled correctly throughout calculations
  - Edge cases handled (zero values, max limits, negative results)
  - Results validated against known aircraft performance data
  - Assumptions documented and reasonable

  Reality Check

  - Results match real-world pilot experience
  - Extreme inputs produce reasonable (not absurd) outputs
  - Safety margins appropriately conservative
  - Accounts for typical environmental factors

  Implementation

  - Calculation runs efficiently (no lag on input changes)
  - Errors handled gracefully with user feedback
  - Input validation prevents invalid states
  - Results cached/memoized where appropriate

  UI/UX

  - Labels clear and unambiguous
  - Units displayed consistently
  - Visual hierarchy guides user flow
  - Critical outputs prominently displayed
  - Help available for complex concepts

  Workflow

  - Logical input order (general → specific)
  - Sensible defaults provided
  - Quick presets for common scenarios
  - Easy to iterate and compare scenarios
  - Export/save functionality for results

  Improvement Opportunities

  - Can inputs be simplified or combined?
  - Are there redundant displays?
  - Could visualization be clearer?
  - Mobile experience adequate?
  - Accessibility considerations?

  FAA MANEUVERS TO CONSIDER

  Potential maneuvers for overlay tool:
  - Steep Turns (45°/60° bank, load factor, stall speed increase)
  - Chandelles (energy exchange, heading change, altitude gain)
  - Lazy Eights (symmetry, altitude/airspeed tolerances)
  - Eights on Pylons (pivotal altitude calculation)
  - Power-Off 180 (glide management, slip effects)
  - Short Field Landing (approach angle, touchdown point)
  - Soft Field Takeoff (ground effect, climb gradient)
  - Emergency Descent (Vne considerations, configuration)
  - Spin Entry/Recovery (incipient vs developed, altitude loss)

  LESSONS LEARNED FROM EM DIAGRAM

  1. Overflow issues: Always set overflow: visible !important on accordion items, bodies, and collapse elements when dropdowns are inside
  2. Dropdown readability: On dark backgrounds, force light background (#f7fafc) with dark text (#1a202c) on dropdown menus and options
  3. Mobile-first complexity: Building separate mobile layout is cleaner than trying to make desktop responsive
  4. Store consistency: Use consistent key names in dcc.Store data across load/save/render callbacks (we had "config" vs "config_key" bug)
  5. Nested flex height: Parent containers need min-height: 0 for children to properly size with flex
  6. Z-index wars: Dropdown menus need high z-index (9999) and positioned parents
  7. Save callback completeness: When adding new form fields, remember to add them to BOTH the State inputs AND the save function parameters
  8. JSON schema matching: Ensure saved data structure matches expected schema (nested objects vs flat)
  9. Units conversion: Apply unit conversion at save time to always store in standard units (KIAS)
  10. Preset completeness: Quick-fill presets should populate ALL fields, not just primary ones

  FILE STRUCTURE SUGGESTION

  maneuver-overlay-tool/
  ├── app.py                 # Main Dash app, callbacks
  ├── assets/
  │   └── styles.css         # Shared TallyAero styles
  ├── layouts/
  │   ├── desktop.py         # Desktop layout
  │   ├── mobile.py          # Mobile layout
  │   └── edit_aircraft.py   # Aircraft editor page
  ├── components/
  │   ├── sidebar.py         # Sidebar with accordions
  │   ├── graph_panel.py     # Main visualization
  │   ├── export_toolbar.py  # Export buttons
  │   └── help_modals.py     # README, disclaimer, help popovers
  ├── core/
  │   ├── calculations.py    # Physics calculations
  │   ├── maneuvers/         # Individual maneuver modules
  │   │   ├── steep_turn.py
  │   │   ├── power_off_180.py
  │   │   └── ...
  │   └── constants.py       # Physical constants
  ├── aircraft_data/         # Aircraft JSON files
  └── tests/                 # Physics validation tests

  Start by setting up the basic layout structure, then implement one complete maneuver with full UI/help/export before expanding to others.

  ---

  This prompt gives the Claude Code agent in your Maneuver Overlay Tool project the full context of what worked, what to avoid, and the patterns to follow.