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
