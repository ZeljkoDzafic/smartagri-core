"""Open-Meteo adapter and the deterministic weather summary W."""
from __future__ import annotations

import os
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from .. import config
from ..core.types import to_date
from ..store import Store
from .base import cached, http_json

DAILY = "temperature_2m_max,temperature_2m_min,precipitation_sum,wind_speed_10m_max,et0_fao_evapotranspiration"
PAST_DAYS, FORECAST_DAYS = 92, 7
SOURCE = "Open-Meteo"


FORECAST_ENDPOINT, ARCHIVE_ENDPOINT = "forecast", "historical-forecast"
# Forecast days of a past decision moment (spec of the evaluation: only a forecast available at as_of may enter W).
PREVIOUS_RUNS_ENDPOINT = "previous-runs"
# Open-Meteo Previous Runs API, https://open-meteo.com/en/docs/previous-runs-api (checked 2026-10-26):
#   "_previous_day0 is the current model run (equivalent to the live Forecast API). _previous_day1 is the value that
#    was predicted 24 hours before valid time, _previous_day2 48 hours before, and so on up to day 7."
#   Only hourly variables are offered (precipitation, temperature_2m, wind_speed_10m, ...; no daily aggregates and no
#   et0_fao_evapotranspiration); most models are archived from January 2024.
# The Historical Forecast API (https://open-meteo.com/en/docs/historical-forecast-api) is different: "Each run's first
# few hours are stitched into a continuous hourly timeseries", i.e. close to an analysis, not the forecast as issued.
# It is used here only for the days BEFORE as_of, which are history at the decision moment, and every profile built
# from it is labelled retrospective_constructed.
PREVIOUS_RUNS_HOURLY = ("precipitation", "temperature_2m", "wind_speed_10m")
PREVIOUS_RUN_MAX_DAY = 7
# A run is taken as issued at the latest moment the documentation allows (valid time - 24 h x N) and as available
# this long after it. Conservative: a value is never used before it can have existed. Engineering assumption about
# publication delay, not an agronomic value (the hourly product module uses the same 6 h default).
PREVIOUS_RUN_AVAILABLE_AFTER = timedelta(hours=6)
# A live forecast fetched more than this after as_of was issued after the decision moment (FR-013).
# Engineering tolerance for the seconds between taking as_of and the HTTP call, not an agronomic value.
FORECAST_FETCH_GRACE = timedelta(hours=1)


def _base() -> str:
    return os.environ.get("OPEN_METEO_BASE", "https://api.open-meteo.com/v1")


def _archive_base() -> str:
    return os.environ.get("OPEN_METEO_ARCHIVE_BASE", "https://historical-forecast-api.open-meteo.com/v1")


def _previous_runs_base() -> str:
    return os.environ.get("OPEN_METEO_PREVIOUS_RUNS_BASE", "https://previous-runs-api.open-meteo.com/v1")


# The Open-Meteo day is cut at the parcel's local midnight. Zones of the home area that share
# Europe/Belgrade's rules (tzdb links or identical zones) send the literal that was always sent, so BiH requests,
# cache keys and offline replays stay byte-identical.
DEFAULT_TIMEZONE = "Europe/Sarajevo"
SAME_AS_DEFAULT = {"Europe/Sarajevo", "Europe/Belgrade", "Europe/Zagreb", "Europe/Ljubljana", "Europe/Skopje",
                   "Europe/Podgorica"}


def request_timezone(time_zone: Optional[str]) -> str:
    """The `timezone` parameter for a parcel zone (None = a parcel stored before the default)."""
    if not time_zone or time_zone in SAME_AS_DEFAULT:
        return DEFAULT_TIMEZONE
    return time_zone


def build_request(lat: float, lon: float, as_of: datetime, today: Optional[date] = None,
                  time_zone: Optional[str] = None) -> Dict[str, Any]:
    """Choose the endpoint and parameters for as_of.

    For as_of = today the forecast endpoint returns the last 92 days plus 7 forecast days; the cache
    key includes the day, so a new day is a new request (live use). For an earlier as_of this is the request for
    the 92 days of HISTORY before as_of (historical-forecast archive, near-analysis values of past days); the 7
    forecast days come from `forecast_request` (Previous Runs API: the forecast as issued before as_of). The
    combined profile is retrospective_constructed (see docs/architecture.md): it was assembled after the fact.
    """
    today = today or datetime.now(as_of.tzinfo).date()
    params: Dict[str, Any] = {"latitude": round(lat, 4), "longitude": round(lon, 4), "daily": DAILY,
                              "timezone": request_timezone(time_zone), "wind_speed_unit": "ms"}
    if as_of.date() >= today:
        params.update(past_days=PAST_DAYS, forecast_days=FORECAST_DAYS)
        return {"endpoint": FORECAST_ENDPOINT, "url": _base() + "/forecast", "params": params,
                "key": dict(params, day=today.isoformat()), "retrospective_constructed": False}
    params.update(start_date=(as_of.date() - timedelta(days=PAST_DAYS)).isoformat(),
                  end_date=(as_of.date() - timedelta(days=1)).isoformat())
    return {"endpoint": ARCHIVE_ENDPOINT, "url": _archive_base() + "/forecast", "params": params,
            "key": dict(params), "retrospective_constructed": True}


def forecast_request(lat: float, lon: float, as_of: datetime) -> Dict[str, Any]:
    """Previous Runs API request for the forecast days of a past as_of: hourly values of every run day 0..7 (GMT),
    from the day before as_of to as_of + FORECAST_DAYS, so that every local day of the horizon is covered."""
    day = as_of.astimezone(timezone.utc).date() if as_of.tzinfo else as_of.date()
    names = [v for v in PREVIOUS_RUNS_HOURLY] + ["%s_previous_day%d" % (v, n) for n in range(1, PREVIOUS_RUN_MAX_DAY + 1)
                                                  for v in PREVIOUS_RUNS_HOURLY]
    params = {"latitude": round(lat, 4), "longitude": round(lon, 4), "hourly": ",".join(names), "timezone": "GMT",
              "wind_speed_unit": "ms", "start_date": (day - timedelta(days=1)).isoformat(),
              "end_date": (day + timedelta(days=FORECAST_DAYS)).isoformat()}
    return {"endpoint": PREVIOUS_RUNS_ENDPOINT, "url": _previous_runs_base() + "/forecast", "params": params,
            "key": dict(params, endpoint=PREVIOUS_RUNS_ENDPOINT)}


def _utc(dt: datetime) -> datetime:
    return dt.astimezone(timezone.utc) if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def issued_at(valid_utc: datetime, n_days: int) -> datetime:
    """Latest issue time the documentation allows for the `_previous_dayN` value of a valid time: valid - 24 h x N."""
    return valid_utc - timedelta(days=n_days)


def forecast_as_issued(raw: Dict[str, Any], as_of: datetime) -> List[Dict[str, Any]]:
    """Hourly forecast that was available at as_of: for every valid hour at or after as_of the value of the newest run
    with issued_at + PREVIOUS_RUN_AVAILABLE_AFTER <= as_of (day N from 1 to 7); hours with no such run are left out.
    Hours before as_of take the day-0 value (the past at the decision moment). Rows: {ts (UTC), precip_mm, temp_c,
    wind_ms, issued_at, lead_hours, run_day}."""
    hourly = (raw or {}).get("hourly") or {}
    times = hourly.get("time") or []
    as_of_utc = _utc(as_of)
    rows: List[Dict[str, Any]] = []

    def value(var: str, i: int):
        col = hourly.get(var)
        return col[i] if col and i < len(col) else None

    for i, t in enumerate(times):
        ts = datetime.fromisoformat(t[:16]).replace(tzinfo=timezone.utc)
        if ts < as_of_utc:
            vals = {k: value(v, i) for k, v in (("precip_mm", "precipitation"), ("temp_c", "temperature_2m"),
                                                 ("wind_ms", "wind_speed_10m"))}
            if any(x is not None for x in vals.values()):
                rows.append(dict(vals, ts=ts, issued_at=None, lead_hours=None, run_day=0))
            continue
        for n in range(1, PREVIOUS_RUN_MAX_DAY + 1):
            issued = issued_at(ts, n)
            if issued + PREVIOUS_RUN_AVAILABLE_AFTER > as_of_utc:
                continue
            vals = {k: value("%s_previous_day%d" % (v, n), i) for k, v in (
                ("precip_mm", "precipitation"), ("temp_c", "temperature_2m"), ("wind_ms", "wind_speed_10m"))}
            if any(x is not None for x in vals.values()):
                rows.append(dict(vals, ts=ts, issued_at=issued, lead_hours=int((ts - issued) / timedelta(hours=1)),
                                 run_day=n))
                break
    return rows


def daily_from_hourly(rows: List[Dict[str, Any]], days: List[date], time_zone: str) -> Dict[str, List[Any]]:
    """Daily aggregates per local day: precipitation sum, min/max temperature, max wind. A day is complete only with
    all its hours; an incomplete day gets None (it is not a forecast that existed at as_of). ET0 is None: the
    Previous Runs API does not offer it, and W uses ET0 only for past days."""
    try:
        from zoneinfo import ZoneInfo
        tz = ZoneInfo(time_zone)
    except Exception:                                    # no tz database: GMT days
        tz = timezone.utc
    by: Dict[date, List[Dict[str, Any]]] = {}
    for r in rows:
        by.setdefault(r["ts"].astimezone(tz).date(), []).append(r)
    out: Dict[str, List[Any]] = {"time": [], "precipitation_sum": [], "temperature_2m_min": [], "temperature_2m_max": [],
                                 "wind_speed_10m_max": [], "et0_fao_evapotranspiration": []}
    for d in days:
        start = datetime(d.year, d.month, d.day, tzinfo=tz)
        n_hours = int((datetime(*(d + timedelta(days=1)).timetuple()[:3], tzinfo=tz) - start).total_seconds() // 3600)
        hs = by.get(d, [])
        complete = len(hs) >= n_hours
        def agg(key, fn):
            xs = [h[key] for h in hs if h[key] is not None]
            return round(fn(xs), 1) if complete and len(xs) == len(hs) and xs else None
        out["time"].append(d.isoformat())
        out["precipitation_sum"].append(agg("precip_mm", sum))
        out["temperature_2m_min"].append(agg("temp_c", min))
        out["temperature_2m_max"].append(agg("temp_c", max))
        out["wind_speed_10m_max"].append(agg("wind_ms", max))
        out["et0_fao_evapotranspiration"].append(None)
    return out


def combine(history: Dict[str, Any], forecast_raw: Dict[str, Any], as_of: datetime, time_zone: str) -> Dict[str, Any]:
    """One daily response (the shape of the forecast endpoint) for a past as_of: history days from the archive, forecast
    days from the runs issued before as_of. `forecast_issued_at` = the oldest issue time among the forecast values of
    the first three days (conservative age of the forecast that W reports)."""
    hist = dict(history.get("daily") or {})
    first = as_of.date()
    keep = [i for i, t in enumerate(hist.get("time") or []) if to_date(t) < first]
    daily = {k: [v[i] for i in keep] for k, v in hist.items() if isinstance(v, list)}
    rows = forecast_as_issued(forecast_raw, as_of)
    days = [first + timedelta(days=k) for k in range(FORECAST_DAYS)]
    fc = daily_from_hourly([r for r in rows], days, time_zone)
    for k in daily:
        daily[k] = daily[k] + fc.get(k, [None] * len(days))
    try:
        from zoneinfo import ZoneInfo
        tz = ZoneInfo(time_zone)
    except Exception:
        tz = timezone.utc
    first3 = [r for r in rows if r["issued_at"] is not None and r["ts"].astimezone(tz).date() < first + timedelta(days=3)]
    issued = min((r["issued_at"] for r in first3), default=None)
    return {"daily": daily, "forecast_issued_at": issued.isoformat() if issued else None,
            "forecast_source": {"endpoint": PREVIOUS_RUNS_ENDPOINT, "run_days": sorted({r["run_day"] for r in rows if r["run_day"]}),
                                "available_after_h": PREVIOUS_RUN_AVAILABLE_AFTER.total_seconds() / 3600.0}}


def fetch(store: Store, lat: float, lon: float, as_of: datetime, refresh: bool = False,
          time_zone: Optional[str] = None) -> Dict[str, Any]:
    """Fetch daily history and forecast around as_of (see build_request).

    A live forecast is accepted only if it was fetched no later than as_of + FORECAST_FETCH_GRACE.
    """
    req = build_request(lat, lon, as_of, time_zone=time_zone)

    def call():
        return http_json("GET", req["url"], "Meteorološki servis nije dostupan", 20.0, params=req["params"])

    if req["endpoint"] == FORECAST_ENDPOINT:            # live use: the forecast as it is now
        not_after = as_of + FORECAST_FETCH_GRACE
        raw, fetched_at, h = cached(store, "open-meteo", req["key"], call, refresh, not_after=not_after)
        return {"raw": raw, "fetched_at": fetched_at, "request_hash": h, "endpoint": req["endpoint"],
                "retrospective_constructed": False}
    # A past decision moment: history from the archive, forecast days as issued before as_of (Previous Runs API).
    freq = forecast_request(lat, lon, as_of)

    def call_forecast():
        return http_json("GET", freq["url"], "Meteorološki servis (arhiva prognoza) nije dostupan", 20.0,
                         params=freq["params"])

    def call_both():
        history, _, _ = cached(store, "open-meteo", req["key"], call, refresh)
        forecast_raw, _, _ = cached(store, "open-meteo", freq["key"], call_forecast, refresh)
        return combine(history, forecast_raw, as_of, req["params"]["timezone"])

    key = {"combined": [req["key"], freq["key"]], "as_of": as_of.isoformat()}
    raw, fetched_at, h = cached(store, "open-meteo", key, call_both, refresh)
    return {"raw": raw, "fetched_at": fetched_at, "request_hash": h, "endpoint": ARCHIVE_ENDPOINT + "+" + PREVIOUS_RUNS_ENDPOINT,
            "retrospective_constructed": True, "forecast_issued_at": raw.get("forecast_issued_at")}


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
