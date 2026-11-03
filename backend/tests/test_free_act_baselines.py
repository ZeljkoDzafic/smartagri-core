"""V0-V3 are "an LLM with the data its rung allows": the model chooses the act, and the decision core's conclusion is
never part of what it receives.

The core still decides for V4 and V5 (their fact sheet, prompt and answers are unchanged). For V0-V3 the fact sheet holds
the question, the parcel data (ungraded below the q layer), the data statements without the core's conclusions, the
limitations, the retrieved passages with the applicability the rung computes, and the calculation tools' outputs; it
holds no act, no action, no timing. The model states its act in a parseable field; an output without a valid act is an
error item, never a default. A template answer for V0-V3 is labelled "template, not a baseline" everywhere. All model
calls here are fakes: no network, no key.
"""
import json

import pytest
import yaml

from smartagri import labels
from smartagri.config import load_variants
from smartagri.core.types import Context
from smartagri.evalkit import report as rep
from smartagri.evalkit.__main__ import main as cli
from smartagri.evalkit.runner import run_scenario
from smartagri.evalkit.scenarios import load_scenarios
from smartagri.llm.base import LLMResponse, ModelCallError, Provider
from smartagri.pipeline import generate as g
from smartagri.pipeline.run import advise
from smartagri.retrieval import Retriever, load_corpus

CORPUS = load_corpus()
RETRIEVER = Retriever(CORPUS.passages)
FREE = ("V0", "V1", "V2", "V3")
CORE = ("V4", "V5")
FREE_KEYS = {"question", "advice_type", "facts", "data", "limitations", "sources", "calculations"}
FORBIDDEN_KEYS = {"act", "act_is_free", "action", "next_question", "what", "when_or_condition", "quantity"}


def _body(act="recommend", question="", summary="Odgovor.", rationale=("x",)):
    return json.dumps({"act": act, "summary": summary, "rationale": list(rationale), "question_to_user": question})


class Recorder(Provider):
    """A provider that records what it was given and answers with a fixed body."""
    name, model = "rec", "rec-model-1"

    def __init__(self, body=None):
        self.body, self.calls = body if body is not None else _body(), []

    def complete(self, system, messages, json_schema=None, max_tokens=4000):
        self.calls.append({"system": system, "payload": json.loads(messages[0]["content"]), "schema": json_schema,
                           "raw": messages[0]["content"]})
        return LLMResponse(self.body, "rec", "rec-model-1", 3, 2, None, "end_turn", request_id="r-1")


def _run(variant, scenario, provider, strict=True):
    sc = yaml.safe_load(open(scenario_path(scenario), encoding="utf-8").read()) if isinstance(scenario, str) else scenario
    return run_scenario(sc, variant, CORPUS, RETRIEVER, g.ProviderGenerator(provider, strict=strict))


def scenario_path(stem):
    from smartagri.evalkit.scenarios import scenario_dir
    return scenario_dir("dev") / (stem + ".yaml")


def _dev_scenarios():
    return load_scenarios("dev")


def _first_payload(variant, sc):
    rec = Recorder()
    ctx = Context.from_dict(sc["context"])
    advise(ctx, CORPUS, RETRIEVER, load_variants()[variant], g.ProviderGenerator(rec, strict=True))
    return rec.calls[0]


# ---------------------------------------------------------------- the fact sheet of V0-V3 holds no conclusion of the core

@pytest.mark.parametrize("variant", FREE)
def test_free_variants_get_no_act_action_or_timing_in_any_dev_scenario(variant):
    for sc in _dev_scenarios():
        call = _first_payload(variant, sc)
        payload = call["payload"]
        assert set(payload) == FREE_KEYS, (sc["id"], variant, set(payload) ^ FREE_KEYS)
        assert not (set(payload) & FORBIDDEN_KEYS)
        # no field of the payload, at any depth, is named like a conclusion of the core
        def keys(o):
            if isinstance(o, dict):
                for k, v in o.items():
                    yield k
                    yield from keys(v)
            elif isinstance(o, list):
                for v in o:
                    yield from keys(v)
        assert not ({"act", "act_is_free", "action", "what", "when_or_condition", "core_action"} & set(keys(payload)))


@pytest.mark.parametrize("variant", FREE)
def test_the_text_of_the_cores_action_is_not_in_the_fact_sheet(variant):
    """The phrases of the core's action (labels.CORE_ACTIONS) and the dose-band sentence never reach V0-V3."""
    phrases = {p for pair in labels.CORE_ACTIONS.values() for p in pair if p}
    for sc in _dev_scenarios():
        raw = _first_payload(variant, sc)["raw"]
        leaked = [p for p in phrases if p in raw]
        assert not leaked, (sc["id"], variant, leaked)
        assert "opseg doze niži" not in raw and "Zbog preduseva" not in raw and "Zbog stajnjaka" not in raw


def test_the_dose_band_statement_is_a_conclusion_and_stays_out_of_free_facts():
    from smartagri.core.decide import decide as dec
    sc = next(s for s in _dev_scenarios() if s["id"].startswith("FER-12"))
    ctx = Context.from_dict(sc["context"])
    ctx.A.previous_crop, ctx.A.manure = "soybean", True
    d = dec(ctx, [], load_variants()["V3"])
    with_c, without_c = g.rationale(ctx, d), g.rationale(ctx, d, conclusions=False)
    assert set(without_c) <= set(with_c)
    if "|dose:" in (d.core_action or "") and not d.core_action.endswith("dose:?"):
        assert any("opseg doze" in x for x in with_c) and not any("opseg doze" in x for x in without_c)


def test_the_free_prompt_does_not_mention_a_core_and_asks_for_the_act():
    p = g.SYSTEM_PROMPT_FREE
    assert "decided by the core" not in p and "act_is_free" not in p and "rule-based" not in p
    assert '"act"' in p and all(a in p for a in g.ACT_VALUES)
    assert g.ANSWER_SCHEMA_FREE["properties"]["act"]["enum"] == list(g.ACT_VALUES)
    assert "act" in g.ANSWER_SCHEMA_FREE["required"] and g.ANSWER_SCHEMA_FREE["additionalProperties"] is False
    for variant in FREE:
        call = _first_payload(variant, _dev_scenarios()[0])
        assert call["system"] == g.system_prompt(free=True) and call["schema"] == g.ANSWER_SCHEMA_FREE


@pytest.mark.parametrize("variant", CORE)
def test_the_core_variants_get_the_same_fact_sheet_prompt_and_schema_as_before(variant):
    """V4 and V5: byte-identical payload construction, prompt and schema (the act and the action are the core's)."""
    for sc in _dev_scenarios():
        ctx = Context.from_dict(sc["context"])
        rec = Recorder()
        advise(ctx, CORPUS, RETRIEVER, load_variants()[variant], g.ProviderGenerator(rec, strict=True))
        call = rec.calls[0]
        assert call["system"] == g.SYSTEM_PROMPT and call["schema"] == g.ANSWER_SCHEMA
        assert list(call["payload"]) == ["question", "advice_type", "act", "act_is_free", "action", "facts", "data",
                                         "limitations", "next_question", "sources", "calculations"]
        # the only core turn without an act of the core is an out-of-scope question in V4 (no policy layer): as before,
        # it keeps the old prompt and the old flag
        out_of_scope = sc["context"]["Q"]["advice_type"] == "out_of_scope" and variant == "V4"
        assert call["payload"]["act_is_free"] is out_of_scope and call["payload"]["act"] in g.ACT_VALUES
    assert g.PROMPT_HASH == "f094d3bf7fd646eed2e1b5d88f233da287e0e008438c941c41d4830a59fea23f"   # unchanged by this change


# ---------------------------------------------------------------- what each rung sees

def _scenario(stem):
    return yaml.safe_load(open(scenario_path(stem), encoding="utf-8").read())


def test_the_rungs_see_what_the_ladder_allows():
    sc = _scenario("IRR-T-01_complete")
    p = {v: _first_payload(v, sc)["payload"] for v in FREE}
    # V0: static profile only, no retrieval; no weather, no NDVI
    assert p["V0"]["sources"] == []
    assert not any("padavin" in f or "evapotranspir" in f for f in p["V0"]["facts"])
    assert p["V0"]["calculations"] == []                       # the tools need the weather summary W
    # V1, V2: retrieved passages, still no W or S
    for v in ("V1", "V2"):
        assert p[v]["sources"], v
        assert not any("padavin" in f for f in p[v]["facts"]) and p[v]["calculations"] == [], v
    # V1: pi is off, so every passage carries the same "applicable" label (a plain RAG baseline)
    assert {s["applicability"] for s in p["V1"]["sources"]} == {labels.APPLICABILITY["applicable"]}
    # V3: weather becomes visible, and the tools' numbers with it
    assert any("padavin" in f for f in p["V3"]["facts"])
    assert any(c["tool"] == "etc" for c in p["V3"]["calculations"])
    # no rung below V4 grades an input
    for v in FREE:
        assert all(row.get("reliability") in (None, "missing") for row in p[v]["data"]), v      # present inputs: ungraded
    # V4 grades them and still sees the same tools
    p4 = _first_payload("V4", sc)["payload"]
    assert any(row.get("reliability") in ("high", "medium", "low") for row in p4["data"])


def test_numbers_from_code_stay_available_to_the_rungs_that_have_the_inputs():
    sc = _scenario("IRR-T-01_complete")
    p3 = _first_payload("V3", sc)["payload"]
    tools = {c["tool"]: c for c in p3["calculations"]}
    # ETc is not an irrigation quantity; net and gross depth follow rules.irrigation.quantity_validated (closed by
    # default, see tests/test_quantity_gate.py) exactly as for V4 and V5
    assert "etc" in set(tools) and tools["etc"]["output"] and not ({"net_irrigation_need", "gross_irrigation"} & set(tools))
    for c in p3["calculations"]:
        assert c["output"] and set(c) >= {"tool", "label", "formula", "inputs", "output", "source_ref", "reason"}
    # the answer of V3 never carries the core's action, whatever the model returns
    out = _run("V3", sc, Recorder(_body("recommend")))
    assert out["turns"][0]["answer"]["action"] is None and out["turns"][0]["answer"]["act_origin"] == "model"


# ---------------------------------------------------------------- the act contract

@pytest.mark.parametrize("act", g.ACT_VALUES)
def test_the_model_chooses_the_act_and_it_is_recorded(act):
    sc = _scenario("IRR-T-02_missing_soil_water")
    question = "Kakvo je stanje vlage u zemljištu?" if act in ("ask", "conditional") else ""
    out = _run("V2", sc, Recorder(_body(act, question)))
    first = out["turns"][0]["answer"]
    assert first["act"] == act and first["act_label"] == labels.ACTS[act] and out["first_act"] == act
    assert first["act_origin"] == "model" and "baseline_label" not in first
    assert out["baseline"] == {"act_chosen_by": "model", "label": None}


@pytest.mark.parametrize("body", [
    '{"summary": "S.", "rationale": ["x"], "question_to_user": ""}',                                  # no act
    '{"act": "", "summary": "S.", "rationale": ["x"], "question_to_user": ""}',                        # empty act
    '{"act": "maybe", "summary": "S.", "rationale": ["x"], "question_to_user": ""}',                   # not one of the four
    '{"act": "Recommend", "summary": "S.", "rationale": ["x"], "question_to_user": ""}',               # not exactly
    '{"act": null, "summary": "S.", "rationale": ["x"], "question_to_user": ""}',
    '{"act": "recommend", "summary": "", "rationale": ["x"], "question_to_user": ""}',                 # no text
    '{"act": "recommend", "summary": "S.", "rationale": "x", "question_to_user": ""}',                 # not a list
])
def test_an_output_without_a_valid_act_is_an_error_not_a_default(body):
    sc = _scenario("IRR-T-02_missing_soil_water")
    with pytest.raises(ModelCallError):
        _run("V1", sc, Recorder(body), strict=True)


def test_in_the_evaluation_such_an_item_is_stored_as_an_error_and_the_run_exits_non_zero(monkeypatch, tmp_path, capsys):
    from smartagri.evalkit import runner
    monkeypatch.setenv("LLM_PROVIDER", "template")
    monkeypatch.setenv("EMBEDDINGS_PROVIDER", "none")
    monkeypatch.setenv("SMARTAGRI_DB", str(tmp_path / "e.sqlite"))
    monkeypatch.setattr(runner, "make_generator",
                        lambda **k: g.ProviderGenerator(Recorder('{"act": "maybe", "summary": "S.", "rationale": []}'), strict=True))
    assert cli(["run", "--set", "dev", "--variant", "V3"]) == 1
    from smartagri.store import make_store
    items = make_store().list_eval_items()
    assert items and all(i.get("error") and i["rateable"] is False and i["first_act"] is None for i in items)
    assert rep.automatic(items) == {}                         # error items are left out of every measure


def test_interactive_use_falls_back_to_the_labelled_template_and_says_so():
    sc = _scenario("IRR-T-02_missing_soil_water")
    out = _run("V1", sc, Recorder('{"act": "maybe", "summary": "S.", "rationale": ["x"]}'), strict=False)
    a = out["turns"][0]["answer"]
    assert a["generator"] == "template" and a["baseline_label"] == g.TEMPLATE_LABEL
    assert out["turns"][0] and out["records"][0]["decisions"]["grounding"]["action"] == "template_after_invalid_act"
    assert out["baseline"] == {"act_chosen_by": "template", "label": g.TEMPLATE_LABEL}


def test_the_prompt_hash_of_a_run_names_the_prompt_that_was_used():
    sc = _scenario("IRR-T-01_complete")
    ctx = Context.from_dict(sc["context"])
    v = load_variants()
    free = advise(ctx, CORPUS, RETRIEVER, v["V3"], g.ProviderGenerator(Recorder(), strict=True))
    core = advise(Context.from_dict(sc["context"]), CORPUS, RETRIEVER, v["V4"], g.ProviderGenerator(Recorder(), strict=True))
    assert free["provenance"]["prompt_hash"] == g.FREE_PROMPT_HASH and core["provenance"]["prompt_hash"] == g.PROMPT_HASH
    assert g.FREE_PROMPT_HASH != g.PROMPT_HASH


def test_the_free_prompt_is_part_of_the_protocol_lock():
    from smartagri.evalkit.__main__ import _lock_inputs
    files, prompt = _lock_inputs("dev")
    assert files["prompt/generator_free_act"] == g.FREE_PROMPT_HASH and prompt == g.PROMPT_HASH


# ---------------------------------------------------------------- the template is not a baseline

@pytest.mark.parametrize("variant", FREE)
def test_template_answers_of_the_free_variants_carry_the_label(variant):
    for sc in _dev_scenarios():
        out = run_scenario(sc, variant, CORPUS, RETRIEVER, g.TemplateGenerator())
        assert out["baseline"] == {"act_chosen_by": "template", "label": "template, not a baseline"}
        assert all(t["answer"]["baseline_label"] == "template, not a baseline" and t["answer"]["generator"] == "template"
                   for t in out["turns"])


@pytest.mark.parametrize("variant", CORE)
def test_core_variants_carry_no_label_and_no_new_field(variant):
    for sc in _dev_scenarios():
        out = run_scenario(sc, variant, CORPUS, RETRIEVER, g.TemplateGenerator())
        assert "baseline" not in out
        assert all("baseline_label" not in t["answer"] and "act_origin" not in t["answer"] for t in out["turns"])


def test_report_and_overview_show_the_label_and_never_a_silent_baseline(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("LLM_PROVIDER", "template")
    monkeypatch.setenv("EMBEDDINGS_PROVIDER", "none")
    monkeypatch.setenv("SMARTAGRI_DB", str(tmp_path / "e.sqlite"))
    assert cli(["run", "--set", "dev"]) == 0                  # the dev-set check with the template still works
    captured = capsys.readouterr()
    assert captured.out.count('"label": "template, not a baseline"') == 4        # one batch summary per V0-V3
    assert captured.err.count("not a result of that rung") == 4
    from smartagri.store import make_store
    store = make_store()
    items = store.list_eval_items()
    auto = rep.automatic(items)
    assert {v for v in auto if auto[v].get("baseline_label")} == set(FREE)
    assert not any("baseline_label" in auto[v] for v in CORE)
    assert cli(["report", "--set", "dev", "--format", "md"]) == 0
    md = capsys.readouterr().out
    assert "template, not a baseline" in md and "V0, V1, V2, V3" in md
    assert all("%s (template, not a baseline)" % v in md for v in FREE)
    assert "V4 (template" not in md and "V5 (template" not in md
    assert cli(["report", "--set", "dev"]) == 0
    assert json.loads(capsys.readouterr().out)["automatic"]["V0"]["baseline_label"] == "template, not a baseline"
    from smartagri.research_api import views
    sets = views.eval_overview(store)["sets"]
    s = next(x for x in sets if x["set"] == "dev")
    assert s["template_variants"] == list(FREE) and s["template_label"] == "template, not a baseline"
    assert "template, not a baseline" in s["report_md"]


def test_a_run_with_a_model_has_no_template_label(monkeypatch, tmp_path, capsys):
    from smartagri.evalkit import runner
    monkeypatch.setenv("LLM_PROVIDER", "template")
    monkeypatch.setenv("EMBEDDINGS_PROVIDER", "none")
    monkeypatch.setenv("SMARTAGRI_DB", str(tmp_path / "e.sqlite"))
    monkeypatch.setattr(runner, "make_generator", lambda **k: g.ProviderGenerator(Recorder(), strict=True))
    assert cli(["run", "--set", "dev", "--variant", "V1"]) == 0
    from smartagri.store import make_store
    items = make_store().list_eval_items()
    assert items and all(i["baseline"] == {"act_chosen_by": "model", "label": None} for i in items)
    assert "baseline_label" not in rep.automatic(items)["V1"]
    out = capsys.readouterr()
    assert "template, not a baseline" not in out.out + out.err


# ---------------------------------------------------------------- the decision of the core is untouched

def test_the_cores_decision_for_every_variant_is_unchanged_by_the_generator_change():
    """The change is in what the generator is given: decide() output is identical to the golden digests."""
    from golden_dev import digest
    assert digest.compute() == digest.load()["items"]
