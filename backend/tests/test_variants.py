import json
import re
from pathlib import Path

from conftest import make_context
from smartagri import config
from smartagri.core.decide import decide

CORE = Path(__file__).resolve().parents[1] / "src" / "smartagri" / "core"


def test_core_never_branches_on_a_variant_name():
    for path in CORE.rglob("*.py"):
        assert not re.search(r"""["']V[0-5]["']""", path.read_text(encoding="utf-8")), path


def test_each_step_of_the_ladder_adds_exactly_one_layer(variants):
    flags = ["retrieval", "applicability", "dynamic_context", "quality", "sufficiency", "asking", "policy", "grounding"]
    names = ["V0", "V1", "V2", "V3", "V4", "V5"]
    changed = [{f for f in flags if getattr(variants[a], f) != getattr(variants[b], f)} for a, b in zip(names, names[1:])]
    assert changed[0] == {"retrieval"}
    assert changed[1] == {"applicability"}
    assert changed[2] == {"applicability", "dynamic_context"}          # conditions now come from the parcel
    assert changed[3] == {"quality", "sufficiency", "asking"}           # the layer tested by E1
    assert changed[4] == {"policy", "grounding"}                        # the layer tested by E3


def test_decision_is_deterministic_and_serialisable(variants):
    ctx = make_context(agronomic={"soil_water_status": None})
    a = decide(ctx, [], variants["V5"]).to_dict()
    b = decide(ctx, [], variants["V5"]).to_dict()
    assert a == b
    assert json.loads(json.dumps(a))["config_hashes"].keys() == set(config.CONFIG_FILES)


def test_dynamic_context_flag_matches_the_applicability_mode(variants):
    """dynamic_context documents the ladder; the code realises it through the pi mode."""
    for v in variants.values():
        assert v.dynamic_context == (v.applicability == "parcel_conditions"), v.name


def test_grounding_flag_controls_the_numeric_check(monkeypatch):
    from smartagri.pipeline import generate

    class FakeBlock:
        type, text = "text", '{"act": "recommend", "summary": "Dajte 40 mm vode.", "rationale": ["x"]}'

    class FakeResponse:
        stop_reason, content = "end_turn", [FakeBlock()]
        usage = type("U", (), {"input_tokens": 1, "output_tokens": 1})()

    g = generate.AnthropicGenerator.__new__(generate.AnthropicGenerator)
    g.model, g._anthropic = "fake", type("A", (), {"APIError": Exception})
    g.client = type("C", (), {"beta": type("B", (), {"messages": type("M", (), {"create": staticmethod(lambda **k: FakeResponse())})()})()})()
    from conftest import make_context
    from smartagri.core.decide import decide
    from smartagri.config import load_variants
    from smartagri.retrieval import load_corpus
    ctx = make_context()
    d = decide(ctx, [], load_variants()["V5"])
    checked, gr, _ = g.generate(ctx, d, load_corpus(), grounding_check=True)
    unchecked, gr2, _ = g.generate(ctx, d, load_corpus(), grounding_check=False)
    assert gr["action"] == "replaced_by_template" and 40.0 in gr["unsupported_numbers"]
    assert gr2["action"] == "not_checked" and unchecked["summary"] == "Dajte 40 mm vode."


def test_support_check_drops_unsupported_sentences(monkeypatch):
    from smartagri.pipeline import generate
    from conftest import make_context
    from smartagri.core.decide import decide
    from smartagri.config import load_variants
    from smartagri.retrieval import load_corpus
    body = ('{"act": "recommend", "summary": "Navodnjavati u naredna dva dana.", "rationale": '
            '["Faza razvoja je BBCH 61.", "Fungicid treba primeniti odmah zbog pegavosti lista kukuruza."]}')

    class Block:
        type, text = "text", body

    class Resp:
        stop_reason, content = "end_turn", [Block()]
        usage = type("U", (), {"input_tokens": 1, "output_tokens": 1})()

    g = generate.AnthropicGenerator.__new__(generate.AnthropicGenerator)
    g.model, g._anthropic = "fake", type("A", (), {"APIError": Exception})
    g.client = type("C", (), {"beta": type("B", (), {"messages": type("M", (), {"create": staticmethod(lambda **k: Resp())})()})()})()
    ctx = make_context()
    d = decide(ctx, [], load_variants()["V5"])
    answer, gr, _ = g.generate(ctx, d, load_corpus(), grounding_check=True)
    assert gr["action"] == "checked" and answer["summary"] == "Navodnjavati u naredna dva dana."
    assert any("Fungicid" in s for s in gr["unsupported_sentences"])
    assert all("Fungicid" not in s for s in answer["rationale"])


# ---------------------------------------------------------------- E4 context ablations (spec 007 T010)

def test_context_ablations_are_config_flags_on_top_of_v5(variants):
    flags = ["retrieval", "applicability", "dynamic_context", "quality", "sufficiency", "asking", "policy", "grounding"]
    for name, dropped in (("V5-weather", "use_weather"), ("V5-satellite", "use_satellite")):
        v = variants[name]
        assert all(getattr(v, f) == getattr(variants["V5"], f) for f in flags), name
        assert getattr(v, dropped) is False
        assert all(getattr(v, f) is True for f in ("use_weather", "use_satellite") if f != dropped)
    for name in ("V0", "V1", "V2", "V3", "V4", "V5"):
        assert variants[name].use_weather and variants[name].use_satellite


def test_pipeline_never_branches_on_a_variant_name():
    pipeline = CORE.parent / "pipeline"
    for path in pipeline.rglob("*.py"):
        assert not re.search(r"""["']V[0-5][^"']*["']""", path.read_text(encoding="utf-8")), path


def test_ablation_removes_weather_or_satellite_before_deciding(variants):
    from smartagri.pipeline.generate import TemplateGenerator
    from smartagri.pipeline.run import ablate_context, advise
    from smartagri.retrieval import Retriever, load_corpus
    corpus = load_corpus()
    retriever = Retriever(corpus.passages)
    ndvi = [{"obs_date": "2026-07-10", "median": 0.8, "p10": 0.7, "p90": 0.85, "usable_share": 0.95}]
    ctx = make_context(ndvi=ndvi)
    ctx.Q.text = "Da li sutra da navodnjavam kukuruz?"

    assert ablate_context(ctx, variants["V5"]) is ctx
    no_w = ablate_context(ctx, variants["V5-weather"])
    assert no_w.W.precip_forecast_3d_mm is None and no_w.S is ctx.S and ctx.W.precip_forecast_3d_mm == 0.0
    no_s = ablate_context(ctx, variants["V5-satellite"])
    assert no_s.S.ndvi_series == [] and no_s.W is ctx.W and len(ctx.S.ndvi_series) == 1

    full = advise(ctx, corpus, retriever, variants["V5"], TemplateGenerator())
    w = advise(ctx, corpus, retriever, variants["V5-weather"], TemplateGenerator())
    s = advise(ctx, corpus, retriever, variants["V5-satellite"], TemplateGenerator())
    assert full["answer"]["act"] == "recommend"
    assert full["decisions"]["quality"]["precip_forecast_3d"]["reliability"] == "high"
    assert w["decisions"]["quality"]["precip_forecast_3d"]["reliability"] == "missing"
    assert w["answer"]["act"] != "recommend" and w["provenance"]["forecast_issued_at"] is None
    assert w["provenance"]["context_used"] == {"weather": False, "satellite": True}
    assert full["decisions"]["quality"]["ndvi_latest"]["reliability"] != "missing"
    assert s["decisions"]["quality"]["ndvi_latest"]["reliability"] == "missing"
    assert s["provenance"]["scene_dates"] == [] and s["answer"]["act"] == "recommend"   # NDVI is only desirable here
