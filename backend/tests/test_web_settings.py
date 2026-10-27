"""Web settings of the research core: registry coverage, layers, limits, history, isolation, evaluation isolation and the
settings block of an answer (smartagri.web_settings, research_api/settings_routes.py, static/settings.js)."""
import json
import re
import shutil
import threading
from datetime import datetime, timedelta
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from smartagri import config
from smartagri.core.decide import decide
from smartagri.core.tools import net_irrigation_need
from smartagri.core.types import AdviceType, Passage
from smartagri.providers import weather
from smartagri.research_api import auth, settings_routes
from smartagri.research_api.app import create_app
from smartagri.research_api.service import ResearchService
from smartagri.web_settings import registry as reg
from smartagri.web_settings.service import Actor, SettingsError, SettingsService, empty_summary

from conftest import make_context

STATIC = Path(__file__).resolve().parents[1] / "src" / "smartagri" / "research_api" / "static"
SQUARE = {"type": "Polygon", "coordinates": [[[17.300, 44.900], [17.302, 44.900], [17.302, 44.902], [17.300, 44.902],
                                              [17.300, 44.900]]]}
CAP = "rules.irrigation.max_single_net_mm"
PW = "maize-field-2026"


def _fake_weather(store, lat, lon, as_of, refresh=False):
    days = [(as_of + timedelta(days=o)).date().isoformat() for o in range(-92, 7)]
    n = len(days)
    return {"raw": {"daily": {"time": days, "precipitation_sum": [0.5] * n, "et0_fao_evapotranspiration": [5.0] * n,
                              "temperature_2m_min": [15.0] * n, "temperature_2m_max": [29.0] * n,
                              "wind_speed_10m_max": [3.0] * n}},
            "fetched_at": as_of.isoformat(), "request_hash": "test"}


@pytest.fixture
def env(monkeypatch, store):
    monkeypatch.delenv("CDSE_CLIENT_ID", raising=False)
    for name in ("SMARTAGRI_SMTP_HOST", "SMARTAGRI_SMTP_FROM", "SMARTAGRI_PUBLIC_URL", "SMARTAGRI_COOKIE_SECURE",
                 "SMARTAGRI_ADMINS", "SMARTAGRI_ACCOUNTS"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("LLM_PROVIDER", "template")
    monkeypatch.setenv("EMBEDDINGS_PROVIDER", "none")
    monkeypatch.setattr(weather, "fetch", _fake_weather)
    return store


@pytest.fixture
def local(env):
    """Local single-user mode (accounts off): the local user is the administrator."""
    return TestClient(create_app(ResearchService(env))), env


def _accounts_app(store, monkeypatch, admins="admin@example.org"):
    monkeypatch.setenv("SMARTAGRI_ACCOUNTS", "optional")
    if admins:
        monkeypatch.setenv("SMARTAGRI_ADMINS", admins)
    svc = ResearchService(store)
    return create_app(svc, auth.Accounts(store)), svc


def _browser(app):
    c = TestClient(app, base_url="http://testserver")
    c.get("/api/auth/me")
    return c


def _send(c, method, path, body=None, csrf=True):
    headers = {"X-CSRF-Token": c.cookies.get("sa_csrf") or ""} if csrf else {}
    return c.request(method, path, json=body if body is not None else {}, headers=headers)


def _signup(app, email):
    c = _browser(app)
    r = _send(c, "POST", "/api/auth/signup", {"email": email, "password": PW})
    assert r.status_code == 201, r.text
    return c


def _parcel(c, texture="loam"):
    sowing = (datetime.now() - timedelta(days=78)).date().isoformat()
    r = _send(c, "POST", "/api/parcels", {"name": "Njiva", "geometry": SQUARE, "sowing_date": sowing,
                                          "irrigation_available": "yes", "irrigation_system_type": "sprinkler",
                                          "soil_texture": texture})
    assert r.status_code == 201, r.text
    return r.json()


def _entry(client, key, parcel_id=None):
    q = "?parcel_id=%s" % parcel_id if parcel_id else ""
    return {e["key"]: e for e in client.get("/api/settings" + q).json()["entries"]}[key]


# ------------------------------------------------------------------------------------------------ the registry
def test_registry_covers_every_leaf_of_the_editable_files():
    assert reg.uncovered() == []                          # a new YAML key without a registry entry fails here
    assert reg.unused_specs() == []                       # and a stale declaration too
    entries = reg.entries()
    assert len({e.key for e in entries}) == len(entries) > 150
    for f in reg.EDITABLE_FILES:
        assert any(e.file == f for e in entries), f


def test_a_new_yaml_key_without_a_registry_entry_is_reported(tmp_path, monkeypatch):
    src = Path(config.config_dir())
    for p in src.glob("*.yaml"):
        shutil.copy(p, tmp_path / p.name)
    data = yaml.safe_load((tmp_path / "rules.yaml").read_text(encoding="utf-8"))
    data["irrigation"]["brand_new_parameter"] = 3
    (tmp_path / "rules.yaml").write_text(yaml.safe_dump(data), encoding="utf-8")
    monkeypatch.setenv("SMARTAGRI_CONFIG_DIR", str(tmp_path))
    config.load_file.cache_clear()
    reg.reset_cache()
    try:
        assert reg.uncovered() == ["rules.irrigation.brand_new_parameter"]
    finally:
        monkeypatch.delenv("SMARTAGRI_CONFIG_DIR")
        config.load_file.cache_clear()
        reg.reset_cache()
    assert reg.uncovered() == []


def test_every_entry_is_described_in_both_languages_with_a_status_and_a_source_where_one_is_claimed():
    for e in reg.entries():
        d = reg.describe(e)
        assert d["label"]["en"].strip() and d["label"]["sr"].strip() and "{name}" not in d["label"]["en"] + d["label"]["sr"], e.key
        assert d["status"] in reg.STATUSES and d["group"] in {g[0] for g in reg.GROUPS}, e.key
        if d["status"] in ("verified", "partly", "disputed"):
            assert d["source"] and d["source"]["url"].startswith("https://") and d["note"]["en"] and d["note"]["sr"], e.key
        if d["status"] in ("no_source", "development") and not d["readonly"]:
            assert d["note"]["en"] and d["note"]["sr"], e.key              # says that the value awaits review
        assert d["default"] == e.default
    assert all(reg.SOURCES[s][0] for s in reg.SOURCES)


def test_the_registry_never_copies_a_default_and_json_round_trips_it():
    # defaults come from the files at run time: changing a file value changes the registry's default
    assert reg.entry_map()[CAP].default == config.load_file("rules")["irrigation"]["max_single_net_mm"]
    json.dumps([reg.describe(e) for e in reg.entries()])
    text = (Path(reg.__file__)).read_text(encoding="utf-8")
    assert "load_file(" in text and "default=50" not in text


def test_public_texts_name_no_private_material():
    text = (Path(reg.__file__).read_text(encoding="utf-8") + (STATIC / "settings.js").read_text(encoding="utf-8")).lower()
    # the words are split in this source so that the repository scanner does not flag the list itself
    assert ", " "audit)" not in text              # the public export rewrites this pattern (split here so it is not rewritten)
    for word in ("the" "sis", "doc" "tor", "diser" "tac", "dok" "tor", "clau" "de", "anthro" "pic", "gem" "ini", "geo" "crop", "agro" "vid"):
        assert word not in text, word


def test_protocol_files_are_read_only_and_not_in_the_registry(local):
    client, _ = local
    keys = {e.key for e in reg.entries()}
    assert not any(k.split(".")[0] in reg.PROTOCOL_FILES for k in keys)
    files = client.get("/api/settings/protocol").json()["files"]
    assert [f["file"] for f in files] == ["variants.yaml", "analysis.yaml", "evaluation.yaml", "vocab.yaml"]
    assert all(f["reason"]["en"] and f["reason"]["sr"] and f["values"] for f in files)
    for name in ("variants", "analysis", "evaluation", "vocab"):
        r = client.put("/api/settings/user", json={"values": {name + ".x": 1}})
        assert r.status_code == 400 and r.json()["errors"][0]["code"] == "unknown_key"


# ------------------------------------------------------------------------------------------------ the overlay
def test_no_overlay_means_the_file_data_itself():
    assert config.active_overlay() is None
    assert config.load("rules") is config.load_file("rules")
    with config.use_overlay(config.Overlay({})):
        assert config.load("rules") is config.load_file("rules")           # an empty overlay changes nothing, copies nothing


def test_an_overlay_is_per_context_and_never_mutates_the_files():
    before = json.dumps(config.load_file("rules"), sort_keys=True)
    seen = {}
    with config.use_overlay(config.Overlay({CAP: 20})):
        assert config.load("rules")["irrigation"]["max_single_net_mm"] == 20
        assert config.load("kc_maize") is config.load_file("kc_maize")      # files without overrides are not copied
        t = threading.Thread(target=lambda: seen.update(other=config.load("rules")["irrigation"]["max_single_net_mm"]))
        t.start()
        t.join()
    assert seen["other"] == config.load_file("rules")["irrigation"]["max_single_net_mm"]   # another thread: files
    assert config.load("rules")["irrigation"]["max_single_net_mm"] == 50
    assert json.dumps(config.load_file("rules"), sort_keys=True) == before
    assert config.active_overlay() is None
    h = config.config_hashes()
    with config.use_overlay(config.Overlay({CAP: 20})):
        assert config.config_hashes() == h                                   # file hashes never move


def test_an_override_changes_a_decision_in_a_controlled_case():
    base = net_irrigation_need("dry", 160, 1.0, 0.0).output
    assert base["applications"] == 2 and base["net_mm"] == 48.0             # 0.6 x 160 x 1.0 = 96 mm in 2 x 48
    with config.use_overlay(config.Overlay({CAP: 20})):
        capped = net_irrigation_need("dry", 160, 1.0, 0.0).output
    assert capped["applications"] == 5 and capped["net_mm"] == 19.2
    assert net_irrigation_need("dry", 160, 1.0, 0.0).output == base


def _decision_json(ctx, variant):
    passages = [Passage.from_dict(p) for p in yaml.safe_load(
        (Path(__file__).resolve().parents[1] / "eval" / "scenarios" / "dev" / "_passages.yaml").read_text(encoding="utf-8"))]
    return json.dumps(decide(ctx, passages, variant).to_dict(), sort_keys=True, default=str)


def test_without_overrides_the_decision_is_byte_identical(variants):
    for advice in (AdviceType.IRRIGATION_TIMING, AdviceType.IRRIGATION_AMOUNT, AdviceType.FERTILIZATION_PLAN,
                   AdviceType.FIELD_OPS_WINDOW, AdviceType.SCOUTING):
        for name in ("V3", "V4", "V5"):
            ctx = make_context(advice)
            plain = _decision_json(ctx, variants[name])
            with config.use_overlay(config.Overlay({}, empty_summary())):
                assert _decision_json(make_context(advice), variants[name]) == plain, (advice, name)


def test_an_override_reaches_quality_and_requirements(variants):
    ctx = make_context(AdviceType.IRRIGATION_TIMING, weather={"forecast_issued_at": "2026-07-10T04:00:00"})
    plain = decide(ctx, [], variants["V4"])
    assert plain.quality["precip_forecast_3d"].reliability.value in ("low", "medium")
    rows = [{"reliability": "high", "max_age_days": 5}]
    with config.use_overlay(config.Overlay({"thresholds.inputs.precip_forecast_3d.grades": rows})):
        lifted = decide(make_context(AdviceType.IRRIGATION_TIMING, weather={"forecast_issued_at": "2026-07-10T04:00:00"}),
                        [], variants["V4"])
    assert lifted.quality["precip_forecast_3d"].reliability.value == "high"
    assert plain.config_hashes == lifted.config_hashes


# ------------------------------------------------------------------------------------------------ validation
def test_values_are_validated_server_side_against_the_registry(local):
    client, _ = local
    put = lambda values: client.put("/api/settings/user", json={"values": values})           # noqa: E731
    assert put({CAP: 9999}).json()["errors"][0] == {"key": CAP, "code": "range", "params": {"min": 1, "max": 300}}
    assert put({CAP: "30"}).json()["errors"][0]["code"] == "type"
    assert put({CAP: True}).json()["errors"][0]["code"] == "type"
    nan = client.put("/api/settings/user", content='{"values": {"%s": NaN}}' % CAP, headers={"Content-Type": "application/json"})
    assert nan.status_code == 400 and nan.json()["errors"][0]["code"] == "type"
    assert put({"rules.nothing.here": 1}).json()["errors"][0]["code"] == "unknown_key"
    assert put({"parcel_features.schema_version": 2}).json()["errors"][0]["code"] == "not_editable"
    assert put({"asking.inputs.ndvi_latest.user_obtainable": True}).json()["errors"][0]["code"] == "not_editable"
    assert put({"rules.fertilization.topdress_bbch": [20, 10]}).json()["errors"][0]["code"] == "order"
    assert put({"rules.soil.awc_by_texture_mm_m": {"sand": 80}}).json()["errors"][0]["code"] == "shape"
    assert put({"rules.irrigation.root_depth_m_by_bbch": [{"bbch_max": 20, "depth": 0.3}]}).json()["errors"][0]["code"] == "last_row"
    assert put({"rules.irrigation.root_depth_m_by_bbch": [{"bbch_max": 20, "depth": 0.3, "x": 1}, {"bbch_max": 99, "depth": 1}]}
               ).json()["errors"][0]["code"] == "shape"
    assert put({"kc_maize.kc": [{"bbch_min": 0, "bbch_max": 10, "kc": 0.3}, {"bbch_min": 12, "bbch_max": 99, "kc": 1.0}]}
               ).json()["errors"][0]["code"] == "contiguous"
    assert put({"rules.optional_inputs.legumes": ["ok", "no spaces allowed"]}).json()["errors"][0]["code"] == "type"
    g = lambda values: client.put("/api/settings/global", json={"values": values, "reason": "t"})         # noqa: E731
    assert g({"parcel_features.ndvi_quality.max_masked_share_for_high": 0.9}).json()["errors"][0]["code"] == "relation_masked"
    assert g({"asking.inputs.phenophase.question_sr": "x" * 401}).json()["errors"][0]["code"] == "type"
    r = put({CAP: 9999, "rules.nothing.here": 1})
    assert {e["key"] for e in r.json()["errors"]} == {CAP, "rules.nothing.here"} and r.json()["detail"] == "Some values were refused."
    assert client.get("/api/settings").json()["effective"]["n_overrides"] == 0               # a refused write changes nothing
    ok = put({CAP: 30, "kc_maize.kc": [{"bbch_min": 0, "bbch_max": 20, "kc": 0.3, "stage": "a"},
                                      {"bbch_min": 21, "bbch_max": 99, "kc": 1.1}]})
    assert ok.status_code == 200 and ok.json()["changed"] == ["kc_maize.kc", CAP]


def test_a_warning_inside_the_range_but_outside_the_recommended_values_cites_the_source(local):
    client, _ = local
    r = client.put("/api/settings/user", json={"values": {CAP: 100}}).json()
    w = r["warnings"][0]
    assert w["code"] == "outside_recommended" and w["range"] == [15, 70] and "FAO" in w["source"]["text"] and w["source"]["url"]
    assert _entry(client, CAP)["warnings"][0]["value"] == 100
    r = client.put("/api/settings/user", json={"values": {CAP: 40}}).json()
    assert r["warnings"] == [] and _entry(client, CAP)["warnings"] == []
    sand = dict(config.load_file("rules")["soil"]["awc_by_texture_mm_m"], sand=120)
    r = client.put("/api/settings/user", json={"values": {"rules.soil.awc_by_texture_mm_m": sand}}).json()
    assert r["warnings"][0]["where"] == "sand" and r["warnings"][0]["range"] == [50, 110]


# ------------------------------------------------------------------------------------------------ layers and limits
def test_precedence_parcel_user_global_file(local):
    client, store = local
    p = _parcel(client)
    pid = p["id"]
    assert _entry(client, CAP)["layer"] == "default" and _entry(client, CAP)["effective"] == 50
    client.put("/api/settings/global", json={"values": {CAP: 45}, "reason": "region"})
    e = _entry(client, CAP)
    assert (e["effective"], e["layer"], e["layers"]) == (45, "global", {"global": 45})
    client.put("/api/settings/user", json={"values": {CAP: 40}})
    e = _entry(client, CAP)
    assert (e["effective"], e["layer"]) == (40, "user")
    assert _entry(client, CAP, pid)["layer"] == "user"
    r = client.put("/api/settings/parcels/" + pid, json={"values": {CAP: 30}})
    assert r.status_code == 200
    e = _entry(client, CAP, pid)
    assert (e["effective"], e["layer"], e["layers"]) == (30, "parcel", {"global": 45, "user": 40, "parcel": 30})
    assert _entry(client, CAP)["effective"] == 40                       # the user view without a parcel is unchanged
    client.post("/api/settings/parcels/%s/reset" % pid, json={"keys": [CAP]})
    assert _entry(client, CAP, pid)["effective"] == 40
    client.post("/api/settings/user/reset", json={"keys": [CAP]})
    assert _entry(client, CAP, pid)["effective"] == 45
    client.post("/api/settings/global/reset", json={"keys": [CAP], "reason": "back"})
    e = _entry(client, CAP, pid)
    assert (e["effective"], e["layer"]) == (50, "default")


def test_limits_the_user_editable_switch_and_the_allowed_range(local):
    client, _ = local
    r = client.put("/api/settings/limits", json={"limits": {CAP: {"min": 20, "max": 40, "user_editable": True}}, "reason": "agronomist"})
    assert r.status_code == 200
    assert client.put("/api/settings/user", json={"values": {CAP: 50}}).json()["errors"][0]["params"] == {"min": 20, "max": 40}
    assert client.put("/api/settings/global", json={"values": {CAP: 15}, "reason": "x"}).status_code == 400   # also the global layer
    assert client.put("/api/settings/user", json={"values": {CAP: 25}}).status_code == 200
    e = _entry(client, CAP)
    assert e["bounds"]["min"] == 20 and e["bounds"]["max"] == 40 and e["limit"]["max"] == 40
    # the limit is refused outside the registry bounds, and without a reason
    assert client.put("/api/settings/limits", json={"limits": {CAP: {"max": 9000}}, "reason": "x"}).json()["errors"][0]["code"] == "range"
    assert client.put("/api/settings/limits", json={"limits": {CAP: {"max": 30}}, "reason": ""}).json()["errors"][0]["code"] == "required"
    assert client.put("/api/settings/limits", json={"limits": {CAP: {"min": 40, "max": 30}}, "reason": "x"}).status_code == 400
    # a user value that falls outside a later, narrower limit is ignored and reported
    client.put("/api/settings/limits", json={"limits": {CAP: {"min": 30, "max": 40}}, "reason": "narrower"})
    e = _entry(client, CAP)
    assert e["effective"] == 50 and e["layer"] == "default" and e["ignored"] == [{"key": CAP, "layer": "user", "reason": "range"}]
    # the switch: users may not change the parameter, the global layer still can
    client.put("/api/settings/limits", json={"limits": {CAP: {"user_editable": False}}, "reason": "locked"})
    assert client.put("/api/settings/user", json={"values": {CAP: 35}}).json()["errors"][0]["code"] == "not_editable_by_user"
    assert _entry(client, CAP)["user_editable"] is False
    assert client.put("/api/settings/global", json={"values": {CAP: 35}, "reason": "ok"}).status_code == 200
    # a global value must stay inside a new limit
    r = client.put("/api/settings/limits", json={"limits": {CAP: {"max": 30}}, "reason": "x"})
    assert r.json()["errors"][0]["code"] == "global_outside_limit"
    # defaults of the switch come from the registry: structural groups are admin-only until the administrator opens them
    assert _entry(client, "requirements.advice_types.irrigation_amount.required")["user_editable"] is False
    assert _entry(client, "rules.soil.efficiency_by_system")["user_editable"] is True
    assert client.put("/api/settings/user", json={"values": {"asking.max_questions": 1}}).json()["errors"][0]["code"] == "not_editable_by_user"
    client.put("/api/settings/limits", json={"limits": {"asking.max_questions": {"user_editable": True}}, "reason": "open"})
    assert client.put("/api/settings/user", json={"values": {"asking.max_questions": 1}}).status_code == 200


def test_table_limits_shape_and_columns(local):
    client, _ = local
    key = "rules.irrigation.root_depth_m_by_bbch"
    client.put("/api/settings/limits", json={"limits": {key: {"max_items": 3, "columns": {"depth": {"max": 1.2}}}}, "reason": "x"})
    rows = [{"bbch_max": 10, "depth": 0.2}, {"bbch_max": 20, "depth": 0.4}, {"bbch_max": 30, "depth": 0.6}, {"bbch_max": 99, "depth": 1.0}]
    assert client.put("/api/settings/user", json={"values": {key: rows}}).json()["errors"][0]["code"] == "items"
    assert client.put("/api/settings/user", json={"values": {key: [{"bbch_max": 20, "depth": 0.5}, {"bbch_max": 99, "depth": 1.5}]}}
                      ).json()["errors"][0]["code"] == "range"
    assert client.put("/api/settings/user", json={"values": {key: [{"bbch_max": 20, "depth": 0.5}, {"bbch_max": 99, "depth": 1.1}]}}).status_code == 200


# ------------------------------------------------------------------------------------------------ history
def test_audit_log_is_append_only_and_complete(local):
    client, store = local
    client.put("/api/settings/user", json={"values": {CAP: 40}, "reason": "first"})
    client.put("/api/settings/user", json={"values": {CAP: 35}, "reason": "second"})
    client.post("/api/settings/user/reset", json={"keys": [CAP], "reason": "third"})
    log = client.get("/api/settings/audit?scope=user").json()
    assert log["total"] == 3
    newest = log["items"][0]
    assert (newest["param"], newest["old"], newest["new"], newest["action"], newest["reason"]) == (CAP, 35, None, "reset", "third")
    assert newest["actor"] == "you" and newest["at"] and newest["version"] == 3
    assert [i["new"] for i in log["items"]] == [None, 35, 40]
    for sql in ("UPDATE settings_audit SET param = 'x'", "DELETE FROM settings_audit",
                "UPDATE settings_versions SET scope = 'x'", "DELETE FROM settings_versions"):
        with pytest.raises(Exception) as exc:
            store._exec(sql)
        assert "append-only" in str(exc.value)
    assert client.get("/api/settings/audit?scope=user").json()["total"] == 3
    assert client.get("/api/settings/audit?scope=user&param=nothing").json()["total"] == 0
    assert client.get("/api/settings/audit?scope=user&action=reset").json()["total"] == 1
    assert client.get("/api/settings/audit?scope=user&since=2999-01-01").json()["total"] == 0
    assert client.get("/api/settings/audit?scope=user&limit=2&offset=2").json()["items"][0]["reason"] == "first"


def test_versions_and_restore_whole_set_one_parameter_and_file_default(local):
    client, _ = local
    awc = "rules.soil.efficiency_by_system"
    client.put("/api/settings/user", json={"values": {CAP: 40}})                      # v1
    client.put("/api/settings/user", json={"values": {CAP: 30, "rules.scouting.contrast_priority": 0.5}})    # v2
    client.put("/api/settings/user", json={"values": {CAP: 20, awc: {"sprinkler": 0.7, "drip": 0.9, "furrow": 0.6}}})   # v3
    versions = client.get("/api/settings/versions?scope=user").json()["versions"]
    assert [v["n"] for v in versions] == [3, 2, 1] and versions[0]["values"][CAP] == 20 and versions[2]["values"] == {CAP: 40}
    r = client.post("/api/settings/restore", json={"scope": "user", "version": 1}).json()          # the whole set of v1
    assert r["version"] == 4 and _entry(client, CAP)["effective"] == 40
    assert "rules.scouting.contrast_priority" not in client.get("/api/settings").json()["entries"][0]["layers"]
    assert _entry(client, "rules.scouting.contrast_priority")["layer"] == "default"
    assert _entry(client, awc)["layer"] == "default"
    r = client.post("/api/settings/restore", json={"scope": "user", "version": 3, "keys": [awc]}).json()   # one parameter of v3
    assert r["changed"] == [awc] and _entry(client, awc)["effective"]["sprinkler"] == 0.7 and _entry(client, CAP)["effective"] == 40
    r = client.post("/api/settings/restore", json={"scope": "user", "version": "default"}).json()    # the file defaults
    assert r["version"] == 6 and _entry(client, CAP)["layer"] == "default" and _entry(client, awc)["layer"] == "default"
    assert [v["n"] for v in client.get("/api/settings/versions?scope=user").json()["versions"]] == [6, 5, 4, 3, 2, 1]   # nothing deleted
    assert client.post("/api/settings/restore", json={"scope": "user", "version": 99}).status_code == 404
    assert client.post("/api/settings/restore", json={"scope": "user", "version": "x"}).status_code == 400
    audit = client.get("/api/settings/audit?scope=user&action=restore").json()
    assert audit["total"] >= 3
    # a restored set is validated again: a limit set after the version was saved refuses it
    client.put("/api/settings/limits", json={"limits": {CAP: {"max": 25}}, "reason": "x"})
    assert client.post("/api/settings/restore", json={"scope": "user", "version": 1}).json()["errors"][0]["code"] == "range"


def test_a_global_change_needs_a_reason_and_the_history_of_limits_is_kept(local):
    client, _ = local
    assert client.put("/api/settings/global", json={"values": {CAP: 40}}).json()["errors"][0]["code"] == "required"
    assert client.put("/api/settings/global", json={"values": {CAP: 40}, "reason": "r1"}).status_code == 200
    assert client.put("/api/settings/global", json={"values": {CAP: 40}, "reason": "r2"}).json()["unchanged"] is True
    client.put("/api/settings/limits", json={"limits": {CAP: {"max": 60}}, "reason": "l1"})
    assert [v["reason"] for v in client.get("/api/settings/versions?scope=global").json()["versions"]] == ["r1"]
    assert [v["reason"] for v in client.get("/api/settings/versions?scope=limits").json()["versions"]] == ["l1"]
    r = client.post("/api/settings/restore", json={"scope": "limits", "version": "default", "reason": "open again"}).json()
    assert r["changed"] == [CAP] and client.get("/api/settings/limits").json()["limits"] == {}
    stale = client.put("/api/settings/user", json={"values": {CAP: 30}, "base_version": 7})
    assert stale.status_code == 409


# ------------------------------------------------------------------------------------------------ accounts: isolation and roles
def test_users_cannot_read_or_write_each_others_settings_or_parcels(env, monkeypatch):
    app, _ = _accounts_app(env, monkeypatch)
    a, b = _signup(app, "a@example.org"), _signup(app, "b@example.org")
    pa = _parcel(a)
    assert _send(a, "PUT", "/api/settings/user", {"values": {CAP: 33}}).status_code == 200
    assert _send(a, "PUT", "/api/settings/parcels/" + pa["id"], {"values": {CAP: 22}}).status_code == 200
    # B sees neither A's user value nor A's parcel value, and cannot touch A's parcel
    assert _entry(b, CAP)["effective"] == 50 and _entry(b, CAP)["layers"] == {}
    assert b.get("/api/settings?parcel_id=" + pa["id"]).status_code == 404
    assert _send(b, "PUT", "/api/settings/parcels/" + pa["id"], {"values": {CAP: 11}}).status_code == 404
    assert _send(b, "POST", "/api/settings/parcels/%s/reset" % pa["id"], {"all": True}).status_code == 404
    assert b.get("/api/settings/versions?scope=parcel&parcel_id=" + pa["id"]).status_code == 404
    assert b.get("/api/settings/audit?scope=parcel&parcel_id=" + pa["id"]).status_code == 404
    assert _send(b, "POST", "/api/settings/restore", {"scope": "parcel", "parcel_id": pa["id"], "version": "default"}).status_code == 404
    assert b.get("/api/settings/versions?scope=user&user_id=anything").status_code == 403
    assert b.get("/api/settings/audit?scope=user").json()["total"] == 0                    # B's own log only
    assert b.get("/api/settings/audit?scope=global").status_code == 403
    assert b.get("/api/settings/audit?scope=user&who=somebody").json()["total"] == 0
    assert _entry(a, CAP, pa["id"])["effective"] == 22
    # the answer of B's parcel is computed without A's values
    pb = _parcel(b)
    run = _send(b, "POST", "/api/parcels/%s/chat" % pb["id"], {"text": "When should I irrigate?", "advice_type": "irrigation_timing"}).json()
    assert run["provenance"]["settings"]["n_overrides"] == 0


def test_anonymous_users_read_the_global_values_and_cannot_write(env, monkeypatch):
    app, _ = _accounts_app(env, monkeypatch)
    admin = _signup(app, "admin@example.org")
    assert _send(admin, "PUT", "/api/settings/global", {"values": {CAP: 44}, "reason": "region"}).status_code == 200
    anon = _browser(app)
    view = anon.get("/api/settings").json()
    assert view["capabilities"] == {"accounts": "optional", "signed_in": False, "can_write": False, "is_admin": False, "parcel_id": None}
    assert _entry(anon, CAP)["effective"] == 44 and _entry(anon, CAP)["layer"] == "global"
    for method, path, body in (("PUT", "/api/settings/user", {"values": {CAP: 30}}), ("POST", "/api/settings/user/reset", {"all": True}),
                               ("PUT", "/api/settings/global", {"values": {CAP: 30}, "reason": "x"}),
                               ("PUT", "/api/settings/limits", {"limits": {CAP: {"max": 60}}, "reason": "x"}),
                               ("POST", "/api/settings/restore", {"scope": "user", "version": "default"})):
        assert _send(anon, method, path, body).status_code == 403, (method, path)
    pid = _parcel(anon)["id"]                                                              # anonymous parcels exist, but are temporary
    assert _send(anon, "PUT", "/api/settings/parcels/" + pid, {"values": {CAP: 30}}).status_code == 403
    assert anon.get("/api/settings/audit").status_code == 403 and anon.get("/api/settings/versions?scope=user").status_code == 403
    run = _send(anon, "POST", "/api/parcels/%s/chat" % pid, {"text": "When should I irrigate?", "advice_type": "irrigation_timing"}).json()
    s = run["provenance"]["settings"]
    assert s["snapshot"][CAP] == {"value": 44, "layer": "global"}                          # an anonymous answer uses the global values


def test_admin_endpoints_are_for_administrators_only(env, monkeypatch):
    app, _ = _accounts_app(env, monkeypatch, admins="Admin@Example.org, other@example.org")
    admin, user = _signup(app, "admin@example.org"), _signup(app, "user@example.org")
    assert admin.get("/api/settings").json()["capabilities"]["is_admin"] is True
    assert user.get("/api/settings").json()["capabilities"]["is_admin"] is False
    for method, path, body in (("PUT", "/api/settings/global", {"values": {CAP: 30}, "reason": "x"}),
                               ("POST", "/api/settings/global/reset", {"all": True, "reason": "x"}),
                               ("PUT", "/api/settings/limits", {"limits": {CAP: {"max": 60}}, "reason": "x"}),
                               ("POST", "/api/settings/restore", {"scope": "global", "version": "default", "reason": "x"}),
                               ("POST", "/api/settings/restore", {"scope": "limits", "version": "default", "reason": "x"})):
        assert _send(user, method, path, body).status_code == 403, (method, path)
    assert user.get("/api/settings/limits").status_code == 403
    assert user.get("/api/settings/versions?scope=global").status_code == 403
    assert user.get("/api/settings/versions?scope=limits").status_code == 403
    assert admin.get("/api/settings/limits").status_code == 200
    assert _send(admin, "PUT", "/api/settings/limits", {"limits": {CAP: {"max": 60}}, "reason": "x"}).status_code == 200
    assert _send(admin, "PUT", "/api/settings/global", {"values": {CAP: 55}, "reason": "x"}).status_code == 200
    # an administrator sees every layer in the log, with who did it; a user cannot
    _send(user, "PUT", "/api/settings/user", {"values": {CAP: 33}})
    log = admin.get("/api/settings/audit").json()
    assert {i["scope"] for i in log["items"]} == {"global", "limits", "user"}
    assert {i["actor"] for i in log["items"] if i["scope"] != "user"} == {"you"}
    assert [i["actor"] for i in log["items"] if i["scope"] == "user"] == ["user@example.org"]
    assert user.get("/api/settings/audit?scope=user").json()["items"][0]["actor"] == "you"


def test_the_admin_list_is_an_allow_list_of_verified_accounts(env, monkeypatch):
    app, _ = _accounts_app(env, monkeypatch, admins="")
    c = _signup(app, "admin@example.org")
    assert c.get("/api/settings").json()["capabilities"]["is_admin"] is False             # no SMARTAGRI_ADMINS: nobody
    monkeypatch.setenv("SMARTAGRI_ADMINS", "someone@example.org")
    assert c.get("/api/settings").json()["capabilities"]["is_admin"] is False


def test_csrf_origin_and_rate_limit(env, monkeypatch):
    app, _ = _accounts_app(env, monkeypatch)
    c = _signup(app, "admin@example.org")
    r = _send(c, "PUT", "/api/settings/user", {"values": {CAP: 30}}, csrf=False)
    assert r.status_code == 403 and "security check" in r.json()["detail"]
    r = c.put("/api/settings/user", json={"values": {CAP: 30}}, headers={"X-CSRF-Token": c.cookies.get("sa_csrf"), "Origin": "https://evil.example"})
    assert r.status_code == 403
    assert _send(c, "PUT", "/api/settings/user", {"values": {CAP: 30}}).status_code == 200
    monkeypatch.setattr(settings_routes, "WRITE_LIMIT", (3, 900))
    codes = [_send(c, "PUT", "/api/settings/user", {"values": {CAP: 20 + i}}).status_code for i in range(4)]
    assert codes[-1] == 429 and 200 in codes
    assert c.get("/api/settings").status_code == 200                                       # reads are not limited


def test_accounts_off_checks_the_origin_of_writes(local):
    client, _ = local
    assert client.put("/api/settings/user", json={"values": {CAP: 30}}, headers={"Origin": "https://evil.example"}).status_code == 403
    assert client.put("/api/settings/user", json={"values": {CAP: 30}}, headers={"Origin": "http://testserver"}).status_code == 200
    assert client.put("/api/settings/user", json={"values": {CAP: 31}}).status_code == 200      # no Origin: not a browser


def test_deleting_an_account_removes_its_current_settings(env, monkeypatch):
    app, svc = _accounts_app(env, monkeypatch)
    c = _signup(app, "gone@example.org")
    _send(c, "PUT", "/api/settings/user", {"values": {CAP: 30}})
    uid = env.find("core_users")[0]["id"]
    assert env.get("settings_user", uid)
    assert _send(c, "POST", "/api/auth/account/delete", {"password": PW}).status_code == 200
    assert env.get("settings_user", uid) is None
    assert len(env.find("settings_audit")) == 1                                            # history stays, with the opaque id only


# ------------------------------------------------------------------------------------------------ provenance
def test_the_answer_records_the_settings_version_hash_and_snapshot(local):
    client, _ = local
    p = _parcel(client)
    ask = lambda: client.post("/api/parcels/%s/chat" % p["id"], json={"text": "When should I irrigate?",   # noqa: E731
                                                                      "advice_type": "irrigation_timing"}).json()
    plain = ask()["provenance"]["settings"]
    assert plain["n_overrides"] == 0 and plain["snapshot"] == {} and plain["hash"] == empty_summary()["hash"]
    client.put("/api/settings/global", json={"values": {CAP: 45}, "reason": "g"})
    client.put("/api/settings/user", json={"values": {"rules.irrigation.rain_wait_mm_3d": 8.0}})
    client.put("/api/settings/parcels/" + p["id"], json={"values": {CAP: 30}})
    run = ask()
    s = run["provenance"]["settings"]
    assert s["version"] == "g1.u1.p1" and s["n_overrides"] == 2 and len(s["hash"]) == 64 and s["hash"] != plain["hash"]
    assert s["snapshot"] == {CAP: {"value": 30, "layer": "parcel"}, "rules.irrigation.rain_wait_mm_3d": {"value": 8.0, "layer": "user"}}
    assert s["layers"] == {"global": 1, "user": 1, "parcel": 1}
    assert run["provenance"]["config_hashes"] == config.config_hashes()
    export = client.get("/api/runs/%s/provenance" % run["id"]).json()
    assert export["settings_used"] == s and export["run"]["provenance"]["settings"] == s
    assert ask()["provenance"]["settings"]["hash"] == s["hash"]                            # the same settings, the same hash
    client.post("/api/settings/parcels/%s/reset" % p["id"], json={"all": True})
    assert ask()["provenance"]["settings"]["hash"] != s["hash"]


def test_the_free_conversation_and_the_profile_also_use_the_overlay(local, monkeypatch):
    client, _ = local
    p = _parcel(client)
    seen = []
    real = config.load

    def spy(name):
        if name == "rules":
            seen.append(config.active_overlay() is not None)
        return real(name)
    monkeypatch.setattr(config, "load", spy)
    client.get("/api/parcels/%s/series" % p["id"])
    client.get("/api/parcels/%s/water-balance" % p["id"])
    client.post("/api/parcels/%s/profile/refresh" % p["id"])
    assert seen and all(seen)


# ------------------------------------------------------------------------------------------------ evaluation isolation
def test_evalkit_and_the_rating_endpoints_never_see_web_settings(local, monkeypatch):
    client, store = local
    client.put("/api/settings/global", json={"values": {CAP: 10}, "reason": "x"})
    assert config.active_overlay() is None and config.load("rules")["irrigation"]["max_single_net_mm"] == 50
    # no module of the core, the evaluation kit or the pipeline refers to the overlay or to the settings package
    base = STATIC.parents[1]
    for sub in ("core", "evalkit", "pipeline", "retrieval", "providers"):
        for path in (base / sub).rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            assert "web_settings" not in text and "use_overlay" not in text and "active_overlay" not in text, path
    # the blind rating endpoints and the evaluation views never enter an overlay
    entered = []
    real = config.use_overlay
    monkeypatch.setattr(config, "use_overlay", lambda o: (entered.append(o), real(o))[1])
    for path in ("/api/eval/rubric", "/api/eval/runs", "/api/eval/rating/next?rater=r1", "/api/evaluation/overview", "/api/llm",
                 "/api/health"):
        client.get(path)
    assert entered == []
    # while a request that computes an answer does
    p = _parcel(client)
    client.get("/api/parcels/%s/series" % p["id"])
    assert entered


def test_the_rating_screen_and_its_endpoints_are_unchanged():
    page = (STATIC / "index.html").read_text(encoding="utf-8")
    block = page[page.index('<section id="v-rate"'):page.index("</section>", page.index('<section id="v-rate"'))]
    assert 'lang="sr-Latn"' in block and "Slepo ocenjivanje" in block and "settings" not in block.lower()
    app_js = (STATIC / "app.js").read_text(encoding="utf-8")
    rating = app_js[app_js.index('$("r-next").onclick'):app_js.index("// ------", app_js.index('$("r-next").onclick'))]
    assert "SmartSettings" not in rating and "/settings" not in rating


def test_the_dev_set_decides_identically_with_an_empty_overlay(variants):
    """The 15 development scenarios (never the test set): every variant gives the same decision with and without an overlay."""
    dev = Path(__file__).resolve().parents[1] / "eval" / "scenarios" / "dev"
    from smartagri.core.types import Context
    passages = [Passage.from_dict(p) for p in yaml.safe_load((dev / "_passages.yaml").read_text(encoding="utf-8"))]
    files = sorted(p for p in dev.glob("*.yaml") if not p.name.startswith("_"))
    assert files
    for path in files:
        ctx = Context.from_dict(yaml.safe_load(path.read_text(encoding="utf-8"))["context"])
        for name in ("V0", "V1", "V2", "V3", "V4", "V5"):
            plain = json.dumps(decide(ctx, passages, variants[name]).to_dict(), sort_keys=True, default=str)
            with config.use_overlay(config.Overlay({}, empty_summary())):
                assert json.dumps(decide(ctx, passages, variants[name]).to_dict(), sort_keys=True, default=str) == plain, (path.stem, name)


# ------------------------------------------------------------------------------------------------ storage
def test_migration_0015_and_the_tables_are_additive(store):
    from smartagri import migrate
    assert [v[0] for v in migrate.VERSIONS][-2:] == ["0014", "0015"]
    assert {r["version"] for r in store._rows("SELECT version FROM schema_migrations")} >= {"0015"}
    from smartagri.store import TABLES
    for t in ("settings_global", "settings_user", "settings_parcel", "settings_limits", "settings_versions", "settings_audit"):
        assert t in TABLES
        store._rows("SELECT 1 FROM %s LIMIT 1" % t)


def test_service_level_rules_without_http(store):
    svc = SettingsService(store)
    me = Actor("u1", False, "optional")
    admin = Actor("adm", True, "optional")
    with pytest.raises(SettingsError) as e:
        svc.update(Actor(None), "user", None, {CAP: 30})
    assert e.value.status == 403
    with pytest.raises(SettingsError) as e:
        svc.update(me, "global", None, {CAP: 30}, "r")
    assert e.value.status == 403
    assert svc.update(admin, "global", None, {CAP: 30}, "r")["version"] == 1
    assert svc.update(me, "user", None, {CAP: 20})["version"] == 1
    ov = svc.overlay_for("u1")
    assert ov.values == {CAP: 20} and ov.meta["snapshot"][CAP]["layer"] == "user"
    assert svc.overlay_for("u2").values == {CAP: 30} and svc.overlay_for(None).values == {CAP: 30}


# ------------------------------------------------------------------------------------------------ the client
def _catalogue():
    text = (STATIC / "i18n.js").read_text(encoding="utf-8")
    return json.loads(text[text.index("/*CATALOGUE*/") + len("/*CATALOGUE*/"):text.index("/*END*/")])


def _settings_js_keys():
    script = (STATIC / "settings.js").read_text(encoding="utf-8")
    s = r'"((?:[^"\\]|\\.)*)"'
    keys = set(re.findall(r"\bt\(" + s, script))
    for name in ("MESSAGES", "STATUS", "LAYER"):
        block = re.search(r"const %s = \{(.*?)\};" % name, script, re.S).group(1)
        keys.update(re.findall(r":\s*" + s, block))
    keys.update({"set", "reset", "restore", "limit", "limits", "user", "parcel", "global"})       # t(v.action), t(LAYER[...])
    return keys


def test_settings_client_strings_are_translated_with_the_same_placeholders():
    sr = _catalogue()
    keys = _settings_js_keys()
    assert len(keys) > 120
    assert not sorted(k for k in keys if k not in sr)
    for k in keys:
        assert sorted(re.findall(r"\{\w+\}", k)) == sorted(re.findall(r"\{\w+\}", sr[k])), k
        assert sr[k].strip() and (sr[k] != k or k in ("limits",)), k
    page = (STATIC / "index.html").read_text(encoding="utf-8")
    for text in ("Agronomic settings", "Parcel settings", "Settings used"):
        assert sr[text]
    assert 'data-nav="settings"' in page and 'id="v-settings"' in page and 'id="p-set-card"' in page
    assert "settings.js" in page and page.index("settings.js") < page.index("app.js")


def test_settings_client_catalogue_has_no_english_left_and_is_ekavian():
    sr = _catalogue()
    english = {"the", "and", "of", "is", "are", "with", "from", "for", "not", "your", "this", "that", "data", "parcel",
               "answer", "weather", "soil", "water", "none", "only", "shown", "click", "press", "missing", "map", "draw",
               "save", "account", "password", "email", "sign", "set", "run", "file", "files", "days"}
    ijekavian = re.compile(r"\b(vrijem|prije|mjer|mjest|primjen|promjen|vrijed|lijep|bijel|riječ|sjem|mjesec|cijel|"
                           r"svjetl|gdje|djel|vjer|snijeg|tjed|slijed|procijen|cijen|uvijek)", re.I)
    for k in _settings_js_keys():
        text = re.sub(r"<code>.*?</code>|\{\w+\}|[\w.]*_[\w.]*", " ", sr[k])
        assert not set(re.findall(r"[A-Za-z]+", text.lower())) & english, (k, sr[k])
        assert not ijekavian.search(sr[k]), (k, sr[k])


def test_registry_labels_are_served_in_both_languages_without_english_in_the_local_one(local):
    client, _ = local
    english = {"the", "of", "is", "with", "for", "not", "this", "that", "data", "only", "set"}
    for e in client.get("/api/settings").json()["entries"]:
        words = set(re.findall(r"[A-Za-z]+", re.sub(r"\{\w+\}|[\w.]*_[\w.]*", " ", e["label"]["sr"] + " " + e["note"]["sr"]).lower()))
        assert not words & english, (e["key"], words & english)
