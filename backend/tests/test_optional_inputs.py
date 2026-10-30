"""Optional inputs change decisions only where a rule says so, and nothing when absent."""
from conftest import make_context
from smartagri.config import load_variants
from smartagri.core.decide import decide
from smartagri.core.quality import annotate_quality, values
from smartagri.core.rules import fertilization_plan
from smartagri.core.tools import estimate_bbch
from smartagri.core.types import Act, AdviceType, Origin, Passage, PassageMeta, Reliability

T = AdviceType
PASSAGES = [Passage("ok", meta=PassageMeta(crop=["maize"]))]


def run(t, **kw):
    return decide(make_context(t, **kw), PASSAGES, load_variants()["V5"])


def test_recent_irrigation_removes_the_need_to_ask():
    without = run(T.IRRIGATION_TIMING, agronomic={"soil_water_status": None})
    assert without.question.input == "soil_water_status"
    recent = {"soil_water_status": None, "last_irrigation_date": "2026-07-10", "last_irrigation_mm": 25}
    d = run(T.IRRIGATION_TIMING, agronomic=recent)
    q = d.quality["soil_water_status"]
    assert q.origin == Origin.DERIVED and q.reliability == Reliability.MEDIUM
    assert d.question is None and d.policy.act == Act.RECOMMEND and d.core_action == "recheck_in_3d"


def test_shallow_or_old_irrigation_is_ignored():
    for agro in ({"last_irrigation_date": "2026-07-10", "last_irrigation_mm": 5},
                 {"last_irrigation_date": "2026-07-01", "last_irrigation_mm": 30}):
        d = run(T.IRRIGATION_TIMING, agronomic=dict(agro, soil_water_status=None))
        assert d.quality["soil_water_status"].reliability == Reliability.MISSING


def test_wilting_is_only_a_low_reliability_hint():
    obs = [{"date": "2026-07-11", "kind": "wilting"}]
    d = run(T.IRRIGATION_TIMING, agronomic={"soil_water_status": None, "observations": obs})
    q = d.quality["soil_water_status"]
    assert q.reliability == Reliability.LOW and d.question.input == "soil_water_status"


def test_fertilization_records_give_nitrogen_from_the_product_catalogue():
    ctx = make_context(T.FERTILIZATION_PLAN, agronomic={
        "bbch": 16, "fertilization_records": [{"date": "2026-04-20", "product": "UREA", "rate_kg_ha": 200}]})
    recs = values(ctx)["previous_fertilization"]
    assert recs[0]["n_kg_ha"] == 92.0
    assert annotate_quality(ctx)["previous_fertilization"].reliability == Reliability.HIGH


def test_legume_previous_crop_and_recent_manure_lower_the_dose_band():
    base = {"phenophase": 16, "previous_fertilization": [], "yield_target": 9.0}
    assert fertilization_plan(base).endswith("dose:medium")
    assert fertilization_plan(dict(base, previous_crop="soybean")).endswith("dose:low")
    assert fertilization_plan(dict(base, previous_crop="wheat")).endswith("dose:medium")
    ctx = make_context(T.FERTILIZATION_PLAN, agronomic={"manure_t_ha": 30, "manure_date": "2025-01-10"})
    assert values(ctx)["manure"] is None                      # older than a year: no credit
    ctx = make_context(T.FERTILIZATION_PLAN, agronomic={"manure_t_ha": 30, "manure_date": "2026-03-10"})
    assert fertilization_plan(dict(base, manure=values(ctx)["manure"])).endswith("dose:low")


def test_humus_gives_the_soil_analysis_level():
    ctx = make_context(T.FERTILIZATION_PLAN, agronomic={"soil_analysis": {"date": "2025-09-01", "humus_pct": 1.6}})
    assert values(ctx)["soil_analysis"]["level"] == "low"


def test_later_hybrid_reaches_stages_later():
    early = estimate_bbch(gdd_since_sowing=700, hybrid_fao=300).output["bbch"]
    late = estimate_bbch(gdd_since_sowing=700, hybrid_fao=600).output["bbch"]
    assert early > late
    assert estimate_bbch(gdd_since_sowing=700).output["bbch"] == estimate_bbch(gdd_since_sowing=700, hybrid_fao=400).output["bbch"]


def test_hail_makes_scouting_a_priority_without_a_satellite_view():
    assert run(T.SCOUTING).policy.act == Act.ABSTAIN
    d = run(T.SCOUTING, agronomic={"observations": [{"date": "2026-07-10", "kind": "hail"}]})
    assert d.policy.act == Act.RECOMMEND and d.core_action == "priority_scouting_event"
    old = run(T.SCOUTING, agronomic={"observations": [{"date": "2026-06-20", "kind": "hail"}]})
    assert old.policy.act == Act.ABSTAIN


def test_absent_optional_inputs_change_nothing():
    for t in (T.IRRIGATION_TIMING, T.IRRIGATION_AMOUNT, T.FERTILIZATION_PLAN, T.FIELD_OPS_WINDOW, T.SCOUTING):
        d = run(t)
        for name in ("irrigation_capacity", "previous_crop", "manure", "hybrid_fao", "plant_density", "field_observation"):
            assert d.quality[name].reliability == Reliability.MISSING


def test_system_capacity_gives_the_duration_of_one_application():
    d = run(T.IRRIGATION_AMOUNT, agronomic={"irrigation_capacity_mm_day": 8})
    t = [x for x in d.tools if x.tool == "application_time"][0]
    gross = [x for x in d.tools if x.tool == "gross_irrigation"][0].output["gross_mm"]
    assert t.output["days_per_application"] == round(gross / 8, 1)
    assert not [x for x in run(T.IRRIGATION_AMOUNT).tools if x.tool == "application_time"]
