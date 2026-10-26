"""Applicability predicate pi(d, C, q, t): is a passage applicable to this parcel, not merely relevant."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from .. import config
from .types import (AdviceType, Applicability, ApplicabilityResult, Context, Passage, QualityProfile,
                    Reliability, to_date)

# check name -> tracked input it depends on (None = depends on nothing uncertain). `crop_identity` exists in the quality
# profile only when the crop plausibility check of the parcel features is switched on (config/parcel_features.yaml); a
# profile without it leaves the crop check exactly as it was.
INPUT_FOR_CHECK = {"crop": "crop_identity", "advice_type": None, "phenophase": "phenophase", "region": None,
                   "agroecology": "irrigation_available", "date": None, "weather_consistency": "precip_forecast_3d",
                   "soil": None}
ALWAYS_HARD = ("crop", "advice_type")
STATUS_ORDER = {Applicability.APPLICABLE: 0, Applicability.CONDITIONAL: 1, Applicability.NOT_APPLICABLE: 2}


def _conditions_from_parcel(ctx: Context, vals: Dict[str, Any]) -> Dict[str, Any]:
    return {"crop": ctx.A.crop, "bbch": vals.get("phenophase"), "region": ctx.P.region_class,
            "irrigation_available": vals.get("irrigation_available"),
            "precip_forecast_3d": vals.get("precip_forecast_3d"), "soil_texture": ctx.A.soil_texture}


def _conditions_from_query(ctx: Context) -> Dict[str, Any]:
    s = ctx.Q.stated_conditions
    return {"crop": s.get("crop"), "bbch": s.get("bbch"), "region": s.get("region"),
            "irrigation_available": s.get("irrigation_available"), "precip_forecast_3d": None,
            "soil_texture": s.get("soil_texture")}


def _check(name: str, p: Passage, cond: Dict[str, Any], t: AdviceType, as_of) -> Optional[bool]:
    """True = holds, False = violated, None = cannot be evaluated (value absent)."""
    m = p.meta
    if name == "crop":
        if m.crop is None:
            return True
        return None if cond["crop"] is None else cond["crop"] in m.crop or "general" in m.crop
    if name == "advice_type":
        return True if m.advice_types is None else t.value in m.advice_types
    if name == "phenophase":
        if m.bbch_min is None and m.bbch_max is None:
            return True
        if cond["bbch"] is None:
            return None
        return (m.bbch_min or 0) <= cond["bbch"] <= (m.bbch_max if m.bbch_max is not None else 99)
    if name == "region":
        if m.region_scope is None or "global" in m.region_scope:
            return True
        return None if cond["region"] is None else cond["region"] in m.region_scope
    if name == "agroecology":
        # irrigated-only passages need irrigation; rainfed-only passages are written for parcels without it.
        # A passage marked both (or neither) does not restrict.
        if bool(m.irrigated) == bool(m.rainfed):
            return True
        if cond["irrigation_available"] is None:
            return None
        return cond["irrigation_available"] == ("yes" if m.irrigated else "no")
    if name == "date":
        if as_of is None or (m.valid_until is None and m.valid_from is None):
            return True
        day = as_of.date()
        return (m.valid_from is None or to_date(m.valid_from) <= day) and \
            (m.valid_until is None or day <= to_date(m.valid_until))
    if name == "soil":
        if not m.soil_scope:
            return True
        return None if cond["soil_texture"] is None else cond["soil_texture"] in m.soil_scope
    if name == "weather_consistency":
        if not m.requires_no_rain_3d:
            return True
        if cond["precip_forecast_3d"] is None:
            return None
        return cond["precip_forecast_3d"] < config.load("rules")["irrigation"]["rain_wait_mm_3d"]
    raise KeyError(name)


def applicability(p: Passage, ctx: Context, q: QualityProfile, vals: Dict[str, Any], mode: str,
                  quality_aware: bool) -> ApplicabilityResult:
    """mode: off | query_conditions | parcel_conditions.

    off              -> every passage applicable (standard RAG: relevance only)
    query_conditions -> conditions taken from the question text, assumed reliable (condition-aware RAG)
    parcel_conditions-> conditions taken from the parcel profile; with quality_aware also graded by q
    """
    if mode == "off":
        return ApplicabilityResult(p.id, Applicability.APPLICABLE)
    t = ctx.Q.advice_type
    from_parcel = mode == "parcel_conditions"
    cond = _conditions_from_parcel(ctx, vals) if from_parcel else _conditions_from_query(ctx)
    unmet: List[str] = []
    unverifiable: List[str] = []
    hard_fail = None
    for name, dep in INPUT_FOR_CHECK.items():
        graded = q.get(dep) if dep else None
        rel = graded.reliability if (graded is not None and from_parcel and quality_aware) else None
        result = _check(name, p, cond, t, ctx.as_of)
        if result is None:
            # Without the q layer a system does not notice a missing condition: it lets the passage through.
            if from_parcel and quality_aware:
                unverifiable.append(name)
            continue
        if result is False:
            unmet.append(name)
            hard = name in ALWAYS_HARD or (name == "phenophase" and (rel is None or rel == Reliability.HIGH))
            if hard and hard_fail is None:
                hard_fail = name
        elif rel == Reliability.LOW:
            unverifiable.append(name)
    if hard_fail:
        status = Applicability.NOT_APPLICABLE
    elif unmet or unverifiable:
        status = Applicability.CONDITIONAL
    else:
        status = Applicability.APPLICABLE
    return ApplicabilityResult(p.id, status, unmet, unverifiable, hard_fail)


def select_budget(results: List[ApplicabilityResult], budget: int = 6) -> List[str]:
    """Applicable passages first, then conditional ones; not-applicable passages are never passed on.

    Input order (retrieval rank) is preserved within each group.
    """
    ranked = sorted((r for r in results if r.status != Applicability.NOT_APPLICABLE),
                    key=lambda r: STATUS_ORDER[r.status])
    return [r.passage_id for r in ranked[:budget]]
