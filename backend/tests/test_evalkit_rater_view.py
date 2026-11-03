"""What the blind rater sees of the inputs: the raw facts (value, origin, age, coverage), not the grades of the q layer.
`rater_view: raw | graded` in config/evaluation.yaml (default raw)."""
import pytest

from smartagri.evalkit import rating, runner, settings
from smartagri.evalkit.scenarios import load_scenario
from smartagri.core.types import Context
from smartagri.store import SqliteStore

GRADE_KEYS = {"reliability", "reliability_label", "basis", "detail"}
RAW_KEYS = {"input", "label", "value_text", "origin", "origin_label", "age_days", "coverage"}


def _view(rater_view):
    sc = load_scenario("dev", "IRR-T-02")
    return runner.scenario_view(sc, Context.from_dict(sc["context"]), rater_view)


def test_the_default_is_raw_and_the_setting_is_validated(monkeypatch):
    assert settings.rater_view() == "raw"
    monkeypatch.setattr(settings.config, "load", lambda name: {"rater_view": "bright"})
    with pytest.raises(settings.SettingsError):
        settings.rater_view()
    monkeypatch.setattr(settings.config, "load", lambda name: {"rater_view": "graded"})
    assert settings.rater_view() == "graded"
    monkeypatch.setattr(settings.config, "load", lambda name: {})
    assert settings.rater_view() == "raw"


def test_raw_view_shows_the_facts_without_any_grade():
    rows = _view("raw")["quality"]
    assert rows and all(set(r) <= RAW_KEYS and "input" in r and "value_text" in r for r in rows)
    assert not any(GRADE_KEYS & set(r) for r in rows)
    assert any(r["origin"] and r["age_days"] is not None for r in rows)       # origin and age are the facts that stay


def test_graded_view_keeps_the_quality_table_as_before():
    rows = _view("graded")["quality"]
    assert all(GRADE_KEYS - {"detail"} <= set(r) for r in rows)
    assert [r["input"] for r in rows] == [r["input"] for r in _view("raw")["quality"]]    # the same inputs, in the same order


def test_the_rest_of_the_view_is_the_same_in_both():
    raw, graded = _view("raw"), _view("graded")
    for k in ("id", "question", "advice_type_label", "context_text"):
        assert raw[k] == graded[k]


def test_the_blind_queue_strips_grades_when_the_setting_is_raw(monkeypatch):
    store = SqliteStore(":memory:")
    graded = _view("graded")
    store.save_eval_item({"id": "i1", "set": "dev", "batch_id": "b", "scenario_id": "S", "variant": "V4", "repeat": 1,
                          "rateable": True, "scenario": graded, "created_at": "x",
                          "turns": [{"question": "q", "answer": {"act": "ask", "generator": "template"}, "user_reply": None}]})
    nxt = rating.next_item(store, "r", "dev")
    assert not any(GRADE_KEYS & set(r) for r in nxt["scenario"]["quality"])           # an item stored graded is shown raw
    monkeypatch.setattr(settings.config, "load", lambda name: {"rater_view": "graded"})
    nxt = rating.next_item(store, "r", "dev")
    assert all("reliability" in r for r in nxt["scenario"]["quality"])
    assert "generator" not in nxt["turns"][0]["answer"]


def test_a_stored_item_records_the_view_it_was_run_with():
    assert _view("raw")["rater_view"] == "raw" and _view("graded")["rater_view"] == "graded"
