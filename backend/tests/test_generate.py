"""Answer generation (spec 004): quantity gate, mandatory notes, fallbacks of the model path,
model-chosen act, summary replacement and template timing. No network: the Anthropic client is faked."""
import copy
import statistics
import time

import pytest

from conftest import make_context
from smartagri import config, labels
from smartagri.config import load_variants
from smartagri.core.decide import decide
from smartagri.core.types import AdviceType, Context
from smartagri.evalkit.scenarios import load_scenarios
from smartagri.pipeline import generate
from smartagri.retrieval import Retriever, load_corpus

CORPUS = load_corpus()
RETRIEVER = Retriever(CORPUS.passages)              # BM25 only, no embedder
QUESTIONS = {AdviceType.IRRIGATION_TIMING: "Da li sutra da navodnjavam kukuruz?",
             AdviceType.IRRIGATION_AMOUNT: "Koliko vode da dam kukuruzu ove nedelje?"}


def decide_with_passages(ctx, variant_name):
    """decide() over passages retrieved for a realistic question, as pipeline.run.advise does."""
    ctx.Q.text = QUESTIONS.get(ctx.Q.advice_type, ctx.Q.text)
    return decide(ctx, RETRIEVER.search(ctx.Q.text, ctx.Q.advice_type), load_variants()[variant_name])


class FakeAPIError(Exception):
    pass


class FakeOverloaded(FakeAPIError):
    pass


def fake_generator(reply=None, stop_reason="end_turn", raises=None, blocks=None):
    """AnthropicGenerator whose client returns `reply` (a JSON string) or raises `raises`."""
    class Block:
        type, text = "text", reply

    class Resp:
        content = [Block()] if blocks is None else blocks
        usage = type("U", (), {"input_tokens": 11, "output_tokens": 7})()

    Resp.stop_reason = stop_reason

    def create(**kwargs):
        if raises is not None:
            raise raises
        return Resp()

    g = generate.AnthropicGenerator.__new__(generate.AnthropicGenerator)
    g.model, g._anthropic = "fake", type("A", (), {"APIError": FakeAPIError})
    g.client = type("C", (), {"beta": type("B", (), {"messages": type("M", (), {"create": staticmethod(create)})()})()})()
    return g


# ------------------------------------------------------------------ T008 quantity gate

def _amount_context():
    return make_context(AdviceType.IRRIGATION_AMOUNT,
                        agronomic={"soil_awc_mm_m": 170.0, "irrigation_efficiency": 0.75, "soil_water_status": "dry"})


def _rules_with(monkeypatch, validated):
    real = config.load
    rules = copy.deepcopy(real("rules"))
    rules["irrigation"]["quantity_validated"] = validated
    monkeypatch.setattr(config, "load", lambda name: rules if name == "rules" else real(name))


def test_quantity_is_withheld_until_the_balance_is_validated(monkeypatch):
    ctx = _amount_context()
    d = decide_with_passages(ctx, "V5")
    assert d.policy.act.value == "recommend" and d.policy.allow_quantity, d.policy

    _rules_with(monkeypatch, False)
    a = generate.template_answer(ctx, d, CORPUS)
    assert a["action"] is not None and a["action"]["quantity"] is None
    assert labels.QUANTITY_NOTE in a["limitations"]

    _rules_with(monkeypatch, True)
    b = generate.template_answer(ctx, d, CORPUS)
    assert b["action"]["quantity"] and "m³ po hektaru" in b["action"]["quantity"]
    assert labels.QUANTITY_NOTE not in b["limitations"]


def test_quantity_never_appears_when_the_policy_forbids_it(monkeypatch):
    _rules_with(monkeypatch, True)
    ctx = make_context(AdviceType.IRRIGATION_AMOUNT, agronomic={"soil_water_status": None})
    d = decide_with_passages(ctx, "V5")
    assert not d.policy.allow_quantity
    a = generate.template_answer(ctx, d, CORPUS)
    assert (a["action"] or {}).get("quantity") is None
    assert all(c["tool"] not in generate.QUANTITY_TOOLS for c in a["calculations"])


# ------------------------------------------------------------------ T009 mandatory notes

def _dev_answers(advice_type):
    for sc in load_scenarios("dev"):
        if sc["context"]["Q"]["advice_type"] != advice_type:
            continue
        for v in load_variants().values():
            ctx = Context.from_dict(sc["context"])
            yield sc["id"], v.name, generate.template_answer(ctx, decide(ctx, [], v), CORPUS)


def test_scouting_answers_always_carry_the_no_diagnosis_note():
    seen = 0
    for sid, vname, a in _dev_answers("scouting"):
        assert labels.NO_DIAGNOSIS in a["limitations"], (sid, vname)
        seen += 1
    ctx = make_context(AdviceType.SCOUTING)                 # no satellite series at all
    for v in load_variants().values():
        assert labels.NO_DIAGNOSIS in generate.template_answer(ctx, decide(ctx, [], v), CORPUS)["limitations"]
    assert seen >= 2 * len(load_variants())


def test_fertilisation_plans_always_carry_the_dose_note():
    seen = 0
    for sid, vname, a in _dev_answers("fertilization_plan"):
        assert labels.DOSE_NOTE in a["limitations"], (sid, vname)
        seen += 1
    assert seen >= 2 * len(load_variants())


# ------------------------------------------------------------------ T014 fallbacks

def _v5_decision():
    ctx = make_context()
    return ctx, decide_with_passages(ctx, "V5")


def test_api_error_falls_back_to_the_template():
    ctx, d = _v5_decision()
    answer, gr, usage = fake_generator(raises=FakeOverloaded("busy")).generate(ctx, d, CORPUS)
    assert gr["action"] == "template_after_error:FakeOverloaded"
    assert usage["llm_calls"] == 0 and answer == generate.template_answer(ctx, d, CORPUS)


@pytest.mark.parametrize("stop", ["refusal", "max_tokens"])
def test_stop_reason_other_than_end_turn_falls_back(stop):
    ctx, d = _v5_decision()
    reply = '{"act": "recommend", "summary": "Navodnjavati odmah.", "rationale": []}'
    answer, gr, usage = fake_generator(reply, stop_reason=stop).generate(ctx, d, CORPUS)
    assert gr["action"] == "template_after_" + stop
    assert usage == {"llm_calls": 1, "input_tokens": 11, "output_tokens": 7}     # the call is still paid for
    assert answer == generate.template_answer(ctx, d, CORPUS) and answer["generator"] == "template"


@pytest.mark.parametrize("reply,blocks", [("not json {", None), ("", None), (None, [])])
def test_unparseable_output_falls_back(reply, blocks):
    ctx, d = _v5_decision()
    answer, gr, _ = fake_generator(reply, blocks=blocks).generate(ctx, d, CORPUS)
    assert gr["action"] == "template_after_unparseable_output"
    assert answer == generate.template_answer(ctx, d, CORPUS)


# ------------------------------------------------------------------ T017 model-chosen act

@pytest.mark.parametrize("grounding_check", [True, False])
def test_act_is_taken_from_the_model_only_when_free(grounding_check):
    reply = '{"act": "abstain", "summary": "Navodnjavati.", "rationale": ["Faza razvoja je BBCH 61."]}'
    g = fake_generator(reply)
    ctx = make_context()
    free = decide_with_passages(ctx, "V3")          # no sufficiency layer: the core chooses no act
    assert free.policy.act is None
    a, _, _ = g.generate(ctx, free, CORPUS, grounding_check=grounding_check)
    assert a["act"] == "abstain" and a["act_label"] == labels.ACTS["abstain"]

    for name in ("V4", "V5"):
        fixed = decide_with_passages(ctx, name)
        assert fixed.policy.act is not None
        b, _, _ = g.generate(ctx, fixed, CORPUS, grounding_check=grounding_check)
        assert b["act"] == fixed.policy.act.value != "abstain"


# ------------------------------------------------------------------ T020a unsupported summary

def test_unsupported_summary_is_replaced_by_the_template_summary():
    ctx, d = _v5_decision()
    reply = ('{"act": "recommend", "summary": "Fungicid treba primeniti odmah zbog pegavosti lista kukuruza.", '
             '"rationale": ["Faza razvoja je BBCH 61."]}')
    answer, gr, _ = fake_generator(reply).generate(ctx, d, CORPUS, grounding_check=True)
    template = generate.template_answer(ctx, d, CORPUS)
    assert gr["action"] == "summary_replaced_by_template"
    assert answer["summary"] == template["summary"]
    assert any("Fungicid" in s for s in gr["unsupported_sentences"])
    assert answer["rationale"] == ["Faza razvoja je BBCH 61."] and answer["generator"] == "anthropic"


# ------------------------------------------------------------------ T027 timing (SC-005)

def test_template_generation_is_fast():
    """SC-005: template generation < 50 ms per answer (median over the development scenarios and variants)."""
    cases = []
    for sc in load_scenarios("dev"):
        for v in load_variants().values():
            ctx = Context.from_dict(sc["context"])
            cases.append((ctx, decide(ctx, [], v)))
    times = []
    for ctx, d in cases:
        t0 = time.perf_counter()
        generate.template_answer(ctx, d, CORPUS)
        times.append(time.perf_counter() - t0)
    assert statistics.median(times) < 0.050, statistics.median(times)


def test_provider_generator_and_selection(monkeypatch):
    import json as _json
    from conftest import make_context
    from smartagri.config import load_variants
    from smartagri.core.decide import decide
    from smartagri.llm import LLMResponse, Provider
    from smartagri.pipeline import generate as g
    from smartagri.retrieval import load_corpus

    class Fake(Provider):
        name, model = "fake", "f1"

        def complete(self, system, messages, json_schema=None, max_tokens=4000):
            data = {"act": "recommend", "summary": "Navodnjavati u naredna dva dana.", "rationale": ["Faza razvoja je BBCH 61."]}
            return LLMResponse(_json.dumps(data), "fake", "f1", 10, 5, None, "end_turn", data)

    ctx = make_context()
    d = decide(ctx, [], load_variants()["V5"])
    answer, grounding, usage = g.ProviderGenerator(Fake()).generate(ctx, d, load_corpus())
    assert answer["summary"] == "Navodnjavati u naredna dva dana." and usage["llm_calls"] == 1
    assert answer["act"] == d.policy.act.value                      # the model never changes the act

    import smartagri.llm as llm
    monkeypatch.setattr(llm, "make_provider", lambda *a, **k: Fake())
    monkeypatch.setenv("LLM_PROVIDER", "claude-cli")
    monkeypatch.delenv("ADVICE_GENERATOR", raising=False)
    assert isinstance(g.make_generator(), g.TemplateGenerator)      # chat model alone does not change the advice
    monkeypatch.setenv("ADVICE_GENERATOR", "llm")
    assert isinstance(g.make_generator(), g.ProviderGenerator)
    monkeypatch.setenv("ADVICE_GENERATOR", "template")
    assert isinstance(g.make_generator(), g.TemplateGenerator)
