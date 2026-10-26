"""Spec 057: the minimal research API of the open-core research repository (core path only, no accounts)."""
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from smartagri.providers import weather
from smartagri.research_api.app import create_app
from smartagri.research_api.service import ResearchService

SQUARE = {"type": "Polygon", "coordinates": [[[17.300, 44.900], [17.302, 44.900], [17.302, 44.902], [17.300, 44.902],
                                              [17.300, 44.900]]]}


def _fake_weather(store, lat, lon, as_of, refresh=False):
    days = [(as_of + timedelta(days=o)).date().isoformat() for o in range(-92, 7)]
    n = len(days)
    return {"raw": {"daily": {"time": days, "precipitation_sum": [0.5] * n, "et0_fao_evapotranspiration": [5.0] * n,
                              "temperature_2m_min": [15.0] * n, "temperature_2m_max": [29.0] * n,
                              "wind_speed_10m_max": [3.0] * n}},
            "fetched_at": as_of.isoformat(), "request_hash": "test"}


@pytest.fixture
def client(monkeypatch, store):
    monkeypatch.delenv("CDSE_CLIENT_ID", raising=False)
    monkeypatch.setenv("LLM_PROVIDER", "template")
    monkeypatch.setenv("EMBEDDINGS_PROVIDER", "none")
    monkeypatch.setattr(weather, "fetch", _fake_weather)
    return TestClient(create_app(ResearchService(store)))


def _parcel(client):
    sowing = (datetime.now() - timedelta(days=78)).date().isoformat()
    r = client.post("/api/parcels", json={"name": "Njiva", "geometry": SQUARE, "sowing_date": sowing,
                                          "irrigation_available": "yes", "irrigation_system_type": "sprinkler",
                                          "soil_texture": "loam"})
    assert r.status_code == 201, r.text
    return r.json()


def test_health_meta_and_client_page(client):
    h = client.get("/api/health").json()
    assert h["status"] == "ok" and h["llm"] == "template" and h["satellite"] == "disabled"
    m = client.get("/api/meta").json()
    assert m["default_variant"] == "V5" and {"V0", "V5"} <= set(m["variants"]) and len(m["advice_types"]) == 5
    assert "SmartAgri" in client.get("/").text


def test_parcel_profile_chat_and_provenance(client):
    p = _parcel(client)
    assert p["region_class"] == "pannonian" and client.get("/api/parcels").json()[0]["id"] == p["id"]
    assert client.get("/api/parcels/%s/profile" % p["id"]).status_code == 404
    prof = client.post("/api/parcels/%s/profile/refresh" % p["id"]).json()
    assert prof["weather"]["status"] == "ok" and prof["quality"]
    run = client.post("/api/parcels/%s/chat" % p["id"],
                      json={"text": "Da li da navodnjavam kukuruz?", "advice_type": "irrigation_timing"}).json()
    a = run["answer"]
    assert a["act"] in ("recommend", "conditional", "ask", "abstain", "refer") and run["variant"] == "V5"
    assert run["provenance"]["config_hashes"] and run["provenance"]["profile_id"] == prof["id"]
    assert client.get("/api/runs/" + run["id"]).json()["id"] == run["id"]
    conv = client.get("/api/conversations/" + run["conversation_id"]).json()
    assert [r["id"] for r in conv["runs"]] == [run["id"]]
    if a["next_question"]:
        nq = a["next_question"]
        r2 = client.post("/api/parcels/%s/chat" % p["id"], json={"conversation_id": run["conversation_id"],
                                                                   "reply": {"input": nq["input"], "value": "__unknown__"}})
        assert r2.status_code == 200 and r2.json()["turn"] == 2


def test_variant_and_validation_errors(client):
    p = _parcel(client)
    assert client.post("/api/parcels/%s/chat" % p["id"], json={"text": "x", "variant": "V9"}).status_code == 400
    assert client.post("/api/parcels/%s/chat" % p["id"], json={"text": ""}).status_code == 400
    assert client.post("/api/parcels", json={"name": "", "geometry": SQUARE}).status_code == 400
    assert client.get("/api/parcels/nope").status_code == 404
    v0 = client.post("/api/parcels/%s/chat" % p["id"], json={"text": "Da li da navodnjavam kukuruz?",
                                                               "advice_type": "irrigation_timing", "variant": "V0"})
    assert v0.status_code == 200 and v0.json()["variant"] == "V0"


def test_llm_status_ai_chat_unavailable_and_rating(client):
    assert client.get("/api/llm").json()["available"] is False         # template generator: no model configured
    p = _parcel(client)
    assert client.post("/api/parcels/%s/ai-chat" % p["id"], json={"message": "Kada da navodnjavam?"}).status_code == 503
    assert client.get("/api/eval/rubric").json()
    assert client.get("/api/eval/rating/next", params={"rater": "r1"}).json() == {"item_id": None, "remaining": 0}
    bad = {"item_id": "nope", "rater": "r1", "r1": 1, "r2": 1, "r3": 1, "r4": 1, "r5": 1}
    assert client.post("/api/eval/rating", json=bad).status_code == 404
    assert client.post("/api/eval/rating", json=dict(bad, r1=3)).status_code == 422


def test_research_api_imports_no_product_module():
    import ast
    from pathlib import Path
    product = {"accounts", "api", "activities", "regions", "scope", "cropmodel", "fields", "product_config", "alerts",
               "sensors", "water", "zones", "scouting", "atlas", "economics", "eudr", "advisor", "worker"}
    for f in (Path(__file__).resolve().parents[1] / "src" / "smartagri" / "research_api").glob("*.py"):
        for n in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
            if isinstance(n, ast.ImportFrom) and n.level == 2 and n.module:
                assert n.module.split(".")[0] not in product, (f.name, n.module)


def test_unclassified_question_asks_for_the_advice_type(client):
    p = _parcel(client)
    run = client.post("/api/parcels/%s/chat" % p["id"], json={"text": "Šta da radim?"}).json()
    assert run["answer"]["act"] == "ask" and run["answer"]["next_question"]["input"] == "advice_type"
    r2 = client.post("/api/parcels/%s/chat" % p["id"], json={"conversation_id": run["conversation_id"],
                                                               "reply": {"input": "advice_type", "value": "irrigation_timing"}})
    assert r2.status_code == 200 and r2.json()["advice_type"] == "irrigation_timing" and r2.json()["turn"] == 2


# ---------------------------------------------------------------- research client assets (map client, no build step)
STATIC_DIR = __import__("pathlib").Path(__file__).resolve().parents[1] / "src" / "smartagri" / "research_api" / "static"


def _static_files():
    return sorted(p.relative_to(STATIC_DIR).as_posix() for p in STATIC_DIR.rglob("*")
                  if p.is_file() and p.name != ".DS_Store" and "__pycache__" not in p.parts)


def test_client_assets_are_served(client):
    page = client.get("/")
    assert page.status_code == 200 and "text/html" in page.headers["content-type"]
    for ref in ("static/app.css", "static/app.js", "static/map.js", "static/theme.js", "static/icon.svg",
                "static/vendor/leaflet/leaflet.js", "static/vendor/leaflet/leaflet.css"):
        assert ref in page.text, ref
    types = {".css": "text/css", ".js": "javascript", ".svg": "image/svg+xml", ".png": "image/png", ".html": "text/html"}
    for rel in _static_files():
        r = client.get("/static/" + rel)
        assert r.status_code == 200, rel
        ext = "." + rel.rsplit(".", 1)[-1] if "." in rel.rsplit("/", 1)[-1] else ""
        if ext in types:
            assert types[ext] in r.headers["content-type"], (rel, r.headers["content-type"])
    assert "BSD" in client.get("/static/vendor/leaflet/LICENSE").text
    assert client.get("/static/nope.js").status_code == 404
    assert client.get("/static/../app.py").status_code == 404


def test_client_has_no_external_resource_except_tiles():
    import re
    for rel in _static_files():
        if rel.startswith("vendor/") or not rel.endswith((".html", ".css", ".js")):
            continue
        text = (STATIC_DIR / rel).read_text(encoding="utf-8")
        for url in re.findall(r"(?:src|href)=[\"'](https?:[^\"']+)", text):
            assert False, (rel, url)
        assert "@import" not in text and "fonts.googleapis" not in text, rel


def test_tile_settings_come_from_the_environment(client, monkeypatch):
    default = client.get("/").text
    assert 'name="smartagri-tile-url" content="https://tile.openstreetmap.org/{z}/{x}/{y}.png"' in default
    assert "OpenStreetMap" in default
    monkeypatch.setenv("SMARTAGRI_TILE_URL", "https://tiles.example.org/{z}/{x}/{y}.png?a=1&b=2")
    monkeypatch.setenv("SMARTAGRI_TILE_ATTRIBUTION", "Example \"tiles\"")
    page = client.get("/").text
    assert 'content="https://tiles.example.org/{z}/{x}/{y}.png?a=1&amp;b=2"' in page
    assert 'content="Example &quot;tiles&quot;"' in page
    monkeypatch.setenv("SMARTAGRI_TILE_URL", "none")
    assert 'name="smartagri-tile-url" content="none"' in client.get("/").text


def test_client_assets_are_packaged():
    """Every file of static/ is listed by the package data of backend/pyproject.toml (a wheel ships the client)."""
    import json
    import re
    text = (STATIC_DIR.parents[3] / "pyproject.toml").read_text(encoding="utf-8")
    m = re.search(r'^"smartagri\.research_api" = (\[.*?\])', text, re.M | re.S)
    assert m, "package data of smartagri.research_api is missing"
    patterns = json.loads(m.group(1))
    root = STATIC_DIR.parent
    packaged = {p.relative_to(STATIC_DIR).as_posix() for pat in patterns for p in root.glob(pat) if p.is_file()}
    assert set(_static_files()) <= packaged, sorted(set(_static_files()) - packaged)


def test_blind_rating_screen_is_unchanged_and_neutral():
    """The rating screen is part of the evaluation protocol: its wording stays as the rater guide expects, and it
    shows no variant, generator or model hint (only the blinded item returned by the API)."""
    import re
    page = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    section = re.search(r'<section id="v-rate".*?</section>', page, re.S).group(0)
    for text in ("<h2>Slepo ocenjivanje</h2>", '<label>Ocenjivač <input id="r-rater"></label>',
                 '<button id="r-next">Sledeća stavka</button>', '<div id="r-item"></div>'):
        assert text in section, text
    script = (STATIC_DIR / "app.js").read_text(encoding="utf-8")
    block = script[script.index('$("r-next").onclick'):script.index("// ------", script.index('$("r-next").onclick'))]
    for text in ("Nema više stavki za ocenjivanje.", "Preostalo: ", "Rubrika:", "Sačuvaj ocenu", '"r1": 0, "r2": 0'):
        assert text in block, text
    for word in ("variant", "Variant", "V0", "V5", "VC", "generator", "model"):
        assert word not in section and word not in block, word


# ---------------------------------------------------------------- answer language (English default, SMARTAGRI_LOCALE)
SERBIAN_MARKERS = ("navodnjav", "Navodnjav", "podat", "Podat", "Nisam", "Koliko", "padavin", "Padavin", "useva", "pouzdan")


def _english(text):
    return text and not any(m in text for m in SERBIAN_MARKERS) and not any(ch in text for ch in "čćšžđČĆŠŽĐ")


def test_answers_are_english_by_default(client, monkeypatch):
    monkeypatch.delenv("SMARTAGRI_LOCALE", raising=False)
    p = _parcel(client)
    prof = client.post("/api/parcels/%s/profile/refresh" % p["id"])
    assert prof.headers["content-language"] == "en"
    assert all(_english(q["label"]) and _english(q["reliability_label"]) for q in prof.json()["quality"])
    assert client.get("/api/meta").json()["locale"] == "en"
    r = client.post("/api/parcels/%s/chat" % p["id"], json={"text": "When should I irrigate?"})
    assert r.status_code == 200 and r.headers["content-language"] == "en"
    run = r.json()
    a = run["answer"]
    assert run["advice_type"] == "irrigation_timing" and run["question"] == "When should I irrigate?"
    assert _english(a["summary"]) and _english(a["act_label"]) and all(_english(x) for x in a["rationale"])
    if a["next_question"]:
        assert _english(a["next_question"]["text"])
        assert all(_english(o["label"]) for o in a["next_question"]["options"])
    assert client.get("/api/parcels/nope").json()["detail"] == "Parcel not found."


def test_english_questions_are_understood(client):
    p = _parcel(client)
    client.post("/api/parcels/%s/profile/refresh" % p["id"])
    for text, kind in (("How much water should I apply?", "irrigation_amount"),
                       ("Is there a weather window for spraying this week?", "field_ops_window"),
                       ("When should I top-dress with nitrogen?", "fertilization_timing")):
        run = client.post("/api/parcels/%s/chat" % p["id"], json={"text": text}).json()
        assert run["advice_type"] == kind, (text, run["advice_type"])
        assert _english(run["answer"]["summary"]), run["answer"]["summary"]
    # Local-language questions still work under the English default (answer in English).
    run = client.post("/api/parcels/%s/chat" % p["id"], json={"text": "Da li da navodnjavam kukuruz?"}).json()
    assert run["advice_type"] == "irrigation_timing" and _english(run["answer"]["summary"])
    # An unrecognised question asks for the advice type, in English.
    run = client.post("/api/parcels/%s/chat" % p["id"], json={"text": "Hello there"}).json()
    assert run["answer"]["next_question"]["input"] == "advice_type" and _english(run["answer"]["next_question"]["text"])


def test_local_locale_keeps_the_previous_behaviour(client, monkeypatch, store):
    from smartagri import labels
    monkeypatch.setenv("SMARTAGRI_LOCALE", "sr-Latn")
    p = _parcel(client)
    prof = client.post("/api/parcels/%s/profile/refresh" % p["id"])
    assert prof.headers["content-language"] == "sr-Latn"
    assert prof.json() == store.latest_profile(p["id"])                 # the stored record, unchanged
    run = client.post("/api/parcels/%s/chat" % p["id"], json={"text": "Da li da navodnjavam kukuruz?"}).json()
    assert run["answer"]["act_label"] == labels.ACTS[run["answer"]["act"]]
    assert client.get("/api/meta").json()["advice_types"][0]["label"] == labels.ADVICE_TYPES["irrigation_timing"]
    assert client.get("/api/parcels/nope").json()["detail"] == "Parcela nije pronađena."
    # A request may ask for English explicitly (?lang= or the X-SmartAgri-Lang header).
    assert client.get("/api/parcels/nope", params={"lang": "en"}).json()["detail"] == "Parcel not found."
    assert client.get("/api/parcels/nope", headers={"X-SmartAgri-Lang": "en"}).json()["detail"] == "Parcel not found."
    monkeypatch.setenv("SMARTAGRI_LOCALE", "xx")                         # unknown value: English
    assert client.get("/api/meta").json()["locale"] == "en"


def test_stored_profile_stays_in_the_default_locale(client, store):
    from smartagri import labels
    p = _parcel(client)
    shown = client.post("/api/parcels/%s/profile/refresh" % p["id"]).json()
    stored = store.latest_profile(p["id"])
    assert {q["label"] for q in stored["quality"]} <= set(labels.INPUTS.values())
    assert [q["input"] for q in shown["quality"]] == [q["input"] for q in stored["quality"]]
    assert shown["quality"] != stored["quality"]


def test_rating_endpoints_run_in_the_default_locale(client, monkeypatch):
    """Blind rating is protocol: its items, rubric and messages stay in the default locale whatever the answer
    locale (SMARTAGRI_LOCALE, ?lang=, header)."""
    from smartagri import i18n, labels
    from smartagri.evalkit import rating
    seen = []

    def next_item(store, rater):
        seen.append(i18n.current())
        return {"item_id": None, "remaining": 0}
    monkeypatch.setattr(rating, "next_item", next_item)
    monkeypatch.delenv("SMARTAGRI_LOCALE", raising=False)
    for kw in ({}, {"headers": {"X-SmartAgri-Lang": "en"}}):
        r = client.get("/api/eval/rating/next", params={"rater": "r1", "lang": "en"}, **kw)
        assert r.status_code == 200
        rub = client.get("/api/eval/rubric", params={"lang": "en"}, **kw)
        assert rub.json() == labels.RUBRIC
    assert seen == [i18n.DEFAULT_LOCALE, i18n.DEFAULT_LOCALE]
    bad = {"item_id": "nope", "rater": "r1", "r1": 1, "r2": 1, "r3": 1, "r4": 1, "r5": 1}
    r = client.post("/api/eval/rating", json=bad, params={"lang": "en"})
    assert r.status_code == 404 and r.json()["detail"] == "Stavka za ocenjivanje nije pronađena."
    assert i18n.current() == i18n.DEFAULT_LOCALE                         # outside a request: the default locale


class _ChatProvider:
    """Fake model: the local answer for the chat prompts, an English translation for the translation prompt."""
    name, model = "fake", "fake-1"

    def __init__(self):
        self.systems = []

    def complete(self, system, messages, json_schema=None, max_tokens=4000):
        import json

        from smartagri.llm.base import LLMResponse
        from smartagri.pipeline import ai_chat
        self.systems.append(system)
        if system in (ai_chat.SYSTEM_PROMPT, ai_chat.APP_SYSTEM_PROMPT):
            data = {"text": "Potrebno je proveriti vlažnost zemljišta.", "cited": [], "question_to_user": ""}
        else:
            data = {"text": "TRANSLATED", "question_to_user": ""}
        return LLMResponse(json.dumps(data), self.name, self.model, 10, 5, 0.0, "end_turn", data)


def test_ai_chat_answers_in_the_language_of_the_message(client, monkeypatch):
    from smartagri import llm
    from smartagri.pipeline import ai_chat
    fake = _ChatProvider()
    monkeypatch.setattr(llm, "make_provider", lambda: fake)
    p = _parcel(client)
    client.post("/api/parcels/%s/profile/refresh" % p["id"])
    run = client.post("/api/parcels/%s/ai-chat" % p["id"], json={"message": "When should I irrigate the maize?"}).json()
    assert fake.systems[0] == ai_chat.SYSTEM_PROMPT                      # the VC baseline prompt is unchanged
    assert run["provenance"]["prompt_hash"] == ai_chat.PROMPT_HASH and run["provenance"]["language"]["detected"] == "en"
    assert "text_local" in run["answer"] and run["answer"]["translation"]["target"] == "en"
    fake.systems.clear()
    local = client.post("/api/parcels/%s/ai-chat" % p["id"], json={"message": "Kada da navodnjavam kukuruz?"}).json()
    assert fake.systems == [ai_chat.SYSTEM_PROMPT]                       # a local message: no translation call
    assert "translation" not in local["answer"] and "language" not in local["answer"]


# ---------------------------------------------------------------- read-only views: series, water balance, evaluation,
# provenance export (no network: weather is the fake above, satellite is not configured)
def _fake_satellite(store, geometry, as_of, refresh=False):
    days = [(as_of - timedelta(days=o)).date().isoformat() for o in (25, 15, 5)]
    def item(day, nodata):
        return {"interval": {"from": day + "T00:00:00Z"},
                "outputs": {"ndvi": {"bands": {"B0": {"stats": {"sampleCount": 100, "noDataCount": nodata,
                                                                  "percentiles": {"10.0": 0.5, "50.0": 0.7, "90.0": 0.8}}}}}}}
    return {"raw": {"data": [item(days[0], 10), item(days[1], 60), item(days[2], 100)]},
            "fetched_at": as_of.isoformat(), "request_hash": "sat-test"}


def test_series_without_profile_is_an_honest_empty_state(client):
    p = _parcel(client)
    s = client.get("/api/parcels/%s/series" % p["id"]).json()
    assert s["weather"]["status"] == "missing" and s["weather"]["rows"] == []
    assert s["ndvi"]["status"] == "missing" and s["ndvi"]["rows"] == []
    wb = client.get("/api/parcels/%s/water-balance" % p["id"]).json()
    assert wb["status"] == "missing" and wb["rows"] == [] and wb["used_by_advice"] is False
    assert client.get("/api/parcels/nope/series").status_code == 404
    assert client.get("/api/parcels/nope/water-balance").status_code == 404


def test_series_show_the_stored_rows_with_source_and_age(client):
    p = _parcel(client)
    client.post("/api/parcels/%s/profile/refresh" % p["id"])
    s = client.get("/api/parcels/%s/series" % p["id"]).json()
    w = s["weather"]
    assert w["status"] == "ok" and w["source"] == "Open-Meteo" and w["fetched_at"] and w["age_hours"] is not None
    assert len(w["rows"]) == 37 and sum(r["is_forecast"] for r in w["rows"]) == 7
    assert {r["et0_mm"] for r in w["rows"]} == {5.0} and {r["precip_mm"] for r in w["rows"]} == {0.5}
    n = s["ndvi"]                                       # CDSE not configured: the stored message, no values
    assert n["status"] == "missing" and n["rows"] == [] and "CDSE" in n["message"]


def test_ndvi_series_carries_valid_pixel_ratio(client, monkeypatch):
    from smartagri.providers import satellite
    monkeypatch.setattr(satellite, "fetch", _fake_satellite)
    p = _parcel(client)
    client.post("/api/parcels/%s/profile/refresh" % p["id"])
    n = client.get("/api/parcels/%s/series" % p["id"]).json()["ndvi"]
    assert n["status"] == "ok" and [r["valid_px_ratio"] for r in n["rows"]] == [0.9, 0.4]   # the empty day is dropped
    assert [r["meets_trend_share"] for r in n["rows"]] == [True, False] and n["cloud_flag"] is None
    assert n["latest_age_days"] == 15 and n["rows"][0]["obs_date"] and n["summary"]["latest_value"] == 0.7


def test_water_balance_uses_the_core_tools(client):
    from smartagri.core.tools import crop_evapotranspiration, estimate_bbch
    p = _parcel(client)
    client.post("/api/parcels/%s/profile/refresh" % p["id"])
    wb = client.get("/api/parcels/%s/water-balance" % p["id"]).json()
    assert wb["status"] == "ok" and wb["computed_in"] == "code" and wb["method"] == "FAO-56"
    assert wb["stage_method"] == "days_since_sowing" and wb["used_by_advice"] is False
    sowing = datetime.fromisoformat(p["agronomic"]["sowing_date"]).date()
    for r in wb["rows"]:
        bbch = estimate_bbch(None, (datetime.fromisoformat(r["date"]).date() - sowing).days).output["bbch"]
        tool = crop_evapotranspiration(bbch, r["et0_mm"]).output
        assert r["bbch"] == bbch and r["kc"] == tool["kc"] and r["etc_mm"] == tool["etc_mm"]
    # loam: AWC 160 mm/m; the deficit never leaves [0, TAW] and grows by ETc - rain while below TAW
    first, second = wb["rows"][0], wb["rows"][1]
    assert first["deficit_mm"] == round(max(0.0, first["etc_mm"] - 0.5), 1)
    assert all(0 <= r["deficit_mm"] <= r["taw_mm"] for r in wb["rows"])
    assert second["deficit_mm"] == round(min(second["taw_mm"], first["deficit_mm"] + second["etc_mm"] - 0.5), 1)
    assert wb["totals"]["et0_observed_mm"] == 150.0 and wb["totals"]["rain_observed_mm"] == 15.0


def test_water_balance_without_a_stage_leaves_etc_empty(client):
    r = client.post("/api/parcels", json={"name": "Bez setve", "geometry": SQUARE})
    pid = r.json()["id"]
    client.post("/api/parcels/%s/profile/refresh" % pid)
    wb = client.get("/api/parcels/%s/water-balance" % pid).json()
    assert wb["status"] == "partial" and "no_stage" in wb["assumptions"]
    assert all(x["kc"] is None and x["etc_mm"] is None and x["deficit_mm"] is None for x in wb["rows"])
    assert all(x["et0_mm"] == 5.0 for x in wb["rows"])


def test_evaluation_overview_reads_evalkit(client, store):
    from smartagri.evalkit import report as rep
    from smartagri.evalkit import tables
    empty = client.get("/api/evaluation/overview").json()
    assert empty["sets"] == [] and empty["has_test_results"] is False
    assert empty["lock"]["status"] in ("not_locked", "locked")
    dev_guard = next(g for g in empty["guard"] if g["set"] == "dev")
    assert dev_guard["status"] in ("clean", "hits") and "hits" not in dev_guard     # counts only, never texts
    items = []
    for variant, act in (("V3", "ask"), ("V4", "conditional")):
        for k in range(3):
            items.append(store.save_eval_item({
                "id": "%s-%d" % (variant, k), "batch_id": "b-" + variant, "scenario_id": "S%d" % k, "variant": variant,
                "repeat": 1, "set": "dev", "created_at": "2026-10-26T08:00:00+02:00", "first_act": act,
                "final_act": act, "n_turns": 1, "first_question_input": None, "expect": {"act": "conditional"},
                "turns": [{"answer": {"act": act, "next_question": None, "sources": []}}], "records": []}))
    o = client.get("/api/evaluation/overview").json()
    (dev,) = o["sets"]
    assert dev["set"] == "dev" and dev["label"] == "development set" and dev["experiment_result"] is False
    assert o["has_test_results"] is False and dev["variants"] == ["V3", "V4"]
    auto = rep.automatic(store.list_eval_items())
    assert dev["automatic"]["V4"]["act_accuracy"] == auto["V4"]["act_accuracy"] == 1.0
    step = next(s for s in dev["steps"] if (s["a"], s["b"]) == ("V4", "V3"))
    expected = rep.paired_measure(rep.scenario_scores(store, items, None), "V4", "V3", "act_correct",
                                  rep.scenario_meta(items))
    assert step["comparison"] == "E1" and step["paired"]["diff"] == expected["diff"] == 1.0
    assert step["paired"]["ci95"] == list(expected["ci95"])
    assert dev["report_md"] == tables.render(store, items, None, None)
    assert dev["raters"] == {} and dev["agreement"] is None


def test_provenance_export_holds_decisions_sources_and_hashes(client):
    p = _parcel(client)
    client.post("/api/parcels/%s/profile/refresh" % p["id"])
    run = client.post("/api/parcels/%s/chat" % p["id"],
                      json={"text": "When should I irrigate?", "advice_type": "irrigation_timing"}).json()
    r = client.get("/api/runs/%s/provenance" % run["id"])
    assert r.status_code == 200 and "attachment" in r.headers["content-disposition"]
    doc = r.json()
    assert doc["format"] == "smartagri-provenance/1" and doc["run"]["id"] == run["id"]
    assert set(doc["decisions"]) >= {"quality", "applicability", "sufficiency", "question", "policy", "grounding"}
    assert doc["hashes"]["config"] == run["provenance"]["config_hashes"] and doc["hashes"]["corpus"]
    assert doc["hashes"]["code_version"]["recorded_with_run"] is False
    assert doc["inputs"] == run["answer"]["data_used"] and doc["sources"] == run["answer"]["sources"]
    assert doc["profile"]["id"] == run["provenance"]["profile_id"] and doc["profile"]["weather"]["source"] == "Open-Meteo"
    assert client.get("/api/runs/nope/provenance").status_code == 404


def test_evaluation_view_is_not_linked_from_the_rating_screen():
    import re
    page = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    section = re.search(r'<section id="v-rate".*?</section>', page, re.S).group(0)
    assert "eval" not in section.replace("Slepo", "").lower().replace("ocenjiva", "")
    script = (STATIC_DIR / "app.js").read_text(encoding="utf-8")
    block = script[script.index('$("r-next").onclick'):script.index("// ------", script.index('$("r-next").onclick'))]
    assert "#/eval" not in block and "/evaluation" not in block
