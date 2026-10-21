"""Open-Meteo adapter and the deterministic weather summary W."""
from __future__ import annotations

import os
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

from .. import config
from ..core.types import to_date
from ..store import Store
from .base import cached, http_json

DAILY = "temperature_2m_max,temperature_2m_min,precipitation_sum,wind_speed_10m_max,et0_fao_evapotranspiration"
PAST_DAYS, FORECAST_DAYS = 92, 7
SOURCE = "Open-Meteo"


FORECAST_ENDPOINT, ARCHIVE_ENDPOINT = "forecast", "historical-forecast"
# A live forecast fetched more than this after as_of was issued after the decision moment (FR-013).
# Engineering tolerance for the seconds between taking as_of and the HTTP call, not an agronomic value.
FORECAST_FETCH_GRACE = timedelta(hours=1)


def _base() -> str:
    return os.environ.get("OPEN_METEO_BASE", "https://api.open-meteo.com/v1")


def _archive_base() -> str:
    return os.environ.get("OPEN_METEO_ARCHIVE_BASE", "https://historical-forecast-api.open-meteo.com/v1")


# Spec 037 FR-013: the Open-Meteo day is cut at the parcel's local midnight. Zones of the home area that share
# Europe/Belgrade's rules (tzdb links or identical zones) send the literal that was always sent, so BiH requests,
# cache keys and offline replays stay byte-identical.
DEFAULT_TIMEZONE = "Europe/Sarajevo"
SAME_AS_DEFAULT = {"Europe/Sarajevo", "Europe/Belgrade", "Europe/Zagreb", "Europe/Ljubljana", "Europe/Skopje",
                   "Europe/Podgorica"}


def request_timezone(time_zone: Optional[str]) -> str:
    """The `timezone` parameter for a parcel zone (None = a parcel stored before spec 037: the default)."""
    if not time_zone or time_zone in SAME_AS_DEFAULT:
        return DEFAULT_TIMEZONE
    return time_zone


def build_request(lat: float, lon: float, as_of: datetime, today: Optional[date] = None,
                  time_zone: Optional[str] = None) -> Dict[str, Any]:
    """Choose the endpoint and parameters for as_of.

    For as_of = today the forecast endpoint returns the last 92 days plus 7 forecast days; the cache
    key includes the day, so a new day is a new request. For an earlier as_of the historical-forecast
    archive is used, which holds what the models said at the time; the result is
    retrospective_constructed (see docs/architecture.md) because it was assembled after the fact.
    """
    today = today or datetime.now(as_of.tzinfo).date()
    params: Dict[str, Any] = {"latitude": round(lat, 4), "longitude": round(lon, 4), "daily": DAILY,
                              "timezone": request_timezone(time_zone), "wind_speed_unit": "ms"}
    if as_of.date() >= today:
        params.update(past_days=PAST_DAYS, forecast_days=FORECAST_DAYS)
        return {"endpoint": FORECAST_ENDPOINT, "url": _base() + "/forecast", "params": params,
                "key": dict(params, day=today.isoformat()), "retrospective_constructed": False}
    params.update(start_date=(as_of.date() - timedelta(days=PAST_DAYS)).isoformat(),
                  end_date=(as_of.date() + timedelta(days=FORECAST_DAYS - 1)).isoformat())
    return {"endpoint": ARCHIVE_ENDPOINT, "url": _archive_base() + "/forecast", "params": params,
            "key": dict(params), "retrospective_constructed": True}


def fetch(store: Store, lat: float, lon: float, as_of: datetime, refresh: bool = False,
          time_zone: Optional[str] = None) -> Dict[str, Any]:
    """Fetch daily history and forecast around as_of (see build_request).

    A live forecast is accepted only if it was fetched no later than as_of + FORECAST_FETCH_GRACE.
    """
    req = build_request(lat, lon, as_of, time_zone=time_zone)

    def call():
        return http_json("GET", req["url"], "Meteorološki servis nije dostupan", 20.0, params=req["params"])

    not_after = as_of + FORECAST_FETCH_GRACE if req["endpoint"] == FORECAST_ENDPOINT else None
    raw, fetched_at, h = cached(store, "open-meteo", req["key"], call, refresh, not_after=not_after)
    return {"raw": raw, "fetched_at": fetched_at, "request_hash": h, "endpoint": req["endpoint"],
            "retrospective_constructed": req["retrospective_constructed"]}


def daily_rows(raw: Dict[str, Any], as_of: date) -> List[Dict[str, Any]]:
    d = raw["daily"]
    rows = []
    for i, day in enumerate(d["time"]):
        rows.append({"date": day, "precip_mm": d["precipitation_sum"][i], "et0_mm": d["et0_fao_evapotranspiration"][i],
                     "tmin_c": d["temperature_2m_min"][i], "tmax_c": d["temperature_2m_max"][i],
                     "wind_max_ms": d["wind_speed_10m_max"][i], "is_forecast": to_date(day) >= as_of})
    return rows


def _sum(rows: List[Dict[str, Any]], key: str) -> Optional[float]:
    vals = [r[key] for r in rows if r[key] is not None]
    return round(sum(vals), 1) if vals and len(vals) == len(rows) else None


def summarize(rows: List[Dict[str, Any]], as_of: datetime, sowing_date: Optional[str], fetched_at: str) -> Dict[str, Any]:
    """Weather summary W. Days before as_of are history; as_of and later are forecast."""
    today = as_of.date()
    past = [r for r in rows if to_date(r["date"]) < today]
    future = [r for r in rows if to_date(r["date"]) >= today]
    base = config.load("rules")["phenology"]["gdd_base_c"]
    gdd = None
    sow = to_date(sowing_date)
    if sow and past and to_date(past[0]["date"]) <= sow:
        season = [r for r in past if to_date(r["date"]) >= sow and r["tmin_c"] is not None and r["tmax_c"] is not None]
        gdd = round(sum(max(0.0, (min(r["tmax_c"], 30.0) + max(r["tmin_c"], base)) / 2.0 - base) for r in season), 0)
    tmins = [r["tmin_c"] for r in future if r["tmin_c"] is not None]
    tmaxs = [r["tmax_c"] for r in future if r["tmax_c"] is not None]
    winds = [r["wind_max_ms"] for r in future if r["wind_max_ms"] is not None]
    return {
        "origin": "modeled",
        "precip_past_7d_mm": _sum(past[-7:], "precip_mm") if len(past) >= 7 else None,
        "precip_past_30d_mm": _sum(past[-30:], "precip_mm") if len(past) >= 30 else None,
        "et0_past_7d_mm": _sum(past[-7:], "et0_mm") if len(past) >= 7 else None,
        "gdd_since_sowing": gdd,
        "precip_forecast_3d_mm": _sum(future[:3], "precip_mm") if len(future) >= 3 else None,
        "precip_forecast_7d_mm": _sum(future[:7], "precip_mm") if len(future) >= 7 else None,
        "tmin_forecast_7d_c": min(tmins) if tmins else None,
        "tmax_forecast_7d_c": max(tmaxs) if tmaxs else None,
        "wind_forecast_max_ms": max(winds) if winds else None,
        "forecast_issued_at": fetched_at if future else None,
        "horizon_days": len(future),
    }
