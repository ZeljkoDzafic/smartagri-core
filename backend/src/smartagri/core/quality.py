"""Input-quality profile q(x) = (origin, age, coverage, reliability)."""
from __future__ import annotations

import dataclasses
import re

from typing import Any, Dict, Optional

from .. import config
from . import parcel_features as pfm
from .tools import estimate_bbch, ndvi_summary
from .types import Context, Observation, Origin, Quality, QualityProfile, Reliability, to_date

SMALL_PARCEL_HA = 0.3

TRACKED_INPUTS = (
    "phenophase", "sowing_date", "ndvi_latest", "ndvi_spatial_contrast", "ndvi_trend",
    "precip_past_7d", "et0_past_7d", "precip_forecast_3d", "precip_forecast_7d", "temp_forecast",
    "wind_forecast", "soil_water_status", "soil_moisture_sensor", "soil_awc", "soil_analysis",
    "irrigation_available", "irrigation_efficiency", "previous_fertilization", "yield_target", "operation",
    # optional inputs
    "irrigation_capacity", "previous_crop", "manure", "hybrid_fao", "plant_density", "field_observation",
)


def product_key(name: Any) -> str:
    """'NPK 15-15-15' -> 'npk_15_15_15', 'UREA' -> 'urea': the keys of rules.optional_inputs.n_content."""
    return re.sub(r"[^a-z0-9]+", "_", str(name or "").lower()).strip("_")


def _age(ctx: Context, when: Any) -> Optional[float]:
    d = to_date(when)
    if d is None or ctx.as_of is None:
        return None
    return float((ctx.as_of.date() - d).days)


def observe_all(ctx: Context) -> Dict[str, Observation]:
    """Raw value, origin, age and coverage of every tracked input. No grading here."""
    a, w = ctx.A, ctx.W
    rules = config.load("rules")
    as_of = ctx.as_of.date() if ctx.as_of else None
    obs: Dict[str, Observation] = {name: Observation() for name in TRACKED_INPUTS}
    user = Origin.USER_REPORTED

    if a.sowing_date:
        obs["sowing_date"] = Observation(a.sowing_date, user)
    # A reported stage and an estimate from the sowing date can both exist; the more reliable one
    # is used, so that an old report never pushes out a better estimate (sigma stays monotone).
    candidates = []
    if a.bbch is not None:
        candidates.append(Observation(a.bbch, Origin(a.bbch_origin), _age(ctx, a.bbch_reported_on) or 0.0))
    if a.sowing_date and as_of:
        est = estimate_bbch(w.gdd_since_sowing, (as_of - to_date(a.sowing_date)).days, a.hybrid_fao)
        if est.output:
            candidates.append(Observation(est.output["bbch"], Origin.DERIVED, 0.0,
                                          source_ref="estimate_bbch:" + est.output["method"]))
    if candidates:
        obs["phenophase"] = max(candidates, key=lambda o: grade("phenophase", o).reliability.rank)

    # External parcel features (docs/parcel-features.md). They never change a VALUE used by the decision; they can only
    # lower a grade (apply_detail in annotate_quality) when a second source contradicts the stage in use.
    features, _rejected = pfm.usable(ctx)
    if features is not None:
        state = pfm.field_state(features, ctx.as_of)
        crop = pfm.crop_identity(a.crop, features)
        if obs["phenophase"].value is not None:
            conflicts = [c for c in (pfm.stage_conflict(obs["phenophase"], features, ctx.as_of),
                                     pfm.marker_conflict(state, obs["phenophase"], ctx.Q.advice_type.value)) if c]
            if conflicts:
                obs["phenophase"] = dataclasses.replace(obs["phenophase"], detail={"conflicts": conflicts})
        if state is not None:
            obs["field_state"] = state
        if crop is not None:
            obs["crop_identity"] = crop

    nd = ndvi_summary(ctx.S.ndvi_series, as_of).output
    if nd:
        ref = "ndvi:" + nd["latest_date"]
        detail = dict(nd.get("quality") or {})
        if nd.get("outliers_excluded"):
            detail["outliers_excluded"] = nd["outliers_excluded"]
        detail = detail or None
        obs["ndvi_latest"] = Observation(nd["latest_value"], Origin.MEASURED, nd["age_days"], nd["usable_share"],
                                         source_ref=ref, detail=detail)
        if nd["spatial_contrast"] is not None:
            obs["ndvi_spatial_contrast"] = Observation(nd["spatial_contrast"], Origin.MEASURED, nd["age_days"],
                                                       nd["usable_share"], source_ref=ref, detail=detail)
        if nd["trend_14d"] is not None:
            obs["ndvi_trend"] = Observation(nd["trend_14d"], Origin.MEASURED, nd["age_days"],
                                            count=nd["trend_count"], source_ref=ref)

    w_origin = Origin(w.origin)
    if w.precip_past_7d_mm is not None:
        obs["precip_past_7d"] = Observation(w.precip_past_7d_mm, w_origin, 0.0)
    if w.et0_past_7d_mm is not None:
        obs["et0_past_7d"] = Observation(w.et0_past_7d_mm, w_origin, 0.0)
    f_age = _age(ctx, w.forecast_issued_at)
    if f_age is not None:
        if w.precip_forecast_3d_mm is not None and w.horizon_days >= 3:
            obs["precip_forecast_3d"] = Observation(w.precip_forecast_3d_mm, Origin.MODELED, f_age)
        if w.precip_forecast_7d_mm is not None and w.horizon_days >= 7:
            obs["precip_forecast_7d"] = Observation(w.precip_forecast_7d_mm, Origin.MODELED, f_age)
        if w.tmin_forecast_7d_c is not None and w.tmax_forecast_7d_c is not None:
            obs["temp_forecast"] = Observation({"tmin": w.tmin_forecast_7d_c, "tmax": w.tmax_forecast_7d_c},
                                               Origin.MODELED, f_age)
        if w.wind_forecast_max_ms is not None:
            obs["wind_forecast"] = Observation(w.wind_forecast_max_ms, Origin.MODELED, f_age)

    if a.soil_water_status:
        obs["soil_water_status"] = Observation(a.soil_water_status, Origin(a.soil_water_origin),
                                               _age(ctx, a.soil_water_reported_on) or 0.0)
    opt = rules["optional_inputs"]
    recent = [o for o in (a.observations or []) if _age(ctx, o.get("date")) is not None
              and 0 <= _age(ctx, o.get("date")) <= opt["field_event_days"]]
    if not a.soil_water_status:
        irr_age = _age(ctx, a.last_irrigation_date)
        wilting = [o for o in recent if o.get("kind") == "wilting" and _age(ctx, o["date"]) <= opt["wilting_hint_days"]]
        if irr_age is not None and 0 <= irr_age <= opt["recent_irrigation_days"] \
                and (a.last_irrigation_mm or 0) >= opt["recent_irrigation_min_mm"]:
            # A recent, deep enough irrigation implies a moist root zone (derived, medium at best).
            obs["soil_water_status"] = Observation("moist", Origin.DERIVED, irr_age,
                                                   source_ref="last_irrigation:%s" % a.last_irrigation_date)
        elif wilting:
            # Wilting suggests dry soil but has other causes: a low-reliability hint to be confirmed.
            obs["soil_water_status"] = Observation("dry", Origin.MODELED, _age(ctx, wilting[-1]["date"]),
                                                   source_ref="observation:wilting")
    if a.soil_moisture_vwc is not None:
        obs["soil_moisture_sensor"] = Observation(a.soil_moisture_vwc, Origin.MEASURED,
                                                  _age(ctx, a.soil_moisture_measured_on) or 0.0)
    if a.soil_awc_mm_m is not None:
        obs["soil_awc"] = Observation(a.soil_awc_mm_m, user)
    elif a.soil_texture in rules["soil"]["awc_by_texture_mm_m"]:
        obs["soil_awc"] = Observation(rules["soil"]["awc_by_texture_mm_m"][a.soil_texture], Origin.DERIVED,
                                      source_ref="texture:" + a.soil_texture)
    if a.soil_analysis:
        analysis = dict(a.soil_analysis)
        if "level" not in analysis and analysis.get("humus_pct") is not None:
            lo, hi = opt["humus_bands_pct"]
            h = float(analysis["humus_pct"])
            analysis["level"] = "low" if h < lo else ("medium" if h < hi else "high")
        obs["soil_analysis"] = Observation(analysis, Origin.MEASURED, _age(ctx, analysis.get("date")))
    if a.irrigation_available in ("yes", "no"):
        obs["irrigation_available"] = Observation(a.irrigation_available, user)
    if a.irrigation_efficiency is not None:
        obs["irrigation_efficiency"] = Observation(a.irrigation_efficiency, user)
    elif a.irrigation_system_type in rules["soil"]["efficiency_by_system"]:
        obs["irrigation_efficiency"] = Observation(rules["soil"]["efficiency_by_system"][a.irrigation_system_type],
                                                   Origin.DERIVED, source_ref="system:" + a.irrigation_system_type)
    if a.fertilization_records is not None:
        # Records take precedence: N per record from the entered value or the product catalogue.
        records = []
        for rec in a.fertilization_records:
            rec = dict(rec)
            if rec.get("n_kg_ha") is None and rec.get("rate_kg_ha") is not None:
                share = opt["n_content"].get(product_key(rec.get("product", "")))
                if share is not None:
                    rec["n_kg_ha"] = round(float(rec["rate_kg_ha"]) * share, 1)
            records.append(rec)
        obs["previous_fertilization"] = Observation(records, user)
    elif a.previous_fertilization is not None:
        obs["previous_fertilization"] = Observation(a.previous_fertilization, user)
    if a.irrigation_capacity_mm_day is not None:
        obs["irrigation_capacity"] = Observation(a.irrigation_capacity_mm_day, user)
    if a.previous_crop:
        obs["previous_crop"] = Observation(a.previous_crop, user)
    manure_age = _age(ctx, a.manure_date)
    if a.manure_t_ha and (manure_age is None or 0 <= manure_age <= opt["manure_credit_days"]):
        obs["manure"] = Observation({"t_ha": a.manure_t_ha, "date": a.manure_date}, user, _age(ctx, a.manure_date))
    if a.hybrid_fao is not None:
        obs["hybrid_fao"] = Observation(a.hybrid_fao, user)
    if a.plant_density_ha is not None:
        obs["plant_density"] = Observation(a.plant_density_ha, user)
    if recent:
        newest = min(_age(ctx, o["date"]) for o in recent)
        obs["field_observation"] = Observation(sorted({o.get("kind") for o in recent}), user, newest)
    if a.yield_target_t_ha is not None:
        obs["yield_target"] = Observation(a.yield_target_t_ha, user)
    if a.operation:
        obs["operation"] = Observation(a.operation, user)
    return obs


def grade(name: str, o: Observation) -> Quality:
    """Deterministic reliability grade from (origin, age, coverage, count) and the threshold table."""
    if o.value is None:
        return Quality(name, Origin.UNKNOWN, None, None, Reliability.MISSING, "not available")
    if name in pfm.FEATURE_INPUTS:
        return pfm.grade_feature_input(name, o)
    spec = config.load("thresholds")["inputs"].get(name, {})
    limit = spec.get("missing_after_days")
    if limit is not None and o.age_days is not None and o.age_days > limit:
        return Quality(name, o.origin, o.age_days, o.coverage, Reliability.MISSING,
                       "older than %s days" % limit, o.source_ref)
    for g in spec.get("grades", []):
        if "origins" in g and o.origin.value not in g["origins"]:
            continue
        if "max_age_days" in g and (o.age_days is None or o.age_days > g["max_age_days"]):
            continue
        if "min_coverage" in g and (o.coverage is None or o.coverage < g["min_coverage"]):
            continue
        if "min_count" in g and (o.count is None or o.count < g["min_count"]):
            continue
        basis = ", ".join("%s=%s" % (k, v) for k, v in g.items() if k != "reliability")
        return Quality(name, o.origin, o.age_days, o.coverage, Reliability(g["reliability"]),
                       "meets: " + (basis or "any"), o.source_ref)
    return Quality(name, o.origin, o.age_days, o.coverage, Reliability(spec.get("default", "low")),
                   "meets no grade", o.source_ref)


def annotate_quality(ctx: Context, quality_aware: bool = True) -> QualityProfile:
    """Quality profile of the context.

    With quality_aware=False (variants without the q layer) no input is graded: every present input is
    marked 'ungraded' (its value is used as it is, with no reliability claim) and every absent one 'missing'.
    Raw facts that belong to the data itself (observation date, age, usable-pixel share, origin) are kept;
    only the grade, which is the output of q, is withheld.
    """
    profile: QualityProfile = {}
    for name, o in observe_all(ctx).items():
        if quality_aware:
            profile[name] = pfm.apply_detail(grade(name, o), o)
            small = ctx.P.area_ha is not None and ctx.P.area_ha < SMALL_PARCEL_HA
            if small and name.startswith("ndvi") and profile[name].reliability == Reliability.HIGH:
                # Under 0.3 ha a parcel has fewer than about 30 Sentinel-2 pixels of 10 m.
                q = profile[name]
                profile[name] = Quality(q.input, q.origin, q.age_days, q.coverage, Reliability.MEDIUM,
                                        q.basis + "; capped: parcel under %.1f ha" % SMALL_PARCEL_HA, q.source_ref,
                                        q.detail)
        elif o.value is None:
            profile[name] = Quality(name, Origin.UNKNOWN, None, None, Reliability.MISSING, "not available")
        else:
            profile[name] = Quality(name, o.origin, o.age_days, o.coverage, Reliability.UNGRADED,
                                    "quality layer off: not graded", o.source_ref)
    return profile


def values(ctx: Context) -> Dict[str, Any]:
    return {name: o.value for name, o in observe_all(ctx).items()}
