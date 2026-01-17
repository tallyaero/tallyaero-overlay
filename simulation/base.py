"""
Base simulation utilities and configuration helpers.
"""
import math
from physics.navigation import _wrap_360


def _canon_flap_config(val: str) -> str:
    """Canonicalize flap configuration strings."""
    v = (val or "clean").strip().lower()
    if v in {"clean", "takeoff", "landing"}:
        return v
    return "clean"


def _canon_prop_config(val: str) -> str:
    """Canonicalize propeller configuration strings."""
    v = (val or "windmilling").strip().lower()
    if v in {"idle", "windmilling", "stationary", "feathered"}:
        return v
    if v in {"stopped", "propstopped", "prop_stopped", "prop stopped"}:
        return "stationary"
    return "windmilling"


def _ref_weight_lb(ac: dict):
    """Extract reference weight from aircraft data."""
    for k in ("max_gross_lb", "max_gross_weight_lb", "mtow_lb", "gross_weight_lb"):
        v = ac.get(k)
        if isinstance(v, (int, float)) and v > 0:
            return float(v)
    return None


def _runtime_total_weight_lb(ac: dict):
    """Extract runtime total weight from aircraft data."""
    for k in ("total_weight_lb", "current_total_weight_lb", "selected_weight_lb"):
        v = ac.get(k)
        if isinstance(v, (int, float)) and v > 0:
            return float(v)
    return None


def _weight_adjust_speed_kias(v_ref_kias: float, ac: dict) -> float:
    """Adjust reference speed by weight ratio."""
    W = _runtime_total_weight_lb(ac)
    Wref = _ref_weight_lb(ac)
    if W is None or Wref is None or W <= 0 or Wref <= 0:
        return float(v_ref_kias)
    return float(v_ref_kias) * math.sqrt(W / Wref)


def _best_glide_speed_kias(ac: dict, engine_option: str = None) -> float:
    """Extract best glide speed from aircraft data."""
    try:
        se = ac.get("single_engine_limits", {})
        bg = se.get("best_glide", None)
        if bg is not None:
            return float(bg)
    except Exception:
        pass
    return 80.0


def _get_best_glide_and_ratio(ac: dict, engine_option: str, flap_config: str, prop_config: str):
    """
    Returns (best_glide_kias, base_glide_ratio).
    Uses OEI block for multi engine when available, otherwise single engine limits.
    Applies weight-based best-glide scaling if ac contains a runtime total_weight_lb.
    """
    flap_config = _canon_flap_config(flap_config)
    prop_config = _canon_prop_config(prop_config)

    se_limits = ac.get("single_engine_limits", {}) or {}
    base_ratio = float(se_limits.get("best_glide_ratio", 9.0))

    bg_kias = None

    # Multi engine: prefer OEI performance if present
    if int(ac.get("engine_count", 1)) > 1 and engine_option:
        try:
            eo = (ac.get("engine_options", {}) or {}).get(engine_option, {}) or {}
            oei = eo.get("oei_performance", {}) or {}

            key = f"{flap_config}_up"
            block = oei.get(key)

            if block is None:
                block = oei.get("clean_up") or oei.get("up") or oei.get("clean") or None

            if block is not None:
                perf = block.get(prop_config)
                if perf is None:
                    perf = block.get("windmilling") or block.get("idle") or block.get("feathered") or block.get("stationary")

                if perf is not None:
                    bg = perf.get("best_glide_speed_kias")
                    if bg is not None:
                        bg_kias = float(bg)
        except Exception:
            bg_kias = None

    # Single engine fallback
    if bg_kias is None:
        bg = se_limits.get("best_glide", None)
        bg_kias = float(bg) if bg is not None else 80.0

    # Weight-adjust final answer
    bg_kias = _weight_adjust_speed_kias(bg_kias, ac)
    return bg_kias, base_ratio
