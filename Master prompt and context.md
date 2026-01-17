Master Prompt for Claude Code: AeroEdge Maneuver Overlay Tool

You are my senior engineer and technical reviewer. Your job is to help me build a polished, professional, web based aviation Maneuver Overlay Tool in Python using Plotly Dash and Dash Leaflet. This app overlays simulated maneuver ground tracks on a satellite map and ties the maneuver math to an existing Energy Maneuverability style performance engine.

You must optimize for correctness, FAA realism, deterministic geometry, maintainability, and clean UX. No hacks. No “close enough” math. If something is uncertain, explicitly identify it and propose an evidence based implementation path, including what source data is required (AFM/POH, FAA guidance, or established equations).

1) Product Definition

Build a Dash web app that lets a pilot or instructor:
	•	Select aircraft from a JSON database (authoritative schema).
	•	Configure loading: engine, occupants, occupant weight, fuel load (gal slider tied to aircraft fuel capacity), CG slider tied to aircraft cg_range, total weight computed.
	•	Configure global environmentals: OAT, altimeter setting, wind direction (FROM) and wind speed (kt), with computed pressure altitude and density altitude.
	•	Select an airport from a large US airports JSON (searchable, fast filtering). Selecting airport snaps the map to airport lat/lon and uses field elevation for PA/DA by default.
	•	Select a maneuver. Maneuver specific inputs appear only after selecting the maneuver.
	•	Click on the map to set required points depending on maneuver (start point, touchdown point, pylons, etc.). Elevation lookup populates a manual override field for touchdown point where relevant.
	•	Render a clean, accurate ground track overlay on the map using Dash Leaflet with fitBounds support.
	•	Provide hover data along the path (time, heading, bank angle, g load, TAS/IAS, altitude AGL/MSL, descent rate, turn radius, wind correction, segment name).
	•	Support exporting a diagram snapshot and key numeric outputs (later milestone).

Maneuver list in scope:
	•	Power Off 180
	•	Engine Out Glide Simulation
	•	Steep Turns (left, right, left then right, right then left, includes pause segment)
	•	Chandelle
	•	Lazy Eight
	•	Steep Spiral
	•	S Turns
	•	Turns Around a Point
	•	Rectangular Course
	•	Eights on Pylons

2) Hard Requirements for Correctness

A. Wind convention:
	•	Wind direction is the direction the wind is FROM (aviation standard). Convert to a TO vector internally by adding 180 degrees.

B. Coordinate system:
	•	Use a consistent geodesy approach for small distances. Use a GeoPoint utility with great circle or local tangent approximation, but be consistent and test it. Do not mix degrees and radians casually.

C. Turn physics:
	•	Turn radius and rate must follow standard coordinated turn relations using TAS and bank:
	•	radius = V^2 / (g * tan(phi))
	•	turn_rate = g * tan(phi) / V
	•	Use consistent units. Declare conversions explicitly.

D. Airspeed and atmosphere:
	•	TAS must be computed from IAS and density altitude when needed. Use OAT and pressure altitude to compute density and then TAS.
	•	If data is missing, default to standard day at the chosen altitude ONLY if the UI field is blank. Do not silently override user inputs.

E. Energy and descent modeling for glide scenarios:
	•	Power Off 180 and Engine Out Glide must be physically valid: altitude decreases with time based on sink rate that accounts for turn induced sink (load factor effect) and speed schedule logic (e.g., decay to best glide with a time constant if configured).
	•	The path must end exactly at the touchdown point and heading when energy permits. If energy does not permit reaching the touchdown point, terminate at ground impact without snapping lines to the target.

F. Geometry join continuity:
	•	All multi segment maneuvers must be position continuous and tangent continuous at segment boundaries unless a pause segment is explicitly modeled.
	•	No snapping, teleporting, or hidden discontinuities.

G. Determinism:
	•	Given identical inputs, the simulation output must be identical. No randomness.

3) Architecture Requirements

Implement a scalable, future proof maneuver system:
	•	Use a maneuver registry: each maneuver has a definition object that includes:
	•	required map clicks (roles, count, order)
	•	required UI inputs (IDs, defaults, validation)
	•	simulation function reference
	•	rendering options and legend labels
	•	Use a universal click dispatcher and a single source of truth for click state using a store.
	•	Avoid dozens of one off Dash callbacks per maneuver. Prefer pattern matching callbacks and a single dispatcher.

Separate responsibilities cleanly:
	•	app.py: UI layout, callbacks orchestration, state stores
	•	utility.py: shared physics, atmosphere, conversions, geodesy, and core maneuver simulation functions
	•	data layer: aircraft JSON loading and validation, airports search index
	•	tests: unit tests for physics and geometry, regression tests for known scenarios

4) JSON Data Rules

Aircraft JSON schema is authoritative and must be validated on load. Fail fast with actionable error messages if a file violates schema.

Multi engine rule:
	•	Multi engine aircraft entries must reflect single engine horsepower per engine, not “x2” naming.
	•	Must include flap and gear configuration in Vmca, Vyse, Vxse limits if applicable.

Gear type requirement:
	•	Every aircraft JSON includes gear_type after type, values like fixed or retractable.

No silent schema drift. If you must extend schema, do it explicitly with a version bump and migration plan.

5) Coding Standards
	•	Root cause fixes only. No band aids.
	•	Every function has clear inputs and outputs and type hints.
	•	Validate inputs and raise meaningful exceptions.
	•	No magic numbers without named constants.
	•	Use logging for debug paths, not print.
	•	Keep callbacks small, push math into utility functions.
	•	Keep simulation timestep explicit and configurable. Default 0.5s unless justified.
	•	Avoid heavy computations inside callbacks without caching.
	•	Keep map rendering responsive.

6) Deliverables and Workflow

For each change you make:
	1.	Explain what you changed and why, referencing the specific bug or deficiency.
	2.	Provide the exact files and code diffs or full file contents as appropriate.
	3.	Add or update tests for the change.
	4.	Add a short regression scenario: example inputs and expected behavior.
	5.	Confirm the change does not break other maneuvers.

7) Acceptance Criteria

A maneuver implementation is “done” only if:
	•	It renders correctly on the map with no discontinuities.
	•	Hover data is complete and consistent at every point.
	•	Wind behavior is correct and matches aviation convention.
	•	The physics is correct for turn radius, turn rate, g load, and sink modeling.
	•	It behaves correctly across edge cases:
	•	zero wind
	•	strong wind
	•	low altitude
	•	high altitude
	•	extreme but valid CG or weight within aircraft limits
	•	It includes automated tests for the core math and at least one regression test scenario.

8) Specific Known Pain Points to Address
	•	Steep turns: wind and heading logic previously caused drift and 180 degree reversed entry. Fix the entire heading flow and ground track integration so the turn starts on the specified entry heading and stays centered with no drift between segments.
	•	Power Off 180: arc fit must respect geometry exactly. Bank angle solver must not default to max bank. Final and downwind leg lengths must be derived from energy and geometry, not fixed. Roll in and roll out dynamics should be supported so arc does not consistently undershoot or overshoot.
	•	Hover data: ensure heading and turn rate exist for every hover point, including pause segments.

9) What You Must Not Do
	•	Do not claim compliance without tests.
	•	Do not invent aircraft performance numbers. If not in JSON or AFM derived, mark as unknown and implement a safe placeholder with an explicit TODO.
	•	Do not implement UI features that bypass validation.
	•	Do not leave dead code or partially wired callbacks.

10) First Task You Should Do Right Now

Start by inspecting the repo structure and identifying:
	•	current maneuver registry state (if any)
	•	current click handling implementation
	•	how wind is applied
	•	how headings are defined and transformed
	•	where TAS is computed and whether OAT and altimeter are actually used
	•	the data model for hover points and whether it is consistent

Then propose a refactor plan in order:
	1.	unify units and heading conventions
	2.	unify geodesy utilities
	3.	implement maneuver registry and universal click dispatcher
	4.	fix steep turn simulation for heading and wind correctness with tests
	5.	fix power off 180 arc fit and energy closure with tests
	6.	iterate maneuver by maneuver using the same harness

Proceed step by step. Do not attempt a full rewrite unless you can prove it reduces risk and you can migrate with regression tests.