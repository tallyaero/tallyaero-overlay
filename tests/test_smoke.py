"""Smoke tests — every simulation module imports cleanly and exposes its
documented public function. Catches dependency drift and broken imports
before they hit users."""

import importlib

import pytest


SIMULATION_MODULES = [
    ("simulation.base",                  None),  # utility module, no top-level fn
    ("simulation.steep_turn",            "simulate_steep_turn"),
    ("simulation.chandelle",             "simulate_chandelle"),
    ("simulation.lazy_eight",            "simulate_lazy_eight"),
    ("simulation.steep_spiral",          "simulate_steep_spiral"),
    ("simulation.s_turn",                "simulate_s_turn"),
    ("simulation.po180",                 "simulate_power_off_180"),
    ("simulation.glide_path",            "find_required_aob_for_arc_fit"),
    ("simulation.engine_out",            "simulate_engineout_glide"),
    ("simulation.impossible_turn",       "simulate_impossible_turn"),
    ("simulation.turns_around_point",    "simulate_turns_around_point"),
    ("simulation.rectangular_course",    "simulate_rectangular_course"),
    ("simulation.eights_on_pylons",      "simulate_eights_on_pylons"),
]


@pytest.mark.parametrize("module_name,export_name", SIMULATION_MODULES)
def test_simulation_module_imports(module_name, export_name):
    mod = importlib.import_module(module_name)
    if export_name is not None:
        assert hasattr(mod, export_name), \
            f"{module_name} missing expected export: {export_name}"
        assert callable(getattr(mod, export_name)), \
            f"{module_name}.{export_name} is not callable"


def test_core_log_module():
    from core.log import get_logger
    log = get_logger("tests")
    log.info("smoke")
    assert log.name == "tallyaero.overlay.tests"


def test_app_module_imports_without_data():
    """With TALLYAERO_NO_AUTO_INIT=1, app imports without hitting disk."""
    import app
    assert app.aircraft_data == {}
    assert app.airport_data == []
