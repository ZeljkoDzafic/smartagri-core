"""Statistics of the analysis plan: the cluster bootstrap is not estimable below a minimum number of clusters, and the
report says so instead of printing an interval of zero width (E2)."""
from smartagri.evalkit import report, tables


def _scores(n_clusters, per_cluster=2):
    """V4 and V3 scores of scenarios that share parcels: `per_cluster` scenarios on each of `n_clusters` parcels."""
    a, b, meta = {}, {}, {}
    for c in range(n_clusters):
        for k in range(per_cluster):
            s = "S%d_%d" % (c, k)
            a[s], b[s] = {"total": 8.0 + c % 2, "K4": 0.0}, {"total": 6.0 + 0.5 * k, "K4": 1.0 if k else 0.0}
            meta[s] = {"stratum": "complete", "cluster": "parcel-%d" % c}
    return {"V4": a, "V3": b}, meta


def test_two_clusters_give_no_interval_not_a_zero_width_one():
    # the reproduction of the audit: the interval was (0.15, 0.15) with two clusters
    assert report.bootstrap_ci([0.1, 0.2, 0.3, 0.0], clusters=["a", "a", "b", "b"], min_clusters=2) is not None
    assert report.bootstrap_ci([0.1, 0.2, 0.3, 0.0], clusters=["a", "a", "b", "b"]) is None
    four = report.bootstrap_ci([1.0, 1.0, 2.0, 0.0, 3.0, 1.0, 2.0, 1.0], clusters=list("aabbccdd"))
    assert four is None                                    # 4 clusters < the default minimum of 5
    five = report.bootstrap_ci([1.0, 1.0, 2.0, 0.0, 3.0, 1.0, 2.0, 1.0, 2.0, 2.0], clusters=list("aabbccddee"))
    assert five is not None and five[0] < five[1]
    assert report.bootstrap_ci([1.0, 2.0, 3.0]) is not None  # scenarios as units: no cluster minimum applies


def test_the_minimum_is_configurable_and_read_from_the_analysis_plan():
    assert report.analysis_settings()["min_clusters"] == 5
    assert report.min_clusters({}) == report.DEFAULT_MIN_CLUSTERS == 5
    assert report.min_clusters({"min_clusters": 8}) == 8
    assert report.not_estimable_reason(["a", "a", "b"], 5) == "2 clusters, fewer than the minimum of 5"
    assert report.not_estimable_reason(["a", "b", "c", "d", "e"], 5) is None
    assert report.not_estimable_reason(None, 5) is None


def test_paired_measure_says_not_estimable_with_two_parcels():
    scores, meta = _scores(2)
    p = report.paired_measure(scores, "V4", "V3", "total", meta)
    assert p["bootstrap"] == "cluster" and p["n_clusters"] == 2 and p["ci95"] is None
    assert p["ci_status"] == "not_estimable" and "2 clusters" in p["ci_note"] and p["diff"] is not None
    scores, meta = _scores(6)
    p = report.paired_measure(scores, "V4", "V3", "total", meta)
    assert p["ci_status"] == "ok" and p["ci95"][0] < p["ci95"][1] and p["ci_note"] is None


def test_tables_print_the_reason_never_an_interval():
    scores, meta = _scores(2)
    md = tables.table_main(scores, meta, "V4", "V3")
    assert "nije procenjivo" in md and "2 clusters" in md
    scores, meta = _scores(6)
    assert "nije procenjivo" not in tables.table_main(scores, meta, "V4", "V3")


def test_tests_with_a_margin_are_not_estimable_either():
    diffs, cl = [0.1, 0.2, 0.0, 0.1], ["a", "a", "b", "b"]
    ni = report.noninferiority(diffs, 1.0, cl)
    assert ni["noninferior"] is None and ni["ci"] is None and ni["status"] == "not_estimable"
    eq = report.equivalence(diffs, 1.0, cl)
    assert eq["equivalent"] is None and eq["ci"] is None and eq["status"] == "not_estimable"


def test_rated_pairs_say_so_too():
    rated = {v: {"_totals": {"S%d" % i: x for i, x in enumerate(vals)}, "_critical": {"S%d" % i: 0.0 for i in range(4)},
                 "_k4_or_k5": {"S%d" % i: 0.0 for i in range(4)},
                 "_clusters": {"S0": "p", "S1": "p", "S2": "q", "S3": "q"}}
             for v, vals in (("V4", [8, 9, 7, 8]), ("V3", [6, 6, 5, 7]))}
    pair = report.paired(rated, "V4", "V3")
    assert pair["rubric_ci95"] is None and pair["ci_status"] == "not_estimable"
