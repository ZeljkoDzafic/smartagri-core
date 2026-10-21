from conftest import make_context
from smartagri.core.quality import annotate_quality
from smartagri.core.sufficiency import sufficiency
from smartagri.core.types import AdviceType, Sufficiency

T = AdviceType


def sig(t, **kw):
    ctx = make_context(t, **kw)
    return sufficiency(t, annotate_quality(ctx))


def test_complete_context_is_sufficient_for_irrigation():
    assert sig(T.IRRIGATION_TIMING).status == Sufficiency.SUFFICIENT
    assert sig(T.IRRIGATION_AMOUNT).status == Sufficiency.SUFFICIENT


def test_missing_soil_water_makes_timing_insufficient():
    r = sig(T.IRRIGATION_TIMING, agronomic={"soil_water_status": None})
    assert r.status == Sufficiency.INSUFFICIENT
    assert r.missing == [{"one_of": ["soil_water_status", "soil_moisture_sensor"]}]


def test_sensor_reading_satisfies_the_alternative():
    r = sig(T.IRRIGATION_TIMING, agronomic={"soil_water_status": None, "soil_moisture_vwc": 0.15,
                                           "soil_moisture_measured_on": "2026-07-12"})
    assert r.status == Sufficiency.SUFFICIENT


def test_amount_degrades_to_timing_when_only_amount_inputs_are_missing():
    r = sig(T.IRRIGATION_AMOUNT, agronomic={"irrigation_system_type": None, "soil_texture": None})
    assert r.status == Sufficiency.PARTIAL and r.degraded_to == T.IRRIGATION_TIMING
    assert set(r.missing) == {"soil_awc", "irrigation_efficiency"}


def test_stale_soil_water_report_counts_as_missing():
    r = sig(T.IRRIGATION_TIMING, agronomic={"soil_water_reported_on": "2026-07-01"})
    assert r.status == Sufficiency.INSUFFICIENT


def test_fertilization_plan_truth_table():
    base = {"bbch": 16}
    assert sig(T.FERTILIZATION_PLAN, agronomic=base).status == Sufficiency.PARTIAL
    full = dict(base, previous_fertilization=[], yield_target_t_ha=9.0)
    assert sig(T.FERTILIZATION_PLAN, agronomic=full).status == Sufficiency.SUFFICIENT
    old_analysis = dict(base, previous_fertilization=[], soil_analysis={"date": "2015-03-01", "level": "medium"})
    assert sig(T.FERTILIZATION_PLAN, agronomic=old_analysis).status == Sufficiency.PARTIAL


def test_scouting_needs_a_usable_satellite_view():
    assert sig(T.SCOUTING).status == Sufficiency.INSUFFICIENT
    fresh = [dict(obs_date="2026-07-10", median=0.7, p10=0.5, p90=0.8, usable_share=0.9)]
    assert sig(T.SCOUTING, ndvi=fresh).status == Sufficiency.SUFFICIENT


def test_field_ops_needs_the_operation():
    assert sig(T.FIELD_OPS_WINDOW).missing == ["operation"]
    assert sig(T.FIELD_OPS_WINDOW, agronomic={"operation": "spraying"}).status == Sufficiency.SUFFICIENT


def test_adding_information_never_lowers_sufficiency():
    """Proposition 4.3: sigma is monotone in available, reliable inputs."""
    steps = [
        {"soil_water_status": None, "irrigation_system_type": None, "soil_texture": None, "bbch": None, "sowing_date": None},
        {"soil_water_status": None, "irrigation_system_type": None, "soil_texture": None, "bbch": None},
        {"soil_water_status": None, "irrigation_system_type": None, "soil_texture": None},
        {"irrigation_system_type": None, "soil_texture": None},
        {"soil_texture": None},
        {},
    ]
    for t in (T.IRRIGATION_TIMING, T.IRRIGATION_AMOUNT):
        ranks = [sig(t, agronomic=s).status.rank for s in steps]
        assert ranks == sorted(ranks), (t, ranks)
