"""evalkit CLI: run/export (T009), test-set refusal and protocol lock (T022, T032, T033), guard against
development material and isolation checks (T020a, T021), support rate and citation sample (T025).

The real test set is never read: protected-set runs use a temporary folder of copied dev scenarios."""
import json
import shutil
from pathlib import Path

import pytest
import yaml

from smartagri.evalkit import citations, guard, lock, report
from smartagri.evalkit.__main__ import main as cli
from smartagri.evalkit.scenarios import scenario_dir

DEV = scenario_dir("dev")


@pytest.fixture
def env(monkeypatch, tmp_path):
    monkeypatch.setenv("LLM_PROVIDER", "template")
    monkeypatch.setenv("EMBEDDINGS_PROVIDER", "none")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("SMARTAGRI_DB", str(tmp_path / "eval.sqlite"))
    return tmp_path


def _lines(out):
    return [json.loads(line) for line in out.strip().splitlines()]


def _fake_test_set(tmp_path, ids=("IRR-T-01", "SCO-05")):
    folder = tmp_path / "fake_test"
    folder.mkdir()
    for p in DEV.glob("*.yaml"):
        if any(p.name.startswith(i + "_") for i in ids):
            shutil.copy(p, folder / p.name)
    return folder


# ---------------------------------------------------------------- T009 run and export

def test_cli_run_and_export(env, capsys):
    assert cli(["run", "--set", "dev", "--variant", "V5", "--variant", "V3"]) == 0
    batches = _lines(capsys.readouterr().out)
    n = len(list(p for p in DEV.glob("*.yaml") if not p.name.startswith("_")))
    assert [(b["variant"], b["set"], b["n"], b["generator"]) for b in batches] == [("V5", "dev", n, "template"),
                                                                                  ("V3", "dev", n, "template")]
    out = env / "export.json"
    assert cli(["export", "--out", str(out)]) == 0
    data = json.loads(out.read_text(encoding="utf-8"))
    assert len(data["items"]) == 2 * n and data["ratings"] == []
    assert {i["batch_id"] for i in data["items"]} == {b["batch_id"] for b in batches}
    assert cli(["export"]) == 0
    assert len(json.loads(capsys.readouterr().out)["items"]) == 2 * n


def test_cli_run_ablation_variant(env, capsys):
    folder = _fake_test_set(env, ("IRR-T-01",))
    assert cli(["run", "--set", "dev", "--scenarios-dir", str(folder), "--variant", "V5-weather"]) == 0
    assert _lines(capsys.readouterr().out)[0]["variant"] == "V5-weather"
    assert cli(["export"]) == 0
    item = json.loads(capsys.readouterr().out)["items"][0]
    assert item["records"][0]["provenance"]["context_used"] == {"weather": False, "satellite": True}
    assert item["first_act"] != "recommend"                              # without the forecast V5 cannot recommend


# ---------------------------------------------------------------- T022, T032, T033 lock and refusal

def test_run_on_the_test_set_is_refused_without_a_lock(env, capsys):
    assert cli(["run", "--set", "test"]) == 2
    assert "--locked" in capsys.readouterr().err
    assert cli(["run", "--set", "test", "--locked", "--lock-file", str(env / "none.json")]) == 2
    assert "no protocol lock" in capsys.readouterr().err
    assert not (env / "eval.sqlite").exists()                            # refused before the store was opened


def test_lock_then_locked_run_then_tamper(env, capsys):
    folder = _fake_test_set(env)
    lock_file = env / "protocol-lock.json"
    snap = env / "snapshot.tar"
    snap.write_bytes(b"cache snapshot")
    assert cli(["lock", "--set", "test", "--scenarios-dir", str(folder), "--out", str(lock_file)]) == 2   # no snapshot
    capsys.readouterr()
    assert cli(["lock", "--set", "test", "--scenarios-dir", str(folder), "--cache-snapshot", str(snap),
                "--out", str(lock_file)]) == 0
    written = json.loads(capsys.readouterr().out)
    data = json.loads(lock_file.read_text(encoding="utf-8"))
    assert data["combined_sha256"] == written["combined_sha256"] and data["set"] == "test"
    keys = set(data["files"])
    assert {"config/thresholds.yaml", "config/requirements.yaml", "config/variants.yaml",
            "corpus/passages.yaml", "rater_guide/RATER_GUIDE.md"} <= keys
    assert sum(k.startswith("scenarios/") for k in keys) == 2 and len(data["prompt_hash"]) == 64

    assert cli(["lock", "--set", "test", "--scenarios-dir", str(folder), "--cache-snapshot", str(snap),
                "--out", str(lock_file)]) == 2   # no silent overwrite
    capsys.readouterr()
    assert cli(["lock", "--check", "--scenarios-dir", str(folder), "--out", str(lock_file)]) == 0
    assert json.loads(capsys.readouterr().out)["differences"] == []

    args = ["run", "--set", "test", "--locked", "--lock-file", str(lock_file), "--lock-sha256", lock.lock_sha256(lock_file),
            "--scenarios-dir", str(folder), "--variant", "V5"]
    assert cli(args) == 0
    assert _lines(capsys.readouterr().out)[0]["n"] == 2

    target = sorted(folder.glob("*.yaml"))[0]
    target.write_text(target.read_text(encoding="utf-8") + "\n# edited\n", encoding="utf-8")
    assert cli(args) == 2
    assert "changed: scenarios/" + target.name in capsys.readouterr().err
    assert cli(["lock", "--check", "--scenarios-dir", str(folder), "--out", str(lock_file)]) == 1


def test_lock_differences_and_cache_snapshot(env, capsys):
    from smartagri.cache import export_snapshot
    from smartagri.store import SqliteStore
    store = SqliteStore(":memory:")
    store.cache_put("h1", "open-meteo", {"lat": 44.9}, {"daily": {}}, fetched_at="2026-07-01T06:00:00+02:00")
    snap = env / "cache_snapshot.tar"
    export_snapshot(store, snap)
    folder = _fake_test_set(env, ("IRR-T-01",))
    lock_file = env / "lock.json"
    assert cli(["lock", "--scenarios-dir", str(folder), "--cache-snapshot", str(snap), "--out", str(lock_file)]) == 0
    data = json.loads(lock_file.read_text(encoding="utf-8"))
    assert data["cache_snapshot"] == str(snap) and data["files"]["cache_snapshot/cache_snapshot.tar"] == lock.sha256_file(snap)
    capsys.readouterr()
    assert cli(["lock", "--check", "--scenarios-dir", str(folder), "--out", str(lock_file)]) == 0
    capsys.readouterr()
    snap.write_bytes(snap.read_bytes() + b"x")
    assert cli(["lock", "--check", "--scenarios-dir", str(folder), "--out", str(lock_file)]) == 1
    assert "changed: cache_snapshot/cache_snapshot.tar" in json.loads(capsys.readouterr().out)["differences"]

    files = {"a": "1", "b": "2"}
    locked = lock.make_lock("test", files, "p")
    assert lock.differences(locked, files, "p", "test") == []
    assert lock.differences(locked, {"a": "1", "c": "3"}, "q", "dev") == [
        "lock is for set 'test', not 'dev'", "missing: b", "not in lock: c", "changed: generator prompt"]


# ---------------------------------------------------------------- T020a, T021 guard

def test_guard_compares_test_scenarios_with_development_texts(tmp_path, capsys):
    note = ("Parcela na lakom zemljištu, kukuruz u fazi metličenja, korisnik kaže da je zemlja suva "
            "i da kiša nije najavljena za naredne dane.")
    dev_dir, test_dir, cdir = tmp_path / "dev", tmp_path / "test", tmp_path / "corpus"
    for d in (dev_dir, test_dir, cdir):
        d.mkdir()
    (dev_dir / "D-1.yaml").write_text(yaml.safe_dump({"id": "D-1", "question": "x", "note": note}), encoding="utf-8")
    (test_dir / "T-1.yaml").write_text(yaml.safe_dump({"id": "T-1", "question": "y", "notes": note}), encoding="utf-8")
    (cdir / "passages.yaml").write_text(yaml.safe_dump([{"id": "p1", "text": "Nešto sasvim drugo o đubrenju."}]), encoding="utf-8")
    base = ["guard", "--set", "test", "--scenarios-dir", str(test_dir), "--corpus-dir", str(cdir), "--dev-dir", str(dev_dir)]
    assert cli(base) == 1
    res = json.loads(capsys.readouterr().out)
    assert [h["passage"] for h in res["hits"]] == ["dev:D-1:note"] and res["n_dev_fields"] == 2
    assert cli(base + ["--no-dev"]) == 0
    assert guard.scenario_passages([{"id": "D-1", "question": "abc"}]) == [{"id": "dev:D-1:question", "text": "abc"}]


def test_guard_isolation_checks(tmp_path):
    repo = tmp_path / "repo"
    retrieval = repo / "backend" / "src" / "retrieval"
    retrieval.mkdir(parents=True)
    (retrieval / "index.py").write_text("def build(): pass\n", encoding="utf-8")
    corpus = repo / "backend" / "corpus"
    corpus.mkdir()
    res = guard.isolation_checks(repo, corpus, retrieval)
    assert res["problems"] == [] and "not verifiable" in res["notes"][0]
    (repo / ".gitignore").write_text("node_modules/\n", encoding="utf-8")
    assert "not ignored" in guard.isolation_checks(repo, corpus, retrieval)["problems"][0]
    for line in ("backend/eval/scenarios/test/", "/backend/eval/scenarios/", "backend/eval"):
        (repo / ".gitignore").write_text(line + "\n", encoding="utf-8")
        assert guard.isolation_checks(repo, corpus, retrieval)["problems"] == [], line
    (repo / ".gitignore").write_text("backend/eval/\n!backend/eval/scenarios/test/\n", encoding="utf-8")
    assert guard.isolation_checks(repo, corpus, retrieval)["problems"]
    (repo / ".gitignore").write_text("backend/eval/scenarios/test/\n", encoding="utf-8")
    (retrieval / "coverage.py").write_text("SETS = 'eval/scenarios/dev'\n", encoding="utf-8")   # reporting tool: allowed
    assert guard.isolation_checks(repo, corpus, retrieval)["problems"] == []
    (retrieval / "search.py").write_text("PATH = 'eval/scenarios/test'\n", encoding="utf-8")
    inside = repo / "backend" / "eval" / "scenarios" / "test"
    inside.mkdir(parents=True)
    problems = guard.isolation_checks(repo, inside, retrieval)["problems"]
    assert any("search.py" in p for p in problems) and any("inside the scenarios folder" in p for p in problems)


def test_guard_isolation_holds_in_this_repository():
    from smartagri.retrieval.corpus import corpus_dir
    src = Path(guard.__file__).resolve().parents[1]
    res = guard.isolation_checks(src.parents[2], corpus_dir(), src / "retrieval", trace_index=True)
    assert res["problems"] == [], res
    assert any("none under the scenarios folder" in n for n in res["notes"]), res


def test_traced_reads_sees_files_opened_by_the_index_build(tmp_path):
    f = tmp_path / "x.txt"
    f.write_text("a", encoding="utf-8")
    assert str(f) in guard.traced_reads(lambda: f.read_text(encoding="utf-8"))
    assert guard.traced_reads(lambda: None) == []


# ---------------------------------------------------------------- T025 support rate and citation sample

def _item(iid, variant, grounding, answer=None):
    a = answer or {"act": "recommend", "summary": "Navodnjavati. Uskoro.", "rationale": ["Faza je BBCH 61."],
                   "sources": [{"passage_id": "p1", "title": "T", "excerpt": "E"}], "generator": "anthropic"}
    return {"id": iid, "scenario_id": "S-" + iid, "variant": variant, "first_act": a["act"], "final_act": a["act"],
            "n_turns": 1, "first_question_input": None, "turns": [{"question": "q", "answer": a, "user_reply": None}],
            "records": [{"decisions": {"grounding": grounding}, "cost": {}, "provenance": {}}]}


def test_support_rate_and_grounding_actions():
    items = [_item("1", "V5", {"action": "checked", "checked_sentences": 4, "unsupported_sentences": ["x"]}),
             _item("2", "V5", {"action": "summary_replaced_by_template", "checked_sentences": 2,
                               "unsupported_sentences": ["y", "z"]}),
             _item("3", "V5", {"action": "template_after_refusal"}),
             _item("4", "V3", {"action": "not_checked"})]
    auto = report.automatic(items)
    assert auto["V5"]["support_rate"] == 0.5 and auto["V5"]["support_n"] == 6 and auto["V5"]["unsupported_sentences"] == 3
    assert auto["V5"]["grounding_actions"] == {"checked": 1, "summary_replaced_by_template": 1, "template_after_refusal": 1}
    assert auto["V3"]["support_rate"] is None and auto["V3"]["grounding_actions"] == {"not_checked": 1}


def test_citation_sample_is_fixed_and_blind(env, capsys):
    items = [_item(str(i), "V5", {"action": "checked", "checked_sentences": 3, "unsupported_sentences": ["Fungicid."]})
             for i in range(6)]
    items.append(_item("ask", "V5", {"action": "none"}, {"act": "ask", "summary": "Pitanje.", "rationale": [], "sources": []}))
    pop = citations.population(items)
    assert len(pop) == 6 * 4                                # 2 summary + 1 rationale + 1 dropped sentence per item
    assert {r["kind"] for r in pop} == {"summary", "rationale", "dropped"}
    assert [r["automatic_supported"] for r in pop if r["kind"] == "dropped"] == [False] * 6
    a, b = citations.sample(items, 5, seed=7), citations.sample(items, 5, seed=7)
    assert a == b and a["n"] == 5 and a["population"] == 24
    assert all("variant" not in r and "generator" not in r for r in a["rows"])
    assert citations.sample(items, 100)["n"] == 24

    assert cli(["run", "--set", "dev", "--scenarios-dir", str(_fake_test_set(env)), "--variant", "V5"]) == 0
    capsys.readouterr()
    out = env / "sample.json"
    assert cli(["export", "--citation-sample", "3", "--out", str(out)]) == 0
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["seed"] == 7 and data["n"] == min(3, data["population"])
    assert all(r["automatic_supported"] is None for r in data["rows"])     # template text is not support-checked
