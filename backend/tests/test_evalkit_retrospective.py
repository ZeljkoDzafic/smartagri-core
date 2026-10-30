"""Retrospective pairs (parcel x decision moment, outcome realised later): loader with fail-loud and leakage rules, the
set names that are protected like the test set, the fixed decision hour, and the pure rain-wait outcome function.

Nothing is fetched and no real data is used; pairs are written to a temporary folder outside the repository."""
import copy
import json
from datetime import date, datetime, timezone

import pytest
import yaml

from smartagri.evalkit import retrospective as retro
from smartagri.evalkit import scenarios
from smartagri.evalkit.__main__ import main as cli
from smartagri.evalkit.scenarios import scenario_dir

DEV = scenario_dir("dev")
PAIR = {
    "schema": "smartagri-retrospective-pair/1", "id": "RET-2025-001", "season": 2025, "parcel_code": "P01",
    "stratum": "6th-leaf-to-tasselling:irrigation_timing",
    "decision_at": "2025-07-14T08:00:00+02:00", "advice_type": "irrigation_timing",
    "question": "Da li sutra da navodnjavam kukuruz?",
    "context": {"P": {"parcel_id": "P01", "area_ha": 2.1, "centroid_lat": 44.9, "centroid_lon": 17.3, "region_class": "pannonian"},
                "A": {"sowing_date": "2025-04-25", "irrigation_available": "yes", "irrigation_system_type": "sprinkler"},
                "W": {"origin": "modeled", "precip_past_7d_mm": 2.0, "et0_past_7d_mm": 38.0, "precip_forecast_3d_mm": 18.0,
                      "precip_forecast_7d_mm": 22.0, "forecast_issued_at": "2025-07-14T04:00:00+02:00", "horizon_days": 7}},
    "weather_snapshot": {"source": "previous-runs", "model": "best_match", "ref": "cache:0123abcd",
                         "issued_before": "2025-07-14T04:00:00+02:00"},
    "outcome": {"source": "station", "daily_precip_mm": {"2025-07-14": 0.0, "2025-07-15": 12.0, "2025-07-16": 9.5,
                                                         "2025-07-17": 0.0}},
}


def _write(folder, *pairs):
    folder.mkdir(exist_ok=True)
    for p in pairs:
        (folder / ("%s.json" % p["id"])).write_text(json.dumps(p), encoding="utf-8")
    return folder


def _pair(**changes):
    p = copy.deepcopy(PAIR)
    for k, v in changes.items():
        p[k] = v
    return p


def test_a_valid_pair_loads_as_a_scenario_with_the_outcome_kept_apart(tmp_path):
    folder = _write(tmp_path / "retro", PAIR)
    (sc,) = retro.load_pairs(folder, season=2025)
    assert sc["id"] == "RET-2025-001" and sc["cluster"] == "P01" and sc["stratum"].startswith("6th-leaf")
    ctx = sc["context"]
    assert ctx["Q"] == {"text": PAIR["question"], "advice_type": "irrigation_timing"} and ctx["as_of"] == PAIR["decision_at"]
    assert "outcome" not in json.dumps(ctx) and "daily_precip_mm" not in json.dumps(ctx)       # the system never sees it
    assert sc["outcome"]["daily_precip_mm"]["2025-07-15"] == 12.0
    assert sc["retrospective"]["weather_snapshot"]["ref"] == "cache:0123abcd" and sc["retrospective"]["season"] == 2025
    from smartagri.core.types import Context
    assert Context.from_dict(ctx).Q.text == PAIR["question"]                                    # a normal scenario context
    from smartagri.evalkit import guard
    assert ("question", PAIR["question"]) in guard.scenario_fields(sc)                          # the leakage guard reads it


@pytest.mark.parametrize("change, message", [
    ({"unexpected": 1}, "unknown field"),
    ({"schema": "other"}, "schema"),
    ({"season": 2024}, "season 2024"),
    ({"decision_at": "2025-07-14T08:00:00"}, "UTC offset"),
    ({"advice_type": "astrology"}, "advice_type"),
    ({"weather_snapshot": {"source": "previous-runs", "ref": "x", "issued_before": "2025-07-14T09:00:00+02:00"}},
     "issued after the decision"),
    ({"weather_snapshot": {"source": "previous-runs"}}, "weather_snapshot"),
    ({"outcome": {"source": "station", "daily_precip_mm": {"2025-07-13": 1.0}}}, "before the decision"),
    ({"outcome": {"source": "station"}}, "daily_precip_mm"),
    ({"outcome": {"source": "station", "daily_precip_mm": {"2025-07-15": -1.0}}}, "negative"),
    ({"context": dict(PAIR["context"], outcome={"rain": 12})}, "outcome"),
    ({"context": dict(PAIR["context"], as_of="2025-07-14T08:00:00+02:00")}, "as_of"),
    ({"context": dict(PAIR["context"], Q={"text": "x"})}, "Q"),
    ({"context": dict(PAIR["context"], A={"sowing_date": "2025-04-25", "last_irrigation_date": "2025-07-20"})},
     "dated after the decision"),
    ({"context": dict(PAIR["context"], S={"ndvi_series": [{"obs_date": "2025-07-15", "median": 0.6, "usable_share": 0.9}]})},
     "after the decision"),
])
def test_a_malformed_or_leaking_pair_fails_loudly(tmp_path, change, message):
    folder = _write(tmp_path / "retro", _pair(**change))
    with pytest.raises(retro.RetrospectiveError, match=message):
        retro.load_pairs(folder, season=2025)


def test_duplicate_ids_and_empty_or_unreadable_folders_fail(tmp_path):
    folder = _write(tmp_path / "retro", PAIR)
    (folder / "copy.json").write_text(json.dumps(PAIR), encoding="utf-8")
    with pytest.raises(retro.RetrospectiveError, match="duplicate"):
        retro.load_pairs(folder)
    (folder / "copy.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(retro.RetrospectiveError, match="copy.json"):
        retro.load_pairs(folder)
    (tmp_path / "e").mkdir()
    with pytest.raises(retro.RetrospectiveError, match="no pair files"):
        retro.load_pairs(tmp_path / "e")
    with pytest.raises(retro.RetrospectiveError, match="not a folder"):
        retro.load_pairs(tmp_path / "missing")


def test_the_folder_must_be_outside_the_repository():
    inside = scenario_dir("dev")
    with pytest.raises(retro.RetrospectiveError, match="outside the repository"):
        retro.load_pairs(inside)


def test_set_names_map_to_seasons_and_the_test_season_is_protected(tmp_path, monkeypatch):
    assert scenarios.RETRO_SETS == {"retrospective-dev": 2024, "retrospective-test": 2025}
    assert "retrospective-test" in scenarios.PROTECTED_SETS and "retrospective-dev" not in scenarios.PROTECTED_SETS
    folder = _write(tmp_path / "retro", PAIR)
    assert [s["id"] for s in scenarios.load_scenarios("retrospective-test", folder)] == ["RET-2025-001"]
    with pytest.raises(retro.RetrospectiveError, match="season 2025"):
        scenarios.load_scenarios("retrospective-dev", folder)                              # the 2025 pair is not development
    monkeypatch.delenv("SMARTAGRI_RETRO_DIR", raising=False)
    with pytest.raises(retro.RetrospectiveError, match="SMARTAGRI_RETRO_DIR"):
        scenarios.scenario_dir("retrospective-test")
    monkeypatch.setenv("SMARTAGRI_RETRO_DIR", str(tmp_path))
    assert scenarios.scenario_dir("retrospective-test") == tmp_path / "retrospective-test"


def test_a_protected_retrospective_set_runs_only_locked_and_a_dev_run_over_it_is_refused(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("LLM_PROVIDER", "template")
    monkeypatch.setenv("EMBEDDINGS_PROVIDER", "none")
    monkeypatch.setenv("SMARTAGRI_DB", str(tmp_path / "e.sqlite"))
    folder = _write(tmp_path / "retro", PAIR)
    assert cli(["run", "--set", "retrospective-test", "--scenarios-dir", str(folder), "--variant", "V4"]) == 2
    assert "--locked" in capsys.readouterr().err
    # the development season runs freely, and the pair is answered like any scenario; the outcome is stored, not shown
    dev = _write(tmp_path / "retro_dev", _pair(id="RET-2024-001", season=2024,
                                                 decision_at="2024-07-14T08:00:00+02:00",
                                                 weather_snapshot=dict(PAIR["weather_snapshot"], issued_before="2024-07-14T04:00:00+02:00"),
                                                 outcome={"source": "station", "daily_precip_mm": {"2024-07-15": 3.0}},
                                                 context=dict(PAIR["context"], W=dict(PAIR["context"]["W"], forecast_issued_at="2024-07-14T04:00:00+02:00"),
                                                              A={"sowing_date": "2024-04-25", "irrigation_available": "yes"})))
    assert cli(["run", "--set", "retrospective-dev", "--scenarios-dir", str(dev), "--variant", "V4"]) == 0
    from smartagri.store import make_store
    (item,) = make_store().list_eval_items()
    assert item["scenario_id"] == "RET-2024-001" and item["outcome"]["daily_precip_mm"] == {"2024-07-15": 3.0}
    assert item["retrospective"]["season"] == 2024 and "outcome" not in json.dumps(item["scenario"])
    from smartagri.evalkit import rating
    blind = rating.next_item(make_store(), "r", "retrospective-dev")
    assert "outcome" not in json.dumps(blind) and "weather_snapshot" not in json.dumps(blind)


# ---------------------------------------------------------------- the fixed decision hour (also for ordinary scenarios)

def test_decision_hour_is_unset_by_default_and_fixes_the_instant_when_given(tmp_path):
    base = scenarios.load_scenarios("dev", DEV)
    assert base == scenarios.load_scenarios("dev", DEV, decision_hour_utc=None)               # no behaviour change by default
    folder = tmp_path / "aware"
    folder.mkdir()
    doc = yaml.safe_load((DEV / "IRR-T-04_rain_coming.yaml").read_text(encoding="utf-8"))
    doc["context"]["as_of"] = "2026-07-12T06:00:00+02:00"
    doc["context"]["W"]["forecast_issued_at"] = "2026-07-12T04:00:00+02:00"
    (folder / "a.yaml").write_text(yaml.safe_dump(doc), encoding="utf-8")
    (sc,) = scenarios.load_scenarios("dev", folder, decision_hour_utc=10)
    assert datetime.fromisoformat(sc["context"]["as_of"]) == datetime(2026, 7, 12, 10, tzinfo=timezone.utc)
    (sc,) = scenarios.load_scenarios("dev", folder)
    assert str(sc["context"]["as_of"]).startswith("2026-07-12") and sc["context"]["as_of"] != "2026-07-12T10:00:00+00:00"
    with pytest.raises(ValueError, match="another local day"):
        scenarios.load_scenarios("dev", folder, decision_hour_utc=23)                            # 01:00 the next day at +02
    with pytest.raises(ValueError, match="hour"):
        scenarios.load_scenarios("dev", folder, decision_hour_utc=24)
    with pytest.raises(ValueError, match="UTC offset"):
        scenarios.load_scenarios("dev", DEV, decision_hour_utc=10)                              # the dev files are naive


def test_decision_hour_on_a_pair_is_checked_against_everything_dated(tmp_path):
    folder = _write(tmp_path / "retro", PAIR)
    (sc,) = retro.load_pairs(folder, decision_hour_utc=9)
    assert datetime.fromisoformat(sc["context"]["as_of"]) == datetime(2025, 7, 14, 9, tzinfo=timezone.utc)
    assert sc["retrospective"]["decision_hour_utc"] == 9
    with pytest.raises(retro.RetrospectiveError, match="issued after the decision"):
        retro.load_pairs(folder, decision_hour_utc=1)                                           # the snapshot is from 02:00 UTC


# ---------------------------------------------------------------- the objective outcome of rain-wait advice

PARAMS = dict(window_days=3, threshold_mm=5.0, effect_lag_days=1, include_decision_day=False)
RAIN = {"2025-07-14": 0.0, "2025-07-15": 2.0, "2025-07-16": 4.0, "2025-07-17": 1.0}


def test_the_outcome_function_has_no_defaults_for_the_undecided_parameters():
    import inspect
    sig = inspect.signature(retro.rain_wait_outcome)
    undecided = ("window_days", "threshold_mm", "effect_lag_days", "include_decision_day")
    assert all(sig.parameters[k].default is inspect.Parameter.empty and sig.parameters[k].kind is inspect.Parameter.KEYWORD_ONLY
               for k in undecided)
    with pytest.raises(TypeError):
        retro.rain_wait_outcome("wait", date(2025, 7, 14), RAIN)


def test_wait_advice_is_contrary_when_the_rain_did_not_come():
    out = retro.rain_wait_outcome("wait", date(2025, 7, 14), RAIN, **PARAMS)
    assert out["evaluable"] and out["rain_mm"] == 7.0 and out["window"] == ["2025-07-15", "2025-07-17"]
    assert out["contrary"] is False                                                             # 7 mm >= 5 mm: waiting was justified
    dry = dict(RAIN, **{"2025-07-16": 0.5})
    assert retro.rain_wait_outcome("wait", date(2025, 7, 14), dry, **PARAMS)["contrary"] is True
    exact = dict(RAIN, **{"2025-07-16": 2.0})
    assert retro.rain_wait_outcome("wait", date(2025, 7, 14), exact, **PARAMS)["contrary"] is False   # exactly the threshold


def test_irrigate_now_advice_is_contrary_when_the_rain_came_before_it_could_act():
    rain = {"2025-07-15": 6.0, "2025-07-16": 0.0}
    out = retro.rain_wait_outcome("irrigate_now", date(2025, 7, 14), rain, **PARAMS)
    assert out["contrary"] is True and out["window"] == ["2025-07-15", "2025-07-15"] and out["rain_mm"] == 6.0
    late = {"2025-07-15": 1.0, "2025-07-16": 9.0}
    assert retro.rain_wait_outcome("irrigate_now", date(2025, 7, 14), late, **PARAMS)["contrary"] is False


def test_the_decision_day_counts_only_when_asked():
    rain = dict(RAIN, **{"2025-07-14": 8.0})
    a = retro.rain_wait_outcome("wait", date(2025, 7, 14), rain, **dict(PARAMS, include_decision_day=True))
    assert a["window"] == ["2025-07-14", "2025-07-16"] and a["rain_mm"] == 14.0
    assert retro.rain_wait_outcome("wait", date(2025, 7, 14), rain, **PARAMS)["rain_mm"] == 7.0


def test_incomplete_data_or_other_advice_is_not_evaluable_never_guessed():
    gap = {"2025-07-15": 2.0, "2025-07-17": 1.0}
    out = retro.rain_wait_outcome("wait", "2025-07-14", gap, **PARAMS)
    assert out["evaluable"] is False and out["contrary"] is None and "2025-07-16" in out["reason"]
    none = dict(RAIN, **{"2025-07-16": None})
    assert retro.rain_wait_outcome("wait", date(2025, 7, 14), none, **PARAMS)["evaluable"] is False
    other = retro.rain_wait_outcome("recheck", date(2025, 7, 14), RAIN, **PARAMS)
    assert other["evaluable"] is False and "rain-wait" in other["reason"]
    for bad in (dict(PARAMS, window_days=0), dict(PARAMS, threshold_mm=-1), dict(PARAMS, effect_lag_days=0)):
        with pytest.raises(ValueError):
            retro.rain_wait_outcome("wait", date(2025, 7, 14), RAIN, **bad)


def test_advice_kind_from_the_core_action():
    assert retro.advice_kind("wait_for_rain") == "wait" and retro.advice_kind("irrigate_within_2d") == "irrigate_now"
    assert retro.advice_kind("recheck_in_3d") is None and retro.advice_kind(None) is None


# ---------------------------------------------------------------- the lock covers pairs and the decision hour

def test_a_retrospective_folder_is_locked_and_the_decision_hour_is_part_of_the_lock(tmp_path, monkeypatch, capsys):
    from smartagri.evalkit import lock
    monkeypatch.setattr(lock, "git_state", lambda: {"git": True, "commit": "0" * 40, "dirty": []})
    monkeypatch.setenv("LLM_PROVIDER", "template")
    monkeypatch.setenv("EMBEDDINGS_PROVIDER", "none")
    monkeypatch.setenv("SMARTAGRI_DB", str(tmp_path / "e.sqlite"))
    folder = _write(tmp_path / "retro", PAIR)
    snap = tmp_path / "snap.tar"
    snap.write_bytes(b"snapshot")
    out = tmp_path / "lock.json"
    assert cli(["lock", "--set", "retrospective-test", "--scenarios-dir", str(folder), "--cache-snapshot", str(snap),
                "--out", str(out), "--decision-hour-utc", "9"]) == 0
    data = json.loads(out.read_text())
    assert data["run"]["decision_hour_utc"] == 9 and any(k.startswith("scenarios/RET-2025-001") for k in data["files"])
    capsys.readouterr()
    base = ["run", "--set", "retrospective-test", "--locked", "--lock-file", str(out), "--lock-sha256", lock.lock_sha256(out),
            "--scenarios-dir", str(folder), "--variant", "V4"]
    assert cli(base) == 2 and "changed: decision_hour_utc" in capsys.readouterr().err        # the hour is locked
    assert cli(base + ["--decision-hour-utc", "9"]) == 0
    from smartagri.store import make_store
    (item,) = make_store().list_eval_items()
    assert item["decision_hour_utc"] == 9 and item["retrospective"]["decision_hour_utc"] == 9
    assert item["lock_sha256"] == lock.lock_sha256(out)
    pair_file = folder / "RET-2025-001.json"
    pair_file.write_text(pair_file.read_text().replace("12.0", "13.0"))                       # an outcome edited after the lock
    assert cli(base + ["--decision-hour-utc", "9"]) == 2 and "changed: scenarios/RET-2025-001.json" in capsys.readouterr().err
