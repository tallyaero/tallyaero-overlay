"""
Smoke tests for the callbacks/ package.

Each migrated module exports `register(app)`. We don't exercise the callbacks
(that requires a full Dash app instance); we just verify the public surface
and that register_all() invokes every submodule.
"""

from __future__ import annotations

import inspect

import pytest


def test_register_all_exists():
    from callbacks import register_all
    assert callable(register_all)


# Auto-discover every submodule in callbacks/ (excluding __init__).
def _submodules():
    import pkgutil
    import callbacks as pkg
    return [
        name
        for _, name, _ in pkgutil.iter_modules(pkg.__path__)
        if not name.startswith("_")
    ]


def test_each_submodule_exports_register():
    """Every module in callbacks/ must have a `register(app)` callable taking
    exactly one arg."""
    import importlib

    for name in _submodules():
        mod = importlib.import_module(f"callbacks.{name}")
        assert hasattr(mod, "register"), f"callbacks.{name} missing register()"
        sig = inspect.signature(mod.register)
        params = list(sig.parameters.values())
        assert len(params) == 1, (
            f"callbacks.{name}.register must take exactly one arg (app), got {len(params)}"
        )


def test_register_all_invokes_each_submodule():
    """register_all(app) must call register() on every submodule, passing
    the same app object to each. Auto-discovers modules so new ones are
    covered without test edits.
    """
    import importlib
    import callbacks as pkg

    submods = _submodules()
    modules = [importlib.import_module(f"callbacks.{n}") for n in submods]

    called: list[tuple[str, object]] = []
    originals: dict[str, callable] = {}

    try:
        for name, mod in zip(submods, modules):
            originals[name] = mod.register
            # Closure-bound name so we record which module was called.
            mod.register = (lambda app, _n=name: called.append((_n, app)))

        sentinel = object()
        pkg.register_all(sentinel)

        names_called = [c[0] for c in called]
        for name in submods:
            assert name in names_called, f"callbacks.{name}.register not invoked"
        for _, app in called:
            assert app is sentinel, "register() got wrong app object"
    finally:
        for name, mod in zip(submods, modules):
            if name in originals:
                mod.register = originals[name]
