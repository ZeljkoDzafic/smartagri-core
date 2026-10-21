from __future__ import annotations

import math
from typing import Optional

from ... import config
from ..types import ToolResult

SOURCE = "Allen et al. (1998), FAO-56, ch. 8 (simplified root-zone balance)"

# Fraction of total available water assumed depleted for each qualitative soil status.
# PLACEHOLDER mapping for development; review with the agronomist before locking.
DEPLETION_BY_STATUS = {"dry": 0.60, "moist": 0.30, "wet": 0.05}


def net_irrigation_need(soil_water_status: Optional[str], awc_mm_m: Optional[float],
                        root_depth_m: Optional[float], rain_next_mm: Optional[float]) -> ToolResult:
    """Net depth needed to refill the root zone, less expected rain, split into single applications.

    One application is capped (config rules.irrigation.max_single_net_mm) because a root zone
    cannot take an arbitrarily large depth at once.
    """
    inputs = {"soil_water_status": soil_water_status, "awc_mm_m": awc_mm_m, "root_depth_m": root_depth_m,
              "rain_next_mm": rain_next_mm}
    formula = ("net_total_mm = max(0, depletion_fraction * awc_mm_m * root_depth_m - rain_next_mm); "
               "applications = ceil(net_total_mm / max_single_net_mm)")
    missing = [k for k, v in inputs.items() if v is None]
    if missing:
        return ToolResult("net_irrigation_need", inputs, None, formula, SOURCE, "missing: " + ", ".join(missing))
    if soil_water_status not in DEPLETION_BY_STATUS:
        return ToolResult("net_irrigation_need", inputs, None, formula, SOURCE, "unknown soil_water_status")
    cap = float(config.load("rules")["irrigation"]["max_single_net_mm"])
    taw = awc_mm_m * root_depth_m
    depletion = DEPLETION_BY_STATUS[soil_water_status] * taw
    total = max(0.0, depletion - rain_next_mm)
    applications = int(math.ceil(total / cap)) if total > 0 else 0
    per_application = round(total / applications, 1) if applications else 0.0
    return ToolResult("net_irrigation_need", inputs,
                      {"taw_mm": round(taw, 1), "depletion_mm": round(depletion, 1), "net_total_mm": round(total, 1),
                       "applications": applications, "net_mm": per_application}, formula, SOURCE)
