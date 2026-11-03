"""Protocol decisions of 2026-11-03: the E1-VC label, the origin of W and S per scenario, the minimum kappa."""
import pytest

from smartagri.evalkit import report, scenarios, tables


def test_analysis_plan_names_the_key_secondary_vc_comparison_outside_holm():
    plan = report.analysis_settings()
    assert plan["key_secondary_vc"]["name"] == "E1-VC" and plan["key_secondary_vc"]["comparison"] == ["V4", "VC"]
    assert all(m["comparison"] != ["V4", "VC"] for m in plan["holm"]["family"])


def _scores(with_vc=True):
    scores = {"V3": {"s1": {"k4_or_k5": 1.0, "total": 5.0}, "s2": {"k4_or_k5": 1.0, "total": 5.0}},
              "V4": {"s1": {"k4_or_k5": 0.0, "total": 7.0}, "s2": {"k4_or_k5": 0.0, "total": 8.0}}}
    if with_vc:
        scores["VC"] = {"s1": {"k4_or_k5": 1.0, "total": 6.0}, "s2": {"k4_or_k5": 0.0, "total": 6.0}}
    return scores


def test_e1_vc_table_is_labelled_and_says_when_vc_was_not_run():
    meta = {"s1": {"cluster": "s1"}, "s2": {"cluster": "s2"}}
    md = tables.table_e1_vc(_scores(), meta)
    assert "Tabela 7.2a. E1-VC: V4 prema VC" in md and "Holm" in md
    assert "nema ocenjene stavke" in tables.table_e1_vc(_scores(with_vc=False), meta)
    assert "nije podešen" in tables.table_e1_vc(_scores(), meta, settings={})


def test_input_origin_record_is_checked_per_scenario():
    assert scenarios.input_origin_issues({"id": "A"}) == ["A: input_origin is missing"]
    ok = {"id": "A", "input_origin": {"weather": "previous_runs", "satellite": "real"}}
    assert scenarios.input_origin_issues(ok) == []
    bad = {"id": "B", "input_origin": {"weather": "guess", "satellite": "real"}}
    assert any("weather" in p for p in scenarios.input_origin_issues(bad))
    degraded = {"id": "C", "input_origin": {"weather": "previous_runs", "satellite": "degraded"}}
    assert any("degradation" in p for p in scenarios.input_origin_issues(degraded))
    degraded["input_origin"]["degradation"] = "latest scene moved 14 days back, 30 % usable pixels"
    assert scenarios.input_origin_issues(degraded) == []


def test_origin_summary_counts_scenarios_once_and_lists_missing_and_degraded():
    items = [{"scenario_id": "A", "input_origin": {"weather": "previous_runs", "satellite": "real"}},
             {"scenario_id": "A", "input_origin": {"weather": "previous_runs", "satellite": "real"}},
             {"scenario_id": "B", "input_origin": {"weather": "previous_runs", "satellite": "degraded", "degradation": "old scene"}},
             {"scenario_id": "C"}]
    o = report.origin_summary(items)
    assert o["n_scenarios"] == 3 and o["counts"] == {"previous_runs / real": 1, "previous_runs / degraded": 1}
    assert o["degradations"] == {"B": "old scene"} and o["missing"] == ["C"]
    md = tables.table_origin(items)
    assert "Tabela 7.1a" in md and "old scene" in md and "Bez zapisa o poreklu: C" in md


def test_minimum_kappa_is_read_from_the_plan_and_applied():
    assert report.min_kappa() == 0.60
    assert report.min_kappa({}) is None
    assert report.kappa_status(0.61, 0.60) == "reached" and report.kappa_status(0.59, 0.60) == "not reached"
    assert report.kappa_status(None, 0.60) == "not estimable" and report.kappa_status(0.9, None) == "no minimum set"
    for bad in (0, 1.5, "x", True):
        with pytest.raises(ValueError):
            report.min_kappa({"agreement": {"min_kappa": bad}})
    agree = {"n_items": 20, "r1": {"kappa_quadratic": 0.8, "kappa_ci95": [0.6, 0.9], "percent_agreement": 0.9},
             "r2": {"kappa_quadratic": 0.4, "kappa_ci95": [0.1, 0.7], "percent_agreement": 0.7}}
    md = tables.table_agreement(agree, ("a", "b"))
    assert "dostignuto" in md and "nije dostignuto" in md and "κ ≥ 0,60" in md.replace("0.60", "0,60") or "κ ≥ 0.6" in md


def test_origin_command_fails_until_every_scenario_records_its_inputs(tmp_path, capsys):
    import yaml
    from smartagri.evalkit.__main__ import main
    (tmp_path / "A.yaml").write_text(yaml.safe_dump({"id": "A", "input_origin": {"weather": "previous_runs", "satellite": "real"}}))
    assert main(["origin", "--set", "dev", "--scenarios-dir", str(tmp_path)]) == 0
    (tmp_path / "B.yaml").write_text(yaml.safe_dump({"id": "B"}))
    assert main(["origin", "--set", "dev", "--scenarios-dir", str(tmp_path)]) == 1
    assert "B: input_origin is missing" in capsys.readouterr().out
