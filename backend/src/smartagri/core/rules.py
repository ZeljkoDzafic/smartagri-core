"""Deterministic decision cores D_t(values) -> action class.

No language model is involved. The cores exist for two reasons: they make the recommended class of
action checkable, and they let question selection ask "would the answer change the decision?".
All thresholds come from config/rules.yaml and must be reviewed by the agronomist before locking.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from .. import config
from .types import AdviceType

UNKNOWN = "?"


def _band(value: Optional[float], bounds) -> str:
    if value is None:
        return UNKNOWN
    if value < bounds[0]:
        return "low"
    return "medium" if value < bounds[1] else "high"


def soil_status(v: Dict[str, Any]) -> Optional[str]:
    if v.get("soil_water_status"):
        return v["soil_water_status"]
    vwc = v.get("soil_moisture_sensor")
    if vwc is None:
        return None
    lo, hi = config.load("rules")["irrigation"]["vwc_bands"]
    return "dry" if vwc < lo else ("moist" if vwc < hi else "wet")


def n_level(prev: Any) -> str:
    if prev is None:
        return UNKNOWN
    if isinstance(prev, str):
        return prev
    total = sum(float(item.get("n_kg_ha", 0) or 0) for item in prev)
    if total <= 0:
        return "none"
    return "full" if total >= config.load("rules")["fertilization"]["season_n_full_kg_ha"] else "partial"


def irrigation_timing(v: Dict[str, Any]) -> str:
    r = config.load("rules")["irrigation"]
    if v.get("irrigation_available") == "no":
        return "not_possible"
    if v.get("phenophase") is not None and v["phenophase"] >= r["late_season_bbch"]:
        return "late_season"
    rain = v.get("precip_forecast_3d")
    if rain is not None and rain >= r["rain_wait_mm_3d"]:
        return "wait_for_rain"
    status = soil_status(v)
    if status is None:
        return UNKNOWN
    return {"dry": "irrigate_within_2d", "moist": "recheck_in_3d", "wet": "not_needed"}[status]


def irrigation_amount(v: Dict[str, Any]) -> str:
    timing = irrigation_timing(v)
    if timing in ("not_possible", "late_season", "wait_for_rain", "not_needed"):
        return timing
    status = soil_status(v)
    dose = {"dry": "full_refill", "moist": "partial_refill"}.get(status, UNKNOWN)
    band = _band(v.get("soil_awc"), config.load("rules")["irrigation"]["awc_bands_mm_m"])
    return "%s|awc:%s" % (dose, band)


def _fert_window(bbch: Optional[int]) -> str:
    f = config.load("rules")["fertilization"]
    if bbch is None:
        return UNKNOWN
    lo, hi = f["topdress_bbch"]
    if bbch > f["late_bbch_max"]:
        return "too_late"
    if bbch < lo:
        return "wait_for_window"
    return "topdress_now" if bbch <= hi else "late_window_caution"


def fertilization_timing(v: Dict[str, Any]) -> str:
    return _fert_window(v.get("phenophase"))


def fertilization_plan(v: Dict[str, Any]) -> str:
    window = _fert_window(v.get("phenophase"))
    if window == "too_late":
        return window
    prev = n_level(v.get("previous_fertilization"))
    if prev == "full":
        return "no_additional_n"
    analysis = v.get("soil_analysis")
    if isinstance(analysis, dict):
        analysis = analysis.get("level")
    if analysis in ("low", "medium", "high"):
        dose = {"low": "high", "medium": "medium", "high": "low"}[analysis]   # low fertility -> higher dose
    else:
        dose = _band(v.get("yield_target"), config.load("rules")["fertilization"]["yield_bands_t_ha"])
    if dose != UNKNOWN and n_credit(v):
        dose = {"high": "medium", "medium": "low", "low": "low"}[dose]          # legume or manure N credit
    return "%s|prev:%s|dose:%s" % (window, prev, dose)


def n_credit(v: Dict[str, Any]) -> bool:
    """Nitrogen left by a legume previous crop or by manure in the last year (spec 009, US2)."""
    opt = config.load("rules")["optional_inputs"]
    if v.get("previous_crop") in opt["legumes"]:
        return True
    return bool(v.get("manure"))


def field_ops_window(v: Dict[str, Any]) -> str:
    r = config.load("rules")["field_ops"]
    op = v.get("operation")
    if not op:
        return UNKNOWN
    rain = v.get("precip_forecast_3d")
    if rain is None:
        rain = v.get("precip_forecast_7d")
    temp = v.get("temp_forecast") or {}
    wind = v.get("wind_forecast")
    if op == "spraying":
        if (wind is not None and wind > r["spraying_max_wind_ms"]) or (rain is not None and rain > r["rain_block_mm_3d"]):
            return "postpone"
        return "window_open"
    if op == "sowing":
        return "postpone" if temp.get("tmin") is not None and temp["tmin"] <= r["frost_tmin_c"] else "window_open"
    if op == "fertilizing":
        return "window_open_before_rain" if rain is not None and rain > r["rain_block_mm_3d"] else "window_open_dry"
    return "postpone" if rain is not None and rain > 5 * r["rain_block_mm_3d"] else "window_open"


def scouting(v: Dict[str, Any]) -> str:
    r = config.load("rules")["scouting"]
    opt = config.load("rules")["optional_inputs"]
    events = set(v.get("field_observation") or [])
    if events & set(opt["priority_events"]):
        return "priority_scouting_event"          # hail, lodging or waterlogging reported this week
    if v.get("ndvi_latest") is None:
        return "no_satellite_view"
    contrast, trend = v.get("ndvi_spatial_contrast"), v.get("ndvi_trend")
    if (contrast is not None and contrast >= r["contrast_priority"]) or (trend is not None and trend <= r["trend_priority"]):
        return "priority_scouting"
    return "routine_scouting"


CORES = {
    AdviceType.IRRIGATION_TIMING: irrigation_timing,
    AdviceType.IRRIGATION_AMOUNT: irrigation_amount,
    AdviceType.FERTILIZATION_PLAN: fertilization_plan,
    AdviceType.FERTILIZATION_TIMING: fertilization_timing,
    AdviceType.FIELD_OPS_WINDOW: field_ops_window,
    AdviceType.SCOUTING: scouting,
}


def decide_action_core(t: AdviceType, v: Dict[str, Any]) -> Optional[str]:
    core = CORES.get(t)
    return core(v) if core else None
