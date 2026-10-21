from __future__ import annotations

from datetime import date
from typing import List, Optional

from ..types import NdviObservation, ToolResult, to_date

SOURCE = "Sentinel-2 L2A NDVI statistics per parcel geometry"
MIN_SHARE_FOR_TREND = 0.60


def ndvi_summary(series: List[NdviObservation], as_of: Optional[date]) -> ToolResult:
    """Latest usable observation, 14-day trend and spatial contrast (p90 - p10).

    Observations dated after as_of are ignored: nothing from the future may enter a decision.
    """
    inputs = {"n_observations": len(series), "as_of": as_of.isoformat() if as_of else None}
    obs = [o for o in series if o.median is not None and (as_of is None or to_date(o.obs_date) <= as_of)]
    obs.sort(key=lambda o: to_date(o.obs_date))
    if not obs:
        return ToolResult("ndvi_summary", inputs, None, "", SOURCE, "no usable observation")
    latest = obs[-1]
    latest_date = to_date(latest.obs_date)
    age = (as_of - latest_date).days if as_of else None
    contrast = None
    if latest.p10 is not None and latest.p90 is not None:
        contrast = round(latest.p90 - latest.p10, 3)
    window = [o for o in obs if (latest_date - to_date(o.obs_date)).days <= 14
              and o.usable_share >= MIN_SHARE_FOR_TREND]
    trend = round(window[-1].median - window[0].median, 3) if len(window) >= 2 else None
    return ToolResult("ndvi_summary", inputs, {
        "latest_value": latest.median, "latest_date": latest.obs_date, "age_days": age,
        "usable_share": latest.usable_share, "spatial_contrast": contrast,
        "trend_14d": trend, "trend_count": len(window),
    }, "contrast = p90 - p10; trend = last median - first median within 14 days", SOURCE)
