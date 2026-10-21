
from conftest import make_context
from smartagri.core.quality import annotate_quality, grade
from smartagri.core.types import Observation, Origin, Reliability


def rel(ctx, name, aware=True):
    return annotate_quality(ctx, aware)[name].reliability


def test_user_reported_recent_phenophase_is_high():
    assert rel(make_context(), "phenophase") == Reliability.HIGH


def test_phenophase_derived_from_sowing_date_is_medium():
    ctx = make_context(agronomic={"bbch": None})
    q = annotate_quality(ctx)["phenophase"]
    assert q.reliability == Reliability.MEDIUM and q.origin == Origin.DERIVED


def test_missing_inputs_are_missing():
    ctx = make_context(agronomic={"soil_water_status": None, "irrigation_available": "unknown"})
    assert rel(ctx, "soil_water_status") == Reliability.MISSING
    assert rel(ctx, "irrigation_available") == Reliability.MISSING
    assert rel(ctx, "ndvi_latest") == Reliability.MISSING


def test_ndvi_grades_by_age_and_coverage():
    def ndvi(date, share):
        return [dict(obs_date=date, median=0.7, p10=0.6, p90=0.8, usable_share=share)]
    assert rel(make_context(ndvi=ndvi("2026-07-09", 0.90)), "ndvi_latest") == Reliability.HIGH
    assert rel(make_context(ndvi=ndvi("2026-07-03", 0.65)), "ndvi_latest") == Reliability.MEDIUM
    assert rel(make_context(ndvi=ndvi("2026-07-03", 0.55)), "ndvi_latest") == Reliability.LOW
    assert rel(make_context(ndvi=ndvi("2026-06-01", 0.95)), "ndvi_latest") == Reliability.MISSING


def test_observations_after_as_of_are_ignored():
    future = [dict(obs_date="2026-07-20", median=0.7, p10=0.6, p90=0.8, usable_share=0.95)]
    assert rel(make_context(ndvi=future), "ndvi_latest") == Reliability.MISSING


def test_efficiency_derived_from_system_type_is_medium():
    assert rel(make_context(), "irrigation_efficiency") == Reliability.MEDIUM
    assert rel(make_context(agronomic={"irrigation_efficiency": 0.8}), "irrigation_efficiency") == Reliability.HIGH


def test_stale_forecast_is_not_high():
    assert rel(make_context(), "precip_forecast_3d") == Reliability.HIGH
    assert rel(make_context(weather={"forecast_issued_at": "2026-07-08T04:00:00"}), "precip_forecast_3d") == Reliability.LOW


def test_quality_layer_off_takes_values_at_face_value():
    stale = [dict(obs_date="2026-06-30", median=0.7, p10=0.6, p90=0.8, usable_share=0.5)]
    assert rel(make_context(ndvi=stale), "ndvi_latest", aware=False) == Reliability.HIGH


def test_monotonic_in_age_and_coverage():
    """Older data or lower coverage can never raise reliability (Proposition 4.1)."""
    ages = [0, 2, 5, 6, 10, 11, 20, 31]
    shares = [0.3, 0.6, 0.8, 1.0]
    for name in ("ndvi_latest", "soil_water_status", "precip_forecast_3d", "soil_analysis", "phenophase"):
        for origin in (Origin.MEASURED, Origin.USER_REPORTED, Origin.DERIVED, Origin.MODELED):
            for share in shares:
                ranks = [grade(name, Observation(1, origin, float(a), share)).reliability.rank for a in ages]
                assert ranks == sorted(ranks, reverse=True), (name, origin, share, ranks)
            for age in ages:
                ranks = [grade(name, Observation(1, origin, float(age), s)).reliability.rank for s in shares]
                assert ranks == sorted(ranks), (name, origin, age, ranks)


def test_old_stage_report_does_not_displace_a_better_estimate():
    ctx = make_context(agronomic={"bbch": 40, "bbch_reported_on": "2026-06-10"})
    q = annotate_quality(ctx)["phenophase"]
    assert q.origin == Origin.DERIVED and q.reliability == Reliability.MEDIUM


def test_ndvi_on_a_small_parcel_is_at_most_medium():
    fresh = [dict(obs_date="2026-07-10", median=0.7, p10=0.6, p90=0.8, usable_share=0.95)]
    ctx = make_context(ndvi=fresh)
    assert rel(ctx, "ndvi_latest") == Reliability.HIGH
    ctx.P.area_ha = 0.2
    q = annotate_quality(ctx)["ndvi_latest"]
    assert q.reliability == Reliability.MEDIUM and "capped" in q.basis
