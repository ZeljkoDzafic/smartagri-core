"""Build the parcel profile: fetch weather and satellite data, summarise, and annotate quality."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from ..i18n import L
from ..core.quality import annotate_quality, observe_all
from ..core.tools import ndvi_summary
from ..core.types import (Agronomic, Context, NdviObservation, ParcelFeatures, ParcelInfo, Question, SatelliteSummary,
                          WeatherSummary)
from ..core import parcel_features as features_contract
from ..providers import parcel_features as features_provider, satellite, weather
from ..providers.base import ProviderUnavailable
from ..store import Store, new_id, now_iso

AGRONOMIC_FIELDS = set(Agronomic.__dataclass_fields__)


def context_from(parcel: Dict[str, Any], profile: Dict[str, Any], question: Optional[Question] = None,
                 questions_asked: int = 0, declined: Optional[List[str]] = None,
                 agronomic_override: Optional[Dict[str, Any]] = None) -> Context:
    a = {k: v for k, v in dict(parcel.get("agronomic") or {}, **(agronomic_override or {})).items() if k in AGRONOMIC_FIELDS}
    w = (profile.get("weather") or {}).get("summary") or {}
    series = [NdviObservation(**o) for o in (profile.get("satellite") or {}).get("series") or []]
    features = _stored_features(profile)
    return Context(
        P=ParcelInfo(parcel["id"], parcel.get("area_ha"), parcel["centroid"]["lat"], parcel["centroid"]["lon"],
                     parcel.get("region_class")),
        A=Agronomic(**a),
        W=WeatherSummary(**w),
        S=SatelliteSummary(ndvi_series=features_contract.merge_ndvi(series, features), parcel_features=features),
        Q=question or Question(),
        as_of=datetime.fromisoformat(profile["as_of"]),
        questions_asked=questions_asked,
        declined_inputs=list(declined or []),
    )


def _stored_features(profile: Dict[str, Any]) -> Optional[ParcelFeatures]:
    """The parcel features a profile holds (already validated against the parcel when the profile was built); they are
    checked again against the profile's decision moment, and an unusable document is left out."""
    stored = profile.get("parcel_features") or {}
    if stored.get("status") != "ok" or not stored.get("document"):
        return None
    try:
        return features_contract.parse(stored["document"], as_of=datetime.fromisoformat(profile["as_of"]))
    except features_contract.ParcelFeaturesError:
        return None


def quality_rows(ctx: Context, log_sources: Optional[Dict[str, List[str]]] = None) -> List[Dict[str, Any]]:
    """Every tracked input with its value and quality, labelled for the user. With `log_sources` (
    agronomic field -> activity ids) the rows whose value came from the activity log say so in origin_label."""
    obs, q = observe_all(ctx), annotate_quality(ctx)
    rows = []
    for name, quality in q.items():
        text = L().value_text(name, obs[name].value)
        if name == "ndvi_latest" and obs[name].value is not None:
            text += " (%s)" % L().fmt_date(quality.source_ref.split(":", 1)[-1])
        row = {"input": name, "label": L().INPUTS.get(name, name), "value_text": text,
               "origin": quality.origin.value, "origin_label": L().ORIGIN[quality.origin.value],
               "age_days": quality.age_days, "coverage": quality.coverage,
               "reliability": quality.reliability.value,
               "reliability_label": L().RELIABILITY[quality.reliability.value], "basis": quality.basis}
        if quality.detail:                      # NDVI mask fields, the stage conflict: structured, labelled by the client
            row["detail"] = quality.detail
        rows.append(row)
    if log_sources:
        from ..activities import log_rows
        rows = log_rows(rows, log_sources)
    return rows


def build_profile(store: Store, parcel: Dict[str, Any], as_of: Optional[datetime] = None,
                  refresh: bool = True) -> Dict[str, Any]:
    """Fetch what can be fetched. A provider that fails leaves its part 'missing'; the profile is still usable."""
    as_of = as_of or datetime.now().astimezone().replace(microsecond=0)
    lat, lon = parcel["centroid"]["lat"], parcel["centroid"]["lon"]
    sowing = (parcel.get("agronomic") or {}).get("sowing_date")

    # retrospective_constructed: for an as_of before today the weather was assembled after the fact: past days from
    # the historical-forecast archive, forecast days from the Previous Runs API as issued before as_of
    # (providers/weather.py). It is recorded here and copied into the profile provenance.
    w: Dict[str, Any] = {"status": "missing", "message": "", "source": weather.SOURCE, "fetched_at": None,
                         "summary": None, "daily": [], "request_hash": None, "endpoint": None,
                         "retrospective_constructed": False}
    try:
        # The parcel's zone; home-area parcels make exactly the call they always made.
        tz = weather.request_timezone(parcel.get("time_zone"))
        got = weather.fetch(store, lat, lon, as_of, refresh) if tz == weather.DEFAULT_TIMEZONE else \
            weather.fetch(store, lat, lon, as_of, refresh, time_zone=tz)
        rows = weather.daily_rows(got["raw"], as_of.date())
        w.update(status="ok", fetched_at=got["fetched_at"], request_hash=got["request_hash"],
                 endpoint=got.get("endpoint"), retrospective_constructed=bool(got.get("retrospective_constructed")),
                 summary=weather.summarize(rows, as_of, sowing,
                                           # a past as_of: the (conservative) issue time of the runs used, never the
                                           # time we fetched the archive; live: the fetch time
                                           (got.get("forecast_issued_at") or None) if got.get("retrospective_constructed")
                                           else got["fetched_at"]), daily=rows[-(30 + 7):])
    except ProviderUnavailable as exc:
        w["message"] = str(exc)

    s: Dict[str, Any] = {"status": "missing", "message": "", "source": satellite.SOURCE, "fetched_at": None,
                         "series": [], "summary": None, "request_hash": None}
    try:
        got = satellite.fetch(store, parcel["geometry"], as_of, refresh)
        series = satellite.parse_series(got["raw"], as_of.date())
        summary = ndvi_summary([NdviObservation(**o) for o in series], as_of.date()).output
        s.update(status="ok" if series else "missing", fetched_at=got["fetched_at"], request_hash=got["request_hash"],
                 series=series, summary=summary,
                 message="" if series else "U poslednjih 90 dana nema upotrebljivog snimka bez oblaka.")
    except ProviderUnavailable as exc:
        s["message"] = str(exc)

    # Precomputed parcel features (a generic provider; docs/parcel-features.md). Only a configured provider adds
    # anything to the profile; a document that breaks the contract is recorded as rejected, with the reasons.
    pf: Optional[Dict[str, Any]] = None
    if features_provider.configured():
        pf = {"status": "absent", "message": "", "source": features_provider.SOURCE, "document": None,
              "document_sha256": None, "producer": None}
        try:
            doc = features_provider.load_document(parcel["id"], parcel["geometry"], as_of)
            if doc is not None:
                pf.update(status="ok", document=doc, document_sha256=features_contract.document_sha256(doc),
                          producer=doc.get("producer"))
        except ProviderUnavailable as exc:
            pf.update(status="rejected", message=str(exc))

    profile = {"id": new_id(), "parcel_id": parcel["id"], "as_of": as_of.isoformat(), "created_at": now_iso(),
               "weather": w, "satellite": s,
               "provenance": {"as_of": as_of.isoformat(), "weather_request_hash": w["request_hash"],
                              "weather_endpoint": w["endpoint"],
                              "weather_retrospective_constructed": w["retrospective_constructed"],
                              "satellite_request_hash": s["request_hash"],
                              "scene_dates": [o["obs_date"] for o in s["series"]]}}
    if pf is not None:
        profile["parcel_features"] = pf
        profile["provenance"].update(parcel_features_status=pf["status"], parcel_features_sha256=pf["document_sha256"],
                                     parcel_features_producer=pf["producer"], parcel_features_message=pf["message"])
    profile["quality"] = quality_rows(context_from(parcel, profile))
    return store.save_profile(profile)
