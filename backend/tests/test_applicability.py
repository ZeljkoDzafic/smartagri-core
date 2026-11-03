import pytest
from conftest import make_context
from smartagri.core.applicability import applicability, select_budget
from smartagri.core.quality import annotate_quality, values
from smartagri.core.types import Applicability, ApplicabilityResult, Passage, PassageMeta


def run(passage, ctx, mode="parcel_conditions", aware=True):
    return applicability(passage, ctx, annotate_quality(ctx, aware), values(ctx), mode, aware)


def P(**meta):
    meta.setdefault("crop", ["maize"])
    meta.setdefault("advice_types", ["irrigation_timing"])
    return Passage("p", meta=PassageMeta(**meta))


def test_off_mode_accepts_everything():
    assert run(P(crop=["wheat"]), make_context(), mode="off").status == Applicability.APPLICABLE


def test_wrong_crop_and_wrong_advice_type_are_hard_failures():
    assert run(P(crop=["wheat"]), make_context()).hard_fail == "crop"
    assert run(P(advice_types=["scouting"]), make_context()).hard_fail == "advice_type"


def test_matching_passage_is_applicable():
    assert run(P(bbch_min=51, bbch_max=69, region_scope=["pannonian"]), make_context()).status == Applicability.APPLICABLE


def test_wrong_phase_is_hard_only_when_phase_is_reliable():
    grain_fill = P(bbch_min=71, bbch_max=85)
    confirmed = make_context()                                  # BBCH 61 reported yesterday -> high
    r = run(grain_fill, confirmed)
    assert r.status == Applicability.NOT_APPLICABLE and r.hard_fail == "phenophase"
    estimated = make_context(agronomic={"bbch": None})          # derived from sowing date -> medium
    r = run(grain_fill, estimated)
    assert r.status == Applicability.CONDITIONAL and "phenophase" in r.unmet


def test_soft_conditions_make_a_passage_conditional():
    r = run(P(region_scope=["mediterranean"]), make_context())
    assert r.status == Applicability.CONDITIONAL and r.unmet == ["region"]
    r = run(P(valid_until="2020-01-01"), make_context())
    assert r.status == Applicability.CONDITIONAL and r.unmet == ["date"]
    r = run(P(irrigated=True), make_context(agronomic={"irrigation_available": "no"}))
    assert r.status == Applicability.CONDITIONAL and r.unmet == ["agroecology"]


def test_missing_input_is_unverifiable_only_with_quality_layer():
    irrigated_only = P(irrigated=True)
    ctx = make_context(agronomic={"irrigation_available": "unknown"})
    assert run(irrigated_only, ctx).unverifiable == ["agroecology"]
    assert run(irrigated_only, ctx, aware=False).status == Applicability.APPLICABLE


def test_weather_condition_contradicted_by_forecast():
    r = run(P(requires_no_rain_3d=True), make_context(weather={"precip_forecast_3d_mm": 18.0}))
    assert r.status == Applicability.CONDITIONAL and r.unmet == ["weather_consistency"]


def test_query_conditions_ignore_the_parcel_profile():
    """The condition-aware baseline sees only what the question states."""
    grain_fill = P(bbch_min=71, bbch_max=85)
    silent = make_context()                         # parcel is at BBCH 61, question says nothing
    assert run(grain_fill, silent, mode="query_conditions", aware=False).status == Applicability.APPLICABLE
    stated = make_context(stated={"crop": "maize", "bbch": 61})
    assert run(grain_fill, stated, mode="query_conditions", aware=False).status == Applicability.NOT_APPLICABLE


def test_budget_prefers_applicable_and_drops_not_applicable():
    res = [ApplicabilityResult("a", Applicability.CONDITIONAL), ApplicabilityResult("b", Applicability.NOT_APPLICABLE),
           ApplicabilityResult("c", Applicability.APPLICABLE), ApplicabilityResult("d", Applicability.APPLICABLE)]
    assert select_budget(res, budget=3) == ["c", "d", "a"]


# ---------------------------------------------------------------- valid_from, soil_scope, rainfed


@pytest.mark.parametrize("meta, agronomic, status, unmet, unverifiable", [
    # soil texture vs soil_scope: a soft condition, never a hard failure
    ({"soil_scope": ["loam", "clay_loam"]}, {}, Applicability.APPLICABLE, [], []),
    ({"soil_scope": ["sand"]}, {}, Applicability.CONDITIONAL, ["soil"], []),
    ({"soil_scope": ["sand"]}, {"soil_texture": None}, Applicability.CONDITIONAL, [], ["soil"]),
    # rainfed-only passage vs irrigation availability
    ({"rainfed": True}, {"irrigation_available": "no"}, Applicability.APPLICABLE, [], []),
    ({"rainfed": True}, {"irrigation_available": "yes"}, Applicability.CONDITIONAL, ["agroecology"], []),
    ({"rainfed": True}, {"irrigation_available": "unknown"}, Applicability.CONDITIONAL, [], ["agroecology"]),
    ({"rainfed": True, "irrigated": True}, {"irrigation_available": "no"}, Applicability.APPLICABLE, [], []),
    ({"irrigated": True, "rainfed": False}, {"irrigation_available": "yes"}, Applicability.APPLICABLE, [], []),
    # valid_from vs as_of (2026-07-12)
    ({"valid_from": "2026-07-12"}, {}, Applicability.APPLICABLE, [], []),
    ({"valid_from": "2026-07-13"}, {}, Applicability.CONDITIONAL, ["date"], []),
    ({"valid_from": "2020-01-01", "valid_until": "2026-07-11"}, {}, Applicability.CONDITIONAL, ["date"], []),
    ({"valid_from": "2020-01-01", "valid_until": "2030-01-01"}, {}, Applicability.APPLICABLE, [], []),
    # claims_numeric does not restrict applicability
    ({"claims_numeric": True}, {}, Applicability.APPLICABLE, [], []),
])
def test_new_meta_checks(meta, agronomic, status, unmet, unverifiable):
    r = run(P(**meta), make_context(agronomic=agronomic))
    assert (r.status, r.unmet, r.unverifiable, r.hard_fail) == (status, unmet, unverifiable, None)


def test_soil_scope_without_quality_layer_lets_a_missing_texture_through():
    r = run(P(soil_scope=["sand"]), make_context(agronomic={"soil_texture": None}), aware=False)
    assert r.status == Applicability.APPLICABLE


def test_query_conditions_use_the_stated_soil_texture_only():
    sandy = P(soil_scope=["sand"])
    assert run(sandy, make_context(), mode="query_conditions", aware=False).status == Applicability.APPLICABLE
    stated = make_context(stated={"soil_texture": "clay"})
    assert run(sandy, stated, mode="query_conditions", aware=False).unmet == ["soil"]


def test_new_meta_fields_round_trip_through_from_dict():
    p = Passage.from_dict({"id": "x", "meta": {"valid_from": "2017-09-07", "soil_scope": ["loam"], "rainfed": True,
                                               "claims_numeric": True}})
    assert p.meta.to_dict()["soil_scope"] == ["loam"] and p.meta.rainfed is True and p.meta.claims_numeric is True
