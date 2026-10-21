from conftest import make_context
from smartagri.core.decide import decide
from smartagri.core.types import Act, AdviceType, Passage, PassageMeta

T = AdviceType
PASSAGES = [Passage("ok", meta=PassageMeta(crop=["maize"]))]


def act(variants, name, t, passages=PASSAGES, **kw):
    return decide(make_context(t, **kw), passages, variants[name])


def test_variants_without_sufficiency_delegate_the_act(variants):
    for name in ("V0", "V1", "V2", "V3"):
        d = act(variants, name, T.IRRIGATION_TIMING, agronomic={"soil_water_status": None})
        assert d.policy.act is None and d.sufficiency is None and d.question is None


def test_sufficient_context_recommends(variants):
    d = act(variants, "V5", T.IRRIGATION_AMOUNT)
    assert d.policy.act == Act.RECOMMEND and d.policy.allow_quantity
    assert d.tools[-1].output["gross_mm"] > 0


def test_high_risk_asks_and_allows_no_quantity(variants):
    d = act(variants, "V5", T.IRRIGATION_AMOUNT, agronomic={"soil_water_status": None})
    assert d.policy.act == Act.ASK and not d.policy.allow_quantity
    assert d.tools[-1].output is None            # the tool refuses to compute without soil water


def test_low_risk_gives_conditional_answer_with_question(variants):
    d = act(variants, "V5", T.IRRIGATION_TIMING, agronomic={"soil_water_status": None})
    assert d.policy.act == Act.CONDITIONAL and d.question.input == "soil_water_status"


def test_partial_without_useful_question_degrades(variants):
    d = act(variants, "V5", T.IRRIGATION_AMOUNT, agronomic={"irrigation_system_type": None})
    assert d.policy.act == Act.CONDITIONAL and d.policy.reason_code == "degraded_to_irrigation_timing"
    assert not d.policy.allow_quantity


def test_unobtainable_missing_input_abstains(variants):
    d = act(variants, "V5", T.SCOUTING)
    assert d.policy.act == Act.ABSTAIN


def test_no_applicable_passage_abstains(variants):
    wheat = [Passage("w", meta=PassageMeta(crop=["wheat"]))]
    d = act(variants, "V5", T.IRRIGATION_TIMING, passages=wheat)
    assert d.policy.act == Act.ABSTAIN and d.policy.reason_code == "corpus_insufficient"


def test_out_of_scope_abstains(variants):
    d = act(variants, "V5", T.OUT_OF_SCOPE)
    assert d.policy.act == Act.ABSTAIN and d.policy.reason_code == "out_of_scope"


def test_without_policy_layer_nothing_is_withheld(variants):
    """V4 has sufficiency and asking but no policy: it never abstains and never guards quantities."""
    d = act(variants, "V4", T.SCOUTING)
    assert d.policy.act == Act.RECOMMEND and "missing_inputs_unresolved" in d.policy.warnings
    d = act(variants, "V4", T.IRRIGATION_TIMING, agronomic={"soil_water_status": None})
    assert d.policy.act == Act.ASK


def test_declined_input_is_not_asked_again(variants):
    ctx = make_context(T.IRRIGATION_TIMING, agronomic={"soil_water_status": None})
    ctx.declined_inputs = ["soil_water_status"]
    d = decide(ctx, PASSAGES, variants["V5"])
    assert d.question.input is None and d.question.reason == "not_obtainable"
    assert d.policy.act == Act.ABSTAIN               # the input is absent, not merely stale


def test_stale_but_present_input_gives_a_conditional_answer(variants):
    stale = [dict(obs_date="2026-06-30", median=0.7, p10=0.4, p90=0.8, usable_share=0.5)]
    d = act(variants, "V5", T.SCOUTING, ndvi=stale)
    assert d.policy.act == Act.CONDITIONAL and d.policy.reason_code == "unreliable_inputs_stated"
    d = act(variants, "V5", T.IRRIGATION_TIMING, weather={"forecast_issued_at": "2026-07-08T04:00:00"})
    assert d.policy.act == Act.CONDITIONAL and d.policy.reason_code == "unreliable_inputs_stated"


def _conflict_passages(status_b_meta=None):
    a = Passage("a", meta=PassageMeta(crop=["maize"], recommends={"irrigation_at_flowering": "irrigate"}))
    b = Passage("b", meta=PassageMeta(**dict({"crop": ["maize"], "recommends": {"irrigation_at_flowering": "wait"}},
                                         **(status_b_meta or {}))))
    return [a, b]


def test_conflict_between_applicable_sources_degrades_the_advice(variants):
    d = act(variants, "V5", T.IRRIGATION_TIMING, passages=_conflict_passages())
    assert d.policy.act == Act.CONDITIONAL and d.policy.reason_code == "source_conflict"
    assert d.conflicts[0].resolution == "degrade" and set(d.conflicts[0].values) == {"irrigate", "wait"}


def test_conflict_prefers_the_applicable_source(variants):
    d = act(variants, "V5", T.IRRIGATION_TIMING, passages=_conflict_passages({"region_scope": ["mediterranean"]}))
    assert d.policy.act == Act.RECOMMEND
    assert d.conflicts[0].resolution == "prefer_applicable" and d.conflicts[0].preferred_value == "irrigate"


def test_conflict_is_only_reported_below_the_policy_layer(variants):
    d = act(variants, "V4", T.IRRIGATION_TIMING, passages=_conflict_passages())
    assert d.policy.act == Act.RECOMMEND and d.conflicts[0].resolution == "degrade"


def test_template_answer_states_both_sides_of_a_conflict(variants):
    from smartagri.pipeline.generate import template_answer
    from smartagri.retrieval import load_corpus
    ctx = make_context(T.IRRIGATION_TIMING)
    d = decide(ctx, _conflict_passages(), variants["V5"])
    a = template_answer(ctx, d, load_corpus())
    text = " ".join(a["rationale"])
    assert a["act"] == "conditional" and "irrigate" in text and "wait" in text and "ne slažu" in a["summary"]
