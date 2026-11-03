from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import List, Optional

from ... import config
from .. import parcel_features
from ..types import NdviObservation, ToolResult, to_date

SOURCE = "Sentinel-2 L2A NDVI statistics per parcel geometry"
MIN_SHARE_FOR_TREND = 0.60


def publication_lag_hours() -> float:
    """Hours after the end of the sensing day before a scene may enter a decision (rules.satellite, audit D9)."""
    return float((config.load("rules").get("satellite") or {}).get("publication_lag_hours", 0) or 0)


def scene_available(obs_date: object, as_of: object) -> bool:
    """May the scene of `obs_date` enter a decision taken at `as_of` (a moment or a date; a date is its midnight)?
    The sensing day counts as over at its end, plus the publication lag: with no lag a scene of the decision day is not
    usable, on both sides of the pipeline (the provider and the summary use this one rule)."""
    if as_of is None:
        return True
    moment = as_of if isinstance(as_of, datetime) else datetime.combine(as_of, time.min)
    ready = datetime.combine(to_date(obs_date), time.min) + timedelta(days=1, hours=publication_lag_hours())
    return ready <= moment.replace(tzinfo=None)


def ndvi_summary(series: List[NdviObservation], as_of: Optional[date],
                 as_of_moment: Optional[datetime] = None) -> ToolResult:
    """Latest usable observation, 14-day trend and spatial contrast (p90 - p10).

    Observations whose scene is not yet available at the decision moment (`scene_available`) are ignored: nothing from the future may enter a decision. An observation the
    producer screened out as a temporal outlier (`temporal_outlier`, parcel_features) is left out as well, and the
    dates left out are named in the output.
    """
    inputs = {"n_observations": len(series), "as_of": as_of.isoformat() if as_of else None}
    obs = [o for o in series if o.median is not None and (as_of is None or scene_available(o.obs_date, as_of_moment or as_of))]
    outliers: List[str] = []
    cfg = parcel_features.settings()["ndvi_quality"]
    if cfg["enabled"] and cfg["exclude_temporal_outliers"]:
        outliers = [o.obs_date for o in obs if o.temporal_outlier]
        obs = [o for o in obs if not o.temporal_outlier]
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
    out = {
        "latest_value": latest.median, "latest_date": latest.obs_date, "age_days": age,
        "usable_share": latest.usable_share, "spatial_contrast": contrast,
        "trend_14d": trend, "trend_count": len(window),
    }
    detail = parcel_features.ndvi_detail(latest)
    if detail:                                   # only when the observation carries mask metadata
        out["quality"] = detail
    if outliers:
        out["outliers_excluded"] = outliers
    return ToolResult("ndvi_summary", inputs, out, "contrast = p90 - p10; trend = last median - first median within 14 days", SOURCE)
