"""Code, config/analysis.yaml and docs/protocol.md agree on the plan: primary outcome K4 or K5, key secondary outcomes,
the Holm family of the first lock, E5 outside the first lock (a switch), and no test evaluated with an undecided margin."""
import pytest

from smartagri.evalkit import lock, report, tables
from smartagri.store import SqliteStore

PLAN = report.analysis_settings()


def test_analysis_yaml_states_the_plan_of_the_first_lock():
    assert PLAN["primary"]["comparison"] == ["V4", "V3"] and PLAN["primary"]["measure"] == "k4_or_k5"
    assert PLAN["primary"]["classes"] == ["K4", "K5"]
    assert PLAN["scope"] == {"variants": ["V3", "V4", "VC"], "include_e5": False}
    family = {m["name"]: (tuple(m["comparison"]), m["measure"]) for m in PLAN["holm"]["family"]}
    assert family == {"E1-rubrika": (("V4", "V3"), "total"), "E1-K1": (("V4", "V3"), "K1"),
                      "E1-K2": (("V4", "V3"), "K2"), "E1-K3": (("V4", "V3"), "K3"),
                      "E1-prvi-cin": (("V4", "V3"), "act_correct")}
    assert PLAN["noninferiority"]["margin"] is None and PLAN["equivalence"]["margin"] is None


def test_the_protocol_text_names_the_same_plan():
    text = lock.default_analysis_plan().read_text(encoding="utf-8")
    assert "K4 ∪ K5" in text and "k4_or_k5" in text
    assert "One primary outcome: the rate of scenarios with a K4 or K5 error" in text
    for m in PLAN["holm"]["family"]:
        assert m["name"] in text, m["name"]
    assert "E5 is not in the first lock" in text and "include_e5" in text
    assert "K1 cannot occur while `quantity_validated` is false" in text


def _store(clusters=6, k4_v3=(0, 1, 2), k5_v3=(), k1_v3=()):
    """V4 and V3 items and ratings of `clusters` scenarios, one parcel each."""
    store = SqliteStore(":memory:")
    for c in range(clusters):
        for v in ("V3", "V4"):
            iid = "%s-%d" % (v, c)
            store.save_eval_item({"id": iid, "variant": v, "scenario_id": "S%d" % c, "stratum": "complete",
                                  "cluster": "p%d" % c, "first_act": "recommend", "final_act": "recommend", "n_turns": 1,
                                  "first_question_input": None, "expect": {"act": "recommend"}, "reference": None,
                                  "retrieval": None, "repeat": 1, "batch_id": "b", "set": "test", "rateable": True,
                                  "created_at": "2026-10-29T10:00:00", "turns": [], "records": []})
            crit = []
            if v == "V3":
                crit = (["K4"] if c in k4_v3 else []) + (["K5"] if c in k5_v3 else []) + (["K1"] if c in k1_v3 else [])
            store.save_rating({"id": "r" + iid, "item_id": iid, "rater": "agro", "r1": 2, "r2": 2, "r3": 2, "r4": 2, "r5": 2,
                               "critical": crit, "comment": "", "created_at": "x"})
    return store


def test_the_primary_measure_is_k4_or_k5_not_any_class():
    store = SqliteStore(":memory:")
    base = {"variant": "V3", "stratum": "complete", "cluster": "p", "first_act": "recommend", "final_act": "recommend",
            "n_turns": 1, "first_question_input": None, "expect": None, "reference": None, "retrieval": None, "repeat": 1,
            "batch_id": "b", "set": "test", "rateable": True, "created_at": "x", "turns": [], "records": []}
    for n, crit in enumerate((["K1"], ["K4"], ["K5"], ["K2", "K3"], [])):
        store.save_eval_item(dict(base, id="i%d" % n, scenario_id="S%d" % n))
        store.save_rating({"id": "r%d" % n, "item_id": "i%d" % n, "rater": "a", "r1": 1, "r2": 1, "r3": 1, "r4": 1, "r5": 1,
                           "critical": crit, "comment": "", "created_at": "x"})
    scores = report.scenario_scores(store, store.list_eval_items(), "a")["V3"]
    assert [scores["S%d" % n]["k4_or_k5"] for n in range(5)] == [0.0, 1.0, 1.0, 0.0, 0.0]
    assert [scores["S%d" % n]["critical"] for n in range(5)] == [1.0, 1.0, 1.0, 1.0, 0.0]
    assert report.primary_measure({"primary": {"measure": "k4_or_k5"}}) == "k4_or_k5"
    with pytest.raises(ValueError):
        report.primary_measure({"primary": {"measure": "critical_typo"}})
    r = report.rated(store, store.list_eval_items(), "a")["V3"]
    assert r["k4_or_k5_rate"] == 0.4 and r["critical_rate"] == 0.8


def test_the_report_leads_with_k4_or_k5_and_draws_the_e1_verdict():
    store = _store()
    items = store.list_eval_items()
    md = tables.render(store, items, "agro", None)
    assert "K4 ∪ K5" in md.split("Tabela 7.3.")[0]                        # the first row of the primary table
    assert "E1 (primarno, K4 ∪ K5)" in md and "nije procenjivo" not in md.split("Tabela 7.3.")[0]
    scores = report.scenario_scores(store, items, "agro")
    p = report.paired_measure(scores, "V4", "V3", "k4_or_k5", report.scenario_meta(items))
    assert p["diff"] == -0.5 and p["ci_status"] == "ok"
    verdict = tables.e1_verdict(p)
    assert verdict in ("podržano", "neodređeno")


def test_e1_verdict_wording():
    ok = {"ci95": (-0.4, -0.1), "ci_status": "ok", "diff": -0.25}
    assert tables.e1_verdict(ok) == "podržano"
    assert tables.e1_verdict(dict(ok, ci95=(-0.3, 0.05))) == "neodređeno"
    assert tables.e1_verdict({"ci95": None, "ci_status": "not_estimable", "ci_note": "2 clusters", "diff": -0.5}) == \
        "nije procenjivo (2 clusters)"
    assert tables.e1_verdict(None) == tables.DASH


def test_holm_family_of_the_first_lock():
    store = _store(clusters=8, k4_v3=(0, 1), k5_v3=(2,), k1_v3=())
    items = store.list_eval_items()
    scores = report.scenario_scores(store, items, "agro")
    rows = report.holm_family(scores, report.scenario_meta(items), PLAN)
    names = [r["name"] for r in rows]
    assert names == ["E1-rubrika", "E1-K1", "E1-K2", "E1-K3", "E1-prvi-cin"]
    by = {r["name"]: r for r in rows}
    assert by["E1-K1"]["p"] is None and by["E1-K1"]["p_holm"] is None          # no variation: not counted in the family
    assert by["E1-rubrika"]["p"] is None or 0 <= by["E1-rubrika"]["p"] <= 1
    md = tables.table_holm(scores, report.scenario_meta(items), PLAN)
    assert "Holm" in md and "E1-K2" in md


def test_e5_is_outside_the_first_lock_unless_switched_on():
    store = _store()
    md = tables.render(store, store.list_eval_items(), "agro", None)
    assert "Tabela 7.10." not in md and "E5 nije u prvom zaključavanju" in md
    on = dict(PLAN, scope=dict(PLAN["scope"], include_e5=True))
    md = tables.render(store, store.list_eval_items(), "agro", None, settings=on)
    assert "Tabela 7.10." in md


def test_a_test_with_an_undecided_margin_is_not_evaluated_and_says_why():
    diffs = [0.1, -0.1, 0.0, 0.2] * 5
    ni = report.noninferiority(diffs, None)
    assert ni["status"] == "not_evaluated" and ni["noninferior"] is None and ni["ci"] is None
    assert "margin" in ni["reason"] and "protocol owner" in ni["reason"]
    eq = report.equivalence(diffs, None)
    assert eq["status"] == "not_evaluated" and eq["equivalent"] is None and "margin" in eq["reason"]
    assert report.noninferiority(diffs, 0.5)["status"] == "ok"
    for bad in (0, -1.0, "x"):
        with pytest.raises(ValueError):
            report.noninferiority(diffs, bad)
        with pytest.raises(ValueError):
            report.equivalence(diffs, bad)
    md = tables.equivalence_note({"V4": {"S": {"total": 1.0}}, "V3": {"S": {"total": 1.0}}},
                                 {"S": {"stratum": "complete", "cluster": "S"}})
    assert "nije ocenjeno" in md and "granica nije zadata" in md
