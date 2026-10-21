"""Spec 004 T021: LLM entailment judge plugged into the support check. No network, no key:
the Anthropic client is faked and ClaudeJudge is built without importing the SDK."""
import json

from conftest import make_context
from smartagri.config import load_variants
from smartagri.core.decide import decide
from smartagri.core.grounding import support_check
from smartagri.pipeline import generate, judge as judge_mod
from smartagri.pipeline.run import advise
from smartagri.retrieval import Retriever, load_corpus

SENTENCE = "Kukuruz je najosetljiviji na sušu u fazi svilanja."
SOURCE = "U fazi svilanja kukuruz je najosetljiviji na nedostatak vode i sušu."


class FakeAPIError(Exception):
    pass


def _response(text=None, stop_reason="end_turn"):
    class Block:
        type = "text"

    Block.text = text

    class Resp:
        content = [Block()]
        usage = type("U", (), {"input_tokens": 5, "output_tokens": 3})()

    Resp.stop_reason = stop_reason
    return Resp()


def fake_judge(reply=None, stop_reason="end_turn", raises=None):
    calls = []

    def create(**kwargs):
        calls.append(kwargs)
        if raises is not None:
            raise raises
        return _response(reply, stop_reason)

    j = judge_mod.ClaudeJudge.__new__(judge_mod.ClaudeJudge)
    j._anthropic = type("A", (), {"APIError": FakeAPIError})
    j.client = type("C", (), {"beta": type("B", (), {"messages": type("M", (), {"create": staticmethod(create)})()})()})()
    j.model, j.usage, j.fallbacks, j._cache = "fake-judge", {"llm_calls": 0, "input_tokens": 0, "output_tokens": 0}, 0, {}
    return j, calls


def _lexical(sentence, source):
    return support_check([sentence], [source])[0]["score"]


def test_judge_returns_the_model_score_and_requests_low_effort_structured_output():
    j, calls = fake_judge(json.dumps({"supported": True, "score": 0.83}))
    assert j(SENTENCE, SOURCE) == 0.83
    kw = calls[0]
    assert kw["output_config"]["effort"] == "low"
    assert kw["output_config"]["format"]["schema"] == judge_mod.JUDGE_SCHEMA
    assert kw["betas"] == ["server-side-fallback-2026-07-01"] and kw["fallbacks"] == "default"
    assert kw["system"] == judge_mod.JUDGE_PROMPT
    j(SENTENCE, SOURCE)
    assert len(calls) == 1 and j.usage["llm_calls"] == 1                     # cached per pair
    verdict = support_check([SENTENCE], [SOURCE], judge=j)[0]
    assert verdict["score"] == 0.83 and verdict["supported"]


def test_score_is_clamped_to_the_unit_interval():
    j, _ = fake_judge(json.dumps({"supported": True, "score": 7}))
    assert j(SENTENCE, SOURCE) == 1.0


def test_api_error_falls_back_to_the_lexical_score():
    j, _ = fake_judge(raises=FakeAPIError("overloaded"))
    assert j(SENTENCE, SOURCE) is None and j.fallbacks == 1
    assert support_check([SENTENCE], [SOURCE], judge=j)[0]["score"] == _lexical(SENTENCE, SOURCE)


def test_refusal_and_unparseable_output_fall_back_to_the_lexical_score():
    for j, _ in (fake_judge(stop_reason="refusal"), fake_judge(stop_reason="max_tokens"), fake_judge("not json")):
        assert j(SENTENCE, SOURCE) is None
        assert support_check([SENTENCE], [SOURCE], judge=j)[0]["score"] == _lexical(SENTENCE, SOURCE)


def test_judge_is_off_by_default(monkeypatch):
    monkeypatch.delenv("GROUNDING_JUDGE", raising=False)
    assert judge_mod.make_judge() is None
    monkeypatch.setenv("GROUNDING_JUDGE", "lexical")
    assert judge_mod.make_judge() is None


def _generator(j):
    body = json.dumps({"act": "recommend", "summary": "Navodnjavati u naredna dva dana.",
                       "rationale": ["Faza razvoja je BBCH 61."]})
    g = generate.AnthropicGenerator.__new__(generate.AnthropicGenerator)
    g.model, g._anthropic, g.judge = "fake", type("A", (), {"APIError": FakeAPIError}), j
    g.client = type("C", (), {"beta": type("B", (), {"messages": type("M", (), {
        "create": staticmethod(lambda **k: _response(body))})()})()})()
    return g


def test_generator_passes_the_judge_and_counts_its_calls():
    j, calls = fake_judge(json.dumps({"supported": False, "score": 0.1}))
    ctx = make_context()
    d = decide(ctx, [], load_variants()["V5"])
    answer, gr, usage = _generator(j).generate(ctx, d, load_corpus(), grounding_check=True)
    assert gr["judge"] == "llm" and calls                                    # the judge was consulted
    assert gr["action"] == "summary_replaced_by_template"                    # judge said: not supported
    assert usage["llm_calls"] == 1 + len(calls)


def test_provenance_records_the_judge_prompt_hash_only_when_used():
    corpus = load_corpus()
    variant = load_variants()["V5"]
    ctx = make_context()
    ctx.Q.text = "Da li sutra da navodnjavam kukuruz?"
    j, _ = fake_judge(json.dumps({"supported": True, "score": 0.9}))
    out = advise(ctx, corpus, Retriever(corpus.passages), variant, _generator(j))
    assert out["provenance"]["judge_prompt_hash"] == judge_mod.JUDGE_PROMPT_HASH
    assert len(judge_mod.JUDGE_PROMPT_HASH) == 64
    ctx = make_context()
    ctx.Q.text = "Da li sutra da navodnjavam kukuruz?"
    out = advise(ctx, corpus, Retriever(corpus.passages), variant, generate.TemplateGenerator())
    assert out["provenance"]["judge_prompt_hash"] is None
