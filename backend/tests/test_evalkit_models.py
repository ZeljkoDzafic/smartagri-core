"""An evaluation run never changes model silently and never falls back to the template.

config/evaluation.yaml pins the model (exact id), effort and output limit; the environment must agree with it; no
server-side fallback is sent; every failed or substituted model call becomes an error item and the run exits
non-zero. All model calls here are fakes: no network, no key."""
import json
import sys

import pytest

from conftest import make_context
from smartagri.config import load_variants
from smartagri.evalkit import settings as st
from smartagri.evalkit.__main__ import main as cli
from smartagri.llm.base import LLMError, LLMResponse, ModelCallError, Provider
from smartagri.pipeline import generate as g
from smartagri.retrieval import load_corpus


@pytest.fixture
def env(monkeypatch, tmp_path):
    for k in ("LLM_MODEL", "JUDGE_MODEL", "GROUNDING_JUDGE", "ADVICE_GENERATOR", "DATABASE_URL"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("LLM_PROVIDER", "template")
    monkeypatch.setenv("EMBEDDINGS_PROVIDER", "none")
    monkeypatch.setenv("SMARTAGRI_DB", str(tmp_path / "eval.sqlite"))
    return tmp_path


class APIError(Exception):
    pass


def _client(response=None, error=None, seen=None):
    def create(**kwargs):
        if seen is not None:
            seen.append(kwargs)
        if error:
            raise error
        return response
    return type("C", (), {"beta": type("B", (), {"messages": type("M", (), {"create": staticmethod(create)})()})()})()


def _response(model="claude-opus-5-5", stop="end_turn", body=None):
    body = body or '{"act": "recommend", "summary": "Navodnjavati.", "rationale": ["x"], "question_to_user": ""}'
    block = type("Block", (), {"type": "text", "text": body})()
    return type("R", (), {"stop_reason": stop, "content": [block], "model": model, "_request_id": "req_42",
                          "usage": type("U", (), {"input_tokens": 11, "output_tokens": 7})()})()


def _generator(client, strict=True, fallback=False):
    gen = g.AnthropicGenerator.__new__(g.AnthropicGenerator)
    gen.model, gen._anthropic, gen.judge, gen.client = "claude-opus-5-5", type("A", (), {"APIError": APIError}), None, client
    gen.strict, gen.server_fallback, gen.effort, gen.max_tokens = strict, fallback, "low", 16000
    return gen


def _decision(name="V3"):
    from smartagri.core.decide import decide
    ctx = make_context()
    return ctx, decide(ctx, [], load_variants()[name])


# ---------------------------------------------------------------- settings

def test_the_pinned_model_is_an_exact_id_and_aliases_are_refused(env, monkeypatch):
    cfg = st.load()
    assert st.is_exact_model_id(cfg["llm"]["model"]) and cfg["llm"]["server_fallback"] is False
    for alias in ("sonnet", "opus", "haiku", "", None, "mistral-small-latest", "llama3:latest"):
        assert not st.is_exact_model_id(alias), alias
    assert st.check(cfg, need_model=True) == []
    monkeypatch.setenv("LLM_MODEL", "sonnet")
    assert any("LLM_MODEL=sonnet differs" in p for p in st.check(cfg, need_model=True))
    monkeypatch.delenv("LLM_MODEL")
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    assert any("LLM_PROVIDER=openai differs" in p for p in st.check(cfg, need_model=True))
    bad = {"llm": dict(cfg["llm"], model="sonnet", server_fallback=True), "judge": cfg["judge"]}
    assert len(st.check(bad, need_model=False)) == 0 and len(st.check(bad, need_model=True)) >= 2


def test_cli_refuses_an_llm_run_whose_environment_differs_from_the_config(env, monkeypatch, capsys):
    monkeypatch.setenv("ADVICE_GENERATOR", "llm")
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("LLM_MODEL", "sonnet")
    assert cli(["run", "--set", "dev", "--variant", "V3"]) == 2
    assert "differs from config/evaluation.yaml" in capsys.readouterr().err


# ---------------------------------------------------------------- no silent template

def test_strict_generator_raises_when_the_package_is_missing(env, monkeypatch):
    monkeypatch.setenv("ADVICE_GENERATOR", "llm")
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    monkeypatch.setitem(sys.modules, "anthropic", None)          # import anthropic -> ImportError
    with pytest.raises(ModelCallError):
        g.make_generator(strict=True, settings=st.load())
    assert isinstance(g.make_generator(), g.TemplateGenerator)   # interactive use stays usable offline


def test_strict_generator_raises_for_an_unknown_provider(env, monkeypatch):
    monkeypatch.setenv("ADVICE_GENERATOR", "llm")
    monkeypatch.setenv("LLM_PROVIDER", "no-such-provider")
    with pytest.raises(ModelCallError):
        g.make_generator(strict=True, settings=st.load())
    assert isinstance(g.make_generator(), g.TemplateGenerator)


@pytest.mark.parametrize("client", [_client(error=APIError("down")), _client(_response(stop="refusal")),
                                    _client(_response(stop="max_tokens")), _client(_response(body="not json"))])
def test_a_failed_call_raises_in_strict_mode_and_is_marked_interactively(client):
    ctx, d = _decision()
    with pytest.raises(ModelCallError):
        _generator(client, strict=True).generate(ctx, d, load_corpus(), grounding_check=False)
    answer, grounding, _ = _generator(client, strict=False).generate(ctx, d, load_corpus(), grounding_check=False)
    assert grounding["action"].startswith("template_after_")


def test_an_answer_from_another_model_is_an_error():
    ctx, d = _decision()
    with pytest.raises(ModelCallError):
        _generator(_client(_response(model="claude-opus-5")), strict=True).generate(ctx, d, load_corpus())


def test_no_server_side_fallback_and_the_actual_model_is_recorded():
    from smartagri.pipeline.run import advise
    from smartagri.retrieval import Retriever
    seen = []
    gen = _generator(_client(_response(), seen=seen), strict=True, fallback=False)
    corpus = load_corpus()
    ctx = make_context()
    ctx.Q.text = "Da li sutra da navodnjavam kukuruz?"
    out = advise(ctx, corpus, Retriever(corpus.passages), load_variants()["V3"], gen)
    assert "fallbacks" not in seen[0] and "betas" not in seen[0] and seen[0]["model"] == "claude-opus-5-5"
    assert seen[0]["max_tokens"] == 16000 and seen[0]["output_config"]["effort"] == "low"
    call = out["provenance"]["llm_call"]
    assert call == {"provider": "anthropic", "model_requested": "claude-opus-5-5", "model": "claude-opus-5-5",
                    "request_id": "req_42", "input_tokens": 11, "output_tokens": 7}
    seen.clear()
    _generator(_client(_response(), seen=seen), strict=False, fallback=True).generate(*_decision(), load_corpus())
    assert seen[0]["fallbacks"] == "default"                       # interactive use keeps the fallback


class FakeProvider(Provider):
    name, model = "fake", "fake-model-1"

    def __init__(self, answer_model="fake-model-1", fail=False):
        self.answer_model, self.fail = answer_model, fail

    def complete(self, system, messages, json_schema=None, max_tokens=4000):
        if self.fail:
            raise LLMError("fake: down")
        body = '{"act": "recommend", "summary": "S.", "rationale": ["x"], "question_to_user": ""}'
        return LLMResponse(body, "fake", self.answer_model, 3, 2, None, "end_turn", request_id="r-1")


def test_provider_generator_is_strict_too():
    ctx, d = _decision()
    with pytest.raises(ModelCallError):
        g.ProviderGenerator(FakeProvider(fail=True), strict=True).generate(ctx, d, load_corpus(), grounding_check=False)
    with pytest.raises(ModelCallError):
        g.ProviderGenerator(FakeProvider(answer_model="other"), strict=True).generate(ctx, d, load_corpus())
    gen = g.ProviderGenerator(FakeProvider(), strict=True)
    gen.generate(ctx, d, load_corpus(), grounding_check=False)
    assert gen.last_call["model"] == "fake-model-1" and gen.last_call["request_id"] == "r-1"


# ---------------------------------------------------------------- the run fails loudly

def test_failed_items_are_stored_as_errors_and_the_run_exits_non_zero(env, monkeypatch, capsys):
    from smartagri.evalkit import runner
    from smartagri.store import make_store
    monkeypatch.setattr(runner, "make_generator",
                        lambda **k: g.ProviderGenerator(FakeProvider(fail=True), strict=True))
    assert cli(["run", "--set", "dev", "--variant", "V3"]) == 1
    batch = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert batch["failed"] > 0 and batch["n"] == 0
    items = make_store().list_eval_items()
    assert items and all(i["error"] and i["rateable"] is False and i["turns"] == [] for i in items)
    assert all(i["generation"]["generator"] == "fake" for i in items)


def test_a_template_run_records_how_it_was_generated(env, capsys):
    from smartagri.store import make_store
    assert cli(["run", "--set", "dev", "--variant", "V4"]) == 0
    item = make_store().list_eval_items()[0]
    assert item["generation"]["generator"] == "template" and item["generation"]["model"] is None
    assert item["models_used"] == [] and item["request_ids"] == []


# ---------------------------------------------------------------- providers

def test_anthropic_provider_without_server_fallback_reports_the_request_id(monkeypatch):
    import types
    fake = types.ModuleType("anthropic")                 # the SDK is an optional extra: a stand-in module, no network
    fake.APIError = APIError
    monkeypatch.setitem(sys.modules, "anthropic", fake)
    from smartagri.llm.anthropic_provider import AnthropicProvider
    seen = []
    p = AnthropicProvider(model="claude-opus-5-5", client=_client(_response(), seen=seen), server_fallback=False,
                          effort="low")
    r = p.complete("s", [{"role": "user", "content": "x"}])
    assert "fallbacks" not in seen[0] and r.request_id == "req_42" and r.model == "claude-opus-5-5"


def test_claude_cli_default_model_is_an_exact_id(monkeypatch):
    from smartagri.llm.claude_cli import ClaudeCliProvider
    for k in ("CLAUDE_CLI_MODEL", "LLM_MODEL"):
        monkeypatch.delenv(k, raising=False)
    assert st.is_exact_model_id(ClaudeCliProvider(runner=lambda *a, **k: None).model)


def test_vc_provider_is_refused_with_an_alias(env, monkeypatch):
    from smartagri.evalkit import vc
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("LLM_MODEL", "opus")
    with pytest.raises(vc.Unavailable):
        vc.provider_or_refuse()
