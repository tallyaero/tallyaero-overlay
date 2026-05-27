"""
TallyAero — Plotly theme palettes for the EM diagram chart.

Plotly's `paper_bgcolor`, `plot_bgcolor`, and trace colors are baked into the
figure layout at render time. CSS variables can't reach them. So we mirror
the TallyAero `--ta-*` design tokens here as a pair of palette dicts and
expose a single helper `get_palette(theme_pref)` that `update_graph` calls.

Brand/signal colors (stall red, Vyse blue, corner orange, energy green) live
in the figure code itself and are intentionally theme-stable — pilots learn
the meaning of "the red curve" and that meaning shouldn't flip between modes.

Only structural colors flip:
    paper/plot bg, foreground lines (G-limit, axes), grid, title, annotation
    muted lines (Ps contours), tick labels.
"""

from __future__ import annotations

from typing import Literal, TypedDict


class Palette(TypedDict):
    paper_bg:        str   # paper_bgcolor
    plot_bg:         str   # plot_bgcolor
    text:            str   # default font color
    title:           str   # chart title color
    fg:              str   # foreground line color — was "black"
    muted:           str   # muted line color — was "gray"
    grid:            str   # axis gridcolor
    axis_line:       str   # axis linecolor
    tick:            str   # tick label color
    annotation_bg:   str   # annotation backgrounds
    annotation_text: str   # annotation text default


# Palettes (verbatim mirrors of --ta-* tokens in assets/tokens.css)
LIGHT: Palette = {
    "paper_bg":        "#f8fafc",   # --ta-surface-primary
    "plot_bg":         "#ffffff",   # --ta-surface-secondary  (slight contrast w/ paper)
    "text":            "#0f172a",   # --ta-text-primary
    "title":           "#0a47c9",   # --ta-brand-blue-dark    (was hardcoded #005F8C)
    "fg":              "#0f172a",   # foreground = primary text
    "muted":           "#94a3b8",   # --ta-text-tertiary       (was "gray")
    "grid":            "#e2e8f0",   # --ta-border-primary
    "axis_line":       "#cbd5e1",   # --ta-text-quaternary
    "tick":            "#64748b",   # --ta-text-secondary
    "annotation_bg":   "rgba(248,250,252,0.9)",
    "annotation_text": "#0f172a",
}

DARK: Palette = {
    "paper_bg":        "#0a0e17",   # --ta-surface-primary (dark)
    "plot_bg":         "#161e2d",   # --ta-surface-secondary (dark)
    "text":            "#f1f5f9",   # --ta-text-primary (dark)
    "title":           "#3B82F6",   # --ta-brand-blue-light (better contrast on dark)
    "fg":              "#f1f5f9",
    "muted":           "#64748b",   # --ta-text-quaternary (dark)
    "grid":            "#222f49",   # --ta-border-primary (dark)
    "axis_line":       "#94a3b8",
    "tick":            "#cbd5e1",
    "annotation_bg":   "rgba(22,30,45,0.92)",
    "annotation_text": "#f1f5f9",
}


ThemePref = Literal["light", "dark", "system", None]


def get_palette(theme_pref: ThemePref = None) -> Palette:
    """Resolve a theme preference to a concrete palette.

    Args:
        theme_pref: One of "light", "dark", "system", or None. If "system" or
            None, we currently default to LIGHT (server-side resolution can't
            know the client's prefers-color-scheme; client-side post-processing
            can override later if needed).

    Returns:
        The Palette dict.

    Notes:
        Server-side rendering has no access to the client's OS theme, so
        "system" resolves to LIGHT here. The client-side early-paint script
        in app.index_string sets data-theme on <html> based on actual OS
        preference, and the toggle UI lets the user override.
    """
    if theme_pref == "dark":
        return DARK
    # "light", "system", None, and anything unknown → light.
    return LIGHT
