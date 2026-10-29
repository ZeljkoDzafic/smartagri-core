"""`evalkit assign`: one repetition per scenario, a balanced seeded subset, per-rater seeded order, all recorded; the
rating queue never mixes sets, batches of one variant, or locks."""
import json

import pytest

from smartagri.evalkit import rating
from smartagri.evalkit.__main__ import main as cli
from smartagri.store import SqliteStore

STRATA = {"complete": 6, "missing_input": 4, "unreliable_input": 3}


@pytest.fixture
def store(monkeypatch, tmp_path):
    monkeypatch.setenv("SMARTAGRI_ASSIGNMENTS_DIR", str(tmp_path / "assignments"))
    return SqliteStore(":memory:")


def _fill(store, variants=("V3", "V4", "VC"), repeats=2, batch_prefix="b", lock=None, set_name="test"):
    n = 0
    for stratum, count in STRATA.items():
        for k in range(count):
            for v in variants:
                for r in range(1, repeats + 1):
                    n += 1
                    store.save_eval_item({"id": "%s%s%03d" % (batch_prefix, v, n),
                                          "set": set_name, "batch_id": batch_prefix + v, "scenario_id": "%s-%d" % (stratum[:3], k),
                                          "variant": v, "repeat": r, "repeats": repeats, "stratum": stratum,
                                          "created_at": "2026-10-29T10:00:00+02:00", "rateable": True, "turns": [],
                                          "scenario": {"id": "x"}, "lock_sha256": lock})
    return n


def test_one_repetition_per_scenario_fixed_or_seeded(store):
    _fill(store)
    fixed = rating.assign(store, "a1", "test", repeat=2, write=False)
    by_id = {i["id"]: i for i in store.list_eval_items()}
    assert {by_id[x]["repeat"] for x in fixed["items"]} == {2} and len(fixed["items"]) == 13 * 3
    assert fixed["repeat_rule"] == {"mode": "fixed", "repeat": 2}
    seeded = rating.assign(store, "a1", "test", pick_repeat=True, seed=5, write=False)
    picked = {}
    for x in seeded["items"]:
        picked.setdefault(by_id[x]["scenario_id"], set()).add(by_id[x]["repeat"])
    assert len(seeded["items"]) == 13 * 3 and all(len(r) == 1 for r in picked.values())   # one repetition per scenario, all variants alike
    assert seeded["repeat_rule"]["mode"] == "seeded" and seeded["repeat_rule"]["picked"] == {s: sorted(r)[0] for s, r in picked.items()}
    assert {r for rs in picked.values() for r in rs} == {1, 2}                               # both repetitions are used
    again = rating.assign(store, "a2", "test", pick_repeat=True, seed=5, write=False)
    assert again["repeat_rule"] == seeded["repeat_rule"]                                      # the same for every rater
    with pytest.raises(ValueError):
        rating.assign(store, "a1", "test", repeat=1, pick_repeat=True, write=False)
    with pytest.raises(ValueError):
        rating.assign(store, "a1", "test", repeat=9, write=False)                             # no such repetition


def test_balanced_subset_n_per_stratum_seeded_and_recorded(store):
    _fill(store)
    a = rating.assign(store, "a1", "test", repeat=1, per_stratum=2, seed=3, write=False)
    by_id = {i["id"]: i for i in store.list_eval_items()}
    chosen = a["subset"]["scenarios"]
    assert a["subset"]["per_stratum"] == 2 and a["subset"]["seed"] == 3
    assert {s: len(v) for s, v in chosen.items()} == {"complete": 2, "missing_input": 2, "unreliable_input": 2}
    assert len(a["items"]) == 6 * 3
    assert {by_id[x]["scenario_id"] for x in a["items"]} == {s for v in chosen.values() for s in v}
    other_rater = rating.assign(store, "a2", "test", repeat=1, per_stratum=2, seed=3, write=False)
    assert other_rater["subset"] == a["subset"] and other_rater["items"] != a["items"]       # same subset, own order
    reseeded = rating.assign(store, "a1", "test", repeat=1, per_stratum=2, seed=4, write=False)
    assert reseeded["subset"]["scenarios"] != chosen
    short = rating.assign(store, "a1", "test", repeat=1, per_stratum=5, write=False)
    assert short["subset"]["short"] == {"missing_input": 4, "unreliable_input": 3} and len(short["subset"]["scenarios"]["complete"]) == 5


def test_subset_keeps_only_scenarios_present_in_every_variant(store):
    _fill(store, repeats=1)
    store.save_eval_item({"id": "z1", "set": "test", "batch_id": "bV3", "scenario_id": "extra-0", "variant": "V3", "repeat": 1,
                          "stratum": "complete", "created_at": "x", "rateable": True, "turns": []})
    a = rating.assign(store, "a1", "test", per_stratum=10, write=False)
    assert "extra-0" not in a["subset"]["scenarios"]["complete"] and a["subset"]["incomplete"] == ["extra-0"]


def test_assignment_file_records_everything_and_the_queue_follows_it(store, capsys, monkeypatch, tmp_path):
    _fill(store, lock="a" * 64)
    a = rating.assign(store, "agronom 1", "test", pick_repeat=True, per_stratum=2, seed=9)
    data = json.loads(open(a["path"]).read())
    assert data["lock_sha256"] == "a" * 64 and data["seed"] == 9 and data["rater"] == "agronom 1"
    assert data["order_rule"].startswith("sha256(seed|rater|scenario|variant|repeat)")
    assert data["items_sha256"] and data["repeat_rule"]["mode"] == "seeded" and data["subset"]["per_stratum"] == 2
    first = rating.next_item(store, "agronom 1")
    assert first["item_id"] == data["items"][0] and first["remaining"] == 18


def test_the_queue_never_mixes_two_batches_of_one_variant_or_two_locks(store):
    _fill(store, variants=("V4",), repeats=1)
    _fill(store, variants=("V4",), repeats=1, batch_prefix="again")
    with pytest.raises(ValueError, match="several batches"):
        rating.next_item(store, "r", "test")
    with pytest.raises(ValueError, match="several batches"):
        rating.assign(store, "r", "test", write=False)
    ok = rating.next_item(store, "r", "test", batches=["bV4"])
    assert ok["remaining"] == 13
    _fill(store, variants=("V3",), repeats=1, batch_prefix="x", lock="e" * 64)
    with pytest.raises(ValueError, match="different protocol locks"):
        rating.assign(store, "r", "test", batches=["bV4", "xV3"], write=False)


def test_cli_assign_options(store, capsys, monkeypatch):
    monkeypatch.setenv("SMARTAGRI_DB", "")
    import smartagri.store as st
    monkeypatch.setattr(st, "make_store", lambda *a, **k: store)
    _fill(store)
    assert cli(["assign", "--set", "test", "--rater", "r1", "--pick-repeat", "--per-stratum", "2", "--seed", "4", "--dry-run"]) == 0
    shown = json.loads(capsys.readouterr().out)
    assert shown["n"] == 18 and shown["repeat_rule"]["mode"] == "seeded" and shown["subset"]["per_stratum"] == 2
