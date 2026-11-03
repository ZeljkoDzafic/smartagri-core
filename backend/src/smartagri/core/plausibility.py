"""Plausibility of the inputs the decision reads (audit D3, D13).

A value that cannot be right is not used. This module only says WHY a value is implausible; q (core/quality.py) grades
such an input "low" with the basis "implausible value", and `values()` hands it to the decision cores and the tools as
unknown, so it can never make a decision sufficient or change an action. The limits are configuration
(rules.input_limits, development values; see docs/limitations.md); a value on a limit is plausible, except that an
efficiency must be greater than zero.
"""
from __future__ import annotations

import math
from typing import Any, Optional

from .. import config
from .types import parse_date

# Input name (core/quality.py TRACKED_INPUTS) -> key of rules.input_limits.
LIMIT_KEY = {
    "soil_moisture_sensor": "soil_moisture_vwc", "soil_awc": "soil_awc_mm_m", "irrigation_efficiency": "irrigation_efficiency",
    "precip_past_7d": "precipitation_mm", "precip_forecast_3d": "precipitation_mm", "precip_forecast_7d": "precipitation_mm",
    "et0_past_7d": "et0_mm", "yield_target": "yield_target_t_ha",
}
LOWER_EXCLUSIVE = frozenset({"irrigation_efficiency"})      # an efficiency of 0 would divide by zero
FINITE_NON_NEGATIVE = frozenset({"wind_forecast", "irrigation_capacity", "plant_density", "hybrid_fao"})
SOIL_WATER_STATES = ("dry", "moist", "wet")
BBCH_RANGE = (0, 99)                                        # the BBCH scale itself, not an agronomic parameter


def number(value: Any) -> Optional[float]:
    """`value` as a float when it is a real number (not a bool, a string, a container); else None."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def limits(key: str) -> list:
    return list(config.load("rules")["input_limits"][key])


def check_number(value: Any, lo: Optional[float] = None, hi: Optional[float] = None, lower_exclusive: bool = False) -> Optional[str]:
    """Why `value` is not an acceptable number, or None."""
    x = number(value)
    if x is None:
        return "not a number"
    if not math.isfinite(x):
        return "not finite"
    if lo is not None and (x <= lo if lower_exclusive else x < lo):
        return "below the minimum of %g" % lo
    if hi is not None and x > hi:
        return "above the maximum of %g" % hi
    return None


def problem(name: str, value: Any) -> Optional[str]:
    """The reason the value of input `name` is implausible, or None when it can be used."""
    if value is None:
        return None
    if name in LIMIT_KEY:
        lo, hi = limits(LIMIT_KEY[name])
        return check_number(value, lo, hi, name in LOWER_EXCLUSIVE)
    if name in FINITE_NON_NEGATIVE:
        return check_number(value, 0.0, None)
    if name == "phenophase":
        return check_number(value, *BBCH_RANGE)
    if name == "temp_forecast":
        if not isinstance(value, dict):
            return "not a number"
        return next((r for r in (check_number(v) for v in value.values()) if r), None)
    if name == "sowing_date" and parse_date(value) is None:
        return "not an ISO date"
    if name == "soil_water_status" and value not in SOIL_WATER_STATES:
        return "not one of %s" % ", ".join(SOIL_WATER_STATES)
    return None
