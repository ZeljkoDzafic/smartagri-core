"""Coverage report and retrieval baseline command."""
from smartagri.evalkit.scenarios import load_scenarios
from smartagri.retrieval import bench, coverage, load_corpus


def test_coverage_counts_applicable_passages_per_advice_type():
    rep = coverage.coverage(load_scenarios("dev"), load_corpus(), minimum=3)
    assert list(rep["per_advice_type"]) == coverage.ADVICE_TYPES
    rows = {r["id"]: r for r in rep["scenarios"]}
    assert "OUT-08" not in rows                                     # out of scope has no corpus
    r = rows["IRR-T-01"]
    assert r["applicable"] + r["conditional"] + r["not_applicable"] == rep["passages"]
    assert rep["per_advice_type"]["irrigation_timing"]["typical_basis"] == "complete"
    assert rep["per_advice_type"]["irrigation_amount"]["typical_basis"] == "all"
    assert rep["vocabulary_violations"] == [] and len(rep["verify"]) == 18
    text = coverage.render(rep)
    assert "fertilization_timing" in text and "Passages marked verify: 18" in text


def test_coverage_refuses_the_test_set(capsys):
    assert coverage.main(["--set", "test"]) == 2


def test_recall_counts_entries_not_passages():
    resolved = {"doc#": ["a", "b"], "c": ["c"], "missing": []}
    assert bench.recall(["b", "x"], resolved, 1) == 0.5
    assert bench.recall(["x", "y"], resolved, 2) == 0.0
    assert bench.recall(["x"], {"missing": []}, 6) is None


def test_bench_reports_recall_and_latency(monkeypatch):
    monkeypatch.setenv("EMBEDDINGS_PROVIDER", "none")
    rep = bench.bench(load_scenarios("dev"), repeats=2)
    assert rep["mode"] == "lexical (BM25)" and rep["latency_ms"]["queries"] > 0
    assert {r["id"] for r in rep["scenarios"]} >= {"IRR-T-01", "SCO-06"}
    assert all(0.0 <= r["recall_at_6"] <= r["recall_at_20"] <= 1.0 for r in rep["scenarios"])
    assert bench.main(["--set", "test"]) == 2
