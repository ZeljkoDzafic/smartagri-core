"""Leakage guard, synthetic sweep, retrieval/citation measures and markdown report.

Everything here uses synthetic data or development scenarios; the test set is never read."""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from smartagri.evalkit import guard, report, sources, sweep, tables
from smartagri.evalkit.__main__ import main as cli
from smartagri.evalkit.scenarios import load_scenario
from smartagri.store import SqliteStore

SRC = Path(__file__).resolve().parents[1] / "src"
PASSAGE = ("Kukuruz je najosetljiviji na nedostatak vode u periodu metličenja i svilanja. Ako je zemljište "
           "u zoni korena suvo, a padavine nisu najavljene, navodnjavanje u ovoj fazi ne treba odlagati.")


# ---------------------------------------------------------------- leakage guard

def _sc(**fields):
    base = {"id": "S-1", "question": "Da li da navodnjavam?", "context": {"Q": {"text": "Da li da navodnjavam?"}}}
    base.update(fields)
    return base


def test_guard_words_fold_like_retrieval_without_stemming():
    assert guard.words("Đubrivo i NAVODNJAVANJE") == ["djubrivo", "navodnjavanje"]   # folded, stop word dropped
    assert guard.words("navodnjavanja")[0] != guard.words("navodnjavanje")[0]          # no stem truncation


def test_guard_flags_half_of_8grams():
    passages = [{"id": "p1", "text": PASSAGE}, {"id": "p2", "text": "Prskanje se obavlja po mirnom vremenu."}]
    # two copied runs of 11 words, broken by one inserted word: half the 8-grams shared, no 12-word span
    text = ("Kukuruz je najosetljiviji na nedostatak vode u periodu metličenja i svilanja, ako je zemljište u zoni korena, "
            "inače u zoni korena suvo, a padavine nisu najavljene, navodnjavanje u ovoj fazi ne treba odlagati.")
    res = guard.check([_sc(reference={"notes_for_rater": text})], passages)
    hits = res["hits"]
    assert [h["passage"] for h in hits] == ["p1"] and hits[0]["field"] == "reference.notes_for_rater"
    assert hits[0]["shared_8gram_share"] == 0.5 and not hits[0]["exact_12_span"]
    assert guard.check([_sc(note=text)], passages, share=0.6)["hits"] == []


def test_guard_flags_exact_12_word_span_below_share():
    long_text = ("Ovo je dugačka napomena za ocenjivača koja opisuje parcelu, setvu, zemljište, prognozu i mnogo "
                 "drugih okolnosti koje nemaju veze sa izvorom, a onda navodi: ako je zemljište u zoni korena suvo, "
                 "a padavine nisu najavljene, navodnjavanje u ovoj fazi ne treba odlagati.")
    res = guard.check([_sc(scenario_note=long_text)], [{"id": "p1", "text": PASSAGE}])
    assert len(res["hits"]) == 1
    hit = res["hits"][0]
    assert hit["exact_12_span"] and hit["shared_8gram_share"] < 0.5


def test_guard_checks_user_replies_and_reference_lists_but_not_source_ids():
    sc = _sc(user_replies={"soil_water_status": PASSAGE},
             reference={"acceptable_actions": ["nešto sasvim drugo"], "applicable_sources": [PASSAGE]})
    res = guard.check([sc], [{"id": "p1", "text": PASSAGE}])
    assert [h["field"] for h in res["hits"]] == ["user_replies.soil_water_status"]
    paths = [p for p, _ in guard.scenario_fields(sc)]
    assert "reference.acceptable_actions[0]" in paths and not any("applicable_sources" in p for p in paths)


def test_guard_clean_and_short_fields():
    res = guard.check([_sc(note="Kratka napomena.")], [{"id": "p1", "text": PASSAGE}])
    assert res["hits"] == [] and res["n_fields_shorter_than_n"] == res["n_fields"]


def _write_set(tmp_path, scenarios, passages):
    sdir, cdir = tmp_path / "sc", tmp_path / "corpus"
    sdir.mkdir()
    cdir.mkdir()
    for sc in scenarios:
        (sdir / ("%s.yaml" % sc["id"])).write_text(yaml.safe_dump(sc, allow_unicode=True), encoding="utf-8")
    (cdir / "passages.yaml").write_text(yaml.safe_dump(passages, allow_unicode=True), encoding="utf-8")
    return sdir, cdir


def test_guard_cli_exit_codes(tmp_path, capsys):
    sdir, cdir = _write_set(tmp_path, [_sc(note=PASSAGE)], [{"id": "p1", "text": PASSAGE}])
    assert cli(["guard", "--scenarios-dir", str(sdir), "--corpus-dir", str(cdir)]) == 1
    out = json.loads(capsys.readouterr().out)
    assert out["hits"][0]["passage"] == "p1"
    clean_dir = tmp_path / "clean"
    clean_dir.mkdir()
    (clean_dir / "S-2.yaml").write_text(yaml.safe_dump(_sc(id="S-2")), encoding="utf-8")
    assert cli(["guard", "--scenarios-dir", str(clean_dir), "--corpus-dir", str(cdir)]) == 0


def test_guard_never_loads_the_decision_model(tmp_path):
    sdir, cdir = _write_set(tmp_path, [_sc()], [{"id": "p1", "text": PASSAGE}])
    code = ("import sys; from smartagri.evalkit.__main__ import main; "
            "rc = main(['guard', '--scenarios-dir', %r, '--corpus-dir', %r]); "
            "bad = [m for m in ('smartagri.core.decide', 'smartagri.pipeline.run', 'smartagri.evalkit.runner') if m in sys.modules]; "
            "print('LOADED', bad); sys.exit(rc)") % (str(sdir), str(cdir))
    env = dict(os.environ, PYTHONPATH=str(SRC))
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env)
    assert out.returncode == 0, out.stderr
    assert "LOADED []" in out.stdout


def test_guard_dev_set_is_clean():
    assert cli(["guard", "--set", "dev"]) == 0


# ---------------------------------------------------------------- synthetic sweep

def test_parse_vary():
    assert sweep.parse_vary(["ndvi_age=2,5", "usable_share=[0.3,0.9]"]) == [("ndvi_age", [2.0, 5.0]), ("usable_share", [0.3, 0.9])]
    with pytest.raises(ValueError):
        sweep.parse_vary(["cloud=1"])
    with pytest.raises(ValueError):
        sweep.parse_vary(["ndvi_age="])


def test_derive_shifts_dates_and_share():
    sc = load_scenario("dev", "SCO-06")          # as_of 2026-07-12, NDVI on 07-05 and 07-10
    d = sweep.derive(sc, {"ndvi_age": 8, "forecast_age": 2, "usable_share": 0.3, "soil_water_age": 4, "bbch_age": 1})
    series = d["context"]["S"]["ndvi_series"]
    assert [o["obs_date"] for o in series] == ["2026-06-29", "2026-07-04"]      # spacing kept, latest 8 days old
    assert series[-1]["usable_share"] == 0.3 and series[0]["usable_share"] == 0.90
    assert d["context"]["W"]["forecast_issued_at"] == "2026-07-10T06:00:00"
    assert d["context"]["A"]["soil_water_reported_on"] == "2026-07-08"
    assert d["context"]["A"]["bbch_reported_on"] == "2026-07-11"
    assert "expect" not in d and d["id"].startswith("SCO-06~")
    assert sc["context"]["S"]["ndvi_series"][-1]["obs_date"] == "2026-07-10"      # original untouched
    with pytest.raises(ValueError):
        sweep.derive(load_scenario("dev", "IRR-T-01"), {"ndvi_age": 3})           # no NDVI series


def _row(params, suff, act="recommend"):
    return {"params": params, "sufficiency": suff, "act": act}


def test_monotonicity_detects_rank_increase_with_age():
    rows = [_row({"ndvi_age": 2, "usable_share": 0.9}, "partial"), _row({"ndvi_age": 8, "usable_share": 0.9}, "sufficient"),
            _row({"ndvi_age": 2, "usable_share": 0.3}, "insufficient"), _row({"ndvi_age": 8, "usable_share": 0.3}, "insufficient")]
    v = sweep.monotonicity(rows, ["ndvi_age", "usable_share"])
    assert len(v) == 1 and v[0]["vary"] == "ndvi_age" and v[0]["to"] == {"ndvi_age": 8, "usable_share": 0.9}
    # lower usable share must not raise sufficiency either
    rows = [_row({"usable_share": 0.9}, "partial"), _row({"usable_share": 0.3}, "sufficient")]
    assert sweep.monotonicity(rows, ["usable_share"])[0]["vary"] == "usable_share"
    # variants without sigma report no sufficiency: nothing to check
    assert sweep.monotonicity([_row({"ndvi_age": 2}, None), _row({"ndvi_age": 9}, "sufficient")], ["ndvi_age"]) == []


def test_sweep_refuses_the_test_set(capsys):
    with pytest.raises(PermissionError):
        sweep.sweep({"id": "x", "context": {}}, "test", [("ndvi_age", [1.0])], "V5", lambda s: {})
    assert cli(["sweep", "--scenario", "T-SCO-01", "--set", "test", "--vary", "ndvi_age=2"]) == 2


@pytest.fixture
def template(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "template")
    monkeypatch.setenv("EMBEDDINGS_PROVIDER", "none")


def test_sweep_dev_scenario_end_to_end(template, capsys):
    rc = cli(["sweep", "--scenario", "SCO-05", "--set", "dev", "--vary", "ndvi_age=2,12,20",
              "--vary", "forecast_age=0,4", "--vary", "usable_share=0.3,0.9", "--variant", "V5", "--format", "json"])
    assert rc == 0
    res = json.loads(capsys.readouterr().out)
    assert len(res["rows"]) == 12 and res["monotonicity_violations"] == []
    fresh = [r for r in res["rows"] if r["params"] == {"ndvi_age": 2.0, "forecast_age": 0.0, "usable_share": 0.9}][0]
    stale = [r for r in res["rows"] if r["params"] == {"ndvi_age": 20.0, "forecast_age": 0.0, "usable_share": 0.9}][0]
    assert fresh["sufficiency"] == "sufficient" and stale["sufficiency"] == "insufficient"
    assert stale["act"] != "recommend"
    text = sweep.text_table(res)
    assert "monotonicity: OK" in text and "ndvi_age" in text.splitlines()[1]


# ---------------------------------------------------------------- retrieval and citation measures

CORPUS = [("fao56-kc-mid", "fao56"), ("fao56-kc-late", "fao56"), ("note-a", "dev_notes"), ("note-b", "dev_notes"),
          ("wheat", "wheat_guide")]


def test_source_entry_forms():
    assert sources.matches("fao56-kc-mid", "fao56-kc-mid", "fao56")
    assert sources.matches("fao56", "fao56-kc-late", "fao56")                 # whole document by id
    assert sources.matches("fao56#fao56-kc", "fao56-kc-late", "fao56")        # section prefix
    assert sources.matches("dev_notes#", "note-a", "dev_notes")
    assert not sources.matches("fao56#fao56-kc-mid", "note-a", "dev_notes")
    assert not sources.matches("fao56-kc", "fao56-kc-mid", "fao56")           # bare prefix is not a match


def test_reference_sources_merge_blocks():
    sc = {"applicable_sources": ["a"], "reference": {"applicable_sources": ["b", "a"], "not_applicable_sources": ["c"]},
          "expect": {"not_applicable": ["d"]}}
    assert sources.reference_sources(sc) == (["a", "b"], ["c", "d"])
    assert sources.retrieval_record({"id": "x"}, CORPUS, ["note-a"]) is None


def test_retrieval_scores():
    sc = {"applicable_sources": ["fao56-kc-mid", "dev_notes#note-a", "missing-doc"], "not_applicable_sources": ["wheat"]}
    rec = sources.retrieval_record(sc, CORPUS, ["fao56-kc-mid", "wheat", "note-b", "fao56-kc-late"])
    assert rec["unresolved"] == ["missing-doc"] and rec["k"] == 4
    s = sources.scores(rec)
    assert s == {"recall_at_k": 0.5, "precision_applicable": 0.25, "not_applicable_rate": 0.25}
    empty = sources.scores(dict(rec, budget=[]))
    assert empty == {"recall_at_k": 0.0, "precision_applicable": None, "not_applicable_rate": None}


def _item(variant, scenario, first_act="recommend", final_act=None, retrieval=None, cited=True, stratum="complete",
          expect_act=None, cost=None):
    answer = {"act": final_act or first_act, "sources": [{"passage_id": "p"}] if cited else [], "next_question": None}
    return {"id": "%s-%s" % (variant, scenario), "variant": variant, "scenario_id": scenario, "stratum": stratum,
            "cluster": scenario, "first_act": first_act, "final_act": final_act or first_act, "n_turns": 1,
            "first_question_input": None, "expect": {"act": expect_act} if expect_act else None, "reference": None,
            "retrieval": retrieval, "repeat": 1, "batch_id": "b", "created_at": "2026-10-12T00:00:00",
            "turns": [{"question": "q", "answer": answer, "user_reply": None}],
            "records": [{"cost": cost or {"llm_calls": 1, "input_tokens": 100, "output_tokens": 20, "seconds": 0.5},
                         "provenance": {"model": "m", "corpus_hash": "abc"}, "decisions": {}}]}


def test_automatic_reports_retrieval_and_citation():
    rec = sources.retrieval_record({"applicable_sources": ["note-a"], "not_applicable_sources": ["wheat"]}, CORPUS,
                                   ["note-a", "wheat"])
    items = [_item("V3", "s1", retrieval=rec), _item("V3", "s2", cited=False),
             _item("V3", "s3", first_act="ask", cited=False)]
    a = report.automatic(items)["V3"]
    assert a["recall_at_k"] == 1.0 and a["precision_applicable"] == 0.5 and a["not_applicable_rate"] == 0.5
    assert a["recall_n"] == 1 and a["k"] == [2]
    assert a["citation_coverage"] == 0.5 and a["citation_n"] == 2          # the 'ask' answer is not advice
    assert a["first_ask_share"] == round(1 / 3.0, 3)


def test_run_scenario_stores_retrieval_record(template):
    from smartagri.evalkit.runner import run_scenario
    from smartagri.pipeline.generate import make_generator
    from smartagri.retrieval import load_corpus, make_retriever
    corpus = load_corpus()
    res = run_scenario(load_scenario("dev", "IRR-T-01"), "V5", corpus, make_retriever(corpus), make_generator())
    rec = res["retrieval"]
    assert rec["budget"] == res["records"][0]["decisions"]["passage_budget"]
    assert set(rec["applicable"]) == {"fao56-kc-maize-mid", "note-irrigation-flowering"}
    assert "fao56-kc-mid" in rec["unresolved"]                              # _passages.yaml id, not in this corpus
    assert res["first_sufficiency"] == "sufficient"
    assert sources.scores(rec)["not_applicable_rate"] == 0.0


# ---------------------------------------------------------------- markdown report

def test_markdown_report_without_data_is_all_dashes():
    md = tables.render(SqliteStore(":memory:"), [])
    for heading in ("## 7.1", "## 7.2", "## 7.3", "## 7.5", "## 7.6", "## 7.7"):
        assert heading in md
    for caption in ("Tabela 7.1.", "Tabela 7.2.", "Tabela 7.3.", "Tabela 7.4.", "Tabela 7.4a.", "Tabela 7.6.", "Tabela 7.7.",
                    "Tabela 7.8."):
        assert caption in md
    rows, body = [], False
    for line in md.splitlines():
        if line.startswith("|---"):
            body = True
        elif line.startswith("| ") and body:
            rows.append(line)
        else:
            body = False
    cells = [c.strip() for row in rows for c in row.strip("|").split("|")[1:]]
    assert cells and set(cells) <= {"—", "E1", "E2", "E3", "V4 − V3", "total", "K1", "K2", "K3", "act_correct"}


def _rate(store, item_id, total_r5, critical):
    store.save_rating({"id": "r-" + item_id, "item_id": item_id, "rater": "agro", "r1": 2, "r2": 2, "r3": 2, "r4": 2,
                       "r5": total_r5, "critical": critical, "comment": "", "created_at": "2026-10-12T00:00:00"})


def test_markdown_report_main_test_numbers():
    store = SqliteStore(":memory:")
    items = []
    for k in range(12):
        s = "s%02d" % k
        stratum = "complete" if k < 4 else "missing_input"
        for v in ("V3", "V4"):
            it = _item(v, s, stratum=stratum, first_act="recommend" if v == "V3" else "ask", expect_act="ask")
            items.append(store.save_eval_item(it))
            bad = v == "V3" and stratum == "missing_input"
            _rate(store, it["id"], 0 if bad else 2, ["K4"] if bad else [])
    md = tables.render(store, store.list_eval_items(), "agro")
    lines = {row.split("|")[1].strip(): [c.strip() for c in row.strip("|").split("|")] for row in md.split("## E5")[0].splitlines()
             if row.startswith("| ")}
    total = lines["Rubrika ukupno (0–10)"]
    assert total[1:4] == ["8,67", "10,00", "1,33"] and total[5] == "8 / 4 / 0"
    assert total[4].startswith("[") and total[4] != "—"
    assert lines["Stopa K4 (preuranjena preporuka)"][1:4] == ["0,67", "0,00", "-0,67"]
    assert lines["Tačnost odluke o činu (prvi korak)"][1:4] == ["0,00", "1,00", "1,00"]
    assert lines["potpuni ulazi"][1] == "4" and lines["potpuni ulazi"][5] == "—"          # n < 10: no interval
    assert lines["V1"][1] == "—" and lines["V3"][1:5] == ["12", "1", "12", "1,00"]
    assert lines["V3"][6] == "1200 / 240"
    p = report.paired_measure(report.scenario_scores(store, store.list_eval_items(), "agro"), "V4", "V3", "total",
                              report.scenario_meta(items))
    assert (p["wins"], p["ties"], p["losses"]) == (8, 4, 0) and p["bootstrap"] == "scenario"


def test_report_cli_markdown(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("SMARTAGRI_DB", str(tmp_path / "x.sqlite"))
    assert cli(["report", "--format", "md"]) == 0
    assert "Tabela 7.7." in capsys.readouterr().out
