from __future__ import annotations

from typing import Optional

from ... import config
from ..types import ToolResult

SOURCE = "config/rules.yaml: phenology (approximate; review before locking)"


def estimate_bbch(gdd_since_sowing: Optional[float] = None, days_since_sowing: Optional[int] = None,
                  hybrid_fao: Optional[int] = None) -> ToolResult:
    """Estimate maize BBCH from thermal time, or from days since sowing when no thermal time exists.

    The result is always an estimate: origin 'derived', never better than medium reliability.
    """
    rules = config.load("rules")["phenology"]
    inputs = {"gdd_since_sowing": gdd_since_sowing, "days_since_sowing": days_since_sowing, "hybrid_fao": hybrid_fao}
    # Later maturity groups need more thermal time for the same stage (spec 009, US3).
    scale = 1.0
    if hybrid_fao is not None:
        opt = config.load("rules")["optional_inputs"]
        scale = 1.0 + (hybrid_fao - opt["fao_reference"]) / 100.0 * opt["fao_gdd_per_100"]
    if gdd_since_sowing is not None:
        for row in rules["gdd_to_bbch"]:
            if gdd_since_sowing <= row["gdd_max"] * scale:
                return ToolResult("estimate_bbch", inputs, {"bbch": row["bbch"], "method": "gdd"},
                                  "lookup of cumulative GDD (base %s C)" % rules["gdd_base_c"], SOURCE)
    if days_since_sowing is not None and days_since_sowing >= 0:
        for row in rules["days_to_bbch"]:
            if days_since_sowing <= row["days_max"] * scale:
                return ToolResult("estimate_bbch", inputs, {"bbch": row["bbch"], "method": "days"},
                                  "lookup of days since sowing", SOURCE)
    return ToolResult("estimate_bbch", inputs, None, "", SOURCE, "missing sowing date and thermal time")
