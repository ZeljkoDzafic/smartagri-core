from conftest import make_context
from smartagri.core.asking import choose_question
from smartagri.core.quality import annotate_quality, values
from smartagri.core.sufficiency import sufficiency
from smartagri.core.types import AdviceType

T = AdviceType


def ask(t, asked=0, **kw):
    ctx = make_context(t, questions_asked=asked, **kw)
    s = sufficiency(t, annotate_quality(ctx))
    return choose_question(t, values(ctx), s.missing_inputs(), ctx.questions_asked)


def test_asks_for_soil_water_when_it_changes_the_decision():
    c = ask(T.IRRIGATION_TIMING, agronomic={"soil_water_status": None})
    assert c.input == "soil_water_status" and c.reason == "selected"
    assert c.how_to_obtain            # the user is told how to get the answer
    top = [x for x in c.candidates if x.input == "soil_water_status"][0]
    assert top.sensitivity == 2 and len(top.outcomes) == 3


def test_does_not_ask_when_rain_makes_the_answer_irrelevant():
    c = ask(T.IRRIGATION_TIMING, agronomic={"soil_water_status": None}, weather={"precip_forecast_3d_mm": 18.0})
    assert c.input is None and c.reason == "decision_insensitive"


def test_never_asks_for_inputs_the_user_cannot_supply():
    c = ask(T.SCOUTING)
    assert c.input is None and c.reason == "not_obtainable"


def test_efficiency_does_not_change_the_decision_class_so_soil_water_is_asked():
    c = ask(T.IRRIGATION_AMOUNT, agronomic={"soil_water_status": None, "irrigation_system_type": None})
    assert c.input == "soil_water_status"
    eff = [x for x in c.candidates if x.input == "irrigation_efficiency"][0]
    assert eff.sensitivity == 0


def test_question_budget_is_respected():
    c = ask(T.IRRIGATION_TIMING, asked=2, agronomic={"soil_water_status": None})
    assert c.input is None and c.reason == "budget_exhausted"


def test_ties_are_broken_by_cost():
    c = ask(T.FERTILIZATION_PLAN, agronomic={"bbch": 16})
    assert c.input == "previous_fertilization"     # cheaper than obtaining a soil analysis


def test_late_season_makes_soil_water_irrelevant():
    c = ask(T.IRRIGATION_TIMING, agronomic={"soil_water_status": None, "bbch": 87})
    assert c.input is None and c.reason == "decision_insensitive"
