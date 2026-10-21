"""Deterministic agronomic tools. The language model never computes numbers; these do.

Every tool returns a ToolResult with its inputs, output, formula and source. A tool that lacks
an input returns output=None with a reason. It never substitutes a default value.
"""
from .etc import crop_evapotranspiration, kc_for_bbch
from .irrigation import gross_irrigation
from .ndvi_stats import ndvi_summary
from .phenology import estimate_bbch
from .water_balance import net_irrigation_need

__all__ = ["crop_evapotranspiration", "kc_for_bbch", "gross_irrigation", "ndvi_summary",
           "estimate_bbch", "net_irrigation_need"]
