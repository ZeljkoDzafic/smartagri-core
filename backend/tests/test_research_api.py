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
