"""Sentinel-2 L2A NDVI statistics per parcel through the Copernicus Data Space Statistical API."""
from __future__ import annotations

import os
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

from ..store import Store
from .base import ProviderUnavailable, cached, http_json

TOKEN_URL = "https://identity.dataspace.copernicus.eu/auth/realms/CDSE/protocol/openid-connect/token"
STATS_URL = "https://sh.dataspace.copernicus.eu/api/v1/statistics"
SOURCE = "Sentinel-2 L2A (Copernicus Data Space)"
LOOKBACK_DAYS = 90

# NDVI with a per-pixel validity mask from the scene classification layer.
# Excluded SCL classes: 0 no data, 1 saturated, 3 cloud shadow, 8 and 9 cloud, 10 cirrus, 11 snow.
EVALSCRIPT = """//VERSION=3
function setup() {
  return {input: [{bands: ["B04", "B08", "SCL", "dataMask"]}],
          output: [{id: "ndvi", bands: 1, sampleType: "FLOAT32"}, {id: "dataMask", bands: 1}]};
}
function evaluatePixel(s) {
  var bad = [0, 1, 3, 8, 9, 10, 11].indexOf(s.SCL) >= 0;
  var den = s.B08 + s.B04;
  var ok = s.dataMask == 1 && !bad && den > 0;
  return {ndvi: [ok ? (s.B08 - s.B04) / den : 0], dataMask: [ok ? 1 : 0]};
}
"""


def configured() -> bool:
    return bool(os.environ.get("CDSE_CLIENT_ID") and os.environ.get("CDSE_CLIENT_SECRET"))


def _token() -> str:
    body = http_json("POST", TOKEN_URL, "Prijava na satelitski servis nije uspela", 20.0,
                     data={"grant_type": "client_credentials", "client_id": os.environ["CDSE_CLIENT_ID"],
                           "client_secret": os.environ["CDSE_CLIENT_SECRET"]})
    try:
        return body["access_token"]
    except (KeyError, TypeError):
        raise ProviderUnavailable("Prijava na satelitski servis nije uspela: KeyError")


def build_request(geometry: Dict[str, Any], as_of: datetime) -> Dict[str, Any]:
    start = (as_of - timedelta(days=LOOKBACK_DAYS)).strftime("%Y-%m-%dT00:00:00Z")
    end = as_of.strftime("%Y-%m-%dT00:00:00Z")      # scenes from as_of's own day onward are excluded
    return {
        "input": {"bounds": {"geometry": geometry, "properties": {"crs": "http://www.opengis.net/def/crs/EPSG/0/4326"}},
                  "data": [{"type": "sentinel-2-l2a", "dataFilter": {"mosaickingOrder": "leastCC"}}]},
        "aggregation": {"timeRange": {"from": start, "to": end}, "aggregationInterval": {"of": "P1D"},
                        "evalscript": EVALSCRIPT, "resx": 10, "resy": 10},
        "calculations": {"ndvi": {"statistics": {"default": {"percentiles": {"k": [10, 50, 90]}}}}},
    }


def fetch(store: Store, geometry: Dict[str, Any], as_of: datetime, refresh: bool = False) -> Dict[str, Any]:
    if not configured():
        raise ProviderUnavailable("Satelitski servis nije podešen (CDSE_CLIENT_ID i CDSE_CLIENT_SECRET).")
    request = build_request(geometry, as_of)

    def call():
        return http_json("POST", STATS_URL, "Satelitski servis nije dostupan", 60.0, json=request,
                         headers={"Authorization": "Bearer " + _token(), "Accept": "application/json"})

    raw, fetched_at, h = cached(store, "cdse-statistical", request, call, refresh)
    return {"raw": raw, "fetched_at": fetched_at, "request_hash": h}


def parse_series(raw: Dict[str, Any], as_of: Optional[date] = None) -> List[Dict[str, Any]]:
    """Turn a Statistical API response into NDVI observations with the share of usable pixels.

    usable_share = 1 - noDataCount / sampleCount, where no-data includes pixels masked as cloud,
    shadow or snow by the evalscript. Days with no usable pixel are dropped. With as_of, observations
    dated on or after the as_of day are dropped as well (FR-013), whatever the cached response holds.
    """
    series = []
    for item in raw.get("data", []):
        try:
            stats = item["outputs"]["ndvi"]["bands"]["B0"]["stats"]
        except KeyError:
            continue
        samples = stats.get("sampleCount") or 0
        usable = samples - (stats.get("noDataCount") or 0)
        if samples <= 0 or usable <= 0:
            continue
        if as_of is not None and item["interval"]["from"][:10] >= as_of.isoformat():
            continue
        pct = stats.get("percentiles", {})
        series.append({"obs_date": item["interval"]["from"][:10], "median": round(float(pct["50.0"]), 3),
                       "p10": round(float(pct["10.0"]), 3), "p90": round(float(pct["90.0"]), 3),
                       "usable_share": round(usable / float(samples), 3)})
    return sorted(series, key=lambda o: o["obs_date"])
