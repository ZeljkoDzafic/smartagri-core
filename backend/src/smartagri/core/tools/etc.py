from __future__ import annotations

from typing import Optional

from ... import config
from ..plausibility import check_number
from ..types import ToolResult

SOURCE = "Allen et al. (1998), FAO-56, Table 12"


def kc_for_bbch(bbch: Optional[int]) -> Optional[float]:
    if bbch is None:
        return None
    for row in config.load("kc_maize")["kc"]:
        if row["bbch_min"] <= bbch <= row["bbch_max"]:
            return float(row["kc"])
    return None


def crop_evapotranspiration(bbch: Optional[int], et0_mm: Optional[float]) -> ToolResult:
    """ETc = Kc x ET0 over the same period as et0_mm."""
    inputs = {"bbch": bbch, "et0_mm": et0_mm}
    kc = kc_for_bbch(bbch)
    if et0_mm is not None and check_number(et0_mm, 0.0):
        return ToolResult("etc", inputs, None, "ETc = Kc * ET0", SOURCE, "invalid et0_mm: " + check_number(et0_mm, 0.0))
    if kc is None or et0_mm is None:
        missing = [k for k, v in (("bbch", kc), ("et0_mm", et0_mm)) if v is None]
        return ToolResult("etc", inputs, None, "ETc = Kc * ET0", SOURCE, "missing: " + ", ".join(missing))
    return ToolResult("etc", inputs, {"kc": kc, "etc_mm": round(kc * et0_mm, 1)}, "ETc = Kc * ET0", SOURCE)
