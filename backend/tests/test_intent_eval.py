import pytest

from smartagri.core.types import AdviceType
from smartagri.evalkit import rating, report
from smartagri.evalkit.runner import load_scenarios, run_batch
from smartagri.pipeline.intent import apply_reply, classify, parse_reply

T = AdviceType


@pytest.mark.parametrize("question, expected", [
    ("Da li sutra da navodnjavam kukuruz?", T.IRRIGATION_TIMING),
    ("Koliko vode da dam kukuruzu ove nedelje?", T.IRRIGATION_AMOUNT),
    ("Koliko azota da dam u prihrani?", T.FERTILIZATION_PLAN),
    ("Kada da radim prihranu?", T.FERTILIZATION_TIMING),
    ("Mogu li sutra da prskam?", T.FIELD_OPS_WINDOW),
    ("Koji deo parcele da obiđem prvo?", T.SCOUTING),
    ("Koji herbicid da koristim?", T.OUT_OF_SCOPE),
    ("Šta da radim?", None),
])
def test_classify(question, expected):
    assert classify(question) == expected


@pytest.mark.parametrize("name, text, expected", [
    ("soil_water_status", "Suvo je, mrvi se", ("value", "dry")),
    ("soil_water_status", "umereno vlažno", ("value", "moist")),
    ("soil_water_status", "baš je vlažno", ("value", "wet")),
    ("soil_water_status", "ne znam", ("declined", None)),
    ("irrigation_available", "nemam", ("value", "no")),
    ("irrigation_available", "da, imam tifon", ("value", "yes")),
    ("irrigation_efficiency", "kap po kap", ("value", "drip")),
    ("phenophase", "ima 8 listova", ("value", 18)),
    ("phenophase", "počelo je svilanje", ("value", 65)),
    ("previous_fertilization", "nisam ništa dao", ("value", [])),
    ("yield_target", "oko 9,5 tona", ("value", 9.5)),
    ("operation", "prskanje", ("value", "spraying")),
    ("soil_water_status", "plavo", ("unparsed", None)),
])
def test_parse_reply(name, text, expected):
    assert parse_reply(name, text) == expected


def test_fertilizer_reply_converts_product_to_nitrogen():
    kind, value = parse_reply("previous_fertilization", "200 kg/ha uree")
    assert kind == "value" and value[0]["n_kg_ha"] == 92.0
    # without the per-hectare cue the unit is unclear (per parcel or per hectare): not read, asked again
    assert parse_reply("previous_fertilization", "200 kg uree") == ("unparsed", None)


def test_apply_reply_stamps_the_report_date():
    a = apply_reply({}, "soil_water_status", "dry", "2026-07-12")
    assert a == {"soil_water_status": "dry", "soil_water_origin": "user_reported", "soil_water_reported_on": "2026-07-12"}
    assert apply_reply({}, "irrigation_efficiency", "drip", "x") == {"irrigation_system_type": "drip"}


def test_eval_batch_rating_and_report(monkeypatch, store):
    monkeypatch.setenv("LLM_PROVIDER", "template")
    monkeypatch.setenv("EMBEDDINGS_PROVIDER", "none")
    n = len(load_scenarios("dev"))
    for variant in ("V3", "V4", "V5"):
        assert run_batch(store, "dev", variant)["n"] == n
    auto = report.automatic(store.list_eval_items())
    # Scenarios marked `xfail_reason:` state a sensible expectation the code does not yet meet; they are
    # excluded here exactly as tests/test_dev_scenarios.py marks them xfail.
    xfail_ids = {sc["id"] for sc in load_scenarios("dev") if sc.get("xfail_reason")}
    checked = [i for i in store.list_eval_items()
               if i["variant"] in ("V4", "V5") and i["expect"] and i["scenario_id"] not in xfail_ids]
    assert checked and all(i["first_act"] == i["expect"]["act"] for i in checked)
    assert auto["V4"]["act_accuracy_n"] > 0 and auto["V5"]["act_accuracy_n"] > 0
    assert auto["V5"]["question_target_accuracy"] == 1.0
    assert auto["V5"]["mean_turns"] > auto["V3"]["mean_turns"] == 1.0

    item = rating.next_item(store, "agro")
    assert item["remaining"] == 3 * n and "variant" not in item and "expect" not in item
    assert all("generator" not in t["answer"] for t in item["turns"])
    for i in store.list_eval_items():
        good = i["variant"] == "V5"
        rating.save(store, {"item_id": i["id"], "rater": "agro", "r1": 2, "r2": 2, "r3": 2, "r4": 2 if good else 1,
                            "r5": 2 if good else 0, "critical": [] if good else ["K4"], "comment": ""})
        rating.save(store, {"item_id": i["id"], "rater": "cand", "r1": 2, "r2": 2, "r3": 2, "r4": 2 if good else 1,
                            "r5": 2 if good else 1, "critical": [], "comment": ""})
    assert rating.next_item(store, "agro") == {"item_id": None, "remaining": 0}
    rated = report.rated(store, store.list_eval_items(), "agro")
    assert rated["V5"]["rubric_total"] == 10.0 and rated["V3"]["k4_rate"] == 1.0
    pair = report.paired(rated, "V5", "V3")
    assert pair["n_scenarios"] == n and pair["rubric_diff"] == 3.0 and pair["critical_rate_diff"] == -1.0
    assert pair["rubric_wilcoxon"]["p_two_sided"] < 0.05
    agree = report.agreement(store, "agro", "cand")
    assert agree["n_items"] == 3 * n and agree["r4"]["kappa_quadratic"] == 1.0
    assert 0 < agree["r5"]["kappa_quadratic"] < 1 and agree["critical_K4"]["percent_agreement"] < 1
    with pytest.raises(ValueError):
        rating.save(store, {"item_id": store.list_eval_items()[0]["id"], "rater": "agro", "r1": 0, "r2": 0, "r3": 0,
                            "r4": 0, "r5": 0, "critical": ["K9"], "comment": ""})


def test_cluster_bootstrap_and_wilcoxon():
    diffs = [1.0, 1.0, 2.0, 0.0, 3.0, 1.0, 2.0, 1.0]
    lo, hi = report.bootstrap_ci(diffs, clusters=["a", "a", "b", "b", "c", "c", "d", "d"], min_clusters=4)
    assert lo <= report.mean(diffs) <= hi
    assert report.bootstrap_ci(diffs, clusters=["a", "a", "b", "b", "c", "c", "d", "d"]) is None   # 4 < the default 5
    assert report.bootstrap_ci([1.0, 2.0], clusters=["a", "a"], min_clusters=1) is None
    w = report.wilcoxon_signed_rank([1, 2, 3, 4, 5, 6, 7, -1])
    assert w["n"] == 8 and w["p_two_sided"] < 0.05
    assert report.wilcoxon_signed_rank([1, -1, 0]) is None
    # Known value: n=10 all positive gives z = 2.803 (normal approximation).
    assert report.wilcoxon_signed_rank(list(range(1, 11)))["z"] == 2.803


def test_kappa_weights():
    a, b = [0, 1, 2, 2, 1], [1, 1, 2, 0, 1]
    assert report.weighted_kappa(a, b, weights="quadratic") != report.weighted_kappa(a, b, weights="linear")
    assert report.weighted_kappa([0, 1, 0, 1], [0, 1, 1, 0], 2, "none") == 0.0


def test_weighted_kappa_bounds():
    assert report.weighted_kappa([0, 1, 2, 2], [0, 1, 2, 2]) == 1.0
    assert report.weighted_kappa([0, 0, 2, 2], [2, 2, 0, 0]) < 0
    assert report.bootstrap_ci([1.0]) is None
    lo, hi = report.bootstrap_ci([1.0, 2.0, 3.0, 2.0])
    assert 1.0 <= lo <= hi <= 3.0
