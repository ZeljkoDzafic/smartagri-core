from __future__ import annotations

from typing import Optional

from ..plausibility import check_number
from ..types import ToolResult

SOURCE = "FAO, Irrigation Water Management: Irrigation Scheduling, ch. 3"


def gross_irrigation(net_mm: Optional[float], efficiency: Optional[float]) -> ToolResult:
    """gross = net / efficiency; 1 mm on 1 ha = 10 m3."""
    inputs = {"net_mm": net_mm, "efficiency": efficiency}
    formula = "gross_mm = net_mm / efficiency; m3_per_ha = gross_mm * 10"
    if net_mm is None or efficiency is None:
        return ToolResult("gross_irrigation", inputs, None, formula, SOURCE, "missing net_mm or efficiency")
    if check_number(net_mm, 0.0) or check_number(efficiency):
        return ToolResult("gross_irrigation", inputs, None, formula, SOURCE, "net_mm and efficiency must be finite, net_mm >= 0")
    if not 0 < efficiency <= 1:
        return ToolResult("gross_irrigation", inputs, None, formula, SOURCE, "efficiency must be in (0, 1]")
    gross = net_mm / efficiency
    return ToolResult("gross_irrigation", inputs,
                      {"gross_mm": round(gross, 1), "m3_per_ha": round(gross * 10, 0)}, formula, SOURCE)
